# -*- coding: utf-8 -*-
"""
===================================
歷史記錄相關模型
===================================

職責：
1. 定義歷史記錄列表和詳情模型
2. 定義分析報告完整模型
"""

from typing import Optional, List, Any, Dict, Literal

from pydantic import BaseModel, ConfigDict, Field

from api.v1.schemas.market_phase import MarketPhaseSummary
from src.schemas.decision_action import DecisionAction


class HistoryItem(BaseModel):
    """歷史記錄摘要（列表展示用）"""

    id: Optional[int] = Field(None, description="分析歷史記錄主鍵 ID")
    query_id: str = Field(..., description="分析記錄關聯 query_id（批量分析時重複）")
    stock_code: str = Field(..., description="股票代碼")
    stock_name: Optional[str] = Field(None, description="股票名稱")
    report_type: Optional[str] = Field(None, description="報告類型")
    trend_prediction: Optional[str] = Field(None, description="趨勢預測")
    analysis_summary: Optional[str] = Field(None, description="分析摘要")
    sentiment_score: Optional[int] = Field(
        None,
        description="情緒評分（歷史數據可能超出 0-100 範圍，讀取時不做約束）",
    )
    operation_advice: Optional[str] = Field(None, description="操作建議")
    action: Optional[DecisionAction] = Field(None, description="結構化建議動作 taxonomy")
    action_label: Optional[str] = Field(None, description="建議動作展示標籤")
    current_price: Optional[float] = Field(None, description="分析時股價")
    change_pct: Optional[float] = Field(None, description="分析時漲跌幅(%)")
    volume_ratio: Optional[float] = Field(None, description="分析時量比")
    turnover_rate: Optional[float] = Field(None, description="分析時換手率")
    model_used: Optional[str] = Field(
        None,
        description="分析歷史記錄中的模型快照，僅用於展示歷史元數據；不參與模型配置或運行時路由決策",
    )
    market_phase_summary: Optional[MarketPhaseSummary] = Field(
        None,
        description="本次分析市場階段低敏摘要",
    )
    created_at: Optional[str] = Field(None, description="創建時間")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "id": 1234,
            "query_id": "abc123",
            "stock_code": "600519",
            "stock_name": "貴州茅臺",
            "report_type": "detailed",
            "sentiment_score": 75,
            "operation_advice": "持有",
            "created_at": "2024-01-01T12:00:00"
        }
    })


class HistoryListResponse(BaseModel):
    """歷史記錄列表響應"""
    
    total: int = Field(..., description="總記錄數")
    page: int = Field(..., description="當前頁碼")
    limit: int = Field(..., description="每頁數量")
    items: List[HistoryItem] = Field(default_factory=list, description="記錄列表")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "total": 100,
            "page": 1,
            "limit": 20,
            "items": []
        }
    })


class DeleteHistoryRequest(BaseModel):
    """刪除歷史記錄請求"""

    record_ids: List[int] = Field(default_factory=list, description="要刪除的歷史記錄主鍵 ID 列表")


class DeleteHistoryResponse(BaseModel):
    """刪除歷史記錄響應"""

    deleted: int = Field(..., description="實際刪除的歷史記錄數量")


class NewsIntelItem(BaseModel):
    """新聞情報條目"""

    title: str = Field(..., description="新聞標題")
    snippet: str = Field("", description="新聞摘要（最多200字）")
    url: str = Field(..., description="新聞鏈接")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "title": "公司發布業績快報，營收同比增長 20%",
            "snippet": "公司公告顯示，季度營收同比增長 20%...",
            "url": "https://example.com/news/123"
        }
    })


class NewsIntelResponse(BaseModel):
    """新聞情報響應"""

    total: int = Field(..., description="新聞條數")
    items: List[NewsIntelItem] = Field(default_factory=list, description="新聞列表")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "total": 2,
            "items": []
        }
    })


class ReportMeta(BaseModel):
    """報告元信息"""

    model_config = ConfigDict(protected_namespaces=("model_validate", "model_dump"))

    id: Optional[int] = Field(None, description="分析歷史記錄主鍵 ID（僅歷史報告有此字段）")
    query_id: str = Field(..., description="分析記錄關聯 query_id（批量分析時重複）")
    stock_code: str = Field(..., description="股票代碼")
    stock_name: Optional[str] = Field(None, description="股票名稱")
    report_type: Optional[str] = Field(None, description="報告類型")
    report_language: Optional[str] = Field(None, description="報告輸出語言（zh/en）")
    created_at: Optional[str] = Field(None, description="創建時間")
    current_price: Optional[float] = Field(None, description="分析時股價")
    change_pct: Optional[float] = Field(None, description="分析時漲跌幅(%)")
    model_used: Optional[str] = Field(
        None,
        description="歷史報告元數據中的模型快照，僅用於展示，不影響 Provider/Model/Base URL 運行時路由",
    )
    market_phase_summary: Optional[MarketPhaseSummary] = Field(
        None,
        description="本次分析市場階段低敏摘要",
    )


