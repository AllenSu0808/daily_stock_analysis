# -*- coding: utf-8 -*-
"""
===================================
股票數據服務層
===================================

職責：
1. 封裝股票數據獲取邏輯
2. 提供實時行情和歷史數據接口
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from src.repositories.stock_repo import StockRepository

logger = logging.getLogger(__name__)


class StockService:
    """
    股票數據服務
    
    封裝股票數據獲取的業務邏輯
    """
    
    def __init__(self):
        """初始化股票數據服務"""
        self.repo = StockRepository()
    
    def get_realtime_quote(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """
        獲取股票實時行情
        
        Args:
            stock_code: 股票代碼
            
        Returns:
            實時行情數據字典
        """
        try:
            # 調用數據獲取器獲取實時行情
            from data_provider.base import DataFetcherManager
            
            manager = DataFetcherManager()
            quote = manager.get_realtime_quote(stock_code)
            
            if quote is None:
                logger.warning(f"獲取 {stock_code} 實時行情失敗")
                return None
            
            # UnifiedRealtimeQuote 是 dataclass，使用 getattr 安全訪問字段
            # 字段映射: UnifiedRealtimeQuote -> API 響應
            # - code -> stock_code
            # - name -> stock_name
            # - price -> current_price
            # - change_amount -> change
            # - change_pct -> change_percent
            # - open_price -> open
            # - high -> high
            # - low -> low
            # - pre_close -> prev_close
            # - volume -> volume
            # - amount -> amount
            return {
                "stock_code": getattr(quote, "code", stock_code),
                "stock_name": getattr(quote, "name", None),
                "current_price": getattr(quote, "price", 0.0) or 0.0,
                "change": getattr(quote, "change_amount", None),
                "change_percent": getattr(quote, "change_pct", None),
                "open": getattr(quote, "open_price", None),
                "high": getattr(quote, "high", None),
                "low": getattr(quote, "low", None),
                "prev_close": getattr(quote, "pre_close", None),
                "volume": getattr(quote, "volume", None),
                "amount": getattr(quote, "amount", None),
                "update_time": datetime.now().isoformat(),
            }
            
        except ImportError:
            logger.warning("DataFetcherManager 未找到，使用佔位數據")
            return self._get_placeholder_quote(stock_code)
        except Exception as e:
            logger.error(f"獲取實時行情失敗: {e}", exc_info=True)
            return None
    
    def get_history_data(
        self,
        stock_code: str,
        period: str = "daily",
        days: int = 30
    ) -> Dict[str, Any]:
        """
        獲取股票歷史行情
        
        Args:
            stock_code: 股票代碼
            period: K 線周期 (daily/weekly/monthly)
            days: 獲取天數
            
        Returns:
            歷史行情數據字典
            
        Raises:
            ValueError: 當 period 不是 daily 時拋出（weekly/monthly 暫未實現）
        """
        # 驗證 period 參數，只支持 daily
        if period != "daily":
            raise ValueError(
                f"暫不支持 '{period}' 周期，目前僅支持 'daily'。"
                "weekly/monthly 聚合功能將在後續版本實現。"
            )
        
        try:
            # 調用數據獲取器獲取歷史數據
            from data_provider.base import DataFetcherManager
            
            manager = DataFetcherManager()
            df, source = manager.get_daily_data(stock_code, days=days)
            
            if df is None or df.empty:
                logger.warning(f"獲取 {stock_code} 歷史數據失敗")
                return {"stock_code": stock_code, "period": period, "data": []}
            
            # 獲取股票名稱
            stock_name = manager.get_stock_name(stock_code)
            
            # 轉換爲響應格式
            data = []
            for _, row in df.iterrows():
                date_val = row.get("date")
                if hasattr(date_val, "strftime"):
                    date_str = date_val.strftime("%Y-%m-%d")
                else:
                    date_str = str(date_val)
                
                data.append({
                    "date": date_str,
                    "open": float(row.get("open", 0)),
                    "high": float(row.get("high", 0)),
                    "low": float(row.get("low", 0)),
                    "close": float(row.get("close", 0)),
                    "volume": float(row.get("volume", 0)) if row.get("volume") else None,
                    "amount": float(row.get("amount", 0)) if row.get("amount") else None,
                    "change_percent": float(row.get("pct_chg", 0)) if row.get("pct_chg") else None,
                })
            
            return {
                "stock_code": stock_code,
                "stock_name": stock_name,
                "period": period,
                "data": data,
            }
            
        except ImportError:
            logger.warning("DataFetcherManager 未找到，返回空數據")
            return {"stock_code": stock_code, "period": period, "data": []}
        except Exception as e:
            logger.error(f"獲取歷史數據失敗: {e}", exc_info=True)
            return {"stock_code": stock_code, "period": period, "data": []}
    
    def _get_placeholder_quote(self, stock_code: str) -> Dict[str, Any]:
        """
        獲取佔位行情數據（用於測試）
        
        Args:
            stock_code: 股票代碼
            
        Returns:
            佔位行情數據
        """
        return {
            "stock_code": stock_code,
            "stock_name": f"股票{stock_code}",
            "current_price": 0.0,
            "change": None,
            "change_percent": None,
            "open": None,
            "high": None,
            "low": None,
            "prev_close": None,
            "volume": None,
            "amount": None,
            "update_time": datetime.now().isoformat(),
        }
