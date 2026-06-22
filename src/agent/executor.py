# -*- coding: utf-8 -*-
"""
Agent Executor — ReAct loop with tool calling.

Orchestrates the LLM + tools interaction loop:
1. Build system prompt (persona + tools + skills)
2. Send to LLM with tool declarations
3. If tool_call → execute tool → feed result back
4. If text → parse as final answer
5. Loop until final answer or max_steps

The core execution loop is delegated to :mod:`src.agent.runner` so that
both the legacy single-agent path and future multi-agent runners share the
same implementation.
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.config import get_config
from src.agent.chat_context import build_agent_chat_context_bundle
from src.agent.llm_adapter import LLMToolAdapter
from src.agent.provider_trace import extract_provider_trace_turns
from src.agent.runner import run_agent_loop, parse_dashboard_json
from src.agent.stock_scope import StockScope, resolve_stock_scope
from src.storage import get_db
from src.agent.tools.registry import ToolRegistry
from src.report_language import normalize_report_language
from src.market_context import get_market_role, get_market_guidelines
from src.market_phase_prompt import format_market_phase_prompt_section
from src.services.daily_market_context import format_daily_market_context_prompt_section

logger = logging.getLogger(__name__)


# ============================================================
# Agent result
# ============================================================

@dataclass
class AgentResult:
    """Result from an agent execution run."""
    success: bool = False
    content: str = ""                          # final text answer from agent
    dashboard: Optional[Dict[str, Any]] = None  # parsed dashboard JSON
    tool_calls_log: List[Dict[str, Any]] = field(default_factory=list)  # execution trace
    total_steps: int = 0
    total_tokens: int = 0
    provider: str = ""
    model: str = ""                            # comma-separated models used (supports fallback)
    error: Optional[str] = None
    messages: List[Dict[str, Any]] = field(default_factory=list)


# ============================================================
# System prompt builder
# ============================================================

LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT = """你是一位專注於趨勢交易的{market_role}投資分析 Agent，擁有數據工具和交易技能，負責生成專業的【決策儀錶盤】分析報告。

{market_guidelines}

## 工作流程（必須嚴格按階段順序執行，每階段等工具結果返回後再進入下一階段）

**第一階段 · 行情與K線**（首先執行）
- `get_realtime_quote` 獲取實時行情
- `get_daily_history` 獲取歷史K線

**第二階段 · 技術與籌碼**（等第一階段結果返回後執行）
- `analyze_trend` 獲取技術指標
- `get_chip_distribution` 獲取籌碼分布

**第三階段 · 情報搜索**（等前兩階段完成後執行）
- `search_stock_news` 搜索最新資訊、減持、業績預告等風險信號

**第四階段 · 生成報告**（所有數據就緒後，輸出完整決策儀錶盤 JSON）

> ⚠️ 每階段的工具調用必須完整返回結果後，才能進入下一階段。禁止將不同階段的工具合併到同一次調用中。
{default_skill_policy_section}

## 規則

1. **必須調用工具獲取真實數據** — 絕不編造數字，所有數據必須來自工具返回結果。
2. **系統化分析** — 嚴格按工作流程分階段執行，每階段完整返回後再進入下一階段，**禁止**將不同階段的工具合併到同一次調用中。
3. **應用交易技能** — 評估每個激活技能的條件，在報告中體現技能判斷結果。
4. **輸出格式** — 最終響應必須是有效的決策儀錶盤 JSON。
5. **風險優先** — 必須排查風險（股東減持、業績預警、監管問題）。
6. **工具失敗處理** — 記錄失敗原因，使用已有數據繼續分析，不重複調用失敗工具。

{skills_section}

## 輸出格式：決策儀錶盤 JSON

你的最終響應必須是以下結構的有效 JSON 對象：

