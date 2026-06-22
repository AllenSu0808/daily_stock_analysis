# -*- coding: utf-8 -*-
"""
大盤復盤市場區域配置

定義各市場區域的指數、新聞搜索詞、Prompt 提示等元數據，
供 MarketAnalyzer 按 region 切換 A 股/美股復盤行爲。
"""

from dataclasses import dataclass
from typing import List


@dataclass
class MarketProfile:
    """大盤復盤市場區域配置"""

    region: str  # "cn" | "us"
    # 用於判斷整體走勢的指數代碼，cn 用上證 000001，us 用標普 SPX
    mood_index_code: str
    # 新聞搜索關鍵詞
    news_queries: List[str]
    # 指數點評 Prompt 提示語
    prompt_index_hint: str
    # 市場概況是否包含漲跌家數、漲停跌停（A 股有，美股無）
    has_market_stats: bool
    # 市場概況是否包含板塊漲跌（A 股有，美股暫無）
    has_sector_rankings: bool


CN_PROFILE = MarketProfile(
    region="cn",
    mood_index_code="000001",
    news_queries=[
        "A股 大盤 復盤",
        "股市 行情 分析",
        "A股 市場 熱點 板塊",
    ],
    prompt_index_hint="分析上證、深證、創業板等各指數走勢特點",
    has_market_stats=True,
    has_sector_rankings=True,
)

US_PROFILE = MarketProfile(
    region="us",
    mood_index_code="SPX",
    news_queries=[
        "美股 大盤",
        "US stock market",
        "S&P 500 NASDAQ",
    ],
    prompt_index_hint="分析標普500、納斯達克、道指等各指數走勢特點",
    has_market_stats=False,
    has_sector_rankings=False,
)

HK_PROFILE = MarketProfile(
    region="hk",
    mood_index_code="HSI",
    news_queries=[
        "港股 大盤 復盤",
        "Hong Kong stock market",
        "恒生指數 行情",
    ],
    prompt_index_hint="分析恒生指數、恒生科技指數、國企指數等各指數走勢特點",
    has_market_stats=False,
    has_sector_rankings=False,
)


def get_profile(region: str) -> MarketProfile:
    """根據 region 返回對應的 MarketProfile"""
    if region == "us":
        return US_PROFILE
    if region == "hk":
        return HK_PROFILE
    return CN_PROFILE
