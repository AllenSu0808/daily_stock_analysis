# -*- coding: utf-8 -*-
"""
===================================
分析歷史數據訪問層
===================================

職責：
1. 封裝分析歷史數據的數據庫操作
2. 提供 CRUD 接口
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from src.storage import DatabaseManager, AnalysisHistory

logger = logging.getLogger(__name__)


class AnalysisRepository:
    """
    分析歷史數據訪問層
    
    封裝 AnalysisHistory 表的數據庫操作
    """
    
    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        """
        初始化數據訪問層
        
        Args:
            db_manager: 數據庫管理器（可選，默認使用單例）
        """
        self.db = db_manager or DatabaseManager.get_instance()
    
    def get_by_query_id(self, query_id: str) -> Optional[AnalysisHistory]:
        """
        根據 query_id 獲取分析記錄
        
        Args:
            query_id: 查詢 ID
            
        Returns:
            AnalysisHistory 對象，不存在返回 None
        """
        try:
            records = self.db.get_analysis_history(query_id=query_id, limit=1)
            return records[0] if records else None
        except Exception as e:
            logger.error(f"查詢分析記錄失敗: {e}")
            return None
    
    def get_list(
        self,
        code: Optional[str] = None,
        days: int = 30,
        limit: int = 50
    ) -> List[AnalysisHistory]:
        """
        獲取分析記錄列表
        
        Args:
            code: 股票代碼篩選
            days: 時間範圍（天）
            limit: 返回數量限制
            
        Returns:
            AnalysisHistory 對象列表
        """
        try:
            return self.db.get_analysis_history(
                code=code,
                days=days,
                limit=limit
            )
        except Exception as e:
            logger.error(f"獲取分析列表失敗: {e}")
            return []
    
    def save(
        self,
        result: Any,
        query_id: str,
        report_type: str,
        news_content: Optional[str] = None,
        context_snapshot: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        保存分析結果
        
        Args:
            result: 分析結果對象
            query_id: 查詢 ID
            report_type: 報告類型
            news_content: 新聞內容
            context_snapshot: 上下文快照
            
        Returns:
            新保存的 AnalysisHistory.id；保存失敗返回 0。
        """
        try:
            return self.db.save_analysis_history(
                result=result,
                query_id=query_id,
                report_type=report_type,
                news_content=news_content,
                context_snapshot=context_snapshot
            )
        except Exception as e:
            logger.error(f"保存分析結果失敗: {e}")
            return 0
    
    def count_by_code(self, code: str, days: int = 30) -> int:
        """
        統計指定股票的分析記錄數
        
        Args:
            code: 股票代碼
            days: 時間範圍（天）
            
        Returns:
            記錄數量
        """
        try:
            records = self.db.get_analysis_history(code=code, days=days, limit=1000)
            return len(records)
        except Exception as e:
            logger.error(f"統計分析記錄失敗: {e}")
            return 0
