# -*- coding: utf-8 -*-
"""
===================================
TushareFetcher - 備用數據源 1 (Priority 2)
===================================

數據來源：Tushare Pro API（挖地兔）
特點：需要 Token、有請求配額限制
優點：數據質量高、接口穩定

流控策略：
1. 實現"每分鐘調用計數器"
2. 超過免費配額（80次/分）時，強制休眠到下一分鐘
3. 使用 tenacity 實現指數退避重試
"""

import json as _json
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict, Any

import pandas as pd
import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from .base import BaseFetcher, DataFetchError, RateLimitError, STANDARD_COLUMNS,is_bse_code, is_st_stock, is_kc_cy_stock, normalize_stock_code, _is_hk_market
from .realtime_types import UnifiedRealtimeQuote, ChipDistribution
from src.config import get_config
import os
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


# ETF code prefixes by exchange
# Shanghai: 51xxxx, 52xxxx, 56xxxx, 58xxxx
# Shenzhen: 15xxxx, 16xxxx, 18xxxx
_ETF_SH_PREFIXES = ('51', '52', '56', '58')
_ETF_SZ_PREFIXES = ('15', '16', '18')
_ETF_ALL_PREFIXES = _ETF_SH_PREFIXES + _ETF_SZ_PREFIXES


def _is_etf_code(stock_code: str) -> bool:
    """
    Check if the code is an ETF fund code.

    ETF code ranges:
    - Shanghai ETF: 51xxxx, 52xxxx, 56xxxx, 58xxxx
    - Shenzhen ETF: 15xxxx, 16xxxx, 18xxxx
    """
    code = normalize_stock_code(stock_code)
    return code.startswith(_ETF_ALL_PREFIXES) and len(code) == 6


def _is_us_code(stock_code: str) -> bool:
    """
    判斷代碼是否爲美股
    
    美股代碼規則：
    - 1-5個大寫字母，如 'AAPL', 'TSLA'
    - 可能包含 '.'，如 'BRK.B'
    """
    code = stock_code.strip().upper()
    return bool(re.match(r'^[A-Z]{1,5}(\.[A-Z])?$', code))


class _TushareHttpClient:
    """Lightweight Tushare Pro client that does not require the tushare SDK."""

    def __init__(self, token: str, timeout: int = 30, api_url: str = "http://api.tushare.pro") -> None:
        self._token = token
        self._timeout = timeout
        self._api_url = api_url

    def query(self, api_name: str, fields: str = "", **kwargs) -> pd.DataFrame:
        req_params = {
            "api_name": api_name,
            "token": self._token,
            "params": kwargs,
            "fields": fields,
        }
        res = requests.post(self._api_url, json=req_params, timeout=self._timeout)
        if res.status_code != 200:
            raise Exception(f"Tushare API HTTP {res.status_code}")

        result = _json.loads(res.text)
        if result.get("code") != 0:
            raise Exception(result.get("msg") or f"Tushare API error code {result.get('code')}")

        data = result.get("data") or {}
        columns = data.get("fields") or []
        items = data.get("items") or []
        return pd.DataFrame(items, columns=columns)

    def __getattr__(self, api_name: str):
        if api_name.startswith("_"):
            raise AttributeError(api_name)

        def caller(**kwargs) -> pd.DataFrame:
            return self.query(api_name, **kwargs)

        return caller


