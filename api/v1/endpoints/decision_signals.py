# -*- coding: utf-8 -*-
"""DecisionSignal API endpoints."""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Security
from fastapi.security import APIKeyCookie

from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.decision_signals import (
    DecisionSignalCreateRequest,
    DecisionSignalFeedbackItem,
    DecisionSignalFeedbackRequest,
    DecisionSignalItem,
    DecisionSignalListResponse,
    DecisionSignalMutationResponse,
    DecisionSignalOutcomeListResponse,
    DecisionSignalOutcomeRunRequest,
    DecisionSignalOutcomeRunResponse,
    DecisionSignalOutcomeStatsResponse,
    DecisionSignalStatusUpdateRequest,
)
from src.auth import COOKIE_NAME
from src.services.decision_signal_service import (
    DecisionSignalNotFoundError,
    DecisionSignalService,
    DecisionSignalStorageError,
)
from src.services.decision_signal_outcome_service import DecisionSignalOutcomeService


logger = logging.getLogger(__name__)

admin_session_cookie = APIKeyCookie(
    name=COOKIE_NAME,
    scheme_name="AdminSessionCookie",
    auto_error=False,
)
router = APIRouter(dependencies=[Security(admin_session_cookie)])

AUTH_RESPONSE = {
    401: {
        "model": ErrorResponse,
        "description": "未登錄或管理員會話無效（ADMIN_AUTH_ENABLED=true 時）",
    },
}


def _bad_request(exc: Exception, *, error: str = "validation_error") -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"error": error, "message": str(exc)},
    )


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"error": "not_found", "message": str(exc)},
    )


def _internal_error(message: str, exc: Exception) -> HTTPException:
    logger.error("%s: %s", message, exc, exc_info=True)
    return HTTPException(
        status_code=500,
        detail={"error": "internal_error", "message": message},
    )


@router.post(
    "",
    response_model=DecisionSignalMutationResponse,
    responses={
        **AUTH_RESPONSE,
        400: {"model": ErrorResponse, "description": "請求字段非法"},
        422: {"model": ErrorResponse, "description": "請求體或路徑參數校驗失敗"},
        500: {"model": ErrorResponse, "description": "創建失敗"},
    },
    summary="創建或去重決策信號",
    description=(
        "顯式寫入 DecisionSignal。未傳 horizon/expires_at 時由服務補默認生命周期；"
        "命中同源去重鍵或窄 relaxed 去重時返回已有記錄和 created=false；"
        "active 新建或 expired 續期會失效同股舊 active 相反信號，"
        "active duplicate retry 也會重跑該修復；普通舊 duplicate/replay 不作爲新的激活事件；"
        "不保證並發絕對冪等。"
    ),
    operation_id="createDecisionSignal",
)
def create_signal(request: DecisionSignalCreateRequest) -> DecisionSignalMutationResponse:
    service = DecisionSignalService()
    try:
        payload = request.model_dump(exclude_unset=True)
        return DecisionSignalMutationResponse(**service.create_signal(payload))
    except DecisionSignalStorageError as exc:
        raise _internal_error("Create decision signal failed", exc)
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Create decision signal failed", exc)


