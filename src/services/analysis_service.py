# -*- coding: utf-8 -*-
"""
===================================
分析服務層
===================================

職責：
1. 封裝股票分析邏輯
2. 調用 analyzer 和 pipeline 執行分析
3. 保存分析結果到數據庫
"""

import logging
import copy
import uuid
from typing import Optional, Dict, Any, Callable, List

from src.repositories.analysis_repo import AnalysisRepository
from src.report_language import (
    get_sentiment_label,
    get_localized_stock_name,
    localize_operation_advice,
    localize_trend_prediction,
    normalize_report_language,
)
from src.market_phase_summary import extract_market_phase_summary
from src.schemas.decision_action import build_action_fields
from src.services.run_diagnostics import (
    activate_run_diagnostic_context,
    build_run_diagnostic_summary,
    get_current_diagnostic_context,
    reset_run_diagnostic_context,
)

logger = logging.getLogger(__name__)


class AnalysisService:
    """
    分析服務
    
    封裝股票分析相關的業務邏輯
    """
    
    def __init__(self):
        """初始化分析服務"""
        self.repo = AnalysisRepository()
        self.last_error: Optional[str] = None
    
    def analyze_stock(
        self,
        stock_code: str,
        report_type: str = "detailed",
        force_refresh: bool = False,
        query_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        send_notification: bool = True,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        skills: Optional[List[str]] = None,
        analysis_phase: str = "auto",
        query_source: str = "api",
        portfolio_context: Optional[Dict[str, Any]] = None,
        report_language: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        執行股票分析
        
        Args:
            stock_code: 股票代碼
            report_type: 報告類型 (simple/detailed)
            force_refresh: 是否強制刷新
            query_id: 查詢 ID（可選）
            send_notification: 是否發送通知（API 觸發默認發送）
            analysis_phase: 請求的分析階段覆蓋（auto/premarket/intraday/postmarket）
            
        Returns:
            分析結果字典，包含:
            - stock_code: 股票代碼
            - stock_name: 股票名稱
            - report: 分析報告
        """
        try:
            self.last_error = None
            # 導入分析相關模塊
            from src.config import get_config
            from src.core.pipeline import StockAnalysisPipeline
            from src.enums import ReportType
            
            # 生成 query_id
            if query_id is None:
                query_id = uuid.uuid4().hex
            effective_trace_id = trace_id or query_id
            diag_token = None
            if get_current_diagnostic_context() is None:
                diag_token = activate_run_diagnostic_context(
                    trace_id=effective_trace_id,
                    query_id=query_id,
                    stock_code=stock_code,
                    trigger_source=query_source or "api",
                )
            
            # 獲取配置
            config = get_config()
            normalized_report_language = normalize_report_language(report_language, default="")
            if normalized_report_language:
                config = copy.copy(config)
                config.report_language = normalized_report_language
            
            # 創建分析流水線
            pipeline = StockAnalysisPipeline(
                config=config,
                query_id=query_id,
                trace_id=effective_trace_id,
                query_source=query_source or "api",
                progress_callback=progress_callback,
                analysis_skills=skills,
                analysis_phase=analysis_phase,
                portfolio_context=portfolio_context,
            )
            
            # 確定報告類型 (API: simple/detailed/full/brief -> ReportType)
            rt = ReportType.from_str(report_type)
            
            # 執行分析
            result = pipeline.process_single_stock(
                code=stock_code,
                skip_analysis=False,
                single_stock_notify=send_notification,
                report_type=rt,
            )
            
            if result is None:
                logger.warning(f"分析股票 {stock_code} 返回空結果")
                self.last_error = self.last_error or f"分析股票 {stock_code} 返回空結果"
                return None

            if not getattr(result, "success", True):
                self.last_error = getattr(result, "error_message", None) or f"分析股票 {stock_code} 失敗"
                logger.warning(f"分析股票 {stock_code} 未成功完成: {self.last_error}")
                return None
            
            # 構建響應
            return self._build_analysis_response(result, query_id, report_type=rt.value)
            
        except Exception as e:
            self.last_error = str(e)
            logger.error(f"分析股票 {stock_code} 失敗: {e}", exc_info=True)
            return None
        finally:
            reset_run_diagnostic_context(locals().get("diag_token"))
    
    def _build_analysis_response(
        self, 
        result: Any, 
        query_id: str,
        report_type: str = "detailed",
    ) -> Dict[str, Any]:
        """
        構建分析響應
        
        Args:
            result: AnalysisResult 對象
            query_id: 查詢 ID
            report_type: 歸一化後的報告類型
            
        Returns:
            格式化的響應字典
        """
        # 獲取狙擊點位
        sniper_points = {}
        if hasattr(result, 'get_sniper_points'):
            sniper_points = result.get_sniper_points() or {}
        
        # 計算情緒標籤
        report_language = normalize_report_language(getattr(result, "report_language", "zh"))
        sentiment_label = get_sentiment_label(result.sentiment_score, report_language)
        stock_name = get_localized_stock_name(getattr(result, "name", None), result.code, report_language)
        action_fields = build_action_fields(
            operation_advice=getattr(result, "operation_advice", None),
            explicit_action=getattr(result, "action", None),
            report_type=report_type,
            report_language=report_language,
        )
        diagnostic_context = get_current_diagnostic_context()
        trace_id = diagnostic_context.trace_id if diagnostic_context is not None else query_id
        diagnostic_snapshot = diagnostic_context.snapshot() if diagnostic_context is not None else None
        diagnostic_context_snapshot = getattr(result, "diagnostic_context_snapshot", None)
        market_phase_summary = extract_market_phase_summary(diagnostic_context_snapshot)
        if isinstance(diagnostic_context_snapshot, dict):
            context_snapshot = dict(diagnostic_context_snapshot)
            if diagnostic_snapshot is not None:
                context_snapshot["diagnostics"] = diagnostic_snapshot
        elif diagnostic_snapshot is not None:
            context_snapshot = {"diagnostics": diagnostic_snapshot}
        else:
            context_snapshot = None
        diagnostic_summary = build_run_diagnostic_summary(
            context_snapshot=context_snapshot,
            raw_result=result.to_dict() if hasattr(result, "to_dict") else None,
            report_saved=True,
            query_id=query_id,
            stock_code=result.code,
        )
        
        # 構建報告結構
        report = {
            "meta": {
                "query_id": query_id,
                "trace_id": trace_id,
                "stock_code": result.code,
                "stock_name": stock_name,
                "report_type": report_type,
                "report_language": report_language,
                "current_price": result.current_price,
                "change_pct": result.change_pct,
                "model_used": getattr(result, "model_used", None),
                "market_phase_summary": market_phase_summary,
            },
            "summary": {
                "analysis_summary": result.analysis_summary,
                "operation_advice": localize_operation_advice(result.operation_advice, report_language),
                "action": action_fields["action"],
                "action_label": action_fields["action_label"],
                "trend_prediction": localize_trend_prediction(result.trend_prediction, report_language),
                "sentiment_score": result.sentiment_score,
                "sentiment_label": sentiment_label,
            },
            "strategy": {
                "ideal_buy": sniper_points.get("ideal_buy"),
                "secondary_buy": sniper_points.get("secondary_buy"),
                "stop_loss": sniper_points.get("stop_loss"),
                "take_profit": sniper_points.get("take_profit"),
            },
            "details": {
                "news_summary": result.news_summary,
                "technical_analysis": result.technical_analysis,
                "fundamental_analysis": result.fundamental_analysis,
                "risk_warning": result.risk_warning,
            }
        }
        
        return {
            "query_id": query_id,
            "trace_id": trace_id,
            "stock_code": result.code,
            "stock_name": stock_name,
            "report": report,
            "diagnostic_summary": diagnostic_summary,
        }
