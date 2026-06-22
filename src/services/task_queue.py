# -*- coding: utf-8 -*-
"""
===================================
A股自選股智能分析系統 - 異步任務隊列
===================================

職責：
1. 管理異步分析任務的生命周期
2. 防止相同股票代碼重複提交
3. 提供 SSE 事件廣播機制
4. 任務完成後持久化到數據庫
"""

from __future__ import annotations

import asyncio
import copy
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, List, Any, TYPE_CHECKING, Tuple, Literal, Callable

if TYPE_CHECKING:
    from asyncio import Queue as AsyncQueue

from data_provider.base import canonical_stock_code, normalize_stock_code
from src.services.run_diagnostics import (
    activate_run_diagnostic_context,
    get_current_diagnostic_context,
    reset_run_diagnostic_context,
)
from src.utils.analysis_metadata import SELECTION_SOURCES
from src.services.stock_code_utils import resolve_index_stock_code_for_analysis

logger = logging.getLogger(__name__)


def _dedupe_stock_code_key(stock_code: str) -> str:
    """
    Build the internal duplicate-detection key for a stock code.

    The task queue should treat equivalent market code shapes as the same
    underlying stock, e.g. ``600519`` and ``600519.SH``.
    """
    return resolve_index_stock_code_for_analysis(normalize_stock_code(stock_code))


class TaskStatus(str, Enum):
    """Task status enumeration"""
    PENDING = "pending"        # Waiting for execution
    PROCESSING = "processing"  # In progress
    COMPLETED = "completed"    # Completed
    FAILED = "failed"          # Failed
    CANCEL_REQUESTED = "cancel_requested"  # Cancellation requested
    CANCELLED = "cancelled"    # Cancelled by user/system