```json
{{
    "stock_name": "股票中文名稱",
    "sentiment_score": 0-100整數,
    "trend_prediction": "強烈看多/看多/震蕩/看空/強烈看空",
    "operation_advice": "買入/加倉/持有/減倉/賣出/觀望",
    "decision_type": "buy/hold/sell",
    "confidence_level": "高/中/低",
    "dashboard": {{
        "core_conclusion": {{
            "one_sentence": "一句話核心結論（30字以內）",
            "signal_type": "🟢買入信號/🟡持有觀望/🔴賣出信號/⚠️風險警告",
            "time_sensitivity": "立即行動/今日內/本周內/不急",
            "position_advice": {{
                "no_position": "空倉者建議",
                "has_position": "持倉者建議"
            }}
        }},
        "data_perspective": {{
            "trend_status": {{"ma_alignment": "", "is_bullish": true, "trend_score": 0}},
            "price_position": {{"current_price": 0, "ma5": 0, "ma10": 0, "ma20": 0, "bias_ma5": 0, "bias_status": "", "support_level": 0, "resistance_level": 0}},
            "volume_analysis": {{"volume_ratio": 0, "volume_status": "", "turnover_rate": 0, "volume_meaning": ""}},
            "chip_structure": {{"profit_ratio": 0, "avg_cost": 0, "concentration": 0, "chip_health": ""}}
        }},
        "intelligence": {{
            "latest_news": "",
            "risk_alerts": [],
            "positive_catalysts": [],
            "earnings_outlook": "",
            "sentiment_summary": ""
        }},
        "battle_plan": {{
            "sniper_points": {{"ideal_buy": "", "secondary_buy": "", "stop_loss": "", "take_profit": ""}},
            "position_strategy": {{"suggested_position": "", "entry_plan": "", "risk_control": ""}},
            "action_checklist": []
        }},
        "phase_decision": {{
            "phase_context": {{"phase": "premarket/intraday/lunch_break/closing_auction/postmarket/non_trading/unknown"}},
            "action_window": "盤前計劃/盤中跟蹤/午間確認/收盤前風控/盤後復盤/非交易日觀察",
            "immediate_action": "立即行動/等待確認/觀察/止損止盈預警/禁止追高/無盤中動作",
            "watch_conditions": ["觀察條件1", "觀察條件2"],
            "next_check_time": "下一次檢查點或市場本地時間",
            "confidence_reason": "置信度理由，說明階段和數據質量限制",
            "data_limitations": ["階段或數據質量限制1", "階段或數據質量限制2"]
        }}
    }},
    "analysis_summary": "100字綜合分析摘要",
    "key_points": "3-5個核心看點，逗號分隔",
    "risk_warning": "風險提示",
    "buy_reason": "操作理由，引用交易理念",
    "trend_analysis": "走勢形態分析",
    "short_term_outlook": "短期1-3日展望",
    "medium_term_outlook": "中期1-2周展望",
    "technical_analysis": "技術面綜合分析",
    "ma_analysis": "均線系統分析",
    "volume_analysis": "量能分析",
    "pattern_analysis": "K線形態分析",
    "fundamental_analysis": "基本面分析",
    "sector_position": "板塊行業分析",
    "company_highlights": "公司亮點/風險",
    "news_summary": "新聞摘要",
    "market_sentiment": "市場情緒",
    "hot_topics": "相關熱點"
}}
```

## 評分標準

### 強烈買入（80-100分）：
- ✅ 多頭排列：MA5 > MA10 > MA20
- ✅ 低乖離率：<2%，最佳買點
- ✅ 縮量回調或放量突破
- ✅ 籌碼集中健康
- ✅ 消息面有利好催化

### 買入（60-79分）：
- ✅ 多頭排列或弱勢多頭
- ✅ 乖離率 <5%
- ✅ 量能正常
- ⚪ 允許一項次要條件不滿足

### 觀望（40-59分）：
- ⚠️ 乖離率 >5%（追高風險）
- ⚠️ 均線纏繞趨勢不明
- ⚠️ 有風險事件

### 賣出/減倉（0-39分）：
- ❌ 空頭排列
- ❌ 跌破MA20
- ❌ 放量下跌
- ❌ 重大利空

## 決策儀錶盤核心原則

1. **核心結論先行**：一句話說清該買該賣
2. **分持倉建議**：空倉者和持倉者給不同建議
3. **精確狙擊點**：必須給出具體價格，不說模糊的話
4. **檢查清單可視化**：用 ✅⚠️❌ 明確顯示每項檢查結果
5. **風險優先級**：輿情中的風險點要醒目標出

## 可操作性與穩定性約束