class ReportSummary(BaseModel):
    """報告概覽區"""
    
    analysis_summary: Optional[str] = Field(None, description="關鍵結論")
    operation_advice: Optional[str] = Field(None, description="操作建議")
    action: Optional[DecisionAction] = Field(None, description="結構化建議動作 taxonomy")
    action_label: Optional[str] = Field(None, description="建議動作展示標籤")
    trend_prediction: Optional[str] = Field(None, description="趨勢預測")
    sentiment_score: Optional[int] = Field(
        None,
        description="情緒評分（歷史數據可能超出 0-100 範圍，讀取時不做約束）",
    )
    sentiment_label: Optional[str] = Field(None, description="情緒標籤")


class ReportStrategy(BaseModel):
    """策略點位區"""
    
    ideal_buy: Optional[str] = Field(None, description="理想買入價")
    secondary_buy: Optional[str] = Field(None, description="第二買入價")
    stop_loss: Optional[str] = Field(None, description="止損價")
    take_profit: Optional[str] = Field(None, description="止盈價")


class AnalysisContextPackOverviewSubject(BaseModel):
    """AnalysisContextPack 可見摘要標的信息"""

    code: str = Field(..., description="股票代碼")
    stock_name: Optional[str] = Field(None, description="股票名稱")
    market: Optional[str] = Field(None, description="市場")


class AnalysisContextPackOverviewBlock(BaseModel):
    """AnalysisContextPack 可見摘要數據塊"""

    key: str = Field(..., description="數據塊穩定 key")
    label: str = Field(..., description="數據塊展示名稱")
    status: Literal[
        "available",
        "missing",
        "not_supported",
        "fallback",
        "stale",
        "estimated",
        "partial",
        "fetch_failed",
    ] = Field(..., description="數據塊質量狀態")
    source: Optional[str] = Field(None, description="數據來源")
    warnings: List[str] = Field(default_factory=list, description="數據塊告警碼")
    missing_reasons: List[str] = Field(default_factory=list, description="缺失原因")


class AnalysisContextPackOverviewCounts(BaseModel):
    """AnalysisContextPack 可見摘要狀態計數"""

    available: int = 0
    missing: int = 0
    not_supported: int = 0
    fallback: int = 0
    stale: int = 0
    estimated: int = 0
    partial: int = 0
    fetch_failed: int = 0


class AnalysisContextPackOverviewMetadata(BaseModel):
    """AnalysisContextPack 可見摘要元數據"""

    trigger_source: Optional[str] = Field(None, description="觸發來源")
    news_result_count: Optional[int] = Field(None, description="新聞結果數量")


class AnalysisContextPackOverviewDataQuality(BaseModel):
    """AnalysisContextPack 可見摘要數據質量評分"""

    overall_score: Optional[int] = Field(None, ge=0, le=100, description="輸入數據質量總分")
    level: Optional[Literal["good", "usable", "limited", "poor"]] = Field(
        None,
        description="輸入數據質量等級",
    )
    block_scores: Dict[str, int] = Field(default_factory=dict, description="固定數據塊質量分")
    limitations: List[str] = Field(default_factory=list, description="低敏數據限制說明")


class AnalysisContextPackOverview(BaseModel):
    """歷史/API 可見的低敏 AnalysisContextPack 摘要"""

    pack_version: str = Field(..., description="AnalysisContextPack 版本")
    created_at: Optional[str] = Field(None, description="創建時間")
    subject: AnalysisContextPackOverviewSubject
    blocks: List[AnalysisContextPackOverviewBlock] = Field(default_factory=list)
    counts: AnalysisContextPackOverviewCounts
    data_quality: Optional[AnalysisContextPackOverviewDataQuality] = Field(
        None,
        description="本次分析輸入數據質量低敏摘要",
    )
    warnings: List[str] = Field(default_factory=list, description="頂層數據質量提醒")
    metadata: AnalysisContextPackOverviewMetadata = Field(default_factory=AnalysisContextPackOverviewMetadata)


class ReportDetails(BaseModel):
    """報告詳情區"""
    
    news_content: Optional[str] = Field(None, description="新聞摘要")
    raw_result: Optional[Any] = Field(None, description="原始分析結果（JSON）")
    context_snapshot: Optional[Any] = Field(None, description="分析時上下文快照（JSON）")
    analysis_context_pack_overview: Optional[AnalysisContextPackOverview] = Field(
        None,
        description="本次分析輸入上下文包低敏摘要",
    )
    financial_report: Optional[Any] = Field(None, description="結構化財報摘要（來自 fundamental_context）")
    dividend_metrics: Optional[Any] = Field(None, description="結構化分紅指標（含 TTM 口徑）")
    belong_boards: Optional[Any] = Field(None, description="關聯板塊列表")
    sector_rankings: Optional[Any] = Field(None, description="板塊漲跌榜（結構 {top, bottom}）")


