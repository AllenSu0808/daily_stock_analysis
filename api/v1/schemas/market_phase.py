# -*- coding: utf-8 -*-
"""Market phase summary schemas."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


MarketPhaseValue = Literal[
    "premarket",
    "intraday",
    "lunch_break",
    "closing_auction",
    "postmarket",
    "non_trading",
    "unknown",
]


class MarketPhaseSummary(BaseModel):
    """Low-sensitivity market phase metadata exposed on report meta."""

    market: Optional[str] = Field(None, description="市場區域")
    phase: MarketPhaseValue = Field(..., description="市場階段")
    market_local_time: Optional[str] = Field(None, description="市場本地時間")
    session_date: Optional[str] = Field(None, description="市場本地日期")
    effective_daily_bar_date: Optional[str] = Field(None, description="最新可復用完整日線日期")
    is_trading_day: Optional[bool] = Field(None, description="是否交易日")
    is_market_open_now: Optional[bool] = Field(None, description="當前是否開市")
    is_partial_bar: Optional[bool] = Field(None, description="最新日線是否可能未完成")
    minutes_to_open: Optional[int] = Field(None, description="距離開盤分鐘數")
    minutes_to_close: Optional[int] = Field(None, description="距離收盤分鐘數")
    trigger_source: Optional[str] = Field(None, description="觸發來源")
    analysis_intent: Optional[str] = Field(None, description="分析意圖")
    warnings: List[str] = Field(default_factory=list, description="階段推斷降級告警碼")
