# -*- coding: utf-8 -*-
"""Contract checks for the AnalysisContextPack P0/P1 contract doc."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = PROJECT_ROOT / "docs" / "analysis-context-pack.md"
FULL_GUIDE_PATH = PROJECT_ROOT / "docs" / "full-guide.md"
FULL_GUIDE_EN_PATH = PROJECT_ROOT / "docs" / "full-guide_EN.md"


def _read_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def _section(doc: str, heading: str) -> str:
    marker = f"## {heading}"
    assert marker in doc
    return doc.split(marker, 1)[1].split("\n## ", 1)[0]


def test_analysis_context_pack_doc_has_required_sections() -> None:
    doc = _read_doc()

    for heading in (
        "## 術語與邊界",
        "## P0 範圍與非目標",
        "## P1 內部契約",
        "## P2 Builder 契約",
        "## P3 Runtime Consumption",
        "## P4 歷史記錄、任務狀態與 Web 可見性",
        "## P5 數據質量評分與 Prompt 數據限制",
        "## P6 文檔、遷移與回滾",
        "## 字段質量狀態",
        "## 現有狀態映射",
        "## 七路徑盤點",
        "## 源碼錨點",
        "## 兼容與安全邊界",
    ):
        assert heading in doc


def test_analysis_context_pack_doc_disambiguates_context_surfaces() -> None:
    section = _section(_read_doc(), "術語與邊界")

    for token in (
        "`storage.get_analysis_context()`",
        "`enhanced_context`",
        "`analysis_history.context_snapshot`",
        "Agent executor message context",
        "Agent orchestrator `AgentContext`",
        "`AGENT_ARCH=single`",
        "`AGENT_ARCH=multi`",
    ):
        assert token in section


def test_analysis_context_pack_doc_defines_p0_quality_states() -> None:
    section = _section(_read_doc(), "字段質量狀態")

    for state in (
        "`available`",
        "`missing`",
        "`not_supported`",
        "`fallback`",
        "`stale`",
        "`estimated`",
        "`partial`",
        "`fetch_failed`",
    ):
        assert state in section
    assert "P0 先固定七詞" in section
    assert "P5 在同一 1.0 umbrella 內追加 `fetch_failed`" in section


def test_analysis_context_pack_doc_covers_seven_paths() -> None:
    section = _section(_read_doc(), "七路徑盤點")

    for heading in (
        "### 普通分析",
        "### Agent",
        "### 告警",
        "### 持倉",
        "### 回測",
        "### 歷史",
        "### 通知",
    ):
        assert heading in section


def test_analysis_context_pack_doc_records_agent_context_visibility() -> None:
    section = _section(_read_doc(), "七路徑盤點")

    for token in (
        "`initial_context`",
        "`fundamental_context`",
        "不顯式注入 `fundamental_context` 或 `trend_result`",
        "pre-fetched data",
        "不預注入 `fundamental_context`",
    ):
        assert token in section


def test_analysis_context_pack_doc_records_non_goals_and_safety_boundaries() -> None:
    doc = _read_doc()

    for token in (
        "P1 已新增 `AnalysisContextPack` 內部 schema",
        "不新增 builder",
        "不接入 runtime",
        "不公開完整 pack",
        "不 pack 化 `market_review`",
        "`market_light`",
        "P5 已在同一 1.0 umbrella 內追加該狀態",
        "`analysis_history.context_snapshot.enhanced_context.date`",
        "完整 pack 不默認公開",
        "API key",
        "token",
        "cookie",
        "完整 webhook URL",
        "郵箱密碼",
    ):
        assert token in doc


def test_analysis_context_pack_doc_defines_p1_schema_contract() -> None:
    section = _section(_read_doc(), "P1 內部契約")

    for token in (
        "`src/schemas/analysis_context_pack.py`",
        "`PACK_VERSION = \"1.0\"`",
        "`ContextFieldStatus`",
        "`AnalysisSubject`",
        "`AnalysisContextItem`",
        "`AnalysisContextBlock`",
        "`DataQuality`",
        "`AnalysisContextPack`",
        "`MarketPhaseContext.to_dict()`",
    ):
        assert token in section


def test_analysis_context_pack_doc_records_p1_block_catalog() -> None:
    section = _section(_read_doc(), "P1 內部契約")

    for token in (
        "P1 Block Catalog",
        "`quote`",
        "`daily_bars`",
        "`technical`",
        "`fundamentals`",
        "`news`",
        "`portfolio`",
        "`chip` / `capital_flow`",
        "`events` / `market_context`",
        "不重複新增 `identity` block",
    ):
        assert token in section


def test_analysis_context_pack_doc_records_p1_time_and_status_semantics() -> None:
    section = _section(_read_doc(), "P1 內部契約")

    for token in (
        "`AnalysisContextPack.created_at` 使用 `datetime`",
        "`model_dump(mode=\"json\")` 輸出 ISO 8601",
        "`AnalysisContextItem.timestamp`",
        "`AnalysisContextBlock.timestamp`",
        "Optional[str]",
        "構造時校驗",
        "date-only",
        "`block.status` 表示整塊可用性",
        "`item.status` 表示字段級質量",
        "不實現 `item.status` 到 `block.status` 的自動聚合推導",
    ):
        assert token in section


def test_analysis_context_pack_doc_records_p1_redaction_contract() -> None:
    section = _section(_read_doc(), "P1 內部契約")

    for token in (
        "`AnalysisContextPack.to_safe_dict()`",
        "`redact_sensitive_mapping()`",
        "`api_key`",
        "`access_token`",
        "`authorization_header`",
        "`webhook_url`",
        "`license_key`",
        "[REDACTED]",
        "`data_api`",
        "不掃描普通字符串值",
        "不做 URL 正則脫敏",
    ):
        assert token in section


def test_analysis_context_pack_doc_keeps_later_phases_out_of_p1() -> None:
    section = _section(_read_doc(), "P1 內部契約")

    for token in (
        "不填充運行時數據",
        "不新增 fetcher",
        "不改變 Prompt",
        "不寫入 history/task/report metadata",
        "不把完整 pack 暴露到 API、Web、Bot、Desktop 或通知",
        "P2 builder",
        "P3 runtime",
    ):
        assert token in section


def test_analysis_context_pack_doc_defines_p2_builder_boundaries() -> None:
    section = _section(_read_doc(), "P2 Builder 契約")

    for token in (
        "`AnalysisContextBuilder`",
        "assembler",
        "pipeline 已 fetch",
        "zero-fetch",
        "`PipelineAnalysisArtifacts`",
        "`code`、`stock_name`、`market`",
        "`price_stale`",
        "`quote_stale`",
        "`intraday_realtime_overlay`",
        "`fetch_failed`",
        "P3 runtime",
        "不改變 Prompt",
        "不寫入 history/task/report metadata",
    ):
        assert token in section


def test_analysis_context_pack_docs_record_issue_1386_p3_quality_boundaries() -> None:
    section = _section(_read_doc(), "P2 Builder 契約")

    for token in (
        "`fetched_at`",
        "`provider_timestamp`",
        "`is_stale`",
        "`stale_seconds`",
        "`fallback_from`",
        "`STALE > FALLBACK > AVAILABLE`",
        "builder 只映射上遊 artifact，不做質量評分",
        "`is_partial_bar`、`is_estimated`、`estimated_fields`",
        "`daily_bars` 不承載 partial/estimated",
    ):
        assert token in section

    full_guide = FULL_GUIDE_PATH.read_text(encoding="utf-8")
    full_guide_en = FULL_GUIDE_EN_PATH.read_text(encoding="utf-8")
    assert "盤中數據包與實時質量控制（Issue #1386 P3）" in full_guide
    assert "source` 保留實際成功的數據源 token" in full_guide
    assert "`AnalysisContextBuilder` 只映射這些上遊 artifact" in full_guide
    assert "daily_bars` block 仍表示 storage 中完整日線窗口" in full_guide
    assert "Intraday Data Packet and Realtime Quality Control (Issue #1386 P3)" in full_guide_en
    assert "source` keeps the actual successful provider token" in full_guide_en


def test_analysis_context_pack_doc_defines_p3_runtime_consumption_boundaries() -> None:
    section = _section(_read_doc(), "P3 Runtime Consumption")

    for token in (
        "`StockAnalysisPipeline` 是 summary 的唯一生產者",
        "`PipelineAnalysisArtifacts` -> `AnalysisContextBuilder.build()`",
        "`format_analysis_context_pack_prompt_section()`",
        "`analysis_context_pack_summary`",
        "基礎信息 -> #1386 `market_phase_context` 渲染區塊 -> `analysis_context_pack_summary`",
        "`news.content`、`trend_result`、`chip`、`fundamental_context` 等原始 payload",
        "`AgentExecutor._build_user_message()`",
        "`AgentOrchestrator._build_context()`",
        "`ctx.meta[\"analysis_context_pack_summary\"]`",
        "禁止寫入 `ctx.data`",
        "`BaseAgent._build_messages()`",
        "`_inject_cached_data()`",
        "`news` block 爲 `missing` 是當前 P3 的預期狀態",
        "`analysis_history.context_snapshot`",
        "`analysis_context_pack`",
        "`analysis_context_pack_summary`",
        "Agent 工具級 pack cache 復用",
        "P4 在此基礎上新增低敏 overview",
        "P5 繼續復用 summary 消費路徑",
    ):
        assert token in section

    assert "P3-min" not in section


def test_analysis_context_pack_doc_defines_p4_visibility_contract() -> None:
    section = _section(_read_doc(), "P4 歷史記錄、任務狀態與 Web 可見性")

    for token in (
        "`analysis_context_pack_overview`",
        "專用 renderer",
        "`AnalysisContextPack.to_safe_dict()`",
        "`report.details.analysis_context_pack_overview`",
        "`analysisContextPackOverview`",
        "`GET /api/v1/history/{record_id}`",
        "同步 `POST /api/v1/analysis/analyze`",
        "overview 依賴已持久化的 `analysis_history.context_snapshot`",
        "completed `GET /api/v1/analysis/status/{task_id}`",
        "`sanitize_context_snapshot_for_api()`",
        "`extract_analysis_context_pack_overview()`",
        "`items.value`",
        "`trend_result`",
        "`fundamental_context`",
        "`SAVE_CONTEXT_SNAPSHOT=false`",
        "不持久化整份 `analysis_history.context_snapshot`",
        "`market_phase_summary`",
        "`enhanced_context`",
        "`AnalysisContextSummary`",
        "位置在策略點位和資訊之後、運行診斷之前",
        "默認摺疊",
        "非零的其他狀態計數",
        "不覆蓋 pending/processing TaskPanel",
        "不改通知摘要",
        "質量分/等級",
        "`fetch_failed` 狀態",
    ):
        assert token in section

    assert "運行診斷之後、策略點位之前" not in section


def test_analysis_context_pack_doc_defines_p5_data_quality_contract() -> None:
    section = _section(_read_doc(), "P5 數據質量評分與 Prompt 數據限制")

    for token in (
        "`PACK_VERSION`",
        "`fetch_failed`",
        "`fundamental_context.status == \"failed\"`",
        "`overall_score`",
        "`level`",
        "`block_scores`",
        "`limitations`",
        "`quote=25`",
        "`fetch_failed=25`",
        "`Data Limitations`",
        "`confidence_level` 不得爲 `高` / `High`",
        "`phase × degraded data`",
        "fail-open",
        "不替代 P5 的 confidence/safety 規則",
        "`analysis_context_pack_overview.data_quality`",
        "`details.context_snapshot`",
        "不新增 fetcher",
        "不改變 LLM 輸出 JSON schema",
        "`dashboard.phase_decision`",
    ):
        assert token in section


def test_analysis_context_pack_doc_defines_p6_migration_and_rollback_contract() -> None:
    section = _section(_read_doc(), "P6 文檔、遷移與回滾")

    for token in (
        "四個數據面",
        "內部完整 pack",
        "`analysis_context_pack_summary`",
        "`analysis_context_pack_overview`",
        "`analysis_history.context_snapshot`",
        "摘要可見性矩陣",
        "`SAVE_CONTEXT_SNAPSHOT=true`",
        "`SAVE_CONTEXT_SNAPSHOT=false`",
        "`--no-context-snapshot`",
        "不持久化整份 `analysis_history.context_snapshot`",
        "本次歷史已持久化 `analysis_history.context_snapshot`",
        "`enhanced_context`",
        "`market_phase_summary`",
        "`diagnostics`",
        "`realtime_quote_raw`",
        "不影響當次 `AnalysisContextPack` 構建",
        "不影響內存中的 `result.diagnostic_context_snapshot`",
        "當前不存在",
        "運行時 pack 總開關",
        "發布或代碼回滾",
        "secret",
        "token",
        "webhook",
    ):
        assert token in section


def test_analysis_context_pack_doc_maps_existing_status_terms() -> None:
    section = _section(_read_doc(), "現有狀態映射")

    for token in (
        "`degraded`",
        "`insufficient_data`",
        "`partial_failed`",
        "`data_missing`",
        "`price_stale`",
        "`data_quality=ok/partial/unavailable`",
        "不映射",
    ):
        assert token in section


def test_analysis_context_pack_doc_lists_source_anchors() -> None:
    section = _section(_read_doc(), "源碼錨點")

    for path in (
        "src/core/pipeline.py",
        "src/storage.py",
        "src/analyzer.py",
        "src/agent/orchestrator.py",
        "src/agent/executor.py",
        "src/agent/tools/data_tools.py",
        "src/services/alert_worker.py",
        "src/services/portfolio_service.py",
        "src/services/backtest_service.py",
        "src/repositories/backtest_repo.py",
        "src/services/history_service.py",
        "api/v1/endpoints/history.py",
        "api/v1/endpoints/analysis.py",
        "api/v1/schemas/history.py",
        "api/v1/schemas/portfolio.py",
        "src/notification.py",
        "docs/alerts.md",
        "docs/notifications.md",
    ):
        assert path in section


def test_analysis_context_pack_doc_updates_indexes_and_changelog() -> None:
    index = (PROJECT_ROOT / "docs" / "INDEX.md").read_text(encoding="utf-8")
    index_en = (PROJECT_ROOT / "docs" / "INDEX_EN.md").read_text(encoding="utf-8")
    changelog = (PROJECT_ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "[分析上下文包契約、運行態消費與可見性](analysis-context-pack.md)" in index
    assert "P1/P2 內部契約、P3 Prompt 摘要消費、P4 歷史/API/Web 低敏可見性、P5 數據質量評分、P6 遷移回滾" in index
    assert "#1386 階段感知分析、遷移與回滾入口" in index
    assert (
        "[Analysis Context Pack Contract, Runtime Consumption, And Visibility](analysis-context-pack.md) "
        "<sub><sub>![P6 Badge](https://img.shields.io/badge/P6-orange?style=flat)</sub></sub> "
        "(Chinese-only)"
    ) in index_en
    assert "P1/P2 internal contracts, P3 prompt-summary consumption, P4 history/API/Web low-sensitivity visibility, P5 data-quality scoring, and P6 migration/rollback notes" in index_en
    assert "#1386 market-phase analysis, migration, and rollback entry points" in index_en
    assert "新增 AnalysisContextPack P0 上下文盤點" in changelog
    assert "新增 AnalysisContextPack P1 內部契約與脫敏序列化測試" in changelog
    assert "新增 AnalysisContextPack P2 builder" in changelog
    assert "普通分析與 Agent 運行時 Prompt 接入 AnalysisContextPack 低敏摘要" in changelog
    assert "AnalysisContextPack P4 低敏 overview 接入歷史詳情" in changelog
    assert "AnalysisContextPack P5 增加數據質量評分" in changelog
    assert "明確 AnalysisContextPack P6 文檔、遷移與回滾邊界" in changelog
    assert "#1386 P7 盤前/盤中/盤後分析的入口、遷移、回滾和用戶可見說明" in changelog
    assert "#1386 P5 爲個股分析報告新增 `dashboard.phase_decision`" in changelog
    assert "優化 Web 報告詳情頁信息層級" in changelog


def test_full_guides_cover_issue_1386_p7_user_migration_closeout() -> None:
    guide = (PROJECT_ROOT / "docs" / "full-guide.md").read_text(encoding="utf-8")
    guide_en = (PROJECT_ROOT / "docs" / "full-guide_EN.md").read_text(encoding="utf-8")

    for token in (
        "文檔、配置與遷移說明（Issue #1386 P7）",
        "盤前 / 盤中 / 盤後分析",
        "生成開盤計劃和觀察條件",
        "盤中 / 午間 / 臨近收盤",
        "做實時狀態判斷、風險和機會提醒",
        "`analysis_phase=auto|premarket|intraday|postmarket`",
        "最終報告階段仍以 `report.meta.market_phase_summary.phase` 為準",
        "Web 主分析 / 重新分析 / 持倉手動分析",
        "當前沒有階段覆蓋 selector",
        "進行中任務面板展示請求階段",
        "最終報告頁展示最終階段標籤",
        "Bot / CLI / schedule / 默認 GitHub Actions",
        "只消費公開 `market_phase_summary` 和低敏 `analysis_context_pack_overview`",
        "不公開完整 pack、Prompt summary、新聞正文或持倉敏感明細",
        "舊調用不傳 `analysis_phase` 時保持兼容",
        "回測查詢支持 `analysis_phase=premarket|intraday|postmarket|unknown`",
        "`SAVE_CONTEXT_SNAPSHOT=false`",
        "不關閉當次 `AnalysisContextPack` 構建",
        "低敏 `analysis_context_pack_summary`",
        "`analysis_phase=postmarket`",
        "需要發布回滾或代碼回滾",
    ):
        assert token in guide

    for token in (
        "Documentation, Configuration, And Migration Notes (Issue #1386 P7)",
        "pre-market / intraday / post-market analysis",
        "opening plan and watch conditions",
        "Intraday / lunch break / near close",
        "live state, risk, and opportunity alerts",
        "`analysis_phase=auto|premarket|intraday|postmarket`",
        "final report phase remains `report.meta.market_phase_summary.phase`",
        "Web main analysis / re-analysis / portfolio manual analysis",
        "no phase override selector",
        "the in-progress task panel shows the requested phase",
        "the final report page shows the final phase label",
        "Bot / CLI / schedule / default GitHub Actions",
        "Only consume public `market_phase_summary` and low-sensitivity `analysis_context_pack_overview`",
        "do not expose the full pack, prompt summary, news body text, or sensitive portfolio details",
        "Older callers that omit `analysis_phase` remain compatible",
        "Backtest queries support `analysis_phase=premarket|intraday|postmarket|unknown`",
        "`SAVE_CONTEXT_SNAPSHOT=false`",
        "does not disable current-run `AnalysisContextPack` construction",
        "low-sensitivity `analysis_context_pack_summary`",
        "`analysis_phase=postmarket`",
        "requires a release rollback or code rollback",
    ):
        assert token in guide_en


def test_full_guides_clarify_pack_summary_does_not_replace_legacy_payload_channels() -> None:
    guide = (PROJECT_ROOT / "docs" / "full-guide.md").read_text(encoding="utf-8")
    guide_en = (PROJECT_ROOT / "docs" / "full-guide_EN.md").read_text(encoding="utf-8")

    assert "在這個新增的 pack 摘要區塊中" in guide
    assert "不會通過該區塊看到完整 `news.content`" in guide
    assert "既有 `news_context`、Agent pre-fetched JSON 和 `enhanced_context` 原始數據通道保持 P3 前行爲" in guide
    assert "`report.details.analysis_context_pack_overview`" in guide
    assert "completed `/api/v1/analysis/status/{task_id}`" in guide
    assert "Web 端報告頁在「策略點位」和「資訊」之後展示默認摺疊的數據塊摘要" in guide
    assert "摺疊頭部展示可用數、缺失數、非零的其他狀態計數和觸發來源" in guide
    assert "Web 報告頁在策略點位和資訊之後默認摺疊展示數據塊狀態" in guide
    assert "`details.context_snapshot` 會剝離頂層 `analysis_context_pack_overview`" in guide
    assert "同步分析響應也會讀取本次已落庫的 `analysis_history.context_snapshot` 提取 overview" in guide
    assert "`SAVE_CONTEXT_SNAPSHOT=false` 時新記錄不保證返回該字段" in guide
    assert "AnalysisContextPack 數據質量評分與 Prompt 數據限制（Issue #1389 P5）" in guide
    assert "盤中決策護欄與質量校驗（Issue #1386 P5）" in guide
    assert "`dashboard.phase_decision`" in guide
    assert "`fetch_failed`" in guide
    assert "摺疊頭部新增質量分/等級" in guide
    assert "`report.meta.market_phase_summary`" in guide
    assert "`details.context_snapshot` 會剝離頂層 `market_phase_summary`" in guide
    assert "AnalysisContextPack 文檔、遷移與回滾（Issue #1389 P6）" in guide
    assert "`SAVE_CONTEXT_SNAPSHOT` 是既有環境變量" in guide
    assert "不持久化整份 `analysis_history.context_snapshot`" in guide
    assert "不關閉當次 `AnalysisContextPack` 構建" in guide
    assert "當前沒有運行時 pack 總開關" in guide

    assert "in this new pack-summary section" in guide_en
    assert "not full `news.content`" in guide_en
    assert "Existing `news_context`, Agent pre-fetched JSON, and `enhanced_context` raw-payload channels keep their pre-P3 behavior" in guide_en
    assert "`report.details.analysis_context_pack_overview`" in guide_en
    assert "completed `/api/v1/analysis/status/{task_id}`" in guide_en
    assert "The Web report page renders a collapsed data-block summary after Strategy and News" in guide_en
    assert "available/missing counts, non-zero other status counts, and trigger source" in guide_en
    assert "the Web report page shows the data-block summary collapsed after Strategy and News" in guide_en
    assert "API `details.context_snapshot` strips the top-level `analysis_context_pack_overview`" in guide_en
    assert "sync analysis responses also extract the overview from the just-persisted `analysis_history.context_snapshot`" in guide_en
    assert "new records do not guarantee this field when `SAVE_CONTEXT_SNAPSHOT=false`" in guide_en
    assert "AnalysisContextPack Data Quality Scoring and Prompt Limitations (Issue #1389 P5)" in guide_en
    assert "Intraday Decision Guardrails and Quality Checks (Issue #1386 P5)" in guide_en
    assert "`dashboard.phase_decision`" in guide_en
    assert "`fetch_failed`" in guide_en
    assert "adds quality score/level to the header" in guide_en
    assert "`report.meta.market_phase_summary`" in guide_en
    assert "API `details.context_snapshot` strips the top-level `market_phase_summary`" in guide_en
    assert "AnalysisContextPack Documentation, Migration, and Rollback (Issue #1389 P6)" in guide_en
    assert "`SAVE_CONTEXT_SNAPSHOT` is an existing environment variable" in guide_en
    assert "the full `analysis_history.context_snapshot` is not persisted" in guide_en
    assert "does not disable current-run `AnalysisContextPack` construction" in guide_en
    assert "There is no runtime pack master switch" in guide_en
