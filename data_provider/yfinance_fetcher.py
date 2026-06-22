# -*- coding: utf-8 -*-
"""
===================================
YfinanceFetcher - 兜底數據源 (Priority 4)
===================================

數據來源：Yahoo Finance（通過 yfinance 庫）
特點：國際數據源、可能有延遲或缺失
定位：當所有國內數據源都失敗時的最後保障

關鍵策略：
1. 自動將 A 股代碼轉換爲 yfinance 格式（.SS / .SZ）
2. 處理 Yahoo Finance 的數據格式差異
3. 失敗後指數退避重試
"""

import csv
import logging
from datetime import datetime
from io import StringIO
from typing import Optional, List, Dict, Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from .base import BaseFetcher, DataFetchError, STANDARD_COLUMNS, is_bse_code
from .realtime_types import UnifiedRealtimeQuote, RealtimeSource
from .us_index_mapping import get_us_index_yf_symbol, is_us_stock_code

# 可選導入本地股票映射補丁，若缺失則使用空字典兜底
try:
    from src.data.stock_mapping import STOCK_NAME_MAP, is_meaningful_stock_name
except (ImportError, ModuleNotFoundError):
    STOCK_NAME_MAP = {}

    def is_meaningful_stock_name(name: str | None, stock_code: str) -> bool:
        """簡單的名稱有效性校驗兜底"""
        if not name:
            return False
        n = str(name).strip()
        return bool(n and n.upper() != str(stock_code).strip().upper())

import os

logger = logging.getLogger(__name__)


