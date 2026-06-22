# -*- coding: utf-8 -*-
"""
===================================
數據源策略層 - 包初始化
===================================

本包實現策略模式管理多個數據源，實現：
1. 統一的數據獲取接口
2. 自動故障切換
3. 防封禁流控策略

數據源優先級（動態調整）：
【配置了 TUSHARE_TOKEN 時】
1. TushareFetcher (Priority 0) - 🔥 最高優先級（動態提升）
2. EfinanceFetcher (Priority 0) - 同優先級
3. AkshareFetcher (Priority 1) - 來自 akshare 庫
4. PytdxFetcher (Priority 2) - 來自 pytdx 庫（通達信）
5. BaostockFetcher (Priority 3) - 來自 baostock 庫
6. YfinanceFetcher (Priority 4) - 來自 yfinance 庫

【未配置 TUSHARE_TOKEN 時】
1. EfinanceFetcher (Priority 0) - 最高優先級，來自 efinance 庫
2. AkshareFetcher (Priority 1) - 來自 akshare 庫
3. PytdxFetcher (Priority 2) - 來自 pytdx 庫（通達信）
4. TushareFetcher (Priority 2) - 來自 tushare 庫（不可用）
5. BaostockFetcher (Priority 3) - 來自 baostock 庫
6. YfinanceFetcher (Priority 4) - 來自 yfinance 庫
7. LongbridgeFetcher (Priority 5) - 長橋 OpenAPI（美股/港股兜底）

提示：優先級數字越小越優先，同優先級按初始化順序排列
"""

from .base import BaseFetcher, DataFetcherManager
from .efinance_fetcher import EfinanceFetcher
from .tencent_fetcher import TencentFetcher
from .akshare_fetcher import AkshareFetcher, is_hk_stock_code
from .tushare_fetcher import TushareFetcher
from .pytdx_fetcher import PytdxFetcher
from .baostock_fetcher import BaostockFetcher
from .yfinance_fetcher import YfinanceFetcher
from .longbridge_fetcher import LongbridgeFetcher
from .finnhub_fetcher import FinnhubFetcher
from .alphavantage_fetcher import AlphaVantageFetcher
from .us_index_mapping import is_us_index_code, is_us_stock_code, get_us_index_yf_symbol, US_INDEX_MAPPING

__all__ = [
    'BaseFetcher',
    'DataFetcherManager',
    'EfinanceFetcher',
    'TencentFetcher',
    'AkshareFetcher',
    'TushareFetcher',
    'PytdxFetcher',
    'BaostockFetcher',
    'YfinanceFetcher',
    'LongbridgeFetcher',
    'FinnhubFetcher',
    'AlphaVantageFetcher',
    'is_us_index_code',
    'is_us_stock_code',
    'is_hk_stock_code',
    'get_us_index_yf_symbol',
    'US_INDEX_MAPPING',
]