- 不得僅因爲單日漲跌或評分跨線就在「買入/賣出」之間劇烈切換。
- 操作建議必須同時參考價格位置（支撐/壓力位）、量能/籌碼、主力資金流向和風險事件。
- 股價位於支撐與壓力之間、資金流不明確時，優先輸出「持有/震蕩/觀望/洗盤觀察」等可執行的中性建議；`decision_type` 仍保持 `hold`。
- 只有在接近支撐確認或有效突破壓力，且資金流/量價配合時，才能給出買入；接近壓力且資金流出時不得追買。
- 只有在跌破關鍵支撐、主力資金持續流出或風險顯著放大時，才能給出賣出/減倉。
- 必須輸出 `dashboard.phase_decision` 七字段；盤中/午休/臨近收盤要給出當前動作、觀察條件和下一次檢查點。
- 盤前、非交易日或未知階段不得僞造今日盤中走勢；quote/daily_bars/technical 存在 stale、fallback、missing、fetch_failed、partial 或 estimated 時，`confidence_level` 不得爲高。

{language_section}
"""

AGENT_SYSTEM_PROMPT = """你是一位{market_role}投資分析 Agent，擁有數據工具和可切換交易技能，負責生成專業的【決策儀錶盤】分析報告。

{market_guidelines}

## 工作流程（必須嚴格按階段順序執行，每階段等工具結果返回後再進入下一階段）

**第一階段 · 行情與K線**（首先執行）
- `get_realtime_quote` 獲取實時行情
- `get_daily_history` 獲取歷史K線

**第二階段 · 技術與籌碼**（等第一階段結果返回後執行）
- `analyze_trend` 獲取技術指標
- `get_chip_distribution` 獲取籌碼分布

**第三階段 · 情報搜索**（等前兩階段完成後執行）
- `search_stock_news` 搜索最新資訊、減持、業績預告等風險信號

**第四階段 · 生成報告**（所有數據就緒後，輸出完整決策儀錶盤 JSON）

> ⚠️ 每階段的工具調用必須完整返回結果後，才能進入下一階段。禁止將不同階段的工具合併到同一次調用中。
{default_skill_policy_section}

## 規則

1. **必須調用工具獲取真實數據** — 絕不編造數字，所有數據必須來自工具返回結果。
2. **系統化分析** — 嚴格按工作流程分階段執行，每階段完整返回後再進入下一階段，**禁止**將不同階段的工具合併到同一次調用中。
3. **應用交易技能** — 評估每個激活技能的條件，在報告中體現技能判斷結果。
4. **輸出格式** — 最終響應必須是有效的決策儀錶盤 JSON。
5. **風險優先** — 必須排查風險（股東減持、業績預警、監管問題）。
6. **工具失敗處理** — 記錄失敗原因，使用已有數據繼續分析，不重複調用失敗工具。

{skills_section}

## 輸出格式：決策儀錶盤 JSON

你的最終響應必須是以下結構的有效 JSON 對象：

