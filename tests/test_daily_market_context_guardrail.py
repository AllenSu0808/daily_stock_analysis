# -*- coding: utf-8 -*-
"""Tests for Issue #1381 daily market context decision guardrail."""

from __future__ import annotations

from src.analyzer import AnalysisResult
from src.daily_market_context_guardrail import apply_daily_market_context_guardrail


def _result() -> AnalysisResult:
    return AnalysisResult(
        code="600519",
        name="貴州茅臺",
        sentiment_score=82,
        trend_prediction="看多",
        operation_advice="立即買入並積極加倉",
        decision_type="buy",
        confidence_level="高",
        analysis_summary="個股信號強勢",
        dashboard={
            "operation_advice": "立即買入並積極加倉",
            "decision_type": "buy",
            "core_conclusion": {
                "one_sentence": "立即買入並積極加倉",
                "position_advice": {
                    "no_position": "立即買入並積極加倉",
                    "has_position": "繼續加倉",
                },
            },
            "battle_plan": {
                "position_strategy": {
                    "suggested_position": "滿倉買入",
                    "entry_plan": "突破後立即買入",
                    "risk_control": "回踩繼續加倉",
                },
            },
            "phase_decision": {
                "data_limitations": [],
                "confidence_reason": "趨勢強",
            },
        },
    )


def test_conservative_market_context_softens_aggressive_buy() -> None:
    result = _result()

    adjustments = apply_daily_market_context_guardrail(
        result,
        daily_market_context={
            "region": "cn",
            "trade_date": "2026-06-06",
            "summary": "大盤退潮，高風險，建議觀望，倉位上限30%。",
            "risk_tags": ["high_risk", "low_position_cap"],
        },
        report_language="zh",
    )

    assert "daily_market_context_buy_softened" in adjustments
    assert result.decision_type == "hold"
    assert result.operation_advice == "觀望"
    assert len(result.operation_advice) <= 20
    assert result.confidence_level == "中"
    assert result.sentiment_score == 52
    assert result.dashboard["operation_advice"] == result.operation_advice
    assert result.dashboard["decision_type"] == "hold"
    assert result.dashboard["sentiment_score"] == 52
    core = result.dashboard["core_conclusion"]
    assert core["one_sentence"] == result.operation_advice
    assert core["position_advice"] == {
        "no_position": "大盤環境偏謹慎，暫不開新倉，等待風險緩解或確認信號。",
        "has_position": "僅保留小倉觀察，暫不擴大倉位；若跌破風控位優先降低倉位。",
    }
    position_strategy = result.dashboard["battle_plan"]["position_strategy"]
    assert position_strategy == {
        "suggested_position": "小倉/低倉位",
        "entry_plan": "大盤環境偏謹慎，暫不開新倉，等待風險緩解或確認信號。",
        "risk_control": "大盤風險未緩解前不擴大倉位，嚴格控制回撤。",
    }
    phase_decision = result.dashboard["phase_decision"]
    assert any("大盤環境" in item for item in phase_decision["data_limitations"])
    assert "大盤環境" in phase_decision["confidence_reason"]


def test_position_cap_only_market_context_softens_aggressive_buy() -> None:
    cases = [
        ("zh", "市場震蕩，倉位不超過30%。", "立即買入並積極加倉", "高", "觀望"),
        ("en", "Major indices are mixed. Position limit 30%.", "Buy now and add aggressively.", "High", "Watch"),
    ]
    for language, summary, advice, confidence, expected_advice in cases:
        result = _result()
        result.operation_advice = advice
        result.confidence_level = confidence

        adjustments = apply_daily_market_context_guardrail(
            result,
            daily_market_context={
                "region": "us" if language == "en" else "cn",
                "trade_date": "2026-06-06",
                "summary": summary,
                "risk_tags": [],
                "position_cap": "30%",
            },
            report_language=language,
        )

        assert "daily_market_context_buy_softened" in adjustments
        assert result.decision_type == "hold"
        assert result.operation_advice == expected_advice


def test_neutral_market_context_leaves_hold_unchanged() -> None:
    result = _result()
    result.decision_type = "hold"
    result.operation_advice = "持有觀察"
    result.confidence_level = "中"

    adjustments = apply_daily_market_context_guardrail(
        result,
        daily_market_context={
            "region": "cn",
            "trade_date": "2026-06-06",
            "summary": "市場震蕩，結構分化。",
            "risk_tags": [],
        },
        report_language="zh",
    )

    assert adjustments == []
    assert result.decision_type == "hold"
    assert result.operation_advice == "持有觀察"


def test_conservative_market_context_does_not_soften_negative_buy_language() -> None:
    result = _result()
    result.decision_type = "buy"
    result.operation_advice = "暫不加倉，繼續持有觀察。"
    result.confidence_level = "高"

    adjustments = apply_daily_market_context_guardrail(
        result,
        daily_market_context={
            "region": "cn",
            "trade_date": "2026-06-06",
            "summary": "大盤退潮，高風險，建議觀望，倉位上限30%。",
            "risk_tags": ["high_risk", "low_position_cap"],
        },
        report_language="zh",
    )

    assert adjustments == []
    assert result.decision_type == "buy"
    assert result.operation_advice == "暫不加倉，繼續持有觀察。"