class YfinanceFetcher(BaseFetcher):
    """
    Yahoo Finance 數據源實現

    優先級：4（最低，作爲兜底）
    數據來源：Yahoo Finance

    關鍵策略：
    - 自動轉換股票代碼格式
    - 處理時區和數據格式差異
    - 失敗後指數退避重試

    注意事項：
    - A 股數據可能有延遲
    - 某些股票可能無數據
    - 數據精度可能與國內源略有差異
    """

    name = "YfinanceFetcher"
    priority = int(os.getenv("YFINANCE_PRIORITY", "4"))

    def __init__(self):
        """初始化 YfinanceFetcher"""
        pass

    @staticmethod
    def _is_jp_kr_suffix_stock(stock_code: str) -> bool:
        """Return True for supported JP/KR/TW suffix-only Yahoo symbols."""
        code = (stock_code or "").strip().upper()
        if code.endswith(".T"):
            base = code[:-2]
            return base.isdigit() and len(base) in (4, 5)
        if code.endswith((".KS", ".KQ")):
            base = code.rsplit(".", 1)[0]
            return base.isdigit() and len(base) == 6
        if code.endswith((".TW", ".TWO")):
            base = code.rsplit(".", 1)[0]
            return base.isdigit() and len(base) in (4, 5, 6)
        return False

    def _convert_stock_code(self, stock_code: str) -> str:
        """
        轉換股票代碼爲 Yahoo Finance 格式

        Yahoo Finance 代碼格式：
        - A股滬市：600519.SS (Shanghai Stock Exchange)
        - A股深市：000001.SZ (Shenzhen Stock Exchange)
        - 港股：0700.HK (Hong Kong Stock Exchange)
        - 美股：AAPL, TSLA, GOOGL (無需後綴)

        Args:
            stock_code: 原始代碼，如 '600519', 'hk00700', 'AAPL'

        Returns:
            Yahoo Finance 格式代碼

        Examples:
            >>> fetcher._convert_stock_code('600519')
            '600519.SS'
            >>> fetcher._convert_stock_code('hk00700')
            '0700.HK'
            >>> fetcher._convert_stock_code('AAPL')
            'AAPL'
        """
        code = stock_code.strip().upper()

        # 美股指數：映射到 Yahoo Finance 符號（如 SPX -> ^GSPC）
        yf_symbol, _ = get_us_index_yf_symbol(code)
        if yf_symbol:
            logger.debug(f"識別爲美股指數: {code} -> {yf_symbol}")
            return yf_symbol

        # 美股：1-5 個大寫字母（可選 .X 後綴），原樣返回
        if is_us_stock_code(code):
            logger.debug(f"識別爲美股代碼: {code}")
            return code

        # 日股/韓股/臺股 MVP：顯式 Yahoo Finance suffix-only 代碼，原樣傳給 Yahoo。
        if self._is_jp_kr_suffix_stock(code):
            logger.debug(f"識別爲日韓臺 Yahoo suffix 代碼: {code}")
            return code

        # 港股：hk前綴 -> .HK後綴
        if code.startswith('HK'):
            hk_code = code[2:].lstrip('0') or '0'  # 去除前導0，但保留至少一個0
            hk_code = hk_code.zfill(4)  # 補齊到4位
            logger.debug(f"轉換港股代碼: {stock_code} -> {hk_code}.HK")
            return f"{hk_code}.HK"

        # 已經包含後綴的情況
        if '.SS' in code or '.SZ' in code or '.HK' in code or '.BJ' in code:
            return code

        # 去除可能的 .SH 後綴
        code = code.replace('.SH', '')

        # ETF: Shanghai ETF (51xx, 52xx, 56xx, 58xx) -> .SS; Shenzhen ETF (15xx, 16xx, 18xx) -> .SZ
        if len(code) == 6:
            if code.startswith(('51', '52', '56', '58')):
                return f"{code}.SS"
            if code.startswith(('15', '16', '18')):
                return f"{code}.SZ"

        # BSE (Beijing Stock Exchange): 8xxxxx, 4xxxxx, 920xxx
        if is_bse_code(code):
            base = code.split('.')[0] if '.' in code else code
            return f"{base}.BJ"

        # A股：根據代碼前綴判斷市場
        if code.startswith(('600', '601', '603', '688')):
            return f"{code}.SS"
        elif code.startswith(('000', '002', '300')):
            return f"{code}.SZ"
        else:
            logger.warning(f"無法確定股票 {code} 的市場，默認使用深市")
            return f"{code}.SZ"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        從 Yahoo Finance 獲取原始數據

        使用 yfinance.download() 獲取歷史數據

        流程：
        1. 轉換股票代碼格式
        2. 調用 yfinance API
        3. 處理返回數據
        """
        import yfinance as yf

        # 轉換代碼格式
        yf_code = self._convert_stock_code(stock_code)

        logger.debug(f"調用 yfinance.download({yf_code}, {start_date}, {end_date})")

        try:
            # 使用 yfinance 下載數據
            df = yf.download(
                tickers=yf_code,
                start=start_date,
                end=end_date,
                progress=False,  # 禁止進度條
                auto_adjust=True,  # 自動調整價格（復權）
                multi_level_index=True
            )

            # 篩選出 yf_code 的列, 避免多隻股票數據混淆
            if isinstance(df.columns, pd.MultiIndex) and len(df.columns) > 1:
                ticker_level = df.columns.get_level_values(1)
                mask = ticker_level == yf_code
                if mask.any():
                    df = df.loc[:, mask].copy()

            if df.empty:
                raise DataFetchError(f"Yahoo Finance 未查詢到 {stock_code} 的數據")

            return df

        except Exception as e:
            if isinstance(e, DataFetchError):
                raise
            raise DataFetchError(f"Yahoo Finance 獲取數據失敗: {e}") from e

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """
        標準化 Yahoo Finance 數據

        yfinance 返回的列名：
        Open, High, Low, Close, Volume（索引是日期）

        注意：新版 yfinance 返回 MultiIndex 列名，如 ('Close', 'AMD')
        需要先扁平化列名再進行處理

        需要映射到標準列名：
        date, open, high, low, close, volume, amount, pct_chg
        """
        df = df.copy()

        # 處理 MultiIndex 列名（新版 yfinance 返回格式）
        # 例如: ('Close', 'AMD') -> 'Close'
        if isinstance(df.columns, pd.MultiIndex):
            logger.debug("檢測到 MultiIndex 列名，進行扁平化處理")
            # 取第一級列名（Price level: Close, High, Low, etc.）
            df.columns = df.columns.get_level_values(0)

        # 重置索引，將日期從索引變爲列
        df = df.reset_index()

        # 列名映射（yfinance 使用首字母大寫）
        column_mapping = {
            'Date': 'date',
            'Datetime': 'date',
            'datetime': 'date',
            'Open': 'open',
            'High': 'high',
            'Low': 'low',
            'Close': 'close',
            'Volume': 'volume',
        }

        df = df.rename(columns=column_mapping)
        if 'date' not in df.columns:
            index_col = df.columns[0] if len(df.columns) else None
            if index_col is not None:
                candidate = df[index_col]
                if pd.api.types.is_datetime64_any_dtype(candidate):
                    df = df.rename(columns={index_col: 'date'})
                elif not pd.api.types.is_numeric_dtype(candidate):
                    parsed_dates = pd.to_datetime(candidate, errors='coerce')
                    if parsed_dates.notna().any():
                        df = df.rename(columns={index_col: 'date'})
                        df['date'] = parsed_dates

        # 計算漲跌幅（因爲 yfinance 不直接提供）
        if 'close' in df.columns:
            df['pct_chg'] = df['close'].pct_change() * 100
            df['pct_chg'] = df['pct_chg'].fillna(0).round(2)

        # 計算成交額（yfinance 不提供，使用估算值）
        # 成交額 ≈ 成交量 * 平均價格
        if 'volume' in df.columns and 'close' in df.columns:
            df['amount'] = df['volume'] * df['close']
        else:
            df['amount'] = 0

        # 添加股票代碼列
        df['code'] = stock_code

        # 只保留需要的列
        keep_cols = ['code'] + STANDARD_COLUMNS
        existing_cols = [col for col in keep_cols if col in df.columns]
        df = df[existing_cols]

        return df

    def _fetch_yf_ticker_data(self, yf, yf_code: str, name: str, return_code: str) -> Optional[Dict[str, Any]]:
        """
        通過 yfinance 拉取單個指數/股票的行情數據。

        Args:
            yf: yfinance 模塊引用
            yf_code: yfinance 使用的代碼（如 '000001.SS'、'^GSPC'）
            name: 指數顯示名稱
            return_code: 寫入結果 dict 的 code 字段（如 'sh000001'、'SPX'）

        Returns:
            行情字典，失敗時返回 None
        """
        ticker = yf.Ticker(yf_code)
        # 取近兩日數據以計算漲跌幅
        hist = ticker.history(period='2d')
        if hist.empty:
            return None
        today_row = hist.iloc[-1]
        prev_row = hist.iloc[-2] if len(hist) > 1 else today_row
        price = float(today_row['Close'])
        prev_close = float(prev_row['Close'])
        change = price - prev_close
        change_pct = (change / prev_close) * 100 if prev_close else 0
        high = float(today_row['High'])
        low = float(today_row['Low'])
        # 振幅 = (最高 - 最低) / 昨收 * 100
        amplitude = ((high - low) / prev_close * 100) if prev_close else 0
        return {
            'code': return_code,
            'name': name,
            'current': price,
            'change': change,
            'change_pct': change_pct,
            'open': float(today_row['Open']),
            'high': high,
            'low': low,
            'prev_close': prev_close,
            'volume': float(today_row['Volume']),
            'amount': 0.0,  # Yahoo Finance 不提供準確成交額
            'amplitude': amplitude,
        }

    def get_main_indices(self, region: str = "cn") -> Optional[List[Dict[str, Any]]]:
        """
        獲取主要指數行情 (Yahoo Finance)，支持 A 股、美股與港股。
        region=us 時委託給 _get_us_main_indices。
        region=hk 時委託給 _get_hk_main_indices。
        """
        import yfinance as yf

        if region == "us":
            return self._get_us_main_indices(yf)
        if region == "hk":
            return self._get_hk_main_indices(yf)
        if region == "jp":
            return self._get_jp_main_indices(yf)
        if region == "kr":
            return self._get_kr_main_indices(yf)

        # A 股指數：akshare 代碼 -> (yfinance 代碼, 顯示名稱)
        yf_mapping = {
            'sh000001': ('000001.SS', '上證指數'),
            'sz399001': ('399001.SZ', '深證成指'),
            'sz399006': ('399006.SZ', '創業板指'),
            'sh000688': ('000688.SS', '科創50'),
            'sh000016': ('000016.SS', '上證50'),
            'sh000300': ('000300.SS', '滬深300'),
        }

        results = []
        try:
            for ak_code, (yf_code, name) in yf_mapping.items():
                try:
                    item = self._fetch_yf_ticker_data(yf, yf_code, name, ak_code)
                    if item:
                        results.append(item)
                        logger.debug(f"[Yfinance] 獲取指數 {name} 成功")
                except Exception as e:
                    logger.warning(f"[Yfinance] 獲取指數 {name} 失敗: {e}")

            if results:
                logger.info(f"[Yfinance] 成功獲取 {len(results)} 個 A 股指數行情")
                return results

        except Exception as e:
            logger.error(f"[Yfinance] 獲取 A 股指數行情失敗: {e}")

        return None

    def _get_us_main_indices(self, yf) -> Optional[List[Dict[str, Any]]]:
        """獲取美股主要指數行情（SPX、IXIC、DJI、VIX），復用 _fetch_yf_ticker_data"""
        # 大盤復盤所需核心美股指數
        us_indices = ['SPX', 'IXIC', 'DJI', 'VIX']
        results = []
        try:
            for code in us_indices:
                yf_symbol, name = get_us_index_yf_symbol(code)
                if not yf_symbol:
                    continue
                try:
                    item = self._fetch_yf_ticker_data(yf, yf_symbol, name, code)
                    if item:
                        results.append(item)
                        logger.debug(f"[Yfinance] 獲取美股指數 {name} 成功")
                except Exception as e:
                    logger.warning(f"[Yfinance] 獲取美股指數 {name} 失敗: {e}")

            if results:
                logger.info(f"[Yfinance] 成功獲取 {len(results)} 個美股指數行情")
                return results

        except Exception as e:
            logger.error(f"[Yfinance] 獲取美股指數行情失敗: {e}")

        return None

    def _get_hk_main_indices(self, yf) -> Optional[List[Dict[str, Any]]]:
        """獲取港股主要指數行情（HSI、HSTECH、HSCEI），復用 _fetch_yf_ticker_data"""
        # Yahoo Finance 港股指數符號映射：
        # - HSI -> ^HSI
        # - HSTECH -> HSTECH.HK（不是 ^HSTECH）
        # - HSCEI -> ^HSCE（不是 ^HSCEI）
        # 該映射由離線單測 tests/test_yfinance_hk_indices.py 固化，避免在線依賴導致非確定性失敗。
        hk_indices = {
            'HSI': ('^HSI', '恒生指數'),
            'HSTECH': ('HSTECH.HK', '恒生科技指數'),
            'HSCEI': ('^HSCE', '國企指數'),
        }
        results = []
        try:
            for code, (yf_symbol, name) in hk_indices.items():
                try:
                    item = self._fetch_yf_ticker_data(yf, yf_symbol, name, code)
                    if item:
                        results.append(item)
                        logger.debug(f"[Yfinance] 獲取港股指數 {name} 成功")
                except Exception as e:
                    logger.warning(f"[Yfinance] 獲取港股指數 {name} 失敗: {e}")

            if results:
                logger.info(f"[Yfinance] 成功獲取 {len(results)} 個港股指數行情")
                return results

        except Exception as e:
            logger.error(f"[Yfinance] 獲取港股指數行情失敗: {e}")

        return None

    def _get_jp_main_indices(self, yf) -> Optional[List[Dict[str, Any]]]:
        """獲取日本主要指數行情（日經225、TOPIX），復用 _fetch_yf_ticker_data。"""
        jp_indices = {
            'N225': ('^N225', '日經225'),
            'TOPX': ('^TOPX', '東證指數'),
        }
        results = []
        try:
            for code, (yf_symbol, name) in jp_indices.items():
                try:
                    item = self._fetch_yf_ticker_data(yf, yf_symbol, name, code)
                    if item:
                        results.append(item)
                        logger.debug(f"[Yfinance] 獲取日本指數 {name} 成功")
                except Exception as e:
                    logger.warning(f"[Yfinance] 獲取日本指數 {name} 失敗: {e}")
            if results:
                logger.info(f"[Yfinance] 成功獲取 {len(results)} 個日本指數行情")
                return results
        except Exception as e:
            logger.error(f"[Yfinance] 獲取日本指數行情失敗: {e}")
        return None

    def _get_kr_main_indices(self, yf) -> Optional[List[Dict[str, Any]]]:
        """獲取韓國主要指數行情（KOSPI、KOSDAQ），復用 _fetch_yf_ticker_data。"""
        kr_indices = {
            'KS11': ('^KS11', 'KOSPI'),
            'KQ11': ('^KQ11', 'KOSDAQ'),
        }
        results = []
        try:
            for code, (yf_symbol, name) in kr_indices.items():
                try:
                    item = self._fetch_yf_ticker_data(yf, yf_symbol, name, code)
                    if item:
                        results.append(item)
                        logger.debug(f"[Yfinance] 獲取韓國指數 {name} 成功")
                except Exception as e:
                    logger.warning(f"[Yfinance] 獲取韓國指數 {name} 失敗: {e}")
            if results:
                logger.info(f"[Yfinance] 成功獲取 {len(results)} 個韓國指數行情")
                return results
        except Exception as e:
            logger.error(f"[Yfinance] 獲取韓國指數行情失敗: {e}")
        return None

    def _is_us_stock(self, stock_code: str) -> bool:
        """
        判斷代碼是否爲美股股票（排除美股指數）。

        委託給 us_index_mapping 模塊的 is_us_stock_code()。
        """
        return is_us_stock_code(stock_code)

    def _get_us_stock_quote_from_stooq(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        """
        使用 Stooq 爲美股實時行情提供免密鑰兜底。

        Stooq 提供的是最新交易日行情，精度不如分時實時接口，但在 Yahoo / yfinance
        被限流時，至少能爲 Web UI 提供可用價格；若可獲取到昨收價，則同時提供漲跌幅等衍生指標。
        """
        symbol = stock_code.strip().upper()
        stooq_symbol = f"{symbol.lower()}.us"
        url = f"https://stooq.com/q/l/?s={stooq_symbol}"
        request = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; DSA/1.0; +https://github.com/ZhuLinsen/daily_stock_analysis)",
                "Accept": "text/plain,text/csv,*/*",
            },
        )

        try:
            with urlopen(request, timeout=15) as response:
                payload = response.read().decode("utf-8", "ignore").strip()
        except (HTTPError, URLError, TimeoutError) as exc:
            logger.warning(f"[Stooq] 獲取美股 {symbol} 實時行情失敗: {exc}")
            return None

        if not payload or payload.upper().startswith("NO DATA"):
            logger.warning(f"[Stooq] 無法獲取 {symbol} 的行情數據")
            return None

        def _fetch_prev_close() -> Optional[float]:
            history_url = f"https://stooq.com/q/d/l/?s={stooq_symbol}&i=d"
            history_request = Request(
                history_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; DSA/1.0; +https://github.com/ZhuLinsen/daily_stock_analysis)",
                    "Accept": "text/plain,text/csv,*/*",
                },
            )
            try:
                with urlopen(history_request, timeout=15) as response:
                    history_payload = response.read().decode("utf-8", "ignore").strip()
            except (HTTPError, URLError, TimeoutError) as exc:
                logger.debug(f"[Stooq] 獲取美股 {symbol} 日線歷史失敗: {exc}")
                return None

            if not history_payload or history_payload.upper().startswith("NO DATA"):
                return None

            try:
                reader = csv.reader(StringIO(history_payload))
                header = next(reader, None)
                if not header:
                    return None

                header_tokens = [cell.strip().lower() for cell in header]
                has_header = "close" in header_tokens and "date" in header_tokens
                if not has_header:
                    return None

                date_index = header_tokens.index("date")
                close_index = header_tokens.index("close")

                daily_rows: list[tuple[datetime, float]] = []
                for row in reader:
                    if not row:
                        continue
                    date_text = row[date_index].strip() if len(row) > date_index else ""
                    close_text = row[close_index].strip() if len(row) > close_index else ""
                    if not date_text or not close_text:
                        continue
                    try:
                        dt = datetime.strptime(date_text, "%Y-%m-%d")
                        close_val = float(close_text)
                    except Exception:
                        continue
                    daily_rows.append((dt, close_val))

                if len(daily_rows) < 2:
                    return None

                daily_rows.sort(key=lambda item: item[0])
                return daily_rows[-2][1]
            except Exception:
                return None

        try:
            reader = csv.reader(StringIO(payload))
            first_row = next(reader, None)
            if first_row is None:
                raise ValueError(f"unexpected Stooq payload: {payload}")

            normalized_first_row = [cell.strip() for cell in first_row]
            header_tokens = {cell.lower() for cell in normalized_first_row if cell}
            has_header = 'open' in header_tokens and 'close' in header_tokens
            row = next(reader, None) if has_header else first_row
            if row is None:
                raise ValueError(f"unexpected Stooq payload: {payload}")

            normalized_row = [cell.strip() for cell in row]
            while normalized_row and normalized_row[-1] == '':
                normalized_row.pop()

            if len(normalized_row) >= 8:
                open_index, high_index, low_index, price_index, volume_index = 3, 4, 5, 6, 7
            elif len(normalized_row) >= 7:
                open_index, high_index, low_index, price_index, volume_index = 2, 3, 4, 5, 6
            else:
                raise ValueError(f"unexpected Stooq payload: {payload}")

            open_price = float(normalized_row[open_index])
            high = float(normalized_row[high_index])
            low = float(normalized_row[low_index])
            price = float(normalized_row[price_index])
            volume = int(float(normalized_row[volume_index]))

            prev_close = _fetch_prev_close()
            change_amount = None
            change_pct = None
            amplitude = None
            if prev_close is not None and prev_close > 0:
                change_amount = price - prev_close
                change_pct = (change_amount / prev_close) * 100
                amplitude = ((high - low) / prev_close) * 100

            quote = UnifiedRealtimeQuote(
                code=symbol,
                name=STOCK_NAME_MAP.get(symbol, ''),
                source=RealtimeSource.STOOQ,
                price=price,
                change_pct=round(change_pct, 2) if change_pct is not None else None,
                change_amount=round(change_amount, 4) if change_amount is not None else None,
                volume=volume,
                amount=None,
                volume_ratio=None,
                turnover_rate=None,
                amplitude=round(amplitude, 2) if amplitude is not None else None,
                open_price=open_price,
                high=high,
                low=low,
                pre_close=prev_close,
                pe_ratio=None,
                pb_ratio=None,
                total_mv=None,
                circ_mv=None,
            )
            logger.info(f"[Stooq] 獲取美股 {symbol} 兜底行情成功: 價格={price}")
            return quote
        except Exception as exc:
            logger.warning(f"[Stooq] 解析美股 {symbol} 行情失敗: {exc}")
            return None

    def _get_us_index_realtime_quote(
        self,
        user_code: str,
        yf_symbol: str,
        index_name: str,
    ) -> Optional[UnifiedRealtimeQuote]:
        """
        Get realtime quote for US index (e.g. SPX -> ^GSPC).

        Args:
            user_code: User input code (e.g. SPX)
            yf_symbol: Yahoo Finance symbol (e.g. ^GSPC)
            index_name: Chinese name for the index

        Returns:
            UnifiedRealtimeQuote or None
        """
        import yfinance as yf

        try:
            logger.debug(f"[Yfinance] 獲取美股指數 {user_code} ({yf_symbol}) 實時行情")
            ticker = yf.Ticker(yf_symbol)

            try:
                info = ticker.fast_info
                if info is None:
                    raise ValueError("fast_info is None")
                price = getattr(info, 'lastPrice', None) or getattr(info, 'last_price', None)
                prev_close = getattr(info, 'previousClose', None) or getattr(info, 'previous_close', None)
                open_price = getattr(info, 'open', None)
                high = getattr(info, 'dayHigh', None) or getattr(info, 'day_high', None)
                low = getattr(info, 'dayLow', None) or getattr(info, 'day_low', None)
                volume = getattr(info, 'lastVolume', None) or getattr(info, 'last_volume', None)
            except Exception:
                logger.debug("[Yfinance] fast_info 失敗，嘗試 history 方法")
                hist = ticker.history(period='2d')
                if hist.empty:
                    logger.warning(f"[Yfinance] 無法獲取 {yf_symbol} 的數據")
                    return None
                today = hist.iloc[-1]
                prev = hist.iloc[-2] if len(hist) > 1 else today
                price = float(today['Close'])
                prev_close = float(prev['Close'])
                open_price = float(today['Open'])
                high = float(today['High'])
                low = float(today['Low'])
                volume = int(today['Volume'])

            change_amount = None
            change_pct = None
            if price is not None and prev_close is not None and prev_close > 0:
                change_amount = price - prev_close
                change_pct = (change_amount / prev_close) * 100

            amplitude = None
            if high is not None and low is not None and prev_close is not None and prev_close > 0:
                amplitude = ((high - low) / prev_close) * 100

            quote = UnifiedRealtimeQuote(
                code=user_code,
                name=index_name or user_code,
                source=RealtimeSource.FALLBACK,
                price=price,
                change_pct=round(change_pct, 2) if change_pct is not None else None,
                change_amount=round(change_amount, 4) if change_amount is not None else None,
                volume=volume,
                amount=None,
                volume_ratio=None,
                turnover_rate=None,
                amplitude=round(amplitude, 2) if amplitude is not None else None,
                open_price=open_price,
                high=high,
                low=low,
                pre_close=prev_close,
                pe_ratio=None,
                pb_ratio=None,
                total_mv=None,
                circ_mv=None,
            )
            logger.info(f"[Yfinance] 獲取美股指數 {user_code} 實時行情成功: 價格={price}")
            return quote
        except Exception as e:
            logger.warning(f"[Yfinance] 獲取美股指數 {user_code} 實時行情失敗: {e}")
            return None

    def get_realtime_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        """
        獲取美股/美股指數實時行情數據

        支持美股股票（AAPL、TSLA）和美股指數（SPX、DJI 等）。
        數據來源：yfinance Ticker.info

        Args:
            stock_code: 美股代碼或指數代碼，如 'AMD', 'AAPL', 'SPX', 'DJI'

        Returns:
            UnifiedRealtimeQuote 對象，獲取失敗返回 None
        """
        import yfinance as yf

        # 美股指數：使用映射（SPX -> ^GSPC）
        yf_symbol, index_name = get_us_index_yf_symbol(stock_code)
        if yf_symbol:
            return self._get_us_index_realtime_quote(
                user_code=stock_code.strip().upper(),
                yf_symbol=yf_symbol,
                index_name=index_name,
            )

        # 僅處理美股股票或 JP/KR/TW suffix-only 股票
        if not (self._is_us_stock(stock_code) or self._is_jp_kr_suffix_stock(stock_code)):
            logger.debug(f"[Yfinance] {stock_code} 不是美股或日韓臺 suffix 代碼，跳過")
            return None

        try:
            symbol = self._convert_stock_code(stock_code)
            is_us_symbol = self._is_us_stock(symbol)
            logger.debug(f"[Yfinance] 獲取 {symbol} 實時行情")

            ticker = yf.Ticker(symbol)

            # 嘗試獲取 fast_info（更快，但字段較少）
            try:
                info = ticker.fast_info
                if info is None:
                    raise ValueError("fast_info is None")

                price = getattr(info, 'lastPrice', None) or getattr(info, 'last_price', None)
                prev_close = getattr(info, 'previousClose', None) or getattr(info, 'previous_close', None)
                open_price = getattr(info, 'open', None)
                high = getattr(info, 'dayHigh', None) or getattr(info, 'day_high', None)
                low = getattr(info, 'dayLow', None) or getattr(info, 'day_low', None)
                volume = getattr(info, 'lastVolume', None) or getattr(info, 'last_volume', None)
                market_cap = getattr(info, 'marketCap', None) or getattr(info, 'market_cap', None)

            except Exception:
                # 回退到 history 方法獲取最新數據
                logger.debug("[Yfinance] fast_info 失敗，嘗試 history 方法")
                hist = ticker.history(period='2d')
                if hist.empty:
                    if is_us_symbol:
                        logger.warning(f"[Yfinance] 無法獲取 {symbol} 的數據，嘗試 Stooq 兜底")
                        return self._get_us_stock_quote_from_stooq(symbol)
                    logger.warning(f"[Yfinance] 無法獲取 {symbol} 的數據")
                    return None

                today = hist.iloc[-1]
                prev = hist.iloc[-2] if len(hist) > 1 else today

                price = float(today['Close'])
                prev_close = float(prev['Close'])
                open_price = float(today['Open'])
                high = float(today['High'])
                low = float(today['Low'])
                volume = int(today['Volume'])
                market_cap = None

            # 計算漲跌幅
            change_amount = None
            change_pct = None
            if price is not None and prev_close is not None and prev_close > 0:
                change_amount = price - prev_close
                change_pct = (change_amount / prev_close) * 100

            # 計算振幅
            amplitude = None
            if high is not None and low is not None and prev_close is not None and prev_close > 0:
                amplitude = ((high - low) / prev_close) * 100

            # 獲取股票名稱
            try:
                info_name = ticker.info.get('shortName', '') or ticker.info.get('longName', '') or ''
                name = info_name if is_meaningful_stock_name(info_name, symbol) else STOCK_NAME_MAP.get(symbol, '')
            except Exception:
                name = STOCK_NAME_MAP.get(symbol, '')

            quote = UnifiedRealtimeQuote(
                code=symbol,
                name=name,
                source=RealtimeSource.FALLBACK,
                price=price,
                change_pct=round(change_pct, 2) if change_pct is not None else None,
                change_amount=round(change_amount, 4) if change_amount is not None else None,
                volume=volume,
                amount=None,  # yfinance 不直接提供成交額
                volume_ratio=None,
                turnover_rate=None,
                amplitude=round(amplitude, 2) if amplitude is not None else None,
                open_price=open_price,
                high=high,
                low=low,
                pre_close=prev_close,
                pe_ratio=None,
                pb_ratio=None,
                total_mv=market_cap,
                circ_mv=None,
            )

            logger.info(f"[Yfinance] 獲取 {symbol} 實時行情成功: 價格={price}")
            return quote

        except Exception as e:
            if self._is_us_stock(stock_code):
                logger.warning(f"[Yfinance] 獲取美股 {stock_code} 實時行情失敗: {e}，嘗試 Stooq 兜底")
                return self._get_us_stock_quote_from_stooq(stock_code)
            logger.warning(f"[Yfinance] 獲取 {stock_code} 實時行情失敗: {e}")
            return None


if __name__ == "__main__":
    # 測試代碼
    logging.basicConfig(level=logging.DEBUG)

    fetcher = YfinanceFetcher()

    try:
        df = fetcher.get_daily_data('600519')  # 茅臺
        print(f"獲取成功，共 {len(df)} 條數據")
        print(df.tail())
    except Exception as e:
        print(f"獲取失敗: {e}")
