# -*- coding: utf-8 -*-
"""
===================================
美股指數與股票代碼工具
===================================

提供：
1. 美股指數代碼映射（如 SPX -> ^GSPC）
2. 美股股票代碼識別（AAPL、TSLA 等）

美股指數在 Yahoo Finance 中需使用 ^ 前綴，與股票代碼不同。
"""

import re

# 美股代碼正則：1-5 個大寫字母，可選 .X 後綴（如 BRK.B）
_US_STOCK_PATTERN = re.compile(r'^[A-Z]{1,5}(\.[A-Z])?$')


# 用戶輸入 -> (Yahoo Finance 符號, 中文名稱)
US_INDEX_MAPPING = {
    # 標普 500
    'SPX': ('^GSPC', '標普500指數'),
    '^GSPC': ('^GSPC', '標普500指數'),
    'GSPC': ('^GSPC', '標普500指數'),
    # 道瓊斯工業平均指數
    'DJI': ('^DJI', '道瓊斯工業指數'),
    '^DJI': ('^DJI', '道瓊斯工業指數'),
    'DJIA': ('^DJI', '道瓊斯工業指數'),
    # 納斯達克綜合指數
    'IXIC': ('^IXIC', '納斯達克綜合指數'),
    '^IXIC': ('^IXIC', '納斯達克綜合指數'),
    'NASDAQ': ('^IXIC', '納斯達克綜合指數'),
    # 納斯達克 100
    'NDX': ('^NDX', '納斯達克100指數'),
    '^NDX': ('^NDX', '納斯達克100指數'),
    # VIX 波動率指數
    'VIX': ('^VIX', 'VIX恐慌指數'),
    '^VIX': ('^VIX', 'VIX恐慌指數'),
    # 羅素 2000
    'RUT': ('^RUT', '羅素2000指數'),
    '^RUT': ('^RUT', '羅素2000指數'),
}


def is_us_index_code(code: str) -> bool:
    """
    判斷代碼是否爲美股指數符號。

    Args:
        code: 股票/指數代碼，如 'SPX', 'DJI'

    Returns:
        True 表示是已知美股指數符號，否則 False

    Examples:
        >>> is_us_index_code('SPX')
        True
        >>> is_us_index_code('AAPL')
        False
    """
    return (code or '').strip().upper() in US_INDEX_MAPPING


def is_us_stock_code(code: str) -> bool:
    """
    判斷代碼是否爲美股股票符號（排除美股指數）。

    美股股票代碼爲 1-5 個大寫字母，可選 .X 後綴如 BRK.B。
    美股指數（SPX、DJI 等）明確排除。

    Args:
        code: 股票代碼，如 'AAPL', 'TSLA', 'BRK.B'

    Returns:
        True 表示是美股股票符號，否則 False

    Examples:
        >>> is_us_stock_code('AAPL')
        True
        >>> is_us_stock_code('TSLA')
        True
        >>> is_us_stock_code('BRK.B')
        True
        >>> is_us_stock_code('SPX')
        False
        >>> is_us_stock_code('600519')
        False
    """
    normalized = (code or '').strip().upper()
    # 美股指數不是股票
    if normalized in US_INDEX_MAPPING:
        return False
    return bool(_US_STOCK_PATTERN.match(normalized))


def get_us_index_yf_symbol(code: str) -> tuple:
    """
    獲取美股指數的 Yahoo Finance 符號與中文名稱。

    Args:
        code: 用戶輸入，如 'SPX', '^GSPC', 'DJI'

    Returns:
        (yf_symbol, chinese_name) 元組，未找到時返回 (None, None)。

    Examples:
        >>> get_us_index_yf_symbol('SPX')
        ('^GSPC', '標普500指數')
        >>> get_us_index_yf_symbol('AAPL')
        (None, None)
    """
    normalized = (code or '').strip().upper()
    return US_INDEX_MAPPING.get(normalized, (None, None))