def test_conservative_market_context_does_not_soften_no_action_in_english() -> None:
    result = _result()
    result.decision_type = "hold"
    result.operation_advice = "No add now; keep watching for confirmation."

    adjustments = apply_daily_market_context_guardrail(
        result,
        daily_market_context={
            "region": "us",
            "trade_date": "2026-06-06",
            "summary": "Market cooling and elevated risk. Cautious on new positions."
        },
        report_language="en",
    )

    assert adjustments == []
    assert result.decision_type == "hold"
    assert result.operation_advice == "No add now; keep watching for confirmation."


def test_conservative_market_context_does_not_soften_explicit_negative_add_position() -> None:
    result = _result()
    result.decision_type = "buy"
    result.operation_advice = "不建議加倉，等待窗口更清晰。"
    result.confidence_level = "高"

    adjustments = apply_daily_market_context_guardrail(
        result,
        daily_market_context={
            "region": "cn",
            "trade_date": "2026-06-06",
            "summary": "大盤退潮，高風險，建議觀望，倉位上限30%。",
            "risk_tags": ["high_risk", "low_position_cap"],
        },
        report_language="zh",
    )

    assert adjustments == []
    assert result.decision_type == "buy"
    assert result.operation_advice == "不建議加倉，等待窗口更清晰。"


def test_conservative_market_context_softens_generic_buy_advice_phrase() -> None:
    result = _result()
    result.operation_advice = "回踩買入，強支撐上攻。"
    result.confidence_level = "高"

    adjustments = apply_daily_market_context_guardrail(
        result,
        daily_market_context={
            "region": "cn",
            "trade_date": "2026-06-06",
            "summary": "大盤退潮，高風險，建議觀望，倉位上限30%。",
            "risk_tags": ["high_risk", "low_position_cap"],
        },
        report_language="zh",
    )

    assert "daily_market_context_buy_softened" in adjustments
    assert result.decision_type == "hold"
    assert result.operation_advice == "觀望"


def test_conservative_market_context_softens_when_risk_warning_then_recommend_buy() -> None:
    result = _result()
    result.decision_type = "buy"
    result.operation_advice = "風險不能忽視，但建議買入等待確認信號。"
    result.confidence_level = "高"

    adjustments = apply_daily_market_context_guardrail(
        result,
        daily_market_context={
            "region": "cn",
            "trade_date": "2026-06-06",
            "summary": "大盤退潮，高風險，建議觀望，倉位上限30%。",
            "risk_tags": ["high_risk", "low_position_cap"],
        },
        report_language="zh",
    )

    assert "daily_market_context_buy_softened" in adjustments
    assert result.decision_type == "hold"
    assert result.operation_advice == "觀望"


def test_conservative_market_context_softens_when_negated_chase_then_recommend_buy() -> None:
    result = _result()
    result.decision_type = "buy"
    result.operation_advice = "不建議追高，但建議分批買入。"
    result.confidence_level = "高"

    adjustments = apply_daily_market_context_guardrail(
        result,
        daily_market_context={
            "region": "cn",
            "trade_date": "2026-06-06",
            "summary": "大盤退潮，高風險，建議觀望，倉位上限30%。",
            "risk_tags": ["high_risk", "low_position_cap"],
        },
        report_language="zh",
    )

    assert "daily_market_context_buy_softened" in adjustments
    assert result.decision_type == "hold"
    assert result.operation_advice == "觀望"


def test_conservative_market_context_does_not_soften_buy_when_negated_explicitly_in_english() -> None:
    result = _result()
    result.decision_type = "buy"
    result.operation_advice = "No buy now; avoid adding."

    adjustments = apply_daily_market_context_guardrail(
        result,
        daily_market_context={
            "region": "cn",
            "trade_date": "2026-06-06",
            "summary": "大盤退潮，高風險，建議觀望，倉位上限30%。",
            "risk_tags": ["high_risk", "low_position_cap"],
        },
        report_language="en",
    )

    assert adjustments == []
    assert result.decision_type == "buy"
    assert result.operation_advice == "No buy now; avoid adding."


def test_conservative_market_context_does_not_soften_do_not_buy_in_english() -> None:
    result = _result()
    result.decision_type = "buy"
    result.operation_advice = "Do not buy now; sell into strength."

    adjustments = apply_daily_market_context_guardrail(
        result,
        daily_market_context={
            "region": "us",
            "trade_date": "2026-06-06",
            "summary": "Market cooling and elevated risk. Cautious on new positions.",
        },
        report_language="en",
    )

    assert adjustments == []
    assert result.decision_type == "buy"
    assert result.operation_advice == "Do not buy now; sell into strength."
