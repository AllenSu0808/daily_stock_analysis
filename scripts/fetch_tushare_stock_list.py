#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tushare 股票列表獲取腳本

從 Tushare Pro 獲取 A股、港股、美股列表信息，保存爲 CSV 文件

使用方法：
    python3 scripts/fetch_tushare_stock_list.py
    python3 scripts/fetch_tushare_stock_list.py --a-rk

環境要求：
    - 需要在 .env 中配置 TUSHARE_TOKEN
    - 需要安裝 tushare: pip install tushare
    - 賬號積分要求：
        * A股/港股：2000積分
        * 美股：120積分試用，5000積分正式權限

輸出文件：
    - data/stock_list_a.csv      A股列表（--a-rk 時會覆蓋爲修正後名稱）
    - data/stock_list_hk.csv     港股列表
    - data/stock_list_us.csv     美股列表
    - data/README_stock_list.md  數據說明文檔
"""

import argparse
import os
import sys
import time
import random
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict

import pandas as pd
from dotenv import load_dotenv

# 添加項目根目錄到路徑
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import tushare as ts
except ImportError:
    print("[錯誤] 未安裝 tushare 庫")
    print("請執行: pip install tushare")
    sys.exit(1)


# 配置
load_dotenv()

TUSHARE_TOKEN = os.getenv('TUSHARE_TOKEN')
OUTPUT_DIR = Path(__file__).parent.parent / "data"
PAGE_SIZE = 5000  # 美股每頁讀取數量（API 最大6000，設置5000留餘量）
SLEEP_MIN = 5     # 最小睡眠時間（秒）
SLEEP_MAX = 10    # 最大睡眠時間（秒）
A_RK_BATCH_SIZE = 200
A_RK_FIELDS = "ts_code,name,close,pre_close,trade_time"
A_RK_NAME_PREFIX_RE = re.compile(r"^(XD|XR|DR|N|C)")


def get_tushare_api() -> Optional[ts.pro_api]:
    """
    獲取 Tushare API 實例

    Returns:
        Tushare API 實例，失敗返回 None
    """
    if not TUSHARE_TOKEN:
        print("[錯誤] 未找到 TUSHARE_TOKEN")
        print("請在 .env 文件中配置: TUSHARE_TOKEN=你的token")
        return None

    try:
        api = ts.pro_api(TUSHARE_TOKEN)
        # 測試連接
        api.trade_cal(exchange='SSE', start_date='20240101', end_date='20240101')
        print("✓ Tushare API 連接成功")
        return api
    except Exception as e:
        print(f"[錯誤] Tushare API 連接失敗: {e}")
        print("請檢查：")
        print("  1. TUSHARE_TOKEN 是否正確")
        print("  2. 賬號積分是否足夠（A股/港股需要2000積分）")
        return None


def random_sleep(min_seconds: int = SLEEP_MIN, max_seconds: int = SLEEP_MAX):
    """
    隨機睡眠，避免頻繁請求

    Args:
        min_seconds: 最小睡眠時間
        max_seconds: 最大睡眠時間
    """
    sleep_time = random.uniform(min_seconds, max_seconds)
    print(f"  ⏱  休息 {sleep_time:.1f} 秒...")
    time.sleep(sleep_time)


def fetch_a_stock_list(api: ts.pro_api) -> Optional[pd.DataFrame]:
    """
    獲取 A股列表

    接口：stock_basic
    限量：單次最多6000行（覆蓋全市場A股）

    Args:
        api: Tushare API 實例

    Returns:
        A股數據 DataFrame，失敗返回 None
    """
    print("\n[1/3] 正在獲取 A股列表...")

    try:
        # 獲取所有正常上市的股票
        df = api.stock_basic(
            exchange='',        # 空：全部交易所
            list_status='L',    # L: 上市, D: 退市, P: 暫停上市
            fields='ts_code,symbol,name,area,industry,fullname,enname,cnspell,market,exchange,curr_type,list_status,list_date,delist_date,is_hs,act_name,act_ent_type'
        )

        if df is not None and len(df) > 0:
            print(f"✓ A股列表獲取成功，共 {len(df)} 只股票")
            print("  - 交易所分布：")
            for exchange, count in df['exchange'].value_counts().items():
                print(f"    {exchange}: {count} 只")
            return df
        else:
            print("[錯誤] A股數據爲空")
            return None

    except Exception as e:
        print(f"[錯誤] 獲取 A股列表失敗: {e}")
        return None


def should_fix_a_stock_name(name: str) -> bool:
    """
    判斷 A 股名稱是否屬於需要修正的狀態名。

    主要覆蓋新股、除權除息等前綴：
    XD / XR / DR / N / C
    """
    if name is None:
        return False

    text = str(name).strip()
    if not text or text.lower() in {"nan", "none"}:
        return False

    return bool(A_RK_NAME_PREFIX_RE.match(text))


def chunk_list(items: List[str], chunk_size: int) -> List[List[str]]:
    """將列表按固定大小切片。"""
    return [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]


def fetch_rt_k_names(api: ts.pro_api, ts_codes: List[str]) -> Dict[str, str]:
    """
    批量獲取 rt_k 返回的股票名稱。

    參考官方文檔：
    https://tushare.pro/wctapi/documents/372.md

    rt_k 是 A 股實時日線接口，支持按股票代碼和股票代碼通配符提取
    實時日 K 線行情。本腳本只把它用作名稱回填的輔助來源，修正
    stock_basic 中返回的短期交易狀態前綴名稱。
    """
    if not ts_codes:
        return {}

    name_map: Dict[str, str] = {}
    batches = chunk_list(ts_codes, A_RK_BATCH_SIZE)

    print(f"\n[rt_k] 待修正股票數：{len(ts_codes)}，分 {len(batches)} 批獲取...")

    for index, batch in enumerate(batches, start=1):
        ts_code_param = ",".join(batch)
        print(f"  [rt_k] 第 {index}/{len(batches)} 批：{len(batch)} 只股票")

        try:
            df = api.rt_k(ts_code=ts_code_param, fields=A_RK_FIELDS)
        except Exception as e:
            print(f"  [警告] rt_k 批次 {index} 獲取失敗: {e}")
            continue

        if df is None or len(df) == 0:
            print(f"  [警告] rt_k 批次 {index} 無返回數據")
            continue

        for _, row in df.iterrows():
            code_value = row.get("ts_code", "")
            name_value = row.get("name", "")

            if pd.isna(code_value) or pd.isna(name_value):
                continue

            code = str(code_value).strip()
            name = str(name_value).strip()
            if code and name and code.lower() not in {"nan", "none"} and name.lower() not in {"nan", "none"}:
                name_map[code] = name

        if index < len(batches):
            random_sleep(1, 2)

    print(f"[rt_k] 成功獲取 {len(name_map)} 條名稱映射")
    return name_map


def fix_a_stock_names_with_rt_k(api: ts.pro_api, df: pd.DataFrame) -> pd.DataFrame:
    """
    使用 rt_k 修正 A 股名稱。

    僅對名稱帶有 XD / XR / DR / N / C 前綴的股票進行校正。
    """
    if df is None or len(df) == 0:
        return df

    if "name" not in df.columns or "ts_code" not in df.columns:
        print("[警告] A股數據缺少 ts_code/name 列，跳過 rt_k 名稱修正")
        return df

    fix_mask = df["name"].astype(str).map(should_fix_a_stock_name)
    fix_df = df.loc[fix_mask, ["ts_code", "name"]].copy()

    if fix_df.empty:
        print("[rt_k] 未發現需要修正的 A 股名稱")
        return df

    ts_codes = fix_df["ts_code"].astype(str).tolist()
    print(f"[rt_k] 發現 {len(ts_codes)} 只待修正 A 股：")
    print("  " + ", ".join(ts_codes[:20]) + (" ..." if len(ts_codes) > 20 else ""))

    name_map = fetch_rt_k_names(api, ts_codes)
    if not name_map:
        print("[警告] rt_k 未返回可用名稱，保留原始 A 股名稱")
        return df

    fixed_df = df.copy()
    fixed_count = 0
    for code, new_name in name_map.items():
        if not new_name:
            continue
        match_index = fixed_df.index[fixed_df["ts_code"].astype(str) == code]
        if len(match_index) == 0:
            continue

        old_name = str(fixed_df.loc[match_index[0], "name"])
        if old_name != new_name:
            fixed_df.loc[match_index[0], "name"] = new_name
            fixed_count += 1
            print(f"  ✓ {code}: {old_name} -> {new_name}")

    print(f"[rt_k] A 股名稱修正完成，共修正 {fixed_count} 只股票")
    return fixed_df


def fetch_hk_stock_list(api: ts.pro_api) -> Optional[pd.DataFrame]:
    """
    獲取港股列表

    接口：hk_basic
    限量：單次可提取全部在交易的港股

    Args:
        api: Tushare API 實例

    Returns:
        港股數據 DataFrame，失敗返回 None
    """
    print("\n[2/3] 正在獲取港股列表...")

    try:
        # 獲取所有正常上市的港股
        df = api.hk_basic(
            list_status='L'    # L: 上市, D: 退市
        )

        if df is not None and len(df) > 0:
            print(f"✓ 港股列表獲取成功，共 {len(df)} 只股票")
            return df
        else:
            print("[錯誤] 港股數據爲空")
            return None

    except Exception as e:
        print(f"[錯誤] 獲取港股列表失敗: {e}")
        return None


def fetch_us_stock_list(api: ts.pro_api) -> Optional[pd.DataFrame]:
    """
    獲取美股列表（分頁讀取）

    接口：us_basic
    限量：單次最大6000，需要分頁提取

    Args:
        api: Tushare API 實例

    Returns:
        美股數據 DataFrame，失敗返回 None
    """
    print("\n[3/3] 正在獲取美股列表（分頁讀取）...")

    all_data = []
    offset = 0
    page = 1

    try:
        while True:
            print(f"  第 {page} 頁（offset={offset}）...")

            df = api.us_basic(
                offset=offset,
                limit=PAGE_SIZE
            )

            if df is None or len(df) == 0:
                print(f"  ✓ 第 {page} 頁無數據，讀取完成")
                break

            all_data.append(df)
            print(f"  ✓ 第 {page} 頁獲取 {len(df)} 只股票")

            # 如果返回數據少於頁大小，說明已經到最後一頁
            if len(df) < PAGE_SIZE:
                break

            offset += PAGE_SIZE
            page += 1

            # 隨機休息（最後一頁不需要休息）
            random_sleep()

        if all_data:
            result_df = pd.concat(all_data, ignore_index=True)
            print(f"✓ 美股列表獲取成功，共 {len(result_df)} 只股票（{page} 頁）")

            # 按分類統計
            if 'classify' in result_df.columns:
                print("  - 分類分布：")
                for classify, count in result_df['classify'].value_counts().items():
                    print(f"    {classify}: {count} 只")

            return result_df
        else:
            print("[錯誤] 美股數據爲空")
            return None

    except Exception as e:
        print(f"[錯誤] 獲取美股列表失敗: {e}")
        return None


def save_to_csv(df: pd.DataFrame, filename: str, market_name: str) -> bool:
    """
    保存數據到 CSV 文件

    Args:
        df: 數據 DataFrame
        filename: 文件名
        market_name: 市場名稱（用於日誌）

    Returns:
        是否保存成功
    """
    if df is None or len(df) == 0:
        print(f"[跳過] {market_name} 數據爲空，不保存文件")
        return False

    try:
        output_path = OUTPUT_DIR / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)

        df.to_csv(output_path, index=False, encoding='utf-8-sig')

        file_size = output_path.stat().st_size / 1024  # KB
        print(f"✓ {market_name} 數據已保存：{output_path} ({file_size:.2f} KB)")
        return True

    except Exception as e:
        print(f"[錯誤] 保存 {market_name} 數據失敗: {e}")
        return False


def generate_data_documentation(
    a_df: Optional[pd.DataFrame],
    hk_df: Optional[pd.DataFrame],
    us_df: Optional[pd.DataFrame],
    a_filename: str = "stock_list_a.csv",
    a_title: str = "A股列表"
):
    """
    生成數據說明文檔

    Args:
        a_df: A股數據
        hk_df: 港股數據
        us_df: 美股數據
    """
    doc_path = OUTPUT_DIR / "README_stock_list.md"

    content = f"""# Tushare 股票列表數據說明

