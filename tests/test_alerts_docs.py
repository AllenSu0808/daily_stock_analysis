# -*- coding: utf-8 -*-
"""Contract checks for the alert-center documentation."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = PROJECT_ROOT / "docs" / "alerts.md"


def _read_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_alerts_doc_exists_and_links_p0_scope() -> None:
    doc = _read_doc()

    assert "Issue #1202" in doc
    assert "AGENT_EVENT_ALERT_RULES_JSON" in doc
    assert "EventMonitor" in doc
    assert "P1 Alert API MVP" in doc
    assert "P0 不做" in doc


def test_alerts_doc_covers_legacy_runtime_rules() -> None:
    doc = _read_doc()

    for token in ("price_cross", "price_change_percent", "volume_spike"):
        assert token in doc
    for token in ("sentiment_shift", "risk_flag", "custom"):
        assert token in doc


def test_alerts_doc_defines_required_contract_entities() -> None:
    doc = _read_doc()

    required_sections = (
        "### `alert_rule`",
        "### `alert_trigger`",
        "### `alert_notification`",
        "### `alert_cooldown`",
    )
    for section in required_sections:
        assert section in doc

    required_fields = (
        "target_scope",
        "parameters",
        "cooldown_policy",
        "notification_policy",
        "observed_value",
        "data_timestamp",
        "trigger_id",
        "latency_ms",
        "cooldown_until",
    )
    for field_name in required_fields:
        assert field_name in doc


def test_alerts_doc_covers_storage_evaluation_and_rollback() -> None:
    doc = _read_doc()

    assert (PROJECT_ROOT / "src" / "storage.py").is_file()

    for token in (
        "## 存儲方案評估",
        "src/storage.py",
        "src/repositories/",
        "src/services/",
        "data/stock_analysis.db",
        "冪等初始化",
        "回滾說明",
    ):
        assert token in doc


def test_alerts_doc_keeps_p0_non_goals_explicit() -> None:
    doc = _read_doc()

    for token in (
        "P0 階段不新增 `api/v1/schemas/alerts.py`",
        "P0 階段不新增 Web 告警中心頁面",
        "P0 階段不新增數據庫表",
        "P0 階段不實現觸發歷史",
        "P0 階段不自動遷移、刪除或覆蓋 `AGENT_EVENT_ALERT_RULES_JSON`",
        "P0 階段不重寫 `NotificationService`",
    ):
        assert token in doc


def test_alerts_doc_defines_p1_api_mvp_scope() -> None:
    doc = _read_doc()

    for token in (
        "api/v1/endpoints/alerts.py",
        "api/v1/schemas/alerts.py",
        "GET /api/v1/alerts/rules",
        "POST /api/v1/alerts/rules",
        "GET /api/v1/alerts/rules/{rule_id}",
        "PATCH /api/v1/alerts/rules/{rule_id}",
        "DELETE /api/v1/alerts/rules/{rule_id}",
        "POST /api/v1/alerts/rules/{rule_id}/enable",
        "POST /api/v1/alerts/rules/{rule_id}/disable",
        "POST /api/v1/alerts/rules/{rule_id}/test",
        "GET /api/v1/alerts/triggers",
        "GET /api/v1/alerts/notifications",
        "price_cross",
        "price_change_percent",
        "volume_spike",
        "unsupported",
        "脫敏",
        "保留字段",
        "不執行冷卻或自定義通知語義",
    ):
        assert token in doc


def test_alerts_doc_keeps_p1_non_goals_explicit() -> None:
    doc = _read_doc()

    for token in (
        "不新增 Web 告警中心頁面",
        "不讓 schedule worker 加載持久化 active rules",
        "不實現真實 `alert_trigger` / `alert_notification` 寫入",
        "不實現 `alert_cooldown` 執行語義",
        "不實現 MACD、KDJ、CCI、RSI",
        "不自動遷移、刪除、覆蓋或改寫 legacy 配置",
    ):
        assert token in doc


def test_alerts_doc_defines_p2_worker_scope() -> None:
    doc = _read_doc()

    for token in (
        "## P2 告警評估 Worker",
        "src/services/alert_worker.py",
        "agent_event_monitor",
        "持久化 active rules",
        "legacy JSON",
        "`triggered`、`skipped`、`degraded`、`failed`",
        "不寫 `alert_notifications`",
        "不執行 `cooldown_policy`",
    ):
        assert token in doc


def test_alerts_doc_describes_p1_rollback_for_created_tables() -> None:
    doc = _read_doc()

    for token in (
        "P1 新增 Alert API 代碼",
        "`alert_rules` / `alert_triggers` / `alert_notifications` SQLite 表",
        "Base.metadata.create_all()",
        "SQLite 表與數據不會自動刪除",
        "手動刪除相關表",
    ):
        assert token in doc


def test_alerts_doc_defines_p4_notification_and_cooldown_scope() -> None:
    doc = _read_doc()

    for token in (
        "## P4 通知結果與持久化冷卻",
        "`alert_cooldowns`",
        "`alert_notifications`",
        "`rule_id + target + data_source + data_timestamp`",
        "同一數據點去重",
        "`data_timestamp` 缺失時不做去重",
        "`__cooldown__`",
        "`__cooldown_read_failed__`",
        "`__noise_suppressed__`",
        "notification_noise.py",
        "DB 持久化規則正常路徑使用 `alert_cooldowns`",
        "讀取持久化冷卻狀態失敗",
        "legacy `AGENT_EVENT_ALERT_RULES_JSON` 規則繼續使用 worker 進程內 fingerprint",
        "不會寫入或延長 `alert_cooldowns`",
        "最小回滾方式是 revert P4 PR",
    ):
        assert token in doc


def test_alerts_doc_defines_p5_indicator_scope() -> None:
    doc = _read_doc()

    for token in (
        "## P5 技術指標規則",
        "ma_price_cross",
        "rsi_threshold",
        "macd_cross",
        "kdj_cross",
        "cci_threshold",
        "compute_required_bars",
        "requested_days",
        "required_bars > 365",
        "最近兩根已收盤日線",
        "prev <= threshold < current",
        "Wilder",
        "SMMA",
        "alpha=1/period",
        "EMA(fast_period)",
        "alpha=1/k_period",
        "0.015 * mean_deviation",
        "服務器本地時區啟發式",
        "16:00",
        "日期不可判定都會保守丟棄",
        "legacy JSON 路徑",
        "不擴展 `src/agent/events.py`",
        "HTTP 400 + `validation_error`",
        "HTTP 400 + `unsupported_alert_type`",
        "不支持 MACD 柱體放大/收縮",
        "不支持 KDJ 超買/超賣區規則",
        "不支持 MA 與 MA 雙均線交叉",
        "不支持分鐘線",
        "revert P5 PR",
        "skip unsupported `alert_type`",
    ):
        assert token in doc


def test_alerts_doc_defines_p6_portfolio_and_watchlist_scope() -> None:
    doc = _read_doc()

    for token in (
        "## P6 持倉與自選股聯動",
        "P6 scope/type 矩陣",
        "`watchlist`",
        "`portfolio_holdings`",
        "`portfolio_account`",
        "`portfolio_stop_loss`",
        "`portfolio_concentration`",
        "`portfolio_drawdown`",
        "`portfolio_price_stale`",
        "Target Identity Contract",
        "`effective_target`",
        "`RuntimeAlertRule.key`",
        "`{parent_key}|{effective_target}`",
        "dry-run",
        "`degraded_count`",
        "soft cap",
        "cooldown_active",
        "父規則摘要",
        "legacy `AGENT_EVENT_ALERT_RULES_JSON` 不支持 watchlist、portfolio",
        "sector 級集中度",
        "P6 PR",
    ):
        assert token in doc


def test_alerts_doc_defines_p7_market_light_scope() -> None:
    doc = _read_doc()

    for token in (
        "## P7 大盤紅綠燈結構化告警",
        "MarketLightSnapshot",
        "`target_scope=market`",
        "`market_light_status`",
        "`market_light_score_drop`",
        "`statuses=[\"red\",\"yellow\"]`",
        "`min_drop > 0`",
        "`cn` / `hk` / `us`",
        "雙向約束",
        "`context_snapshot.market_light_snapshots`",
        "`data_quality=unavailable`",
        "`partial_comparison=true`",
        "`missing_dimensions`",
        "canonical scorer",
        "thin wrapper",
        "`load_previous_snapshot(region, before_trade_date)`",
        "最大 `snapshot.trade_date`",
        "舊交易日 backfill",
        "`TRADING_DAY_CHECK_ENABLED`",
        "`data_source=market_light`",
        "legacy `AGENT_EVENT_ALERT_RULES_JSON` 不支持 market 規則",
        "revert P7 PR",
    ):
        assert token in doc


def test_alerts_doc_covers_issue_1386_p7_user_visibility_boundary() -> None:
    doc = _read_doc()
    p7_section = doc.split("#1386 P7 的用戶邊界：", 1)[1].split(
        "\n\n回滾本聯動",
        1,
    )[0]

    for token in (
        "觸發時已經可公開的階段和數據質量摘要",
        "不會自動發起輕量 LLM 盤中分析",
        "不會新增告警表、規則類型、環境變量或 migration",
        "分析 API / Web 手動分析入口",
        "告警通知只保留階段標籤、trigger source、partial-bar warning、數據質量等級和前兩條 limitations",
    ):
        assert token in p7_section


def test_alerts_doc_defines_p8_user_and_deployment_boundaries() -> None:
    doc = _read_doc()

    for token in (
        "## P8 用戶配置與部署邊界",
        "`AGENT_EVENT_MONITOR_ENABLED`",
        "`AGENT_EVENT_MONITOR_INTERVAL_MINUTES`",
        "`NOTIFICATION_ALERT_CHANNELS`",
        "`route_type=alert`",
        "Alert API / Web 告警中心持久化規則",
        "legacy `AGENT_EVENT_ALERT_RULES_JSON`",
        "只兼容 `single_symbol`",
        "P5 技術指標、P6 watchlist/portfolio 或 P7 market light",
        "docker/Dockerfile",
        "`python main.py --schedule`",
        "保留 `data/` 數據庫卷",
        ".github/workflows/00-daily-analysis.yml",
        "一次性分析 workflow",
        "不運行 `--schedule` 後臺 alert worker",
        "沒有映射 `AGENT_EVENT_*`",
        "`/alerts`",
        "Desktop 不新增原生告警管理界面",
        "`triggered`、`skipped`、`degraded`、`failed`",
        "`rule_id + target + data_source + data_timestamp`",
        "回滾 P8 只需 revert 文檔、配置說明和 Web 文案改動",
    ):
        assert token in doc


def test_changelog_mentions_alert_p6_release_note() -> None:
    changelog = (PROJECT_ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "P6" in changelog
    assert "自選股" in changelog
    assert "持倉" in changelog
    assert "賬戶聯動規則" in changelog


def test_changelog_mentions_alert_p8_docs_closeout() -> None:
    changelog = (PROJECT_ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "補齊告警中心 P8 文檔與配置收口說明" in changelog
    assert "GitHub Actions 與 Desktop 邊界" in changelog


def test_changelog_unreleased_keeps_flat_entries() -> None:
    changelog = (PROJECT_ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased = changelog.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0]

    assert "\n### " not in unreleased
