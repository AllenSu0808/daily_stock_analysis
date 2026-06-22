# -*- coding: utf-8 -*-
"""
===================================
股票數據訪問層
===================================

職責：
1. 封裝股票數據的數據庫操作
2. 提供日線數據查詢接口
"""

import logging
from datetime import date
from typing import Optional, List, Dict, Any

import pandas as pd
from sqlalchemy import and_, desc, select

from src.storage import DatabaseManager, StockDaily

logger = logging.getLogger(__name__)


class StockRepository:
    """
    股票數據訪問層
    
    封裝 StockDaily 表的數據庫操作
    """
    
    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        """
        初始化數據訪問層
        
        Args:
            db_manager: 數據庫管理器（可選，默認使用單例）
        """
        self.db = db_manager or DatabaseManager.get_instance()
    
    def get_latest(self, code: str, days: int = 2) -> List[StockDaily]:
        """
        獲取最近 N 天的數據
        
        Args:
            code: 股票代碼
            days: 獲取天數
            
        Returns:
            StockDaily 對象列表（按日期降序）
        """
        try:
            return self.db.get_latest_data(code, days)
        except Exception as e:
            logger.error(f"獲取最新數據失敗: {e}")
            return []
    
    def get_range(
        self,
        code: str,
        start_date: date,
        end_date: date
    ) -> List[StockDaily]:
        """
        獲取指定日期範圍的數據
        
        Args:
            code: 股票代碼
            start_date: 開始日期
            end_date: 結束日期
            
        Returns:
            StockDaily 對象列表
        """
        try:
            return self.db.get_data_range(code, start_date, end_date)
        except Exception as e:
            logger.error(f"獲取日期範圍數據失敗: {e}")
            return []
    
    def save_dataframe(
        self,
        df: pd.DataFrame,
        code: str,
        data_source: str = "Unknown"
    ) -> int:
        """
        保存 DataFrame 到數據庫
        
        Args:
            df: 包含日線數據的 DataFrame
            code: 股票代碼
            data_source: 數據來源
            
        Returns:
            保存的記錄數
        """
        try:
            return self.db.save_daily_data(df, code, data_source)
        except Exception as e:
            logger.error(f"保存日線數據失敗: {e}")
            return 0
    
    def has_today_data(self, code: str, target_date: Optional[date] = None) -> bool:
        """
        檢查是否有指定日期的數據
        
        Args:
            code: 股票代碼
            target_date: 目標日期（默認今天）
            
        Returns:
            是否存在數據
        """
        try:
            return self.db.has_today_data(code, target_date)
        except Exception as e:
            logger.error(f"檢查數據存在失敗: {e}")
            return False
    
    def get_analysis_context(
        self, 
        code: str, 
        target_date: Optional[date] = None
    ) -> Optional[Dict[str, Any]]:
        """
        獲取分析上下文
        
        Args:
            code: 股票代碼
            target_date: 目標日期
            
        Returns:
            分析上下文字典
        """
        try:
            return self.db.get_analysis_context(code, target_date)
        except Exception as e:
            logger.error(f"獲取分析上下文失敗: {e}")
            return None

    def get_start_daily(self, *, code: str, analysis_date: date) -> Optional[StockDaily]:
        """Return StockDaily for analysis_date (preferred) or nearest previous date."""
        with self.db.get_session() as session:
            row = session.execute(
                select(StockDaily)
                .where(and_(StockDaily.code == code, StockDaily.date <= analysis_date))
                .order_by(desc(StockDaily.date))
                .limit(1)
            ).scalar_one_or_none()
            return row

    def get_daily_on_date(self, *, code: str, target_date: date) -> Optional[StockDaily]:
        """Return StockDaily for the exact target_date without trading-day fallback."""
        with self.db.get_session() as session:
            row = session.execute(
                select(StockDaily)
                .where(and_(StockDaily.code == code, StockDaily.date == target_date))
                .limit(1)
            ).scalar_one_or_none()
            return row

    def get_forward_bars(self, *, code: str, analysis_date: date, eval_window_days: int) -> List[StockDaily]:
        """Return forward daily bars after analysis_date, up to eval_window_days."""
        with self.db.get_session() as session:
            rows = session.execute(
                select(StockDaily)
                .where(and_(StockDaily.code == code, StockDaily.date > analysis_date))
                .order_by(StockDaily.date)
                .limit(eval_window_days)
            ).scalars().all()
            return list(rows)