class TushareFetcher(BaseFetcher):
    """
    Tushare Pro 數據源實現
    
    優先級：2
    數據來源：Tushare Pro API
    
    關鍵策略：
    - 每分鐘調用計數器，防止超出配額
    - 超過 80 次/分鐘時強制等待
    - 失敗後指數退避重試
    
    配額說明（Tushare 免費用戶）：
    - 每分鐘最多 80 次請求
    - 每天最多 500 次請求
    """
    
    name = "TushareFetcher"
    priority = int(os.getenv("TUSHARE_PRIORITY", "2"))  # 默認優先級，會在 __init__ 中根據配置動態調整

    def __init__(self, rate_limit_per_minute: int = 80):
        """
        初始化 TushareFetcher

        Args:
            rate_limit_per_minute: 每分鐘最大請求數（默認80，Tushare免費配額）
        """
        self.rate_limit_per_minute = rate_limit_per_minute
        self._call_count = 0  # 當前分鐘內的調用次數
        self._minute_start: Optional[float] = None  # 當前計數周期開始時間
        self._api: Optional[object] = None  # Tushare API 實例
        self.date_list: Optional[List[str]] = None  # 交易日列表緩存（倒序，最新日期在前）
        self._date_list_end: Optional[str] = None  # 緩存對應的截止日期，用於跨日刷新

        # 嘗試初始化 API
        self._init_api()

        # 根據 API 初始化結果動態調整優先級
        self.priority = self._determine_priority()
    
    def _init_api(self) -> None:
        """
        初始化 Tushare API

        如果 Token 未配置，此數據源將不可用。
        這裡直接使用內置 HTTP client，避免運行時強依賴 tushare SDK，
        從而減少 Docker / PyInstaller / 多虛擬環境場景下因缺包導致的初始化失敗。
        """
        config = get_config()

        if not config.tushare_token:
            logger.warning("Tushare Token 未配置，此數據源不可用")
            return

        try:
            self._api = self._build_api_client(config.tushare_token)
            logger.info("Tushare API 初始化成功")
        except Exception as e:
            logger.error(f"Tushare API 初始化失敗: {e}")
            self._api = None

    def _build_api_client(self, token: str) -> _TushareHttpClient:
        """
        Build a lightweight Tushare Pro client over direct HTTP requests.

        The project already normalizes all Pro calls through the same request
        contract, so we do not need the official tushare SDK during runtime.
        """
        client = _TushareHttpClient(token=token)
        logger.debug("Tushare API client configured for direct HTTP calls")
        return client

    def _determine_priority(self) -> int:
        """
        根據 Token 配置和 API 初始化狀態確定優先級

        策略：
        - Token 配置且 API 初始化成功：優先級 -1（絕對最高，優於 efinance）
        - 其他情況：優先級 2（默認）

        Returns:
            優先級數字（0=最高，數字越大優先級越低）
        """
        config = get_config()

        if config.tushare_token and self._api is not None:
            # Token 配置且 API 初始化成功，提升爲最高優先級
            logger.info("✅ 檢測到 TUSHARE_TOKEN 且 API 初始化成功，Tushare 數據源優先級提升爲最高 (Priority -1)")
            return -1

        # Token 未配置或 API 初始化失敗，保持默認優先級
        return 2

    def is_available(self) -> bool:
        """
        檢查數據源是否可用

        Returns:
            True 表示可用，False 表示不可用
        """
        return self._api is not None

    def _check_rate_limit(self) -> None:
        """
        檢查並執行速率限制
        
        流控策略：
        1. 檢查是否進入新的一分鐘
        2. 如果是，重置計數器
        3. 如果當前分鐘調用次數超過限制，強制休眠
        """
        current_time = time.time()
        
        # 檢查是否需要重置計數器（新的一分鐘）
        if self._minute_start is None:
            self._minute_start = current_time
            self._call_count = 0
        elif current_time - self._minute_start >= 60:
            # 已經過了一分鐘，重置計數器
            self._minute_start = current_time
            self._call_count = 0
            logger.debug("速率限制計數器已重置")
        
        # 檢查是否超過配額
        if self._call_count >= self.rate_limit_per_minute:
            # 計算需要等待的時間（到下一分鐘）
            elapsed = current_time - self._minute_start
            sleep_time = max(0, 60 - elapsed) + 1  # +1 秒緩衝
            
            logger.warning(
                f"Tushare 達到速率限制 ({self._call_count}/{self.rate_limit_per_minute} 次/分鐘)，"
                f"等待 {sleep_time:.1f} 秒..."
            )
            
            time.sleep(sleep_time)
            
            # 重置計數器
            self._minute_start = time.time()
            self._call_count = 0
        
        # 增加調用計數
        self._call_count += 1
        logger.debug(f"Tushare 當前分鐘調用次數: {self._call_count}/{self.rate_limit_per_minute}")

    def _call_api_with_rate_limit(self, method_name: str, **kwargs) -> pd.DataFrame:
        """統一通過速率限制包裝 Tushare API 調用。"""
        if self._api is None:
            raise DataFetchError("Tushare API 未初始化，請檢查 Token 配置")

        self._check_rate_limit()
        method = getattr(self._api, method_name)
        return method(**kwargs)

    def _get_china_now(self) -> datetime:
        """返回上海時區當前時間，方便測試覆蓋跨日刷新邏輯。"""
        return datetime.now(ZoneInfo("Asia/Shanghai"))

    def _get_trade_dates(self, end_date: Optional[str] = None) -> List[str]:
        """按自然日刷新交易日曆緩存，避免服務跨日後繼續復用舊日曆。"""
        if self._api is None:
            return []

        china_now = self._get_china_now()
        requested_end_date = end_date or china_now.strftime("%Y%m%d")

        if self.date_list is not None and self._date_list_end == requested_end_date:
            return self.date_list

        start_date = (china_now - timedelta(days=20)).strftime("%Y%m%d")
        df_cal = self._call_api_with_rate_limit(
            "trade_cal",
            exchange="SSE",
            start_date=start_date,
            end_date=requested_end_date,
        )

        if df_cal is None or df_cal.empty or "cal_date" not in df_cal.columns:
            logger.warning("[Tushare] trade_cal 返回爲空，無法更新交易日曆緩存")
            self.date_list = []
            self._date_list_end = requested_end_date
            return self.date_list

        trade_dates = sorted(
            df_cal[df_cal["is_open"] == 1]["cal_date"].astype(str).tolist(),
            reverse=True,
        )
        self.date_list = trade_dates
        self._date_list_end = requested_end_date
        return trade_dates

    @staticmethod
    def _pick_trade_date(trade_dates: List[str], use_today: bool) -> Optional[str]:
        """根據可用交易日列表選擇當天或前一交易日。"""
        if not trade_dates:
            return None
        if use_today or len(trade_dates) == 1:
            return trade_dates[0]
        return trade_dates[1]

    @staticmethod
    def _detect_exchange_hint(stock_code: str) -> Optional[str]:
        """Return SH/SZ/BJ when the raw user input carries an explicit exchange hint."""
        upper = (stock_code or "").strip().upper()
        if upper.startswith(("SH", "SS")) or upper.endswith((".SH", ".SS")):
            return "SH"
        if upper.startswith("SZ") or upper.endswith(".SZ"):
            return "SZ"
        if upper.startswith("BJ") or upper.endswith(".BJ"):
            return "BJ"
        return None

    @classmethod
    def _get_legacy_realtime_symbol(cls, stock_code: str) -> str:
        """Build the legacy tushare symbol while preserving explicit SH/SZ hints."""
        code = normalize_stock_code(stock_code)
        exchange_hint = cls._detect_exchange_hint(stock_code)

        if code == '000001' and exchange_hint == 'SH':
            return 'sh000001'
        if code == '399001':
            return 'sz399001'
        if code == '399006':
            return 'sz399006'
        if code == '000300':
            return 'sh000300'
        if is_bse_code(code):
            return f"bj{code}"
        return code
    
    def _convert_stock_code(self, stock_code: str) -> str:
        """
        轉換 A 股 / ETF / 北交所等爲 Tushare ts_code（不含港股邏輯）。

        Tushare 要求的格式示例：
        - 滬市股票：600519.SH
        - 深市股票：000001.SZ
        - 滬市 ETF：510050.SH
        - 深市 ETF：159919.SZ

        Args:
            stock_code: 原始代碼，如 '600519', '000001', '563230'

        Returns:
            Tushare 格式代碼，如 '600519.SH', '000001.SZ'
        """
        raw_code = stock_code.strip()
        
        # Already has suffix.
        if '.' in raw_code:
            upper = raw_code.upper()
            code = normalize_stock_code(raw_code)
            exchange_hint = self._detect_exchange_hint(raw_code)
            if exchange_hint in ("SH", "SZ", "BJ") and code.isdigit():
                return f"{code}.{exchange_hint}"

            ts_code = upper
            if ts_code.endswith('.SS'):
                return f"{ts_code[:-3]}.SH"
            return ts_code

        if _is_us_code(raw_code):
            raise DataFetchError(f"TushareFetcher 不支持美股 {raw_code}，請使用 AkshareFetcher 或 YfinanceFetcher")

        if _is_hk_market(raw_code):
            #raise DataFetchError(f"TushareFetcher 不支持港股 {raw_code}，請使用 AkshareFetcher")
            return normalize_stock_code(raw_code)

        code = normalize_stock_code(raw_code)
        exchange_hint = self._detect_exchange_hint(raw_code)

        if exchange_hint == "SH":
            return f"{code}.SH"
        if exchange_hint == "SZ":
            return f"{code}.SZ"
        if exchange_hint == "BJ":
            return f"{code}.BJ"

        # ETF: determine exchange by prefix
        if code.startswith(_ETF_SH_PREFIXES) and len(code) == 6:
            return f"{code}.SH"
        if code.startswith(_ETF_SZ_PREFIXES) and len(code) == 6:
            return f"{code}.SZ"
        
        # BSE (Beijing Stock Exchange): 8xxxxx, 4xxxxx, 920xxx
        if is_bse_code(code):
            return f"{code}.BJ"
        
        # Regular stocks
        # Shanghai: 600xxx, 601xxx, 603xxx, 605xxx, 688xxx (STAR Market)
        # Shenzhen: 000xxx, 001xxx, 002xxx, 003xxx, 300xxx, 301xxx (ChiNext)
        if code.startswith(('600', '601', '603', '605', '688')):
            return f"{code}.SH"
        elif code.startswith(('000', '001', '002', '003', '300', '301')):
            return f"{code}.SZ"
        else:
            logger.warning(f"無法確定股票 {code} 的市場，默認使用深市")
            return f"{code}.SZ"

    def _convert_hk_stock_code_for_tushare(self, stock_code: str) -> str:
        """
        將用戶輸入轉爲 Tushare Pro 接口所需的 ts_code（含港股 nnnnn.HK）。

        - 非港股：委託 _convert_stock_code（A 股 / ETF / 北交所等）。
        - 港股：從 HK00700、00700、00700.HK 等形式歸一爲 5 位數字 + .HK。
        """
        raw_code = stock_code.strip()
        if _is_hk_market(raw_code):
            if "." in raw_code:
                ts_code = raw_code.upper()
                if ts_code.endswith(".SS"):
                    return f"{ts_code[:-3]}.SH"
                if ts_code.endswith(".HK"):
                    return ts_code
            digits = re.sub(r"\D", "", raw_code)
            if not digits:
                raise DataFetchError(f"無法識別港股代碼 {raw_code}")
            code = digits[-5:].rjust(5, "0")
            return f"{code}.HK"
        return self._convert_stock_code(stock_code)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        從 Tushare 獲取原始數據
        
        根據代碼類型選擇不同接口：
        - 普通股票：daily()
        - ETF 基金：fund_daily()
        
        流程：
        1. 檢查 API 是否可用
        2. 檢查是否爲美股（不支持）
        3. 執行速率限制檢查
        4. 轉換股票代碼格式
        5. 根據代碼類型選擇接口並調用
        """
        if self._api is None:
            raise DataFetchError("Tushare API 未初始化，請檢查 Token 配置")
        
        # US stocks not supported
        if _is_us_code(stock_code):
            raise DataFetchError(f"TushareFetcher 不支持美股 {stock_code}，請使用 AkshareFetcher 或 YfinanceFetcher")
        
        # Rate-limit check
        self._check_rate_limit()
        
        is_hk = _is_hk_market(stock_code)
         # 判斷是否爲 ETF / 港股，以選擇不同接口
        is_etf = _is_etf_code(stock_code)
        if is_hk:
            ts_code = self._convert_hk_stock_code_for_tushare(stock_code)
            api_name = "hk_daily"
        else:
            ts_code = self._convert_stock_code(stock_code)
            api_name = "fund_daily" if is_etf else "daily"
        
        # Convert date format (Tushare requires YYYYMMDD)
        ts_start = start_date.replace('-', '')
        ts_end = end_date.replace('-', '')
        
       

        logger.debug(f"調用 Tushare {api_name}({ts_code}, {ts_start}, {ts_end})")
        
        try:
            if is_hk:
                # 港股使用 hk_daily 接口
                df = self._api.hk_daily(
                    ts_code=ts_code,
                    start_date=ts_start,
                    end_date=ts_end,
                )
            elif is_etf:
                # ETF uses fund_daily interface
                df = self._api.fund_daily(
                    ts_code=ts_code,
                    start_date=ts_start,
                    end_date=ts_end,
                )
            else:
                # Regular A-share stocks use daily interface
                df = self._api.daily(
                    ts_code=ts_code,
                    start_date=ts_start,
                    end_date=ts_end,
                )
            
            return df
            
        except Exception as e:
            error_msg = str(e).lower()
            
            # 檢測配額超限
            if any(keyword in error_msg for keyword in ['quota', '配額', 'limit', '權限']):
                logger.warning(f"Tushare 配額可能超限: {e}")
                raise RateLimitError(f"Tushare 配額超限: {e}") from e
            
            raise DataFetchError(f"Tushare 獲取數據失敗: {e}") from e
    
    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """
        標準化 Tushare 數據
        
        Tushare daily / fund_daily 返回的列名：
        ts_code, trade_date, open, high, low, close, pre_close, change, pct_chg, vol, amount
        
        需要映射到標準列名：
        date, open, high, low, close, volume, amount, pct_chg

        單位縮放僅適用於 A 股（及 ETF 等使用同一套單位的接口）：
        - vol 按「手」計，乘以 100 轉爲「股」
        - amount 按「千元」計，乘以 1000 轉爲「元」

        港股 hk_daily 返回的 vol / amount 已是可直接使用的量級，不做上述縮放。
        """
        df = df.copy()
        is_hk = _is_hk_market(stock_code)

        # 列名映射
        column_mapping = {
            'trade_date': 'date',
            'vol': 'volume',
            # open, high, low, close, amount, pct_chg 列名相同
        }
        
        df = df.rename(columns=column_mapping)
        
        # 轉換日期格式（YYYYMMDD -> YYYY-MM-DD）
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
        
        # 成交量 / 成交額：僅 A 股類接口做單位換算（港股 hk_daily 不換算）
        if 'volume' in df.columns and not is_hk:
            df['volume'] = df['volume'] * 100
        
        if 'amount' in df.columns and not is_hk:
            df['amount'] = df['amount'] * 1000
        
        # 添加股票代碼列
        df['code'] = stock_code
        
        # 只保留需要的列
        keep_cols = ['code'] + STANDARD_COLUMNS
        existing_cols = [col for col in keep_cols if col in df.columns]
        df = df[existing_cols]
        
        return df

    def get_stock_name(self, stock_code: str) -> Optional[str]:
        """
        獲取股票名稱
        
        使用 Tushare 的 stock_basic 接口獲取股票基本信息
        
        Args:
            stock_code: 股票代碼
            
        Returns:
            股票名稱，失敗返回 None
        """
        if self._api is None:
            logger.warning("Tushare API 未初始化，無法獲取股票名稱")
            return None

        # 檢查緩存
        if hasattr(self, '_stock_name_cache') and stock_code in self._stock_name_cache:
            return self._stock_name_cache[stock_code]
        
        # 初始化緩存
        if not hasattr(self, '_stock_name_cache'):
            self._stock_name_cache = {}
        
        try:
            # 速率限制檢查
            self._check_rate_limit()
            

            # 根據市場/類型選擇基礎信息接口
            if _is_hk_market(stock_code):
                ts_code = self._convert_hk_stock_code_for_tushare(stock_code)
                # 港股：使用 hk_basic
                df = self._api.hk_basic(
                    ts_code=ts_code,
                    fields='ts_code,name'
                )
            elif _is_etf_code(stock_code):
                ts_code = self._convert_stock_code(stock_code)
                # ETF：使用 fund_basic
                df = self._api.fund_basic(
                    ts_code=ts_code,
                    fields='ts_code,name'
                )
            else:
                ts_code = self._convert_stock_code(stock_code)
                # A 股股票：使用 stock_basic
                df = self._api.stock_basic(
                    ts_code=ts_code,
                    fields='ts_code,name'
                )
            
            if df is not None and not df.empty:
                name = df.iloc[0]['name']
                self._stock_name_cache[stock_code] = name
                logger.debug(f"Tushare 獲取股票名稱成功: {stock_code} -> {name}")
                return name
            
        except Exception as e:
            logger.warning(f"Tushare 獲取股票名稱失敗 {stock_code}: {e}")
        
        return None
    
    def get_stock_list(self) -> Optional[pd.DataFrame]:
        """
        獲取股票列表
        
        使用 Tushare 的 stock_basic 接口獲取 A 股列表（不含港股）。
        
        Returns:
            包含 code, name, industry, area, market 列的 DataFrame，失敗返回 None
        """
        if self._api is None:
            logger.warning("Tushare API 未初始化，無法獲取股票列表")
            return None
        
        try:
            self._check_rate_limit()

            df = self._api.stock_basic(
                exchange='',
                list_status='L',
                fields='ts_code,name,industry,area,market'
            )

            if df is None or df.empty:
                return None

            df = df.copy()
            df['code'] = df['ts_code'].astype(str).str.split('.').str[0]

            if not hasattr(self, '_stock_name_cache'):
                self._stock_name_cache = {}
            for _, row in df.iterrows():
                self._stock_name_cache[row['code']] = row['name']

            logger.info(f"Tushare 獲取股票列表成功: {len(df)} 條")
            return df[['code', 'name', 'industry', 'area', 'market']]

        except Exception as e:
            logger.warning(f"Tushare 獲取股票列表失敗: {e}")

        return None
    
    def get_realtime_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        """
        獲取實時行情

        策略：
        1. 優先嘗試 Pro 接口（需要2000積分）：數據全，穩定性高
        2. 失敗降級到舊版接口：門檻低，數據較少

        Args:
            stock_code: 股票代碼

        Returns:
            UnifiedRealtimeQuote 對象，失敗返回 None
        """
        if self._api is None:
            return None

        # HK stocks not supported by Tushare
        if _is_hk_market(stock_code):
            logger.debug(f"TushareFetcher 跳過港股實時行情 {stock_code}")
            return None

        normalized_code = normalize_stock_code(stock_code)

        from .realtime_types import (
            RealtimeSource,
            safe_float, safe_int
        )

        # 速率限制檢查
        self._check_rate_limit()

        # 嘗試 Pro 接口
        try:
            ts_code = self._convert_stock_code(stock_code)
            # 嘗試調用 Pro 實時接口 (需要積分)
            df = self._api.quotation(ts_code=ts_code)

            if df is not None and not df.empty:
                row = df.iloc[0]
                logger.debug(f"Tushare Pro 實時行情獲取成功: {stock_code}")

                return UnifiedRealtimeQuote(
                    code=normalized_code,
                    name=str(row.get('name', '')),
                    source=RealtimeSource.TUSHARE,
                    price=safe_float(row.get('price')),
                    change_pct=safe_float(row.get('pct_chg')),  # Pro 接口通常直接返回漲跌幅
                    change_amount=safe_float(row.get('change')),
                    volume=safe_int(row.get('vol')),
                    amount=safe_float(row.get('amount')),
                    high=safe_float(row.get('high')),
                    low=safe_float(row.get('low')),
                    open_price=safe_float(row.get('open')),
                    pre_close=safe_float(row.get('pre_close')),
                    turnover_rate=safe_float(row.get('turnover_ratio')), # Pro 接口可能有換手率
                    pe_ratio=safe_float(row.get('pe')),
                    pb_ratio=safe_float(row.get('pb')),
                    total_mv=safe_float(row.get('total_mv')),
                )
        except Exception as e:
            # 僅記錄調試日誌，不報錯，繼續嘗試降級
            logger.debug(f"Tushare Pro 實時行情不可用 (可能是積分不足): {e}")

        # 降級：嘗試舊版接口
        try:
            import tushare as ts

            symbol = self._get_legacy_realtime_symbol(stock_code)

            # 調用舊版實時接口 (ts.get_realtime_quotes)
            df = ts.get_realtime_quotes(symbol)

            if df is None or df.empty:
                return None

            row = df.iloc[0]

            # 計算漲跌幅
            price = safe_float(row['price'])
            pre_close = safe_float(row['pre_close'])
            change_pct = 0.0
            change_amount = 0.0

            if price and pre_close and pre_close > 0:
                change_amount = price - pre_close
                change_pct = (change_amount / pre_close) * 100

            # 構建統一對象
            return UnifiedRealtimeQuote(
                code=normalized_code,
                name=str(row['name']),
                source=RealtimeSource.TUSHARE,
                price=price,
                change_pct=round(change_pct, 2),
                change_amount=round(change_amount, 2),
                volume=safe_int(row['volume']) // 100,  # 轉換爲手
                amount=safe_float(row['amount']),
                high=safe_float(row['high']),
                low=safe_float(row['low']),
                open_price=safe_float(row['open']),
                pre_close=pre_close,
            )

        except Exception as e:
            logger.warning(f"Tushare (舊版) 獲取實時行情失敗 {stock_code}: {e}")
            return None

    def get_main_indices(self, region: str = "cn") -> Optional[List[dict]]:
        """
        獲取主要指數實時行情 (Tushare Pro)，僅支持 A 股
        """
        if region != "cn":
            return None
        if self._api is None:
            return None

        from .realtime_types import safe_float

        # 指數映射：Tushare代碼 -> 名稱
        indices_map = {
            '000001.SH': '上證指數',
            '399001.SZ': '深證成指',
            '399006.SZ': '創業板指',
            '000688.SH': '科創50',
            '000016.SH': '上證50',
            '000300.SH': '滬深300',
        }

        try:
            self._check_rate_limit()

            # Tushare index_daily 獲取歷史數據，實時數據需用其他接口或估算
            # 由於 Tushare 免費用戶可能無法獲取指數實時行情，這裡作爲備選
            # 使用 index_daily 獲取最近交易日數據

            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - pd.Timedelta(days=5)).strftime('%Y%m%d')

            results = []

            # 批量獲取所有指數數據
            for ts_code, name in indices_map.items():
                try:
                    df = self._api.index_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
                    if df is not None and not df.empty:
                        row = df.iloc[0] # 最新一天

                        current = safe_float(row['close'])
                        prev_close = safe_float(row['pre_close'])

                        results.append({
                            'code': ts_code.split('.')[0], # 兼容 sh000001 格式需轉換，這裡保持純數字
                            'name': name,
                            'current': current,
                            'change': safe_float(row['change']),
                            'change_pct': safe_float(row['pct_chg']),
                            'open': safe_float(row['open']),
                            'high': safe_float(row['high']),
                            'low': safe_float(row['low']),
                            'prev_close': prev_close,
                            'volume': safe_float(row['vol']),
                            'amount': safe_float(row['amount']) * 1000, # 千元轉元
                            'amplitude': 0.0 # Tushare index_daily 不直接返回振幅
                        })
                except Exception as e:
                    logger.debug(f"Tushare 獲取指數 {name} 失敗: {e}")
                    continue

            if results:
                return results
            else:
                logger.warning("[Tushare] 未獲取到指數行情數據")

        except Exception as e:
            logger.error(f"[Tushare] 獲取指數行情失敗: {e}")

        return None

    def get_market_stats(self) -> Optional[dict]:
        """
        獲取市場漲跌統計 (Tushare Pro)
        2000積分 每天訪問該接口 ts.pro_api().rt_k 兩次
        接口限制見：https://tushare.pro/document/1?doc_id=108
        """
        if self._api is None:
            return None

        try:
            logger.info("[Tushare] ts.pro_api() 獲取市場統計...")
            
            # 獲取當前中國時間，判斷是否在交易時間內
            china_now = self._get_china_now()
            current_clock = china_now.strftime("%H:%M")
            current_date = china_now.strftime("%Y%m%d")

            trade_dates = self._get_trade_dates(current_date)
            if not trade_dates:
                return None

            if current_date in trade_dates:
                if current_clock < '09:30' or current_clock > '16:30':
                    use_realtime = False
                else:
                    use_realtime = True
            else:
                use_realtime = False

            # 若實盤的時候使用 則使用其他可以實盤獲取的數據源 akshare、efinance
            if use_realtime:
                try:
                    df = self._call_api_with_rate_limit("rt_k", ts_code='3*.SZ,6*.SH,0*.SZ,92*.BJ')
                    if df is not None and not df.empty:
                        return self._calc_market_stats(df)
                    
                except Exception as e:
                    logger.error(f"[Tushare] ts.pro_api().rt_k 嘗試獲取實時數據失敗: {e}")
                    return None
            else:

                if current_date not in trade_dates:
                    last_date = self._pick_trade_date(trade_dates, use_today=True)  # 拿最近的日期
                else:
                    if current_clock < '09:30': 
                        last_date = self._pick_trade_date(trade_dates, use_today=False)  # 拿取前一天的數據
                    else:  # 即 '> 16:30'                  
                        last_date = self._pick_trade_date(trade_dates, use_today=True)  # 拿取當天的數據

                if last_date is None:
                    return None

                try:
                    df = self._call_api_with_rate_limit(
                        "daily",
                        ts_code='3*.SZ,6*.SH,0*.SZ,92*.BJ',
                        start_date=last_date,
                        end_date=last_date,
                    )
                    # 爲防止不同接口返回的列名大小寫不一致（例如 rt_k 返回小寫，daily 返回大寫），統一將列名轉爲小寫
                    df.columns = [col.lower() for col in df.columns]

                    # 獲取股票基礎信息（包含代碼和名稱）
                    df_basic = self._call_api_with_rate_limit("stock_basic", fields='ts_code,name')
                    df = pd.merge(df, df_basic, on='ts_code', how='left')
                    # 將 daily的 amount 列的值乘以 1000 來和其他數據源保持一致
                    if 'amount' in df.columns:
                        df['amount'] = df['amount'] * 1000

                    if df is not None and not df.empty:
                        return self._calc_market_stats(df)
                except Exception as e:
                    logger.error(f"[Tushare] ts.pro_api().daily 獲取數據失敗: {e}")
                    

            
        except Exception as e:
            logger.error(f"[Tushare] 獲取市場統計失敗: {e}")

        return None
    
    def _calc_market_stats(
            self,
            df: pd.DataFrame,
            ) -> Optional[Dict[str, Any]]:
            """從行情 DataFrame 計算漲跌統計。"""
            import numpy as np

            df = df.copy()
            
            # 1. 提取基礎比對數據：最新價、昨收
            # 兼容不同接口返回的列名 sina/em efinance tushare xtdata
            code_col = next((c for c in ['代碼', '股票代碼', 'ts_code','stock_code'] if c in df.columns), None)
            name_col = next((c for c in ['名稱', '股票名稱','name','name'] if c in df.columns), None)
            close_col = next((c for c in ['最新價', '最新價', 'close','lastPrice'] if c in df.columns), None)
            pre_close_col = next((c for c in ['昨收', '昨日收盤', 'pre_close','lastClose'] if c in df.columns), None)
            amount_col = next((c for c in ['成交額', '成交額', 'amount','amount'] if c in df.columns), None) 
            
            limit_up_count = 0
            limit_down_count = 0
            up_count = 0
            down_count = 0
            flat_count = 0

            for code, name, current_price, pre_close, amount in zip(
                df[code_col], df[name_col], df[close_col], df[pre_close_col], df[amount_col]
            ):
                
                # 停牌過濾 efinance 的停牌數據有時候會缺失價格顯示爲 '-'，em 顯示爲none
                if pd.isna(current_price) or pd.isna(pre_close) or current_price in ['-'] or pre_close in ['-'] or amount == 0:
                    continue
                
                # em、efinance 爲str 需要轉換爲float
                current_price = float(current_price)
                pre_close = float(pre_close)
                
                # 獲取去除前綴的純數字代碼
                pure_code = normalize_stock_code(str(code)) 

                # A. 確定每隻股票的漲跌幅比例 (使用純數字代碼判斷)
                if is_bse_code(pure_code): 
                    ratio = 0.30
                elif is_kc_cy_stock(pure_code): #pure_code.startswith(('688', '30')):
                    ratio = 0.20
                elif is_st_stock(name): #'ST' in str_name:
                    ratio = 0.05
                else:
                    ratio = 0.10

                # B. 嚴格按照 A 股規則計算漲跌停價：昨收 * (1 ± 比例) -> 四捨五入保留2位小數
                limit_up_price = np.floor(pre_close * (1 + ratio) * 100 + 0.5) / 100.0
                limit_down_price = np.floor(pre_close * (1 - ratio) * 100 + 0.5) / 100.0

                limit_up_price_Tolerance = round(abs(pre_close * (1 + ratio) - limit_up_price), 10)
                limit_down_price_Tolerance = round(abs(pre_close * (1 - ratio) - limit_down_price), 10)

                # C. 精確比對
                if current_price > 0 :
                    is_limit_up = (current_price > 0) and (abs(current_price - limit_up_price) <= limit_up_price_Tolerance)
                    is_limit_down = (current_price > 0) and (abs(current_price - limit_down_price) <= limit_down_price_Tolerance)

                    if is_limit_up:
                        limit_up_count += 1
                    if is_limit_down:
                        limit_down_count += 1

                    if current_price > pre_close:
                        up_count += 1
                    elif current_price < pre_close:
                        down_count += 1
                    else:
                        flat_count += 1
                    
            # 統計數量
            stats = {
                'up_count': up_count,
                'down_count': down_count,
                'flat_count': flat_count,
                'limit_up_count': limit_up_count,
                'limit_down_count': limit_down_count,
                'total_amount': 0.0,
            }
            
            # 成交額統計
            if amount_col and amount_col in df.columns:
                df[amount_col] = pd.to_numeric(df[amount_col], errors='coerce')
                stats['total_amount'] = (df[amount_col].sum() / 1e8)
                
            return stats

    def get_trade_time(self,early_time='09:30',late_time='16:30') -> Optional[str]:
        '''
        獲取當前時間可以獲得數據的開始時間日期

        Args:
                early_time: 默認 '09:30'
                late_time: 默認 '16:30'
                early_time-late_time 之間爲使用上一個交易日數據的時間段，其他時間爲使用當天數據的時間段
        Returns:
                start_date: 可以獲得數據的開始日期
        '''
        china_now = self._get_china_now()
        china_date = china_now.strftime("%Y%m%d")
        china_clock = china_now.strftime("%H:%M")

        trade_dates = self._get_trade_dates(china_date)
        if not trade_dates:
            return None

        if china_date in trade_dates:
            if  early_time < china_clock < late_time: # 使用上一個交易日數據的時間段
                use_today = False
            else:
                use_today = True
        else:
            # 非交易日： today不在trade_dates中，trade_dates[0]就是最近交易日
            use_today = True

        start_date = self._pick_trade_date(trade_dates, use_today=use_today)
        if start_date is None:
            return None

        if not use_today:
            logger.info(f"[Tushare] 當前時間 {china_clock} 可能無法獲取當天籌碼分布，嘗試獲取前一個交易日的數據 {start_date}")

        return start_date
    
    def get_sector_rankings(self, n: int = 5) -> Optional[Tuple[list, list]]:
        """
        獲取行業板塊漲跌榜 (Tushare Pro)
        
        數據源優先級：
        1. 同花順接口 (ts.pro_api().moneyflow_ind_ths)
        2. 東財接口 (ts.pro_api().moneyflow_ind_dc)
        注意：每個接口的行業分類和板塊定義不同，會導致結果兩者不一致
        """
        def _get_rank_top_n(df: pd.DataFrame, change_col: str, industry_name: str, n: int) -> Tuple[list, list]:
            df[change_col] = pd.to_numeric(df[change_col], errors='coerce')
            df = df.dropna(subset=[change_col])

            # 漲幅前n
            top = df.nlargest(n, change_col)
            top_sectors = [
                {'name': row[industry_name], 'change_pct': row[change_col]}
                for _, row in top.iterrows()
            ]

            bottom = df.nsmallest(n, change_col)
            bottom_sectors = [
                {'name': row[industry_name], 'change_pct': row[change_col]}
                for _, row in bottom.iterrows()
            ]
            return top_sectors, bottom_sectors

        # 15:30之後才有當天數據
        start_date = self.get_trade_time(early_time='00:00', late_time='15:30')
        if not start_date:
            return None

        # 優先同花順接口
        logger.info("[Tushare] ts.pro_api().moneyflow_ind_ths 獲取板塊排行(同花順)...")
        try:
            df = self._call_api_with_rate_limit("moneyflow_ind_ths", trade_date=start_date)
            if df is not None and not df.empty:
                change_col = 'pct_change'
                name = 'industry'
                if change_col in df.columns:
                    return _get_rank_top_n(df, change_col, name, n)
        except Exception as e:
            logger.warning(f"[Tushare] 獲取同花順行業板塊漲跌榜失敗: {e} 嘗試東財接口")

        # 同花順接口失敗，降級嘗試東財接口
        logger.info("[Tushare] ts.pro_api().moneyflow_ind_dc 獲取板塊排行(東財)...")
        try:
            df = self._call_api_with_rate_limit("moneyflow_ind_dc", trade_date=start_date)
            if df is not None and not df.empty:
                df = df[df['content_type'] == '行業']  # 過濾出行業板塊
                change_col = 'pct_change'
                name = 'name'
                if change_col in df.columns:
                    return _get_rank_top_n(df, change_col, name, n)
        except Exception as e:
            logger.warning(f"[Tushare] 獲取東財行業板塊漲跌榜失敗: {e}")
            return None
        
        # 獲取爲空或者接口調用失敗，返回 None
        return None
    
    

    
    def get_chip_distribution(self, stock_code: str) -> Optional[ChipDistribution]:
        """
        獲取籌碼分布數據
        
        數據來源：ts.pro_api().cyq_chips()
        包含：獲利比例、平均成本、籌碼集中度
        
        注意：ETF/指數沒有籌碼分布數據，會直接返回 None；港股不支持，直接返回 None。
        5000積分以下每天訪問15次,每小時訪問5次
        
        Args:
            stock_code: 股票代碼
            
        Returns:
            ChipDistribution 對象（最新交易日的數據），獲取失敗返回 None

        """
        if _is_us_code(stock_code):
            logger.warning(f"[Tushare] TushareFetcher 不支持美股 {stock_code} 的籌碼分布")
            return None
        
        if _is_etf_code(stock_code):
            logger.warning(f"[Tushare] TushareFetcher 不支持 ETF {stock_code} 的籌碼分布")
            return None

        if _is_hk_market(stock_code):
            logger.warning(f"[Tushare] TushareFetcher 不支持港股 {stock_code} 的籌碼分布")
            return None
        
        try:
            # 19點之後才有當天數據
            start_date = self.get_trade_time(early_time='00:00', late_time='19:00') 
            if not start_date:
                return None

            ts_code = self._convert_stock_code(stock_code)

            df = self._call_api_with_rate_limit(
                "cyq_chips",
                ts_code=ts_code,
                start_date=start_date,
                end_date=start_date,
            )
            if df is not None and not df.empty:
                daily_df = self._call_api_with_rate_limit(
                    "daily",
                    ts_code=ts_code,
                    start_date=start_date,
                    end_date=start_date,
                )
                if daily_df is None or daily_df.empty:
                    return None
                current_price = daily_df.iloc[0]['close']
                metrics = self.compute_cyq_metrics(df, current_price)

                chip = ChipDistribution(
                    code=stock_code,
                    date=datetime.strptime(start_date, '%Y%m%d').strftime('%Y-%m-%d'),
                    profit_ratio=metrics['獲利比例'],
                    avg_cost=metrics['平均成本'],
                    cost_90_low=metrics['90成本-低'],
                    cost_90_high=metrics['90成本-高'],
                    concentration_90=metrics['90集中度'],
                    cost_70_low=metrics['70成本-低'],
                    cost_70_high=metrics['70成本-高'],
                    concentration_70=metrics['70集中度'],
                )
                
                logger.info(f"[籌碼分布] {stock_code} 日期={chip.date}: 獲利比例={chip.profit_ratio:.1%}, "
                        f"平均成本={chip.avg_cost}, 90%集中度={chip.concentration_90:.2%}, "
                        f"70%集中度={chip.concentration_70:.2%}")
                return chip

        except Exception as e:
            logger.warning(f"[Tushare] 獲取籌碼分布失敗 {stock_code}: {e}")
            return None

    def compute_cyq_metrics(self, df: pd.DataFrame, current_price: float) -> dict:
        """
        基於 Tushare 的籌碼分布明細表 (cyq_chips) 計算常用籌碼指標  
        :param df: 包含 'price' 和 'percent' 列的 DataFrame  
        :param current_price: 股票當天的當前價/收盤價 (用於計算獲利比例)  
        :return: 包含各項籌碼指標的字典  
        """
        import numpy as np
        # 1. 確保按價格從小到大排序 (Tushare 返回的數據往往是純倒序的)
        df_sorted = df.sort_values(by='price', ascending=True).reset_index(drop=True)

        # 2. 防止原始數據 percent 總和產生浮點數誤差，歸一化到 100%
        total_percent = df_sorted['percent'].sum()

        df_sorted['norm_percent'] = df_sorted['percent'] / total_percent * 100

        # 3. 計算籌碼的累積分布
        df_sorted['cumsum'] = df_sorted['norm_percent'].cumsum()

        # --- 獲利比例 ---
        # 所有價格 <= 當前價的籌碼之和
        winner_rate = df_sorted[df_sorted['price'] <= current_price]['norm_percent'].sum()

        # --- 平均成本 ---
        # 價格的加權平均值
        avg_cost = np.average(df_sorted['price'], weights=df_sorted['norm_percent'])

        # --- 輔助函數：求指定累積比例處的價格 ---
        def get_percentile_price(target_pct):
            # 尋找累積求和第一次大於等於目標百分比的行索引
            idx = df_sorted['cumsum'].searchsorted(target_pct)
            idx = min(idx, len(df_sorted) - 1) # 防止越界
            return df_sorted.loc[idx, 'price']

        # --- 90% 成本區與集中度 ---
        # 去頭去尾各 5%
        cost_90_low = get_percentile_price(5)
        cost_90_high = get_percentile_price(95)
        if (cost_90_high + cost_90_low) != 0:
            concentration_90 = (cost_90_high - cost_90_low) / (cost_90_high + cost_90_low) * 100
        else:
            concentration_90 = 0.0
            
        # --- 70% 成本區與集中度 ---
        # 去頭去尾各 15%
        cost_70_low = get_percentile_price(15)
        cost_70_high = get_percentile_price(85)
        if (cost_70_high + cost_70_low) != 0:
            concentration_70 = (cost_70_high - cost_70_low) / (cost_70_high + cost_70_low) * 100
        else:
            concentration_70 = 0.0

        # 返回格式化結果
        return {
            "獲利比例": round(winner_rate/100, 4), # /100 與akshare保持一致，返回小數格式
            "平均成本": round(avg_cost, 4),
            "90成本-低": round(cost_90_low, 4),
            "90成本-高": round(cost_90_high, 4),
            "90集中度": round(concentration_90/100, 4),
            "70成本-低": round(cost_70_low, 4),
            "70成本-高": round(cost_70_high, 4),
            "70集中度": round(concentration_70/100, 4)
        }



if __name__ == "__main__":
    # 測試代碼
    logging.basicConfig(level=logging.DEBUG)
    
    fetcher = TushareFetcher()
    
    try:
        # 測試歷史數據
        df = fetcher.get_daily_data('600519')  # 茅臺
        print(f"獲取成功，共 {len(df)} 條數據")
        print(df.tail())
        
        # 測試股票名稱
        name = fetcher.get_stock_name('600519')
        print(f"股票名稱: {name}")
        
    except Exception as e:
        print(f"獲取失敗: {e}")

    # 測試市場統計
    print("\n" + "=" * 50)
    print("Testing get_market_stats (tushare)")
    print("=" * 50)
    try:
        stats = fetcher.get_market_stats()
        if stats:
            print(f"Market Stats successfully computed:")
            print(f"Up: {stats['up_count']} (Limit Up: {stats['limit_up_count']})")
            print(f"Down: {stats['down_count']} (Limit Down: {stats['limit_down_count']})")
            print(f"Flat: {stats['flat_count']}")
            print(f"Total Amount: {stats['total_amount']:.2f} 億 (Yi)")
        else:
            print("Failed to compute market stats.")
    except Exception as e:
        print(f"Failed to compute market stats: {e}")


    # 測試籌碼分布數據
    print("\n" + "=" * 50)
    print("測試籌碼分布數據獲取")
    print("=" * 50)
    try:
        chip = fetcher.get_chip_distribution('600519')  # 茅臺
    except Exception as e:
        print(f"[籌碼分布] 獲取失敗: {e}")

    # 測試行業板塊排名
    print("\n" + "=" * 50)
    print("測試行業板塊排名獲取")
    print("=" * 50)
    try:
        rankings = fetcher.get_sector_rankings(n=5)
        if rankings:
            top, bottom = rankings
            print("漲幅榜 Top 5:")
            for sector in top:
                print(f"{sector['name']}: {sector['change_pct']}%")
            print("\n跌幅榜 Top 5:")
            for sector in bottom:
                print(f"{sector['name']}: {sector['change_pct']}%")
        else:
            print("未獲取到行業板塊排名數據")
    except Exception as e:
        print(f"[行業板塊排名] 獲取失敗: {e}")
