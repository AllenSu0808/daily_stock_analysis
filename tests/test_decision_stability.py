# -*- coding: utf-8 -*-
"""Tests for structure-aware decision stability calibration."""

from types import SimpleNamespace

from src.analyzer import AnalysisResult, _capital_flow_bias, stabilize_decision_with_structure


def _result(
    *,
    decision_type: str,
    operation_advice: str,
    score: int,
    current_price: float,
    change_pct: float = 0.0,
) -> AnalysisResult:
    return AnalysisResult(
        code="002812",
        name="恩捷股份",
        sentiment_score=score,
        trend_prediction="看多" if decision_type == "buy" else "看空",
        operation_advice=operation_advice,
        decision_type=decision_type,
        report_language="zh",
        current_price=current_price,
        change_pct=change_pct,
        dashboard={
            "core_conclusion": {"one_sentence": "原始結論"},
            "data_perspective": {
                "price_position": {
                    "current_price": current_price,
                    "support_level": 30.0,
                    "resistance_level": 34.0,
                }
            },
        },
    )


def _fund_flow(main: float, five_day: float = 0.0, ten_day: float = 0.0) -> dict:
    return {
        "capital_flow": {
            "status": "ok",
            "data": {
                "stock_flow": {
                    "main_net_inflow": main,
                    "inflow_5d": five_day,
                    "inflow_10d": ten_day,
                }
            },
        }
    }


def _unsupported_fund_flow() -> dict:
    return {"capital_flow": {"status": "not_supported", "data": {}}}


def _unsupported_fund_flow_caps() -> dict:
    return {"capital_flow": {"status": "NOT_SUPPORTED", "data": {"stock_flow": {"main_net_inflow": 0}}}}


def test_capital_flow_bias_is_unavailable_when_stock_flow_data_is_missing() -> None:
    assert _capital_flow_bias(_unsupported_fund_flow()) == "unavailable"
    assert _capital_flow_bias({"capital_flow": {"status": "ok", "data": {}}}) == "unavailable"


def test_capital_flow_bias_is_neutral_when_missing_main_windows_conflict() -> None:
    context = {
        "capital_flow": {
            "data": {
                "stock_flow": {
                    "inflow_5d": 2_000_000,
                    "inflow_10d": -1_000_000,
                }
            }
        }
    }

    assert _capital_flow_bias(context) == "neutral"


def test_capital_flow_bias_is_neutral_when_main_conflicts_with_windows() -> None:
    context = _fund_flow(main=-500_000, five_day=1_200_000, ten_day=2_000_000)

    assert _capital_flow_bias(context) == "neutral"


def test_downgrades_buy_near_resistance_without_fund_confirmation() -> None:
    result = _result(
        decision_type="buy",
        operation_advice="買入",
        score=65,
        current_price=33.4,
    )

    stabilize_decision_with_structure(
        result,
        SimpleNamespace(support_levels=[30.0], resistance_levels=[34.0]),
        _fund_flow(main=-1_000_000, five_day=-2_000_000),
    )

    assert result.decision_type == "hold"
    assert result.sentiment_score <= 59
    assert result.operation_advice == "震蕩觀望"
    assert result.dashboard["decision_stability"]["applied"] is True
    assert "不宜僅因短線反彈追買" in result.risk_warning
    assert result.dashboard["core_conclusion"]["signal_type"] == "🟡持有觀望"


def test_downgrades_buy_mid_range_with_neutral_fund_flow() -> None:
    result = _result(
        decision_type="buy",
        operation_advice="買入",
        score=66,
        current_price=32.0,
    )

    stabilize_decision_with_structure(
        result,
        SimpleNamespace(support_levels=[30.0], resistance_levels=[34.0]),
        _fund_flow(main=0, five_day=0, ten_day=0),
    )

    assert result.decision_type == "hold"
    assert result.sentiment_score <= 59
    assert result.operation_advice == "震蕩觀望"
    assert "資金流不明確" in result.risk_warning


def test_downgrades_buy_when_capital_flow_is_unavailable() -> None:
    buy_result = _result(
        decision_type="buy",
        operation_advice="買入",
        score=66,
        current_price=32.0,
    )
    sell_result = _result(
        decision_type="sell",
        operation_advice="賣出",
        score=30,
        current_price=30.4,
        change_pct=-2.1,
    )

    stabilize_decision_with_structure(
        buy_result,
        SimpleNamespace(support_levels=[30.0], resistance_levels=[34.0]),
        _unsupported_fund_flow(),
    )
    stabilize_decision_with_structure(
        sell_result,
        SimpleNamespace(support_levels=[30.0], resistance_levels=[34.0]),
        _unsupported_fund_flow(),
    )

    assert buy_result.decision_type == "hold"
    assert buy_result.operation_advice == "持有觀察"
    assert buy_result.confidence_level == "低"
    assert buy_result.sentiment_score <= 59
    assert buy_result.dashboard["decision_stability"]["applied"] is True
    assert "買入結論缺少資金面確認" in buy_result.dashboard["decision_stability"]["reason"]
    assert buy_result.dashboard["core_conclusion"]["signal_type"] == "🟡持有觀望"
    assert sell_result.decision_type == "sell"
    assert sell_result.operation_advice == "賣出"
    assert sell_result.dashboard["decision_stability"]["applied"] is False
    assert "未使用資金流校準" in sell_result.dashboard["decision_stability"]["reason"]


