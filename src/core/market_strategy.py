# -*- coding: utf-8 -*-
"""Market strategy blueprints for CN/HK/US daily market recap."""

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class StrategyDimension:
    """Single strategy dimension used by market recap prompts."""

    name: str
    objective: str
    checkpoints: List[str]


@dataclass(frozen=True)
class MarketStrategyBlueprint:
    """Region specific market strategy blueprint."""

    region: str
    title: str
    positioning: str
    principles: List[str]
    dimensions: List[StrategyDimension]
    action_framework: List[str]

    def to_prompt_block(self) -> str:
        """Render blueprint as prompt instructions."""
        principles_text = "\n".join([f"- {item}" for item in self.principles])
        action_text = "\n".join([f"- {item}" for item in self.action_framework])

        dims = []
        for dim in self.dimensions:
            checkpoints = "\n".join([f"  - {cp}" for cp in dim.checkpoints])
            dims.append(f"- {dim.name}: {dim.objective}\n{checkpoints}")
        dimensions_text = "\n".join(dims)

        return (
            f"## Strategy Blueprint: {self.title}\n"
            f"{self.positioning}\n\n"
            f"### Strategy Principles\n{principles_text}\n\n"
            f"### Analysis Dimensions\n{dimensions_text}\n\n"
            f"### Action Framework\n{action_text}"
        )

    def to_markdown_block(self) -> str:
        """Render blueprint as markdown section for template fallback report."""
        dims = "\n".join([f"- **{dim.name}**: {dim.objective}" for dim in self.dimensions])
        section_title = "### VI. Strategy Framework" if self.region == "us" else "### 六、策略框架"
        return f"{section_title}\n{dims}\n"


CN_BLUEPRINT = MarketStrategyBlueprint(
    region="cn",
    title="A股市場三段式復盤策略",
    positioning="聚焦指數趨勢、資金博弈與板塊輪動，形成次日交易計劃。",
    principles=[
        "先看指數方向，再看量能結構，最後看板塊持續性。",
        "結論必須映射到倉位、節奏與風險控制動作。",
        "判斷使用當日數據與近3日新聞，不臆測未驗證信息。",
    ],
    dimensions=[
        StrategyDimension(
            name="趨勢結構",
            objective="判斷市場處於上升、震蕩還是防守階段。",
            checkpoints=["上證/深證/創業板是否同向", "放量上漲或縮量下跌是否成立", "關鍵支撐阻力是否被突破"],
        ),
        StrategyDimension(
            name="資金情緒",
            objective="識別短線風險偏好與情緒溫度。",
            checkpoints=["漲跌家數與漲跌停結構", "成交額是否擴張", "高位股是否出現分歧"],
        ),
        StrategyDimension(
            name="主線板塊",
            objective="提煉可交易主線與規避方向。",
            checkpoints=["領漲板塊是否具備事件催化", "板塊內部是否有龍頭帶動", "領跌板塊是否擴散"],
        ),
    ],
    action_framework=[
        "進攻：指數共振上行 + 成交額放大 + 主線強化。",
        "均衡：指數分化或縮量震蕩，控制倉位並等待確認。",
        "防守：指數轉弱 + 領跌擴散，優先風控與減倉。",
    ],
)

US_BLUEPRINT = MarketStrategyBlueprint(
    region="us",
    title="US Market Regime Strategy",
    positioning="Focus on index trend, macro narrative, and sector rotation to define next-session risk posture.",
    principles=[
        "Read market regime from S&P 500, Nasdaq, and Dow alignment first.",
        "Separate beta move from theme-driven alpha rotation.",
        "Translate recap into actionable risk-on/risk-off stance with clear invalidation points.",
    ],
    dimensions=[
        StrategyDimension(
            name="Trend Regime",
            objective="Classify the market as momentum, range, or risk-off.",
            checkpoints=[
                "Are SPX/NDX/DJI directionally aligned",
                "Did volume confirm the move",
                "Are key index levels reclaimed or lost",
            ],
        ),
        StrategyDimension(
            name="Macro & Flows",
            objective="Map policy/rates narrative into equity risk appetite.",
            checkpoints=[
                "Treasury yield and USD implications",
                "Breadth and leadership concentration",
                "Defensive vs growth factor rotation",
            ],
        ),
        StrategyDimension(
            name="Sector Themes",
            objective="Identify persistent leaders and vulnerable laggards.",
            checkpoints=[
                "AI/semiconductor/software trend persistence",
                "Energy/financials sensitivity to macro data",
                "Volatility signals from VIX and large-cap earnings",
            ],
        ),
    ],
    action_framework=[
        "Risk-on: broad index breakout with expanding participation.",
        "Neutral: mixed index signals; focus on selective relative strength.",
        "Risk-off: failed breakouts and rising volatility; prioritize capital preservation.",
    ],
)

HK_BLUEPRINT = MarketStrategyBlueprint(
    region="hk",
    title="港股市場三段式復盤策略",
    positioning="聚焦恒生指數趨勢、南向資金博弈與板塊輪動，形成次日交易計劃。",
    principles=[
        "先看恆指/恆科/國企指數方向，再看南向資金情緒，最後看板塊持續性。",
        "結論必須映射到倉位、節奏與風險控制動作。",
        "判斷使用當日數據與近3日新聞，不臆測未驗證信息。",
    ],
    dimensions=[
        StrategyDimension(
            name="趨勢結構",
            objective="判斷市場處於上升、震蕩還是防守階段。",
            checkpoints=["恆指/恆科/國企指數是否同向", "放量上漲或縮量下跌是否成立", "關鍵支撐阻力是否被突破"],
        ),
        StrategyDimension(
            name="資金情緒",
            objective="識別南向資金風險偏好與情緒溫度。",
            checkpoints=["南向資金淨流入方向與規模", "港元匯率與內地政策含義", "市場廣度與龍頭集中度"],
        ),
        StrategyDimension(
            name="主線板塊",
            objective="提煉可交易主線與規避方向。",
            checkpoints=["科技/互聯網平臺趨勢持續性", "金融/地產對政策轉向的敏感度", "防禦與成長因子輪動"],
        ),
    ],
    action_framework=[
        "進攻：恆指共振上行 + 南向資金持續流入 + 主線強化。",
        "均衡：指數分化或縮量震蕩，控制倉位並等待確認。",
        "防守：指數轉弱 + 波動率上升，優先風控與減倉。",
    ],
)


def get_market_strategy_blueprint(region: str) -> MarketStrategyBlueprint:
    """Return strategy blueprint by market region."""
    if region == "us":
        return US_BLUEPRINT
    if region == "hk":
        return HK_BLUEPRINT
    return CN_BLUEPRINT
