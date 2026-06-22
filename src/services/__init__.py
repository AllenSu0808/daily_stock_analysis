# -*- coding: utf-8 -*-
"""
===================================
服務層模塊初始化
===================================

職責：
1. 聲明可導出的服務類（延遲導入，避免啓動時拉入 LLM 等重依賴）

使用方式：
    直接從子模塊導入，例如:
    from src.services.history_service import HistoryService
"""


def __getattr__(name: str):
    """延遲導入：僅在通過 src.services.X 訪問時才加載對應子模塊。"""
    _lazy_map = {
        "AnalysisService": "src.services.analysis_service",
        "BacktestService": "src.services.backtest_service",
        "HistoryService": "src.services.history_service",
        "StockService": "src.services.stock_service",
        "TaskService": "src.services.task_service",
        "get_task_service": "src.services.task_service",
    }
    if name in _lazy_map:
        import importlib
        module = importlib.import_module(_lazy_map[name])
        return getattr(module, name)
    raise AttributeError(f"module 'src.services' has no attribute {name!r}")


__all__ = [
    "AnalysisService",
    "BacktestService",
    "HistoryService",
    "StockService",
    "TaskService",
    "get_task_service",
]