def test_downgrades_buy_when_capital_flow_values_are_na() -> None:
    result = _result(
        decision_type="buy",
        operation_advice="買入",
        score=66,
        current_price=33.0,
    )

    stabilize_decision_with_structure(
        result,
        SimpleNamespace(support_levels=[30.0], resistance_levels=[34.0]),
        {
            "capital_flow": {
                "status": "ok",
                "data": {
                    "stock_flow": {
                        "main_net_inflow": "N/A",
                        "inflow_5d": "N/A",
                        "inflow_10d": "N/A",
                    }
                },
            }
        },
    )

    assert result.decision_type == "hold"
    assert result.operation_advice == "持有觀察"
    assert result.dashboard["decision_stability"]["applied"] is True
    assert "資金流數據缺失" in result.dashboard["decision_stability"]["capital_flow_status"]


def test_downgrades_buy_advice_when_decision_type_is_hold_and_capital_flow_unavailable() -> None:
    result = _result(
        decision_type="hold",
        operation_advice="建議買入",
        score=68,
        current_price=32.0,
    )

    stabilize_decision_with_structure(
        result,
        SimpleNamespace(support_levels=[30.0], resistance_levels=[34.0]),
        _unsupported_fund_flow(),
    )

    assert result.decision_type == "hold"
    assert result.operation_advice == "持有觀察"
    assert result.sentiment_score <= 59
    assert result.dashboard["decision_stability"]["applied"] is True
    assert "買入結論缺少資金面確認" in result.dashboard["decision_stability"]["reason"]


def test_downgrades_buy_when_capital_flow_status_is_unavailable_case_insensitive() -> None:
    buy_result = _result(
        decision_type="buy",
        operation_advice="買入",
        score=66,
        current_price=32.0,
    )

    stabilize_decision_with_structure(
        buy_result,
        SimpleNamespace(support_levels=[30.0], resistance_levels=[34.0]),
        _unsupported_fund_flow_caps(),
    )

    assert buy_result.decision_type == "hold"
    assert buy_result.operation_advice == "持有觀察"
    assert buy_result.dashboard["decision_stability"]["applied"] is True
    assert "暫不支持" in str(buy_result.dashboard["decision_stability"]["capital_flow_status"])


def test_skips_downgrade_when_only_generic_risk_warning_and_sell_near_support() -> None:
    result = _result(
        decision_type="sell",
        operation_advice="賣出",
        score=30,
        current_price=30.4,
        change_pct=1.0,
    )
    result.risk_warning = "注意常見回撤風險，建議關注倉位。"

    stabilize_decision_with_structure(
        result,
        SimpleNamespace(support_levels=[30.0], resistance_levels=[34.0]),
        _fund_flow(main=500_000, five_day=300_000),
    )

    assert result.decision_type == "hold"
    assert result.operation_advice == "洗盤觀察"
    assert "價格貼近支撐且未見資金持續流出" in result.risk_warning


def test_stability_can_infer_decision_from_natural_chinese_phrases_in_analyzer_path() -> None:
    result = _result(
        decision_type="建議賣出",
        operation_advice="建議賣出",
        score=30,
        current_price=30.4,
        change_pct=1.0,
    )

    stabilize_decision_with_structure(
        result,
        SimpleNamespace(support_levels=[30.0], resistance_levels=[34.0]),
        _fund_flow(main=500_000, five_day=300_000),
    )

    assert result.decision_type == "hold"
    assert result.operation_advice == "洗盤觀察"
    assert result.dashboard["decision_stability"]["applied"] is True


def test_downgrades_sell_near_support_without_sustained_outflow() -> None:
    result = _result(
        decision_type="sell",
        operation_advice="賣出",
        score=30,
        current_price=30.4,
        change_pct=-2.1,
    )

    stabilize_decision_with_structure(
        result,
        SimpleNamespace(support_levels=[30.0], resistance_levels=[34.0]),
        _fund_flow(main=800_000, five_day=1_200_000),
    )

    assert result.decision_type == "hold"
    assert result.sentiment_score >= 45
    assert result.operation_advice == "洗盤觀察"
    assert "不宜僅因單日下跌直接賣出" in result.risk_warning


def test_preserves_sell_signal_when_significant_risk_exists_near_support() -> None:
    result = _result(
        decision_type="sell",
        operation_advice="賣出",
        score=30,
        current_price=30.4,
        change_pct=-2.1,
    )
    result.risk_warning = "重大利空消息：公司發布重大減持計劃"
    result.dashboard["intelligence"] = {"risk_alerts": ["股東高位減持預告"]}

    stabilize_decision_with_structure(
        result,
        SimpleNamespace(support_levels=[30.0], resistance_levels=[34.0]),
        _fund_flow(main=800_000, five_day=1_200_000),
    )

    assert result.decision_type == "sell"
    assert result.operation_advice == "賣出"


def test_refines_hold_pullback_near_support_as_shakeout_watch() -> None:
    result = _result(
        decision_type="hold",
        operation_advice="持有",
        score=52,
        current_price=30.5,
        change_pct=-1.6,
    )

    stabilize_decision_with_structure(
        result,
        SimpleNamespace(support_levels=[30.0], resistance_levels=[34.0]),
        _fund_flow(main=0, five_day=500_000),
    )

    assert result.decision_type == "hold"
    assert result.operation_advice == "洗盤觀察"
    assert "更適合按洗盤觀察處理" in result.risk_warning