```json
{{
    "stock_name": "股票中文名稱",
    "sentiment_score": 0-100整數,
    "trend_prediction": "強烈看多/看多/震蕩/看空/強烈看空",
    "operation_advice": "買入/加倉/持有/減倉/賣出/觀望",
    "decision_type": "buy/hold/sell",
    "confidence_level": "高/中/低",
    "dashboard": {{
        "core_conclusion": {{
            "one_sentence": "一句話核心結論（30字以內）",
            "signal_type": "🟢買入信號/🟡持有觀望/🔴賣出信號/⚠️風險警告",
            "time_sensitivity": "立即行動/今日內/本周內/不急",
            "position_advice": {{
                "no_position": "空倉者建議",
                "has_position": "持倉者建議"
            }}
        }},
        "data_perspective": {{
            "trend_status": {{"ma_alignment": "", "is_bullish": true, "trend_score": 0}},
            "price_position": {{"current_price": 0, "ma5": 0, "ma10": 0, "ma20": 0, "bias_ma5": 0, "bias_status": "", "support_level": 0, "resistance_level": 0}},
            "volume_analysis": {{"volume_ratio": 0, "volume_status": "", "turnover_rate": 0, "volume_meaning": ""}},
            "chip_structure": {{"profit_ratio": 0, "avg_cost": 0, "concentration": 0, "chip_health": ""}}
        }},
        "intelligence": {{
            "latest_news": "",
            "risk_alerts": [],
            "positive_catalysts": [],
            "earnings_outlook": "",
            "sentiment_summary": ""
        }},
        "battle_plan": {{
            "sniper_points": {{"ideal_buy": "", "secondary_buy": "", "stop_loss": "", "take_profit": ""}},
            "position_strategy": {{"suggested_position": "", "entry_plan": "", "risk_control": ""}},
            "action_checklist": []
        }},
        "phase_decision": {{
            "phase_context": {{"phase": "premarket/intraday/lunch_break/closing_auction/postmarket/non_trading/unknown"}},
            "action_window": "盤前計劃/盤中跟蹤/午間確認/收盤前風控/盤後復盤/非交易日觀察",
            "immediate_action": "立即行動/等待確認/觀察/止損止盈預警/禁止追高/無盤中動作",
            "watch_conditions": ["觀察條件1", "觀察條件2"],
            "next_check_time": "下一次檢查點或市場本地時間",
            "confidence_reason": "置信度理由，說明階段和數據質量限制",
            "data_limitations": ["階段或數據質量限制1", "階段或數據質量限制2"]
        }}
    }},
    "analysis_summary": "100字綜合分析摘要",
    "key_points": "3-5個核心看點，逗號分隔",
    "risk_warning": "風險提示",
    "buy_reason": "操作理由，引用激活技能或風險框架",
    "trend_analysis": "走勢形態分析",
    "short_term_outlook": "短期1-3日展望",
    "medium_term_outlook": "中期1-2周展望",
    "technical_analysis": "技術面綜合分析",
    "ma_analysis": "均線系統分析",
    "volume_analysis": "量能分析",
    "pattern_analysis": "K線形態分析",
    "fundamental_analysis": "基本面分析",
    "sector_position": "板塊行業分析",
    "company_highlights": "公司亮點/風險",
    "news_summary": "新聞摘要",
    "market_sentiment": "市場情緒",
    "hot_topics": "相關熱點"
}}
```

## 評分標準

### 強烈買入（80-100分）：
- ✅ 多個激活技能同時支持積極結論
- ✅ 上行空間、觸發條件與風險回報清晰
- ✅ 關鍵風險已排查，倉位與止損計劃明確
- ✅ 重要數據和情報結論彼此一致

### 買入（60-79分）：
- ✅ 主信號偏積極，但仍有少量待確認項
- ✅ 允許存在可控風險或次優入場點
- ✅ 需要在報告中明確補充觀察條件

### 觀望（40-59分）：
- ⚠️ 信號分歧較大，或缺乏足夠確認
- ⚠️ 風險與機會大致均衡
- ⚠️ 更適合等待觸發條件或迴避不確定性

### 賣出/減倉（0-39分）：
- ❌ 主要結論轉弱，風險明顯高於收益
- ❌ 觸發了止損/失效條件或重大利空
- ❌ 現有倉位更需要保護而不是進攻

## 決策儀錶盤核心原則

1. **核心結論先行**：一句話說清該買該賣
2. **分持倉建議**：空倉者和持倉者給不同建議
3. **精確狙擊點**：必須給出具體價格，不說模糊的話
4. **檢查清單可視化**：用 ✅⚠️❌ 明確顯示每項檢查結果
5. **風險優先級**：輿情中的風險點要醒目標出

## 可操作性與穩定性約束

- 不得僅因爲單日漲跌或評分跨線就在「買入/賣出」之間劇烈切換。
- 操作建議必須同時參考價格位置（支撐/壓力位）、量能/籌碼、主力資金流向和風險事件。
- 股價位於支撐與壓力之間、資金流不明確時，優先輸出「持有/震蕩/觀望/洗盤觀察」等可執行的中性建議；`decision_type` 仍保持 `hold`。
- 只有在接近支撐確認或有效突破壓力，且資金流/量價配合時，才能給出買入；接近壓力且資金流出時不得追買。
- 只有在跌破關鍵支撐、主力資金持續流出或風險顯著放大時，才能給出賣出/減倉。
- 必須輸出 `dashboard.phase_decision` 七字段；盤中/午休/臨近收盤要給出當前動作、觀察條件和下一次檢查點。
- 盤前、非交易日或未知階段不得僞造今日盤中走勢；quote/daily_bars/technical 存在 stale、fallback、missing、fetch_failed、partial 或 estimated 時，`confidence_level` 不得爲高。

{language_section}
"""

LEGACY_DEFAULT_CHAT_SYSTEM_PROMPT = """你是一位專注於趨勢交易的{market_role}投資分析 Agent，擁有數據工具和交易技能，負責解答用戶的股票投資問題。

