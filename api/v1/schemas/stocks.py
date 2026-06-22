# -*- coding: utf-8 -*-
"""
===================================
股票數據相關模型
===================================

職責：
1. 定義股票實時行情模型
2. 定義歷史 K 線數據模型
"""

from typing import Optional, List

from pydantic import BaseModel, ConfigDict, Field


class StockQuote(BaseModel):
    """股票實時行情"""
    
    stock_code: str = Field(..., description="股票代碼")
    stock_name: Optional[str] = Field(None, description="股票名稱")
    current_price: float = Field(..., description="當前價格")
    change: Optional[float] = Field(None, description="漲跌額")
    change_percent: Optional[float] = Field(None, description="漲跌幅 (%)")
    open: Optional[float] = Field(None, description="開盤價")
    high: Optional[float] = Field(None, description="最高價")
    low: Optional[float] = Field(None, description="最低價")
    prev_close: Optional[float] = Field(None, description="昨收價")
    volume: Optional[float] = Field(None, description="成交量（股）")
    amount: Optional[float] = Field(None, description="成交額（元）")
    update_time: Optional[str] = Field(None, description="更新時間")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "stock_code": "600519",
            "stock_name": "貴州茅臺",
            "current_price": 1800.00,
            "change": 15.00,
            "change_percent": 0.84,
            "open": 1785.00,
            "high": 1810.00,
            "low": 1780.00,
            "prev_close": 1785.00,
            "volume": 10000000,
            "amount": 18000000000,
            "update_time": "2024-01-01T15:00:00"
        }
    })


class KLineData(BaseModel):
    """K 線數據點"""
    
    date: str = Field(..., description="日期")
    open: float = Field(..., description="開盤價")
    high: float = Field(..., description="最高價")
    low: float = Field(..., description="最低價")
    close: float = Field(..., description="收盤價")
    volume: Optional[float] = Field(None, description="成交量")
    amount: Optional[float] = Field(None, description="成交額")
    change_percent: Optional[float] = Field(None, description="漲跌幅 (%)")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "date": "2024-01-01",
            "open": 1785.00,
            "high": 1810.00,
            "low": 1780.00,
            "close": 1800.00,
            "volume": 10000000,
            "amount": 18000000000,
            "change_percent": 0.84
        }
    })


class ExtractItem(BaseModel):
    """單條提取結果（代碼、名稱、置信度）"""

    code: Optional[str] = Field(None, description="股票代碼，None 表示解析失敗")
    name: Optional[str] = Field(None, description="股票名稱（如有）")
    confidence: str = Field("medium", description="置信度：high/medium/low")


class ExtractFromImageResponse(BaseModel):
    """圖片股票代碼提取響應"""

    codes: List[str] = Field(..., description="提取的股票代碼（已去重，向後兼容）")
    items: List[ExtractItem] = Field(default_factory=list, description="提取結果明細（代碼+名稱+置信度）")
    raw_text: Optional[str] = Field(None, description="原始 LLM 響應（調試用）")


class StockHistoryResponse(BaseModel):
    """股票歷史行情響應"""
    
    stock_code: str = Field(..., description="股票代碼")
    stock_name: Optional[str] = Field(None, description="股票名稱")
    period: str = Field(..., description="K 線周期")
    data: List[KLineData] = Field(default_factory=list, description="K 線數據列表")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "stock_code": "600519",
            "stock_name": "貴州茅臺",
            "period": "daily",
            "data": []
        }
    })