class AnalysisReport(BaseModel):
    """完整分析報告"""

    meta: ReportMeta = Field(..., description="元信息")
    summary: ReportSummary = Field(..., description="概覽區")
    strategy: Optional[ReportStrategy] = Field(None, description="策略點位區")
    details: Optional[ReportDetails] = Field(None, description="詳情區")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "meta": {
                "query_id": "abc123",
                "stock_code": "600519",
                "stock_name": "貴州茅臺",
                "report_type": "detailed",
                "report_language": "zh",
                "created_at": "2024-01-01T12:00:00"
            },
            "summary": {
                "analysis_summary": "技術面向好，建議持有",
                "operation_advice": "持有",
                "trend_prediction": "看多",
                "sentiment_score": 75,
                "sentiment_label": "樂觀"
            },
            "strategy": {
                "ideal_buy": "1800.00",
                "secondary_buy": "1750.00",
                "stop_loss": "1700.00",
                "take_profit": "2000.00"
            },
            "details": None
        }
    })


class MarkdownReportResponse(BaseModel):
    """Markdown 格式報告響應"""

    content: str = Field(..., description="Markdown 格式的完整報告內容")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "content": "# 📊 貴州茅臺 (600519) 分析報告\n\n> 分析日期：**2024-01-01**\n\n..."
        }
    })


class StockBarItem(BaseModel):
    """個股欄條目（去重後的股票維度摘要）"""

    id: int = Field(..., description="該股最新一次分析的歷史記錄主鍵 ID")
    stock_code: str = Field(..., description="股票代碼")
    stock_name: Optional[str] = Field(None, description="股票名稱")
    report_type: Optional[str] = Field(None, description="報告類型")
    sentiment_score: Optional[int] = Field(
        None,
        description="最新情緒評分",
    )
    operation_advice: Optional[str] = Field(None, description="最新操作建議")
    action: Optional[DecisionAction] = Field(None, description="結構化建議動作 taxonomy")
    action_label: Optional[str] = Field(None, description="建議動作展示標籤")
    analysis_count: int = Field(..., description="該股票的歷史分析總次數")
    last_analysis_time: Optional[str] = Field(None, description="最近一次分析時間")
    model_used: Optional[str] = Field(
        None,
        description="最新分析使用的模型快照",
    )
    market_phase_summary: Optional[MarketPhaseSummary] = Field(
        None,
        description="最新分析市場階段低敏摘要",
    )
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "id": 1234,
            "stock_code": "600519",
            "stock_name": "貴州茅臺",
            "report_type": "detailed",
            "sentiment_score": 75,
            "operation_advice": "持有",
            "analysis_count": 18,
            "last_analysis_time": "2024-01-01T12:00:00",
            "model_used": "Gemini 2.5 Pro",
        }
    })


class StockBarResponse(BaseModel):
    """個股欄列表響應"""

    total: int = Field(..., description="不重複個股數")
    items: List[StockBarItem] = Field(default_factory=list, description="個股列表")


class WatchlistRequest(BaseModel):
    """自選隊列操作請求"""

    stock_code: str = Field(..., description="股票代碼", min_length=1)


class WatchlistResponse(BaseModel):
    """自選隊列響應"""

    stock_codes: List[str] = Field(default_factory=list, description="當前自選隊列股票代碼列表")
    message: str = Field(..., description="操作結果描述")


class RunDiagnosticComponent(BaseModel):
    """單個運行診斷組件摘要。"""

    key: str = Field(..., description="組件鍵")
    label: str = Field(..., description="組件顯示名稱")
    status: str = Field(..., description="組件狀態：ok/degraded/failed/unknown/not_configured/skipped")
    message: str = Field(..., description="用戶可讀摘要")
    details: Optional[Dict[str, Any]] = Field(None, description="摺疊展示的診斷細節")


class RunDiagnosticSummaryResponse(BaseModel):
    """歷史報告運行診斷摘要。"""

    trace_id: Optional[str] = Field(None, description="診斷 trace ID")
    task_id: Optional[str] = Field(None, description="任務 ID")
    query_id: Optional[str] = Field(None, description="分析 query ID")
    stock_code: Optional[str] = Field(None, description="股票代碼")
    trigger_source: Optional[str] = Field(None, description="觸發來源")
    status: str = Field(..., description="總體狀態：normal/degraded/failed/unknown")
    status_label: str = Field(..., description="總體狀態中文標籤")
    reason: str = Field(..., description="最主要的診斷原因")
    components: Dict[str, RunDiagnosticComponent] = Field(default_factory=dict, description="關鍵鏈路診斷組件")
    copy_text: str = Field(..., description="可複製的脫敏排障文本")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "trace_id": "task_abc123",
            "query_id": "task_abc123",
            "stock_code": "600519",
            "status": "degraded",
            "status_label": "部分降級",
            "reason": "實時行情失敗：timeout",
            "components": {},
            "copy_text": "trace_id: task_abc123\nstock_code: 600519\n...",
        }
    })