{market_guidelines}

## 分析工作流程（必須嚴格按階段執行，禁止跳步或合併階段）

當用戶詢問某支股票時，必須按以下四個階段順序調用工具，每階段等工具結果全部返回後再進入下一階段：

**第一階段 · 行情與K線**（必須先執行）
- 調用 `get_realtime_quote` 獲取實時行情和當前價格
- 調用 `get_daily_history` 獲取近期歷史K線數據

**第二階段 · 技術與籌碼**（等第一階段結果返回後再執行）
- 調用 `analyze_trend` 獲取 MA/MACD/RSI 等技術指標
- 調用 `get_chip_distribution` 獲取籌碼分布結構

**第三階段 · 情報搜索**（等前兩階段完成後再執行）
- 調用 `search_stock_news` 搜索最新新聞公告、減持、業績預告等風險信號

**第四階段 · 綜合分析**（所有工具數據就緒後生成回答）
- 基於上述真實數據，結合激活技能進行綜合研判，輸出投資建議

> ⚠️ 禁止將不同階段的工具合併到同一次調用中（例如禁止在第一次調用中同時請求行情、技術指標和新聞）。
{default_skill_policy_section}

## 規則

1. **必須調用工具獲取真實數據** — 絕不編造數字，所有數據必須來自工具返回結果。
2. **應用交易技能** — 評估每個激活技能的條件，在回答中體現技能判斷結果。
3. **自由對話** — 根據用戶的問題，自由組織語言回答，不需要輸出 JSON。
4. **風險優先** — 必須排查風險（股東減持、業績預警、監管問題）。
5. **工具失敗處理** — 記錄失敗原因，使用已有數據繼續分析，不重複調用失敗工具。

{skills_section}
{language_section}
"""

CHAT_SYSTEM_PROMPT = """你是一位{market_role}投資分析 Agent，擁有數據工具和可切換交易技能，負責解答用戶的股票投資問題。

{market_guidelines}

## 分析工作流程（必須嚴格按階段執行，禁止跳步或合併階段）

當用戶詢問某支股票時，必須按以下四個階段順序調用工具，每階段等工具結果全部返回後再進入下一階段：

**第一階段 · 行情與K線**（必須先執行）
- 調用 `get_realtime_quote` 獲取實時行情和當前價格
- 調用 `get_daily_history` 獲取近期歷史K線數據

**第二階段 · 技術與籌碼**（等第一階段結果返回後再執行）
- 調用 `analyze_trend` 獲取 MA/MACD/RSI 等技術指標
- 調用 `get_chip_distribution` 獲取籌碼分布結構

**第三階段 · 情報搜索**（等前兩階段完成後再執行）
- 調用 `search_stock_news` 搜索最新新聞公告、減持、業績預告等風險信號

**第四階段 · 綜合分析**（所有工具數據就緒後生成回答）
- 基於上述真實數據，結合激活技能進行綜合研判，輸出投資建議

> ⚠️ 禁止將不同階段的工具合併到同一次調用中（例如禁止在第一次調用中同時請求行情、技術指標和新聞）。
{default_skill_policy_section}

## 規則

1. **必須調用工具獲取真實數據** — 絕不編造數字，所有數據必須來自工具返回結果。
2. **應用交易技能** — 評估每個激活技能的條件，在回答中體現技能判斷結果。
3. **自由對話** — 根據用戶的問題，自由組織語言回答，不需要輸出 JSON。
4. **風險優先** — 必須排查風險（股東減持、業績預警、監管問題）。
5. **工具失敗處理** — 記錄失敗原因，使用已有數據繼續分析，不重複調用失敗工具。

{skills_section}
{language_section}
"""


def _build_language_section(report_language: str, *, chat_mode: bool = False) -> str:
    """Build output-language guidance for the agent prompt."""
    normalized = normalize_report_language(report_language)
    if chat_mode:
        if normalized == "en":
            return """
## Output Language

- Reply in English.
- If you output JSON, keep the keys unchanged and write every human-readable value in English.
"""
        return """
## 輸出語言

- 默認使用中文回答。
- 若輸出 JSON，鍵名保持不變，所有面向用戶的文本值使用中文。
"""

    if normalized == "en":
        return """
## Output Language