> 數據來源：[Tushare Pro](https://tushare.pro)
> 生成時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 文件說明

| 文件 | 說明 | 記錄數 |
|------|------|--------|
| `{a_filename}` | {a_title} | {len(a_df) if a_df is not None else 0} |
| `stock_list_hk.csv` | 港股列表 | {len(hk_df) if hk_df is not None else 0} |
| `stock_list_us.csv` | 美股列表 | {len(us_df) if us_df is not None else 0} |

---

## A股數據（{a_filename}）

### 數據接口
- **接口名稱**：`stock_basic`
- **數據權限**：2000積分起，每分鐘請求50次
- **數據限量**：單次最多6000行（覆蓋全市場A股）

### 字段說明

| 字段名 | 類型 | 說明 | 示例 |
|--------|------|------|------|
| ts_code | str | TS代碼 | 000001.SZ |
| symbol | str | 股票代碼 | 000001 |
| name | str | 股票名稱 | 平安銀行 |
| area | str | 地域 | 深圳 |
| industry | str | 所屬行業 | 銀行 |
| fullname | str | 股票全稱 | 平安銀行股份有限公司 |
| enname | str | 英文全稱 | Ping An Bank Co., Ltd. |
| cnspell | str | 拼音縮寫 | PAYH |
| market | str | 市場類型 | 主板/創業板/科創板/CDR |
| exchange | str | 交易所代碼 | SSE上交所/SZSE深交所/BSE北交所 |
| curr_type | str | 交易貨幣 | CNY |
| list_status | str | 上市狀態 | L上市/D退市/P暫停上市 |
| list_date | str | 上市日期 | 19910403 |
| delist_date | str | 退市日期 | - |
| is_hs | str | 是否滬深港通標的 | N否/H滬股通/S深股通 |
| act_name | str | 實控人名稱 | - |
| act_ent_type | str | 實控人企業性質 | - |

### 數據樣例
```csv
ts_code,symbol,name,area,industry,fullname,enname,cnspell,market,exchange,curr_type,list_status,list_date,delist_date,is_hs,act_name,act_ent_type
000001.SZ,000001,平安銀行,深圳,銀行,平安銀行股份有限公司,Ping An Bank Co., Ltd.,PAYH,主板,SZSE,CNY,L,19910403,,S,,
000002.SZ,000002,萬科A,深圳,全國地產,萬科企業股份有限公司,China Vanke Co., Ltd.,ZKA,主板,SZSE,CNY,L,19910129,,S,,
```

---

## 港股數據（stock_list_hk.csv）

### 數據接口
- **接口名稱**：`hk_basic`
- **數據權限**：用戶需要至少2000積分才可以調取
- **數據限量**：單次可提取全部在交易的港股列表數據

### 字段說明

| 字段名 | 類型 | 說明 | 示例 |
|--------|------|------|------|
| ts_code | str | TS代碼 | 00001.HK |
| name | str | 股票簡稱 | 長和 |
| fullname | str | 公司全稱 | 長江和記實業有限公司 |
| enname | str | 英文名稱 | CK Hutchison Holdings Ltd. |
| cn_spell | str | 拼音 | ZH |
| market | str | 市場類別 | 主板/創業板 |
| list_status | str | 上市狀態 | L上市/D退市/P暫停上市 |
| list_date | str | 上市日期 | 19720731 |
| delist_date | str | 退市日期 | - |
| trade_unit | float | 交易單位 | 1000 |
| isin | str | ISIN代碼 | KYG217651051 |
| curr_type | str | 貨幣代碼 | HKD |

### 數據樣例
```csv
ts_code,name,fullname,enname,cn_spell,market,list_status,list_date,delist_date,trade_unit,isin,curr_type
00001.HK,長和,長江和記實業有限公司,CK Hutchison Holdings Ltd.,ZH,主板,L,19720731,,1000,KYG217651051,HKD
00002.HK,中電控股,中華電力有限公司,CLP Holdings Ltd.,ZDKG,主板,L,19860125,,1000,HK0002007356,HKD
```

---

## 美股數據（stock_list_us.csv）

### 數據接口
- **接口名稱**：`us_basic`
- **數據權限**：120積分可以試用，5000積分有正式權限
- **數據限量**：單次最大6000，可分頁提取

### 字段說明

| 字段名 | 類型 | 說明 | 示例 |
|--------|------|------|------|
| ts_code | str | 美股代碼 | AAPL |
| name | str | 中文名稱 | 蘋果 |
| enname | str | 英文名稱 | Apple Inc. |
| classify | str | 分類 | ADR/GDR/EQT |
| list_date | str | 上市日期 | 19801212 |
| delist_date | str | 退市日期 | - |

### 分類說明
- **ADR**：美國存託憑證（American Depositary Receipt）
- **GDR**：全球存託憑證（Global Depositary Receipt）
- **EQT**：普通股（Equity）

### 數據樣例
```csv
ts_code,name,enname,classify,list_date,delist_date
AAPL,蘋果,Apple Inc.,EQT,19801212,
TSLA,特斯拉,Tesla Inc.,EQT,20100629,
BABA,阿里巴巴,Alibaba Group Holding Ltd.,ADR,20140919,
```

---

## 使用說明

### 讀取數據

```python
import pandas as pd

# 讀取 A股數據
a_stocks = pd.read_csv('data/{a_filename}')

# 讀取港股數據
hk_stocks = pd.read_csv('data/stock_list_hk.csv')

# 讀取美股數據
us_stocks = pd.read_csv('data/stock_list_us.csv')
```

### 代碼格式說明

**A股代碼格式**：
- 滬市：`600000.SH`（主板）、`688xxx.SH`（科創板）、`900xxx.SH`（B股）
- 深市：`000001.SZ`（主板）、`300xxx.SZ`（創業板）、`200xxx.SZ`（B股）
- 北交所：`8xxxxx.BJ`、`4xxxxx.BJ`、`920xxx.BJ`

**港股代碼格式**：
- 格式：`xxxxx.HK`（5位數字 + .HK）
- 示例：`00700.HK`（騰訊控股）

**美股代碼格式**：
- 格式：代碼字母（無後綴）
- 示例：`AAPL`（蘋果）、`TSLA`（特斯拉）

---

## 注意事項

1. **數據更新**：建議定期更新數據（如每月一次）
2. **積分要求**：
   - A股/港股：需要2000積分
   - 美股：120積分試用，5000積分正式權限
3. **請求限制**：注意 API 的每分鐘請求次數限制
4. **數據完整性**：本數據僅包含基礎信息，如需更多數據請參考 Tushare 官方文檔

---

## 相關鏈接

- [Tushare 官網](https://tushare.pro)
- [Tushare 文檔](https://tushare.pro/document/2)
- [積分獲取辦法](https://tushare.pro/document/1)
- [API 數據調試](https://tushare.pro/document/2)
"""

    try:
        with open(doc_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"✓ 數據說明文檔已生成：{doc_path}")
    except Exception as e:
        print(f"[錯誤] 生成說明文檔失敗: {e}")


def build_arg_parser() -> argparse.ArgumentParser:
    """構建命令行參數。"""
    parser = argparse.ArgumentParser(description="Tushare 股票列表獲取工具")
    parser.add_argument(
        "--a-rk",
        action="store_true",
        help="使用 rt_k 修正 A 股中帶 XD/XR/DR/N/C 前綴的名稱，並覆蓋輸出到 stock_list_a.csv",
    )
    return parser


def main(argv: Optional[List[str]] = None):
    """主函數"""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    print("=" * 60)
    print("Tushare 股票列表獲取工具")
    print("=" * 60)
    print(f"[信息] A股名稱修正模式：{'開啓' if args.a_rk else '關閉'}")

    # 1. 獲取 API 實例
    api = get_tushare_api()
    if not api:
        return 1

    # 2. 獲取 A股數據
    a_df = fetch_a_stock_list(api)
    if a_df is not None:
        a_filename = 'stock_list_a.csv'
        a_title = 'A股列表'
        a_market_name = 'A股'

        if args.a_rk:
            a_df = fix_a_stock_names_with_rt_k(api, a_df)
            a_title = 'A股列表（修正後）'

        save_to_csv(a_df, a_filename, a_market_name)

    # 3. 獲取港股數據
    random_sleep()  # 休息後再獲取港股
    hk_df = fetch_hk_stock_list(api)
    if hk_df is not None:
        save_to_csv(hk_df, 'stock_list_hk.csv', '港股')

    # 4. 獲取美股數據（分頁）
    random_sleep()  # 休息後再獲取美股
    us_df = fetch_us_stock_list(api)
    if us_df is not None:
        save_to_csv(us_df, 'stock_list_us.csv', '美股')

    # 5. 生成數據說明文檔
    print("\n正在生成數據說明文檔...")
    a_filename = 'stock_list_a.csv'
    a_title = 'A股列表（修正後）' if args.a_rk else 'A股列表'
    generate_data_documentation(a_df, hk_df, us_df, a_filename=a_filename, a_title=a_title)

    # 6. 總結
    print("\n" + "=" * 60)
    print("任務完成！")
    print("=" * 60)

    total_count = 0
    if a_df is not None:
        total_count += len(a_df)
        print(f"  ✓ A股：{len(a_df)} 只")
    if hk_df is not None:
        total_count += len(hk_df)
        print(f"  ✓ 港股：{len(hk_df)} 只")
    if us_df is not None:
        total_count += len(us_df)
        print(f"  ✓ 美股：{len(us_df)} 只")

    print(f"\n總計：{total_count} 只股票")
    print(f"輸出目錄：{OUTPUT_DIR}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n[中斷] 用戶取消操作")
        sys.exit(1)
    except Exception as e:
        print(f"\n[錯誤] 未預期的異常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