@dataclass
class TaskInfo:
    """
    Task information dataclass.

    Used for API responses and internal task management.
    """
    task_id: str
    stock_code: str
    stock_name: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0
    message: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    report_type: str = "detailed"
    analysis_phase: str = "auto"
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    original_query: Optional[str] = None
    selection_source: Optional[str] = None
    query_source: str = "api"
    portfolio_context: Optional[Dict[str, Any]] = None
    skills: Optional[List[str]] = None
    report_language: Optional[str] = None
    trace_id: Optional[str] = None
    flow_events: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert task info into an API-friendly dictionary."""
        return {
            "task_id": self.task_id,
            "trace_id": self.trace_id or self.task_id,
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "status": self.status.value,
            "progress": self.progress,
            "message": self.message,
            "report_type": self.report_type,
            "analysis_phase": self.analysis_phase,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error,
            "original_query": self.original_query,
            "selection_source": self.selection_source,
            "skills": self.skills,
        }
    
    def copy(self) -> 'TaskInfo':
        """Create a shallow copy of the task information."""
        return TaskInfo(
            task_id=self.task_id,
            stock_code=self.stock_code,
            stock_name=self.stock_name,
            status=self.status,
            progress=self.progress,
            message=self.message,
            result=self.result,
            error=self.error,
            report_type=self.report_type,
            analysis_phase=self.analysis_phase,
            created_at=self.created_at,
            started_at=self.started_at,
            completed_at=self.completed_at,
            original_query=self.original_query,
            selection_source=self.selection_source,
            query_source=self.query_source,
            portfolio_context=dict(self.portfolio_context) if isinstance(self.portfolio_context, dict) else None,
            skills=list(self.skills) if self.skills is not None else None,
            report_language=self.report_language,
            trace_id=self.trace_id or self.task_id,
            flow_events=copy.deepcopy(self.flow_events),
        )


class DuplicateTaskError(Exception):
    """
    重複提交異常
    
    當股票已在分析中時拋出此異常
    """
    def __init__(self, stock_code: str, existing_task_id: str):
        self.stock_code = stock_code
        self.existing_task_id = existing_task_id
        super().__init__(f"股票 {stock_code} 正在分析中 (task_id: {existing_task_id})")


class AnalysisTaskQueue:
    """
    異步分析任務隊列
    
    單例模式，全局唯一實例
    
    特性：
    1. 防止相同股票代碼重複提交
    2. 線程池執行分析任務
    3. SSE 事件廣播機制
    4. 任務完成後自動持久化
    """
    
    _instance: Optional['AnalysisTaskQueue'] = None
    _instance_lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, max_workers: int = 3):
        # 防止重複初始化
        if hasattr(self, '_initialized') and self._initialized:
            return
        
        self._max_workers = max_workers
        self._executor: Optional[ThreadPoolExecutor] = None
        
        # 核心數據結構
        self._tasks: Dict[str, TaskInfo] = {}           # task_id -> TaskInfo
        self._analyzing_stocks: Dict[str, str] = {}     # dedupe_key -> task_id
        self._futures: Dict[str, Future] = {}           # task_id -> Future
        
        # SSE 訂閱者列表（asyncio.Queue 實例）
        self._subscribers: List['AsyncQueue'] = []
        self._subscribers_lock = threading.Lock()
        
        # 主事件循環引用（用於跨線程廣播）
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None
        
        # 線程安全鎖
        self._data_lock = threading.RLock()
        
        # 任務歷史保留數量（內存中）
        self._max_history = 100
        self._max_flow_events_per_task = 200
        
        self._initialized = True
        logger.info(f"[TaskQueue] 初始化完成，最大並發: {max_workers}")
    
    @property
    def executor(self) -> ThreadPoolExecutor:
        """懶加載線程池"""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=self._max_workers,
                thread_name_prefix="analysis_task_"
            )
        return self._executor

    @property
    def max_workers(self) -> int:
        """Return current executor max worker setting."""
        return self._max_workers

    def _has_inflight_tasks_locked(self) -> bool:
        """Check whether queue has any pending/processing tasks."""
        if self._analyzing_stocks:
            return True
        return any(
            task.status in (TaskStatus.PENDING, TaskStatus.PROCESSING)
            for task in self._tasks.values()
        )

    def sync_max_workers(
        self,
        max_workers: int,
        *,
        log: bool = True,
    ) -> Literal["applied", "unchanged", "deferred_busy"]:
        """
        Try to sync queue concurrency without replacing singleton instance.

        Returns:
            - "applied": new value applied immediately (idle queue only)
            - "unchanged": target equals current value or invalid target
            - "deferred_busy": queue is busy, apply is deferred
        """
        try:
            target = max(1, int(max_workers))
        except (TypeError, ValueError):
            if log:
                logger.warning("[TaskQueue] 忽略非法 MAX_WORKERS 值: %r", max_workers)
            return "unchanged"

        executor_to_shutdown: Optional[ThreadPoolExecutor] = None
        previous: int
        with self._data_lock:
            previous = self._max_workers
            if target == previous:
                return "unchanged"

            if self._has_inflight_tasks_locked():
                if log:
                    logger.info(
                        "[TaskQueue] 最大並發調整延後: 當前繁忙 (%s -> %s)",
                        previous,
                        target,
                    )
                return "deferred_busy"

            self._max_workers = target
            executor_to_shutdown = self._executor
            self._executor = None

        if executor_to_shutdown is not None:
            executor_to_shutdown.shutdown(wait=False)

        if log:
            logger.info("[TaskQueue] 最大並發已更新: %s -> %s", previous, target)
        return "applied"
    
    # ========== 任務提交與查詢 ==========
    
    def is_analyzing(self, stock_code: str) -> bool:
        """
        檢查股票是否正在分析中
        
        Args:
            stock_code: 股票代碼
            
        Returns:
            True 表示正在分析中
        """
        dedupe_key = _dedupe_stock_code_key(stock_code)
        with self._data_lock:
            return dedupe_key in self._analyzing_stocks
    
    def get_analyzing_task_id(self, stock_code: str) -> Optional[str]:
        """
        獲取正在分析該股票的任務 ID
        
        Args:
            stock_code: 股票代碼
            
        Returns:
            任務 ID，如果沒有則返回 None
        """
        dedupe_key = _dedupe_stock_code_key(stock_code)
        with self._data_lock:
            return self._analyzing_stocks.get(dedupe_key)

    def validate_selection_source(self, selection_source: Optional[str]) -> None:
        """
        Validate the selection source parameter.

        Args:
            selection_source: Selection source label.

        Raises:
            ValueError: Raised when the selection source is invalid.
        """
        if selection_source is not None and selection_source not in SELECTION_SOURCES:
            raise ValueError(
                f"Invalid selection_source: {selection_source}. "
                f"Must be one of {SELECTION_SOURCES}"
            )
    
    def submit_task(
        self,
        stock_code: str,
        stock_name: Optional[str] = None,
        original_query: Optional[str] = None,
        selection_source: Optional[str] = None,
        query_source: str = "api",
        portfolio_context: Optional[Dict[str, Any]] = None,
        report_type: str = "detailed",
        analysis_phase: str = "auto",
        force_refresh: bool = False,
        skills: Optional[List[str]] = None,
        report_language: Optional[str] = None,
    ) -> TaskInfo:
        """
        Submit a single analysis task.

        Args:
            stock_code: Stock code
            stock_name: Optional stock name
            original_query: Optional raw user input
            selection_source: Optional source label
            report_type: Report type
            analysis_phase: Requested analysis phase override
            force_refresh: Whether to bypass cache

        Returns:
            TaskInfo: Accepted task information

        Raises:
            DuplicateTaskError: Raised when the stock is already being analyzed
        """
        stock_code = resolve_index_stock_code_for_analysis(stock_code)
        if not stock_code:
            raise ValueError("股票代碼不能爲空或僅包含空白字符")

        accepted, duplicates = self.submit_tasks_batch(
            [stock_code],
            stock_name=stock_name,
            original_query=original_query,
            selection_source=selection_source,
            query_source=query_source,
            portfolio_context=portfolio_context,
            report_type=report_type,
            analysis_phase=analysis_phase,
            force_refresh=force_refresh,
            skills=skills,
            report_language=report_language,
        )
        if duplicates:
            raise duplicates[0]
        return accepted[0]

    def submit_tasks_batch(
        self,
        stock_codes: List[str],
        stock_name: Optional[str] = None,
        original_query: Optional[str] = None,
        selection_source: Optional[str] = None,
        query_source: str = "api",
        portfolio_context: Optional[Dict[str, Any]] = None,
        report_type: str = "detailed",
        analysis_phase: str = "auto",
        force_refresh: bool = False,
        notify: bool = True,
        skills: Optional[List[str]] = None,
        report_language: Optional[str] = None,
    ) -> Tuple[List[TaskInfo], List[DuplicateTaskError]]:
        """
        Submit analysis tasks in batch.

        - Duplicate stocks are skipped and recorded in duplicates.
        - If executor submission fails, the current batch is rolled back.
        """
        self.validate_selection_source(selection_source)

        accepted: List[TaskInfo] = []
        duplicates: List[DuplicateTaskError] = []
        created_task_ids: List[str] = []

        canonical_codes = [
            normalized for normalized in (resolve_index_stock_code_for_analysis(code) for code in stock_codes)
            if normalized
        ]

        with self._data_lock:
            for stock_code in canonical_codes:
                dedupe_key = _dedupe_stock_code_key(stock_code)
                if dedupe_key in self._analyzing_stocks:
                    existing_task_id = self._analyzing_stocks[dedupe_key]
                    duplicates.append(DuplicateTaskError(stock_code, existing_task_id))
                    continue

                task_id = uuid.uuid4().hex
                task_skills = list(skills) if skills is not None else None
                task_info = TaskInfo(
                    task_id=task_id,
                    trace_id=task_id,
                    stock_code=stock_code,
                    stock_name=stock_name,
                    status=TaskStatus.PENDING,
                    message="任務已加入隊列",
                    report_type=report_type,
                    analysis_phase=analysis_phase or "auto",
                    original_query=original_query,
                    selection_source=selection_source,
                    query_source=query_source or "api",
                    portfolio_context=dict(portfolio_context) if isinstance(portfolio_context, dict) else None,
                    skills=task_skills,
                    report_language=report_language,
                )
                self._tasks[task_id] = task_info
                self._analyzing_stocks[dedupe_key] = task_id

                try:
                    future = self.executor.submit(
                        self._execute_task,
                        task_id,
                        stock_code,
                        report_type,
                        force_refresh,
                        notify,
                        task_skills,
                        report_language,
                    )
                except Exception:
                    # Roll back the current batch to avoid partial submission.
                    self._rollback_submitted_tasks_locked(created_task_ids + [task_id])
                    raise

                self._futures[task_id] = future
                accepted.append(task_info)
                created_task_ids.append(task_id)
                logger.info(f"[TaskQueue] 任務已提交: {stock_code} -> {task_id}")

            # Keep task_created ordered before worker-emitted task_started/task_completed.
            # Broadcasting here also preserves batch rollback semantics because we only
            # reach this point after every submit in the batch has succeeded.
            for task_info in accepted:
                self._broadcast_event("task_created", task_info.to_dict())

        return accepted, duplicates

    def submit_background_task(
        self,
        run_task: Callable[[], Optional[Any]],
        *,
        stock_code: str,
        stock_name: Optional[str] = None,
        report_type: str = "detailed",
        message: Optional[str] = "任務已加入隊列",
        task_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> TaskInfo:
        """
        Submit a generic background callable with task lifecycle tracking.

        This is used by callers that need task status visibility but do not
        map to standard per-stock async analysis flow.
        """
        task_id = task_id or uuid.uuid4().hex
        task_info = TaskInfo(
            task_id=task_id,
            trace_id=trace_id or task_id,
            stock_code=stock_code,
            stock_name=stock_name,
            status=TaskStatus.PENDING,
            message=message,
            report_type=report_type,
        )

        with self._data_lock:
            if task_id in self._tasks:
                raise ValueError(f"任務 ID 已存在: {task_id}")
            self._tasks[task_id] = task_info
            try:
                future = self.executor.submit(self._execute_background_task, task_id, run_task)
            except Exception:
                del self._tasks[task_id]
                raise

            self._futures[task_id] = future
            self._broadcast_event("task_created", task_info.to_dict())

        return task_info.copy()

    def _rollback_submitted_tasks_locked(self, task_ids: List[str]) -> None:
        """回滾當前批次已創建但尚未穩定返回給調用方的任務。"""
        for task_id in task_ids:
            future = self._futures.pop(task_id, None)
            if future is not None:
                future.cancel()

            task = self._tasks.pop(task_id, None)
            if task:
                dedupe_key = _dedupe_stock_code_key(task.stock_code)
                if self._analyzing_stocks.get(dedupe_key) == task_id:
                    del self._analyzing_stocks[dedupe_key]
    
    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        """
        獲取任務信息
        
        Args:
            task_id: 任務 ID
            
        Returns:
            TaskInfo 或 None
        """
        with self._data_lock:
            task = self._tasks.get(task_id)
            return task.copy() if task else None

    def append_task_flow_event(
        self,
        task_id: str,
        flow_event: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Append a recent run-flow event to an active task and broadcast it.

        The event cache is deliberately bounded and fail-open; diagnostics must
        never affect the analysis pipeline.
        """
        try:
            event_payload = copy.deepcopy(flow_event)
        except Exception:
            logger.debug("[TaskQueue] 忽略不可複製的運行流事件: task_id=%s", task_id)
            return None

        with self._data_lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            task.flow_events.append(event_payload)
            if len(task.flow_events) > self._max_flow_events_per_task:
                task.flow_events = task.flow_events[-self._max_flow_events_per_task:]
            task_snapshot = task.copy()

        payload = task_snapshot.to_dict()
        payload["flow_event"] = event_payload
        self._broadcast_event("task_progress", payload)
        return event_payload

    def get_task_flow_events(self, task_id: str) -> List[Dict[str, Any]]:
        """Return a copy of the recent run-flow events for a task."""
        with self._data_lock:
            task = self._tasks.get(task_id)
            if not task:
                return []
            return copy.deepcopy(task.flow_events)
    
    def list_pending_tasks(self) -> List[TaskInfo]:
        """
        獲取所有進行中的任務（pending + processing）
        
        Returns:
            任務列表（副本）
        """
        with self._data_lock:
            return [
                task.copy() for task in self._tasks.values()
                if task.status in (TaskStatus.PENDING, TaskStatus.PROCESSING, TaskStatus.CANCEL_REQUESTED)
            ]
    
    def list_all_tasks(self, limit: int = 50) -> List[TaskInfo]:
        """
        獲取所有任務（按創建時間倒序）
        
        Args:
            limit: 返回數量限制
            
        Returns:
            任務列表（副本）
        """
        with self._data_lock:
            tasks = sorted(
                self._tasks.values(),
                key=lambda t: t.created_at,
                reverse=True
            )
            return [t.copy() for t in tasks[:limit]]
    
    def get_task_stats(self) -> Dict[str, int]:
        """
        獲取任務統計信息
        
        Returns:
            統計信息字典
        """
        with self._data_lock:
            stats = {
                "total": len(self._tasks),
                "pending": 0,
                "processing": 0,
                "completed": 0,
                "failed": 0,
            }
            for task in self._tasks.values():
                stats[task.status.value] = stats.get(task.status.value, 0) + 1
            return stats

    def update_task_progress(
        self,
        task_id: str,
        progress: int,
        message: Optional[str] = None,
        *,
        event_type: str = "task_progress",
    ) -> Optional[TaskInfo]:
        """
        Update in-flight task progress and broadcast an SSE event.

        Only pending/processing tasks are updated. Progress is clamped to
        [0, 99] so terminal states remain controlled by completion/failure.
        """
        with self._data_lock:
            task = self._tasks.get(task_id)
            if not task or task.status not in (TaskStatus.PENDING, TaskStatus.PROCESSING):
                return None

            next_progress = max(task.progress, max(0, min(99, int(progress))))
            changed = False
            if next_progress != task.progress:
                task.progress = next_progress
                changed = True
            if message is not None and message != task.message:
                task.message = message
                changed = True

            if not changed:
                return task.copy()

            task_snapshot = task.copy()

        self._broadcast_event(event_type, task_snapshot.to_dict())
        return task_snapshot
    
    # ========== 任務執行 ==========
    
    def _execute_task(
        self,
        task_id: str,
        stock_code: str,
        report_type: str,
        force_refresh: bool,
        notify: bool = True,
        skills: Optional[List[str]] = None,
        report_language: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        執行分析任務（在線程池中運行）
        
        Args:
            task_id: 任務 ID
            stock_code: 股票代碼
            report_type: 報告類型
            force_refresh: 是否強制刷新
            
        Returns:
            分析結果字典
        """
        # 更新狀態爲處理中
        with self._data_lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            trace_id = task.trace_id or task_id
            analysis_phase = task.analysis_phase
            query_source = task.query_source or "api"
            portfolio_context = dict(task.portfolio_context) if isinstance(task.portfolio_context, dict) else None
            task.status = TaskStatus.PROCESSING
            task.started_at = datetime.now()
            task.message = "正在分析中..."
            task.progress = 10
        
        self._broadcast_event("task_started", task.to_dict())
        
        try:
            # 導入分析服務（延遲導入避免循環依賴）
            from src.services.analysis_service import AnalysisService
            
            # 執行分析
            service = AnalysisService()

            def _on_progress(progress: int, message: str) -> None:
                self.update_task_progress(task_id, progress, message)

            diag_token = None
            if get_current_diagnostic_context() is None:
                diag_token = activate_run_diagnostic_context(
                    trace_id=trace_id,
                    task_id=task_id,
                    query_id=task_id,
                    stock_code=stock_code,
                    trigger_source=query_source,
                    event_sink=lambda event: self.append_task_flow_event(task_id, event),
                )
            result = service.analyze_stock(
                stock_code=stock_code,
                report_type=report_type,
                force_refresh=force_refresh,
                query_id=task_id,
                trace_id=trace_id,
                send_notification=notify,
                progress_callback=_on_progress,
                skills=skills,
                analysis_phase=analysis_phase,
                query_source=query_source,
                portfolio_context=portfolio_context,
                report_language=report_language,
            )
            reset_run_diagnostic_context(diag_token)
            diag_token = None
            
            if result:
                # 更新任務狀態爲完成
                with self._data_lock:
                    task = self._tasks.get(task_id)
                    if task:
                        task.status = TaskStatus.COMPLETED
                        task.progress = 100
                        task.completed_at = datetime.now()
                        task.result = result
                        task.message = "分析完成"
                        task.stock_name = result.get("stock_name", task.stock_name)
                        
                        # 從分析中集合移除
                        dedupe_key = _dedupe_stock_code_key(task.stock_code)
                        if dedupe_key in self._analyzing_stocks:
                            del self._analyzing_stocks[dedupe_key]
                
                self._broadcast_event("task_completed", task.to_dict())
                logger.info(f"[TaskQueue] 任務完成: {task_id} ({stock_code})")
                
                # 清理過期任務
                self._cleanup_old_tasks()
                
                return result
            else:
                # 分析返回空結果
                raise Exception(service.last_error or "分析返回空結果")
                
        except Exception as e:
            if "diag_token" in locals():
                reset_run_diagnostic_context(diag_token)
            error_msg = str(e)
            logger.error(f"[TaskQueue] 任務失敗: {task_id} ({stock_code}), 錯誤: {error_msg}")
            
            with self._data_lock:
                task = self._tasks.get(task_id)
                if task:
                    task.status = TaskStatus.FAILED
                    task.completed_at = datetime.now()
                    task.error = error_msg[:200]  # 限制錯誤信息長度
                    task.message = f"分析失敗: {error_msg[:50]}"
                    
                    # 從分析中集合移除
                    dedupe_key = _dedupe_stock_code_key(task.stock_code)
                    if dedupe_key in self._analyzing_stocks:
                        del self._analyzing_stocks[dedupe_key]
            
            self._broadcast_event("task_failed", task.to_dict())
            
            # 清理過期任務
            self._cleanup_old_tasks()
            
            return None

    def _execute_background_task(
        self,
        task_id: str,
        run_task: Callable[[], Optional[Dict[str, Any]]],
    ) -> Optional[Dict[str, Any]]:
        """
        執行通用後臺任務（支持自定義運行邏輯）

        Args:
            task_id: 任務 ID
            run_task: 任務執行函數

        Returns:
            任務執行結果字典（可選）
        """
        with self._data_lock:
            task = self._tasks.get(task_id)
            if not task:
                return None

            trace_id = task.trace_id or task_id
            task.status = TaskStatus.PROCESSING
            task.started_at = datetime.now()
            task.message = "任務執行中"
            task.progress = 10
            self._broadcast_event("task_started", task.to_dict())

        try:
            diag_token = None
            if get_current_diagnostic_context() is None:
                diag_token = activate_run_diagnostic_context(
                    trace_id=trace_id,
                    task_id=task_id,
                    query_id=task_id,
                    stock_code=task.stock_code,
                    trigger_source="api",
                    event_sink=lambda event: self.append_task_flow_event(task_id, event),
                )
            try:
                result = run_task()
            finally:
                reset_run_diagnostic_context(diag_token)
            if result is None:
                raise RuntimeError("任務返回空結果，未生成可持久化內容")

            with self._data_lock:
                task = self._tasks.get(task_id)
                if task:
                    task.status = TaskStatus.COMPLETED
                    task.progress = 100
                    task.completed_at = datetime.now()
                    task.result = result
                    task.message = "任務執行完成"

            self._broadcast_event("task_completed", task.to_dict())
            logger.info(f"[TaskQueue] 自定義任務完成: {task_id}")

            self._cleanup_old_tasks()
            return result

        except Exception as e:  # pragma: no cover - behavior verified in downstream tests
            error_msg = str(e)
            logger.error(
                f"[TaskQueue] 自定義任務失敗: {task_id}, 錯誤: {error_msg}"
            )

            with self._data_lock:
                task = self._tasks.get(task_id)
                if task:
                    task.status = TaskStatus.FAILED
                    task.completed_at = datetime.now()
                    task.error = error_msg[:200]
                    task.message = f"任務失敗: {error_msg[:80]}"

            if task:
                self._broadcast_event("task_failed", task.to_dict())

            self._cleanup_old_tasks()
            return None
    
    def _cleanup_old_tasks(self) -> int:
        """
        清理過期的已完成任務
        
        保留最近 _max_history 個任務
        
        Returns:
            清理的任務數量
        """
        with self._data_lock:
            if len(self._tasks) <= self._max_history:
                return 0
            
            # 按時間排序，刪除舊的已完成任務
            completed_tasks = sorted(
                [t for t in self._tasks.values()
                 if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)],
                key=lambda t: t.created_at
            )
            
            to_remove = len(self._tasks) - self._max_history
            removed = 0
            
            for task in completed_tasks[:to_remove]:
                del self._tasks[task.task_id]
                if task.task_id in self._futures:
                    del self._futures[task.task_id]
                removed += 1
            
            if removed > 0:
                logger.debug(f"[TaskQueue] 清理了 {removed} 個過期任務")
            
            return removed
    
    # ========== SSE 事件廣播 ==========
    
    def subscribe(self, queue: 'AsyncQueue') -> None:
        """
        訂閱任務事件
        
        Args:
            queue: asyncio.Queue 實例，用於接收事件
        """
        with self._subscribers_lock:
            self._subscribers.append(queue)
            # 捕獲當前事件循環（應在主線程的 async 上下文中調用）
            try:
                self._main_loop = asyncio.get_running_loop()
            except RuntimeError:
                # 如果不在 async 上下文中，嘗試獲取事件循環
                try:
                    self._main_loop = asyncio.get_event_loop()
                except RuntimeError:
                    pass
            logger.debug(f"[TaskQueue] 新訂閱者加入，當前訂閱者數: {len(self._subscribers)}")
    
    def unsubscribe(self, queue: 'AsyncQueue') -> None:
        """
        取消訂閱任務事件
        
        Args:
            queue: 要取消訂閱的 asyncio.Queue 實例
        """
        with self._subscribers_lock:
            if queue in self._subscribers:
                self._subscribers.remove(queue)
                logger.debug(f"[TaskQueue] 訂閱者離開，當前訂閱者數: {len(self._subscribers)}")
    
    def _broadcast_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        廣播事件到所有訂閱者
        
        使用 call_soon_threadsafe 確保跨線程安全
        
        Args:
            event_type: 事件類型
            data: 事件數據
        """
        event = {"type": event_type, "data": data}
        
        with self._subscribers_lock:
            subscribers = self._subscribers.copy()
            loop = self._main_loop
        
        if not subscribers:
            return
        
        if loop is None:
            logger.warning("[TaskQueue] 無法廣播事件：主事件循環未設置")
            return
        
        for queue in subscribers:
            try:
                # 使用 call_soon_threadsafe 將事件放入 asyncio 隊列
                # 這是從工作線程向主事件循環發送消息的安全方式
                loop.call_soon_threadsafe(queue.put_nowait, event)
            except RuntimeError as e:
                # 事件循環已關閉
                logger.debug(f"[TaskQueue] 廣播事件跳過（循環已關閉）: {e}")
            except Exception as e:
                logger.warning(f"[TaskQueue] 廣播事件失敗: {e}")
    
    # ========== 清理方法 ==========
    
    def shutdown(self) -> None:
        """關閉任務隊列"""
        if self._executor:
            self._executor.shutdown(wait=True)
            self._executor = None
            logger.info("[TaskQueue] 線程池已關閉")


# ========== 便捷函數 ==========

def get_task_queue() -> AnalysisTaskQueue:
    """
    獲取任務隊列單例
    
    Returns:
        AnalysisTaskQueue 實例
    """
    queue = AnalysisTaskQueue()
    try:
        from src.config import get_config

        config = get_config()
        target_workers = max(1, int(getattr(config, "max_workers", queue.max_workers)))
        queue.sync_max_workers(target_workers, log=False)
    except Exception as exc:
        logger.debug("[TaskQueue] 讀取 MAX_WORKERS 失敗，使用當前並發設置: %s", exc)

    return queue