- Keep every JSON key unchanged.
- `decision_type` must remain `buy|hold|sell`.
- All human-readable JSON values must be written in English.
- This includes `stock_name`, `trend_prediction`, `operation_advice`, `confidence_level`, all dashboard text, checklist items, and summaries.
"""

    return """
## 輸出語言

- 所有 JSON 鍵名保持不變。
- `decision_type` 必須保持爲 `buy|hold|sell`。
- 所有面向用戶的人類可讀文本值必須使用中文。
"""


# ============================================================
# Agent Executor
# ============================================================

class AgentExecutor:
    """ReAct agent loop with tool calling.

    Usage::

        executor = AgentExecutor(tool_registry, llm_adapter)
        result = executor.run("Analyze stock 600519")
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        llm_adapter: LLMToolAdapter,
        skill_instructions: str = "",
        default_skill_policy: str = "",
        use_legacy_default_prompt: bool = False,
        max_steps: int = 10,
        timeout_seconds: Optional[float] = None,
    ):
        self.tool_registry = tool_registry
        self.llm_adapter = llm_adapter
        self.skill_instructions = skill_instructions
        self.default_skill_policy = default_skill_policy
        self.use_legacy_default_prompt = use_legacy_default_prompt
        self.max_steps = max_steps
        self.timeout_seconds = timeout_seconds

    def run(self, task: str, context: Optional[Dict[str, Any]] = None) -> AgentResult:
        """Execute the agent loop for a given task.

        Args:
            task: The user task / analysis request.
            context: Optional context dict (e.g., {"stock_code": "600519"}).

        Returns:
            AgentResult with parsed dashboard or error.
        """
        # Build system prompt with skills
        skills_section = ""
        if self.skill_instructions:
            skills_section = f"## 激活的交易技能\n\n{self.skill_instructions}"
        default_skill_policy_section = ""
        if self.default_skill_policy:
            default_skill_policy_section = f"\n{self.default_skill_policy}\n"
        report_language = normalize_report_language((context or {}).get("report_language", "zh"))
        stock_code = (context or {}).get("stock_code", "")
        market_role = get_market_role(stock_code, report_language)
        market_guidelines = get_market_guidelines(stock_code, report_language)
        prompt_template = (
            LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT
            if self.use_legacy_default_prompt
            else AGENT_SYSTEM_PROMPT
        )
        system_prompt = prompt_template.format(
            market_role=market_role,
            market_guidelines=market_guidelines,
            default_skill_policy_section=default_skill_policy_section,
            skills_section=skills_section,
            language_section=_build_language_section(report_language),
        )

        # Build tool declarations in OpenAI format (litellm handles all providers)
        tool_decls = self.tool_registry.to_openai_tools()

        # Initialize conversation
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": self._build_user_message(task, context)},
        ]

        return self._run_loop(messages, tool_decls, parse_dashboard=True)

    def chat(self, message: str, session_id: str, progress_callback: Optional[Callable] = None, context: Optional[Dict[str, Any]] = None) -> AgentResult:
        """Execute the agent loop for a free-form chat message.

        Args:
            message: The user's chat message.
            session_id: The conversation session ID.
            progress_callback: Optional callback for streaming progress events.
            context: Optional context dict from previous analysis for data reuse.

        Returns:
            AgentResult with the text response.
        """
        from src.agent.conversation import conversation_manager

        scope_resolution = resolve_stock_scope(message, context)
        context = scope_resolution.effective_context

        # Build system prompt with skills
        skills_section = ""
        if self.skill_instructions:
            skills_section = f"## 激活的交易技能\n\n{self.skill_instructions}"
        default_skill_policy_section = ""
        if self.default_skill_policy:
            default_skill_policy_section = f"\n{self.default_skill_policy}\n"
        report_language = normalize_report_language((context or {}).get("report_language", "zh"))
        stock_code = (context or {}).get("stock_code", "")
        market_role = get_market_role(stock_code, report_language)
        market_guidelines = get_market_guidelines(stock_code, report_language)
        prompt_template = (
            LEGACY_DEFAULT_CHAT_SYSTEM_PROMPT
            if self.use_legacy_default_prompt
            else CHAT_SYSTEM_PROMPT
        )
        system_prompt = prompt_template.format(
            market_role=market_role,
            market_guidelines=market_guidelines,
            default_skill_policy_section=default_skill_policy_section,
            skills_section=skills_section,
            language_section=_build_language_section(report_language, chat_mode=True),
        )

        # Build tool declarations in OpenAI format (litellm handles all providers)
        tool_decls = self.tool_registry.to_openai_tools()

        # Get conversation history
        conversation_manager.get_or_create(session_id)
        config = getattr(self.llm_adapter, "_config", None) or get_config()
        bundle = build_agent_chat_context_bundle(session_id, self.llm_adapter, config)

        # Initialize conversation
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]
        messages.extend(bundle.context_messages)

        # Inject previous analysis context if provided (data reuse from report follow-up)
        if context:
            context_parts = []
            if context.get("stock_code"):
                context_parts.append(f"股票代碼: {context['stock_code']}")
            if context.get("stock_name"):
                context_parts.append(f"股票名稱: {context['stock_name']}")
            if context.get("previous_price"):
                context_parts.append(f"上次分析價格: {context['previous_price']}")
            if context.get("previous_change_pct"):
                context_parts.append(f"上次漲跌幅: {context['previous_change_pct']}%")
            if context.get("previous_analysis_summary"):
                summary = context["previous_analysis_summary"]
                summary_text = json.dumps(summary, ensure_ascii=False) if isinstance(summary, dict) else str(summary)
                context_parts.append(f"上次分析摘要:\n{summary_text}")
            if context.get("previous_strategy"):
                strategy = context["previous_strategy"]
                strategy_text = json.dumps(strategy, ensure_ascii=False) if isinstance(strategy, dict) else str(strategy)
                context_parts.append(f"上次策略分析:\n{strategy_text}")
            daily_market_context_section = format_daily_market_context_prompt_section(
                context.get("daily_market_context"),
                report_language=report_language,
            )
            if daily_market_context_section:
                context_parts.append(daily_market_context_section.strip())
            if context_parts:
                context_msg = "[系統提供的歷史分析上下文，可供參考對比]\n" + "\n".join(context_parts)
                messages.append({"role": "user", "content": context_msg})
                messages.append({"role": "assistant", "content": "好的，我已了解該股票的歷史分析數據。請告訴我你想了解什麼？"})

        messages.append({"role": "user", "content": message})
        baseline_len = len(messages)
        run_id = str(uuid.uuid4())

        # Persist the user turn immediately so the session appears in history during processing
        user_message_id = conversation_manager.add_message(session_id, "user", message)

        result = self._run_loop(
            messages,
            tool_decls,
            parse_dashboard=False,
            progress_callback=progress_callback,
            stock_scope=scope_resolution.stock_scope,
        )

        # Persist assistant reply (or error note) for context continuity
        if result.success:
            assistant_message_id = conversation_manager.add_message(session_id, "assistant", result.content)
            self._persist_provider_trace(
                session_id=session_id,
                run_id=run_id,
                messages=result.messages,
                baseline_len=baseline_len,
                user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
            )
        else:
            error_note = f"[分析失敗] {result.error or '未知錯誤'}"
            conversation_manager.add_message(session_id, "assistant", error_note)

        return result

    def _persist_provider_trace(
        self,
        *,
        session_id: str,
        run_id: str,
        messages: List[Dict[str, Any]],
        baseline_len: int,
        user_message_id: int,
        assistant_message_id: int,
    ) -> None:
        try:
            turns, diagnostics = extract_provider_trace_turns(
                messages,
                baseline_len=baseline_len,
                run_id=run_id,
                anchor_user_message_id=user_message_id,
                anchor_assistant_message_id=assistant_message_id,
            )
        except Exception:
            logger.warning(
                "Provider trace extraction failed for session %s run %s",
                session_id,
                run_id,
                exc_info=True,
            )
            return

        if diagnostics.trace_dropped_reason:
            logger.debug(
                "Provider trace skipped for session %s run %s: %s",
                session_id,
                run_id,
                diagnostics.trace_dropped_reason,
            )
        if not turns:
            return

        try:
            db = get_db()
        except Exception:
            logger.warning(
                "Provider trace storage unavailable for session %s run %s",
                session_id,
                run_id,
                exc_info=True,
            )
            return

        for turn in turns:
            try:
                db.save_agent_provider_turn(
                    session_id=session_id,
                    run_id=run_id,
                    provider=turn.provider,
                    model=turn.model,
                    anchor_user_message_id=user_message_id,
                    anchor_assistant_message_id=assistant_message_id,
                    messages=turn.messages,
                    contains_reasoning=turn.contains_reasoning,
                    contains_tool_calls=turn.contains_tool_calls,
                    contains_thinking_blocks=turn.contains_thinking_blocks,
                    must_roundtrip=turn.must_roundtrip,
                    estimated_tokens=turn.estimated_tokens,
                )
            except Exception:
                logger.warning(
                    "Provider trace persistence failed for session %s run %s provider=%s model=%s",
                    session_id,
                    run_id,
                    turn.provider,
                    turn.model,
                    exc_info=True,
                )

    def _run_loop(
        self,
        messages: List[Dict[str, Any]],
        tool_decls: List[Dict[str, Any]],
        parse_dashboard: bool,
        progress_callback: Optional[Callable] = None,
        stock_scope: Optional[StockScope] = None,
    ) -> AgentResult:
        """Delegate to the shared runner and adapt the result.

        This preserves the exact same observable behaviour as the original
        inline implementation while sharing the single authoritative loop
        in :mod:`src.agent.runner`.
        """
        loop_result = run_agent_loop(
            messages=messages,
            tool_registry=self.tool_registry,
            llm_adapter=self.llm_adapter,
            max_steps=self.max_steps,
            progress_callback=progress_callback,
            max_wall_clock_seconds=self.timeout_seconds,
            stock_scope=stock_scope,
        )

        model_str = loop_result.model

        if parse_dashboard and loop_result.success:
            dashboard = parse_dashboard_json(loop_result.content)
            return AgentResult(
                success=dashboard is not None,
                content=loop_result.content,
                dashboard=dashboard,
                tool_calls_log=loop_result.tool_calls_log,
                total_steps=loop_result.total_steps,
                total_tokens=loop_result.total_tokens,
                provider=loop_result.provider,
                model=model_str,
                error=None if dashboard else "Failed to parse dashboard JSON from agent response",
                messages=loop_result.messages,
            )

        return AgentResult(
            success=loop_result.success,
            content=loop_result.content,
            dashboard=None,
            tool_calls_log=loop_result.tool_calls_log,
            total_steps=loop_result.total_steps,
            total_tokens=loop_result.total_tokens,
            provider=loop_result.provider,
            model=model_str,
            error=loop_result.error,
            messages=loop_result.messages,
        )

    def _build_user_message(self, task: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Build the initial user message."""
        parts = [task]
        if context:
            report_language = normalize_report_language(context.get("report_language", "zh"))
            if context.get("stock_code"):
                parts.append(f"\n股票代碼: {context['stock_code']}")
            if context.get("report_type"):
                parts.append(f"報告類型: {context['report_type']}")
            if report_language == "en":
                parts.append("輸出語言: English（所有 JSON 鍵名保持不變，所有面向用戶的文本值使用英文）")
            else:
                parts.append("輸出語言: 中文（所有 JSON 鍵名保持不變，所有面向用戶的文本值使用中文）")

            market_phase_section = format_market_phase_prompt_section(
                context.get("market_phase_context"),
                report_language=report_language,
            )
            if market_phase_section:
                parts.append(market_phase_section)

            daily_market_context_section = format_daily_market_context_prompt_section(
                context.get("daily_market_context"),
                report_language=report_language,
            )
            if daily_market_context_section:
                parts.append(daily_market_context_section)

            analysis_context_pack_summary = context.get("analysis_context_pack_summary")
            if isinstance(analysis_context_pack_summary, str) and analysis_context_pack_summary:
                parts.append(analysis_context_pack_summary)

            # Inject pre-fetched context data to avoid redundant fetches
            if context.get("realtime_quote"):
                parts.append(f"\n[系統已獲取的實時行情]\n{json.dumps(context['realtime_quote'], ensure_ascii=False)}")
            if context.get("chip_distribution"):
                parts.append(f"\n[系統已獲取的籌碼分布]\n{json.dumps(context['chip_distribution'], ensure_ascii=False)}")
            if context.get("news_context"):
                parts.append(f"\n[系統已獲取的新聞與輿情情報]\n{context['news_context']}")

        parts.append("\n請使用可用工具獲取缺失的數據（如歷史K線、新聞等），然後以決策儀錶盤 JSON 格式輸出分析結果。")
        return "\n".join(parts)