@router.get(
    "",
    response_model=DecisionSignalListResponse,
    responses={
        **AUTH_RESPONSE,
        400: {"model": ErrorResponse, "description": "查詢參數非法"},
        422: {"model": ErrorResponse, "description": "查詢參數校驗失敗"},
        500: {"model": ErrorResponse, "description": "查詢失敗"},
    },
    summary="查詢決策信號列表",
    description=(
        "分頁查詢 DecisionSignal；讀取前會懶過期已到 expires_at 的 active 信號。"
        "當 source_type=analysis 且只傳 source_report_id 查詢時，若無命中信號會嘗試基於該歷史報告一次性懶回填 "
        "（僅首次命中列表場景，且該精確查詢會觸發歷史決策信號回填寫入，屬於 read-with-write 行爲；"
        "不影響其他分頁列表篩選參數場景）。"
        "holding_only=true 只讀取 active 賬戶的 portfolio_positions 緩存持倉，不觸發 portfolio snapshot replay。"
    ),
    operation_id="listDecisionSignals",
)
def list_signals(
    market: Optional[str] = Query(None, description="Optional market filter: cn/hk/us/jp/kr"),
    stock_code: Optional[str] = Query(None, description="Optional stock code filter"),
    action: Optional[str] = Query(None, description="Optional decision action filter"),
    market_phase: Optional[str] = Query(None, description="Optional market phase filter"),
    source_type: Optional[str] = Query(None, description="Optional source type filter"),
    source_report_id: Optional[int] = Query(None, description="Optional source report id filter"),
    trace_id: Optional[str] = Query(None, description="Optional trace id filter"),
    trigger_source: Optional[str] = Query(None, description="Optional trigger source filter"),
    status: Optional[str] = Query(None, description="Optional status filter"),
    created_from: Optional[str] = Query(None, description="Inclusive created_at lower bound"),
    created_to: Optional[str] = Query(None, description="Inclusive created_at upper bound"),
    expires_from: Optional[str] = Query(None, description="Inclusive expires_at lower bound"),
    expires_to: Optional[str] = Query(None, description="Inclusive expires_at upper bound"),
    holding_only: bool = Query(False, description="Filter to active cached portfolio holdings only"),
    account_id: Optional[int] = Query(
        None,
        description="Optional active portfolio account id for holding_only",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> DecisionSignalListResponse:
    service = DecisionSignalService()
    try:
        return DecisionSignalListResponse(
            **service.list_signals(
                market=market,
                stock_code=stock_code,
                action=action,
                market_phase=market_phase,
                source_type=source_type,
                source_report_id=source_report_id,
                trace_id=trace_id,
                trigger_source=trigger_source,
                status=status,
                created_from=created_from,
                created_to=created_to,
                expires_from=expires_from,
                expires_to=expires_to,
                holding_only=holding_only,
                account_id=account_id,
                page=page,
                page_size=page_size,
            )
        )
    except DecisionSignalStorageError as exc:
        raise _internal_error("List decision signals failed", exc)
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("List decision signals failed", exc)


@router.post(
    "/outcomes/run",
    response_model=DecisionSignalOutcomeRunResponse,
    responses={
        **AUTH_RESPONSE,
        400: {"model": ErrorResponse, "description": "請求字段非法"},
        404: {"model": ErrorResponse, "description": "信號不存在"},
        422: {"model": ErrorResponse, "description": "請求體校驗失敗"},
        500: {"model": ErrorResponse, "description": "後驗計算失敗"},
    },
    summary="觸發決策信號後驗評估",
    description=(
        "顯式觸發 signal-level outcome 計算；默認跳過 completed 和終態 unable，"
        "但會重算缺少行情數據等可恢復 unable；force=true 會重算並覆蓋同一 "
        "signal_id+horizon+engine_version。"
    ),
    operation_id="runDecisionSignalOutcomes",
)
def run_outcomes(request: DecisionSignalOutcomeRunRequest) -> DecisionSignalOutcomeRunResponse:
    service = DecisionSignalOutcomeService()
    try:
        return DecisionSignalOutcomeRunResponse(
            **service.run_outcomes(
                signal_id=request.signal_id,
                horizons=request.horizons,
                force=request.force,
                market=request.market,
                stock_code=request.stock_code,
                action=request.action,
                source_type=request.source_type,
                status=request.status,
                limit=request.limit,
            )
        )
    except DecisionSignalNotFoundError as exc:
        raise _not_found(exc)
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Run decision signal outcomes failed", exc)


@router.get(
    "/outcomes",
    response_model=DecisionSignalOutcomeListResponse,
    responses={
        **AUTH_RESPONSE,
        400: {"model": ErrorResponse, "description": "查詢參數非法"},
        422: {"model": ErrorResponse, "description": "查詢參數校驗失敗"},
        500: {"model": ErrorResponse, "description": "查詢失敗"},
    },
    summary="查詢決策信號後驗結果",
    description="分頁查詢 signal-level outcome；默認只查當前 signal 後驗 engine_version。",
    operation_id="listDecisionSignalOutcomes",
)
def list_outcomes(
    signal_id: Optional[int] = Query(None, gt=0),
    horizon: Optional[str] = Query(None),
    engine_version: Optional[str] = Query(None),
    eval_status: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> DecisionSignalOutcomeListResponse:
    service = DecisionSignalOutcomeService()
    try:
        return DecisionSignalOutcomeListResponse(
            **service.list_outcomes(
                signal_id=signal_id,
                horizon=horizon,
                engine_version=engine_version,
                eval_status=eval_status,
                outcome=outcome,
                page=page,
                page_size=page_size,
            )
        )
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("List decision signal outcomes failed", exc)


@router.get(
    "/outcomes/stats",
    response_model=DecisionSignalOutcomeStatsResponse,
    responses={
        **AUTH_RESPONSE,
        400: {"model": ErrorResponse, "description": "查詢參數非法"},
        422: {"model": ErrorResponse, "description": "查詢參數校驗失敗"},
        500: {"model": ErrorResponse, "description": "統計失敗"},
    },
    summary="查詢決策信號後驗統計",
    description="默認統計當前 engine_version，且排除 archived 信號。",
    operation_id="getDecisionSignalOutcomeStats",
)
def get_outcome_stats(
    horizons: Optional[List[str]] = Query(None),
    engine_version: Optional[str] = Query(None),
    statuses: Optional[List[str]] = Query(None),
) -> DecisionSignalOutcomeStatsResponse:
    service = DecisionSignalOutcomeService()
    try:
        return DecisionSignalOutcomeStatsResponse(
            **service.get_stats(
                horizons=horizons,
                engine_version=engine_version,
                statuses=statuses,
            )
        )
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Get decision signal outcome stats failed", exc)


@router.get(
    "/latest/{stock_code}",
    response_model=DecisionSignalListResponse,
    responses={
        **AUTH_RESPONSE,
        400: {"model": ErrorResponse, "description": "請求參數非法"},
        422: {"model": ErrorResponse, "description": "路徑或查詢參數校驗失敗"},
        500: {"model": ErrorResponse, "description": "查詢失敗"},
    },
    summary="查詢股票最新 active 決策信號",
    description="返回指定股票最新 active 信號列表；讀取前會執行懶過期。",
    operation_id="getLatestDecisionSignals",
)
def get_latest_active(
    stock_code: str,
    market: Optional[str] = Query(None, description="Optional market filter: cn/hk/us/jp/kr"),
    limit: int = Query(1, ge=1, le=100),
) -> DecisionSignalListResponse:
    service = DecisionSignalService()
    try:
        return DecisionSignalListResponse(
            **service.get_latest_active(
                stock_code=stock_code,
                market=market,
                limit=limit,
            )
        )
    except DecisionSignalStorageError as exc:
        raise _internal_error("Get latest decision signals failed", exc)
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Get latest decision signals failed", exc)


@router.get(
    "/{signal_id}",
    response_model=DecisionSignalItem,
    responses={
        **AUTH_RESPONSE,
        404: {"model": ErrorResponse, "description": "信號不存在"},
        422: {"model": ErrorResponse, "description": "路徑參數校驗失敗"},
        500: {"model": ErrorResponse, "description": "查詢失敗"},
    },
    summary="查詢單條決策信號",
    description="按 ID 查詢單條 DecisionSignal；讀取前會執行懶過期。",
    operation_id="getDecisionSignal",
)
def get_signal(signal_id: int) -> DecisionSignalItem:
    service = DecisionSignalService()
    try:
        return DecisionSignalItem(**service.get_signal(signal_id))
    except DecisionSignalNotFoundError as exc:
        raise _not_found(exc)
    except DecisionSignalStorageError as exc:
        raise _internal_error("Get decision signal failed", exc)
    except Exception as exc:
        raise _internal_error("Get decision signal failed", exc)


@router.get(
    "/{signal_id}/outcomes",
    response_model=DecisionSignalOutcomeListResponse,
    responses={
        **AUTH_RESPONSE,
        404: {"model": ErrorResponse, "description": "信號不存在"},
        422: {"model": ErrorResponse, "description": "路徑參數校驗失敗"},
        500: {"model": ErrorResponse, "description": "查詢失敗"},
    },
    summary="查詢單個決策信號後驗結果",
    description="返回指定 signal_id 在當前 engine_version 下的後驗結果。",
    operation_id="listDecisionSignalOutcomesBySignal",
)
def list_signal_outcomes(signal_id: int) -> DecisionSignalOutcomeListResponse:
    service = DecisionSignalOutcomeService()
    try:
        return DecisionSignalOutcomeListResponse(**service.list_signal_outcomes(signal_id))
    except DecisionSignalNotFoundError as exc:
        raise _not_found(exc)
    except Exception as exc:
        raise _internal_error("List decision signal outcomes failed", exc)


@router.get(
    "/{signal_id}/feedback",
    response_model=DecisionSignalFeedbackItem,
    responses={
        **AUTH_RESPONSE,
        404: {"model": ErrorResponse, "description": "信號不存在"},
        422: {"model": ErrorResponse, "description": "路徑參數校驗失敗"},
        500: {"model": ErrorResponse, "description": "查詢失敗"},
    },
    summary="查詢決策信號用戶反饋",
    description="沒有反饋時返回 feedback_value=null；信號不存在時返回 404。",
    operation_id="getDecisionSignalFeedback",
)
def get_feedback(signal_id: int) -> DecisionSignalFeedbackItem:
    service = DecisionSignalOutcomeService()
    try:
        return DecisionSignalFeedbackItem(**service.get_feedback(signal_id))
    except DecisionSignalNotFoundError as exc:
        raise _not_found(exc)
    except Exception as exc:
        raise _internal_error("Get decision signal feedback failed", exc)


@router.put(
    "/{signal_id}/feedback",
    response_model=DecisionSignalFeedbackItem,
    responses={
        **AUTH_RESPONSE,
        400: {"model": ErrorResponse, "description": "請求字段非法"},
        404: {"model": ErrorResponse, "description": "信號不存在"},
        422: {"model": ErrorResponse, "description": "請求體或路徑參數校驗失敗"},
        500: {"model": ErrorResponse, "description": "更新失敗"},
    },
    summary="寫入決策信號用戶反饋",
    description="按 signal_id upsert 最新 useful/not_useful 反饋。",
    operation_id="putDecisionSignalFeedback",
)
def put_feedback(signal_id: int, request: DecisionSignalFeedbackRequest) -> DecisionSignalFeedbackItem:
    service = DecisionSignalOutcomeService()
    try:
        return DecisionSignalFeedbackItem(
            **service.put_feedback(
                signal_id,
                feedback_value=request.feedback_value,
                reason_code=request.reason_code,
                note=request.note,
                source=request.source,
            )
        )
    except DecisionSignalNotFoundError as exc:
        raise _not_found(exc)
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Put decision signal feedback failed", exc)


@router.patch(
    "/{signal_id}/status",
    response_model=DecisionSignalItem,
    responses={
        **AUTH_RESPONSE,
        400: {"model": ErrorResponse, "description": "狀態非法"},
        404: {"model": ErrorResponse, "description": "信號不存在"},
        422: {"model": ErrorResponse, "description": "請求體或路徑參數校驗失敗"},
        500: {"model": ErrorResponse, "description": "更新失敗"},
    },
    summary="更新決策信號狀態",
    description=(
        "只更新合法狀態和可選 metadata；傳入 metadata 時按整包替換保存。"
        "expired/invalidated/closed/archived 等 terminal 狀態不能直接 PATCH 回 active。"
    ),
    operation_id="updateDecisionSignalStatus",
)
def update_status(signal_id: int, request: DecisionSignalStatusUpdateRequest) -> DecisionSignalItem:
    service = DecisionSignalService()
    try:
        return DecisionSignalItem(
            **service.update_status(
                signal_id,
                status=request.status,
                metadata=request.metadata,
                replace_metadata="metadata" in request.model_fields_set,
            )
        )
    except DecisionSignalNotFoundError as exc:
        raise _not_found(exc)
    except DecisionSignalStorageError as exc:
        raise _internal_error("Update decision signal status failed", exc)
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Update decision signal status failed", exc)
