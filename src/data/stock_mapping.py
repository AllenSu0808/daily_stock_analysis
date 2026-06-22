# -*- coding: utf-8 -*-
from __future__ import annotations

"""
===================================
股票代碼與名稱映射
===================================

Shared stock code -> name mapping, used by analyzer, data_provider, and name_to_code_resolver.
"""

# Stock code -> name mapping (common stocks)
STOCK_NAME_MAP = {
    # === A-shares ===
    "600519": "貴州茅臺",
    "000001": "平安銀行",
    "300750": "寧德時代",
    "002594": "比亞迪",
    "600036": "招商銀行",
    "601318": "中國平安",
    "000858": "五糧液",
    "600276": "恆瑞醫藥",
    "601012": "隆基綠能",
    "002475": "立訊精密",
    "300059": "東方財富",
    "002415": "海康威視",
    "600900": "長江電力",
    "601166": "興業銀行",
    "600028": "中國石化",
    "600030": "中信證券",
    "600031": "三一重工",
    "600050": "中國聯通",
    "600104": "上汽集團",
    "600111": "北方稀土",
    "600150": "中國船舶",
    "600309": "萬華化學",
    "600406": "國電南瑞",
    "600690": "海爾智家",
    "600760": "中航沈飛",
    "600809": "山西汾酒",
    "600887": "伊利股份",
    "600930": "華電新能",
    "601088": "中國神華",
    "601127": "賽力斯",
    "601211": "國泰海通",
    "601225": "陝西煤業",
    "601288": "農業銀行",
    "601328": "交通銀行",
    "601398": "工商銀行",
    "601601": "中國太保",
    "601628": "中國人壽",
    "601658": "郵儲銀行",
    "601668": "中國建築",
    "601728": "中國電信",
    "601816": "京滬高鐵",
    "601857": "中國石油",
    "601888": "中國中免",
    "601899": "紫金礦業",
    "601919": "中遠海控",
    "601985": "中國核電",
    "601988": "中國銀行",
    "603019": "中科曙光",
    "603259": "藥明康德",
    "603501": "豪威集團",
    "603993": "洛陽鉬業",
    "688008": "瀾起科技",
    "688012": "中微公司",
    "688041": "海光信息",
    "688111": "金山辦公",
    "688256": "寒武紀",
    "688981": "中芯國際",
    # === US stocks ===
    "AAPL": "蘋果",
    "TSLA": "特斯拉",
    "MSFT": "微軟",
    "GOOGL": "谷歌A",
    "GOOG": "谷歌C",
    "AMZN": "亞馬遜",
    "NVDA": "英偉達",
    "META": "Meta",
    "AMD": "AMD",
    "INTC": "英特爾",
    "BABA": "阿里巴巴",
    "PDD": "拼多多",
    "JD": "京東",
    "BIDU": "百度",
    "NIO": "蔚來",
    "XPEV": "小鵬汽車",
    "LI": "理想汽車",
    "COIN": "Coinbase",
    "MSTR": "MicroStrategy",
    # === HK stocks (5-digit) ===
    "00700": "騰訊控股",
    "03690": "美團",
    "01810": "小米集團",
    "09988": "阿里巴巴",
    "09618": "京東集團",
    "09888": "百度集團",
    "01024": "快手",
    "00981": "中芯國際",
    "02015": "理想汽車",
    "09868": "小鵬汽車",
    "00005": "滙豐控股",
    "01299": "友邦保險",
    "00941": "中國移動",
    "00883": "中國海洋石油",
}


def is_meaningful_stock_name(name: str | None, stock_code: str) -> bool:
    """Return whether a stock name is useful for display or caching."""
    if not name:
        return False

    normalized_name = str(name).strip()
    if not normalized_name:
        return False

    normalized_code = (stock_code or "").strip().upper()
    if normalized_name.upper() == normalized_code:
        return False

    if normalized_name.startswith("股票"):
        return False

    placeholder_values = {
        "N/A",
        "NA",
        "NONE",
        "NULL",
        "--",
        "-",
        "UNKNOWN",
        "TICKER",
    }
    if normalized_name.upper() in placeholder_values:
        return False

    return True
