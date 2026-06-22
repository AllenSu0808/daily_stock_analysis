#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test generate_index_from_csv.py
"""

import csv
import json
import pytest
from pathlib import Path
from typing import Dict, List

# Add scripts directory to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from generate_index_from_csv import (
    extract_symbol_from_ts_code,
    get_stock_name,
    get_us_delist_priority,
    parse_stock_row,
    determine_market,
    generate_aliases,
    normalize_name_for_pinyin,
    normalize_stock_name_for_index,
    generate_pinyin,
    main,
    compress_index,
    build_stock_index,
    load_tushare_data,
    load_akshare_data,
)


class TestExtractSymbol:
    """測試 Symbol 提取函數"""

    def test_a_stock_sz(self):
        """測試 A股深圳"""
        result = extract_symbol_from_ts_code("000001.SZ", "CN")
        assert result == "000001"

    def test_a_stock_sh(self):
        """測試 A股上海"""
        result = extract_symbol_from_ts_code("600519.SH", "CN")
        assert result == "600519"

    def test_hk_stock(self):
        """測試港股"""
        result = extract_symbol_from_ts_code("00700.HK", "HK")
        assert result == "00700"

    def test_us_stock(self):
        """測試美股"""
        result = extract_symbol_from_ts_code("AAPL", "US")
        assert result == "AAPL"

    def test_jp_stock_preserves_suffix(self):
        """測試日股保留 Yahoo 後綴以避免裸代碼衝突"""
        result = extract_symbol_from_ts_code("7203.T", "JP")
        assert result == "7203.T"

    def test_kr_stock_preserves_suffix(self):
        """測試韓股保留 Yahoo 後綴以避免裸代碼衝突"""
        result = extract_symbol_from_ts_code("005930.KS", "KR")
        assert result == "005930.KS"

    def test_empty_ts_code(self):
        """測試空 ts_code"""
        result = extract_symbol_from_ts_code("", "CN")
        assert result is None

    def test_none_ts_code(self):
        """測試 None ts_code"""
        result = extract_symbol_from_ts_code(None, "CN")
        assert result is None


class TestDetermineMarket:
    """測試市場判斷函數"""

    def test_a_stock_sz(self):
        """測試 A股深圳"""
        result = determine_market("000001.SZ")
        assert result == "CN"

    def test_a_stock_sh(self):
        """測試 A股上海"""
        result = determine_market("600519.SH")
        assert result == "CN"

    def test_hk_stock(self):
        """測試港股"""
        result = determine_market("00700.HK")
        assert result == "HK"

    def test_bse_stock(self):
        """測試北交所"""
        result = determine_market("832566.BJ")
        assert result == "BSE"

    def test_us_stock(self):
        """測試美股"""
        result = determine_market("AAPL")
        assert result == "US"

    def test_us_stock_tesla(self):
        """測試美股特斯拉"""
        result = determine_market("TSLA")
        assert result == "US"

    def test_us_stock_with_dot_suffix(self):
        """測試美股帶點號後綴（BRK.B）"""
        result = determine_market("BRK.B")
        assert result == "US"

    def test_us_stock_class_a(self):
        """測試美股 A 類股（GOOG.A）"""
        result = determine_market("GOOG.A")
        assert result == "US"

    def test_us_stock_units(self):
        """測試美股 Unit（AAPL.U）"""
        result = determine_market("AAPL.U")
        assert result == "US"

    def test_jp_stock_with_yahoo_suffix(self):
        """測試日股 Yahoo 後綴"""
        result = determine_market("7203.T")
        assert result == "JP"

    def test_kr_kospi_stock_with_yahoo_suffix(self):
        """測試韓股 KOSPI Yahoo 後綴"""
        result = determine_market("005930.KS")
        assert result == "KR"

    def test_kr_kosdaq_stock_with_yahoo_suffix(self):
        """測試韓股 KOSDAQ Yahoo 後綴"""
        result = determine_market("035720.KQ")
        assert result == "KR"


class TestGetStockName:
    """測試股票名稱獲取函數"""

    def test_cn_stock_name(self):
        """測試 A股使用 name 字段"""
        row = {'name': '平安銀行', 'enname': 'Ping An Bank'}
        result = get_stock_name(row, 'CN')
        assert result == '平安銀行'

    def test_hk_stock_name(self):
        """測試港股使用 name 字段"""
        row = {'name': '騰訊控股', 'enname': 'Tencent'}
        result = get_stock_name(row, 'HK')
        assert result == '騰訊控股'

    def test_us_stock_name(self):
        """測試美股使用 enname 字段"""
        row = {'name': '蘋果', 'enname': 'Apple Inc.'}
        result = get_stock_name(row, 'US')
        assert result == 'Apple Inc.'

    def test_empty_name(self):
        """測試空名稱"""
        row = {'name': '', 'enname': ''}
        result = get_stock_name(row, 'CN')
        assert result is None

    def test_cn_stock_name_strips_ex_rights_prefix(self):
        """測試 A股除權除息短期前綴不會寫入長期索引名稱"""
        row = {'name': 'XD西藏藥', 'enname': ''}
        result = get_stock_name(row, 'CN')
        assert result == '西藏藥'

    def test_cn_stock_name_preserves_new_stock_prefix(self):
        """測試 A股新股前綴保留，等待後續數據包刷新自然消失"""
        row = {'name': 'N惠康', 'enname': ''}
        result = get_stock_name(row, 'CN')
        assert result == 'N惠康'


class TestDataCleaning:
    """測試數據清洗邏輯"""

    def test_valid_cn_stock(self):
        """測試有效的 A股記錄"""
        row = {
            'ts_code': '000001.SZ',
            'symbol': '000001',
            'name': '平安銀行'
        }
        result = parse_stock_row(row, 'CN')
        assert result is not None
        assert result['ts_code'] == '000001.SZ'
        assert result['symbol'] == '000001'
        assert result['name'] == '平安銀行'
        assert result['market'] == 'CN'

    def test_valid_hk_stock(self):
        """測試有效的港股記錄"""
        row = {
            'ts_code': '00700.HK',
            'name': '騰訊控股',
            'enname': 'Tencent'
        }
        result = parse_stock_row(row, 'HK')
        assert result is not None
        assert result['ts_code'] == '00700.HK'
        assert result['symbol'] == '00700'
        assert result['name'] == '騰訊控股'
        assert result['market'] == 'HK'

    def test_valid_us_stock(self):
        """測試有效的美股記錄"""
        row = {
            'ts_code': 'AAPL',
            'name': '蘋果',
            'enname': 'Apple Inc.'
        }
        result = parse_stock_row(row, 'US')
        assert result is not None
        assert result['ts_code'] == 'AAPL'
        assert result['symbol'] == 'AAPL'
        assert result['name'] == 'Apple Inc.'
        assert result['market'] == 'US'

    def test_valid_us_stock_with_dot_suffix(self):
        """測試有效的美股記錄（帶點號後綴，如 BRK.B）"""
        row = {
            'ts_code': 'BRK.B',
            'name': '',
            'enname': "BERKSHIRE HATHAWAY 'B'"
        }
        result = parse_stock_row(row, None)
        assert result is not None
        assert result['ts_code'] == 'BRK.B'
        assert result['symbol'] == 'BRK.B'
        assert result['name'] == "BERKSHIRE HATHAWAY 'B'"
        assert result['market'] == 'US'

    def test_valid_jp_stock_with_seed_aliases(self):
        """測試有效的日股種子記錄"""
        row = {
            'ts_code': '7203.T',
            'name': '豐田汽車',
            'enname': 'Toyota Motor Corporation',
            'aliases': 'Toyota|Toyota Motor|豐田'
        }
        result = parse_stock_row(row, 'JP')
        assert result is not None
        assert result['ts_code'] == '7203.T'
        assert result['symbol'] == '7203.T'
        assert result['name'] == '豐田汽車'
        assert result['market'] == 'JP'
        assert result['aliases'] == ['Toyota', 'Toyota Motor', '豐田']

    def test_valid_kr_stock_with_seed_aliases(self):
        """測試有效的韓股種子記錄"""
        row = {
            'ts_code': '005930.KS',
            'name': '三星電子',
            'enname': 'Samsung Electronics',
            'aliases': 'Samsung|Samsung Electronics|三星'
        }
        result = parse_stock_row(row, 'KR')
        assert result is not None
        assert result['ts_code'] == '005930.KS'
        assert result['symbol'] == '005930.KS'
        assert result['name'] == '三星電子'
        assert result['market'] == 'KR'
        assert result['aliases'] == ['Samsung', 'Samsung Electronics', '三星']

    def test_us_dummy_filtered(self):
        """測試美股 DUMMY 記錄被過濾"""
        row = {
            'ts_code': 'DUMMY001',
            'name': '測試',
            'enname': 'DUMMY Test Stock'
        }
        result = parse_stock_row(row, 'US')
        assert result is None

    def test_us_dummy_case_insensitive(self):
        """測試 DUMMY 過濾不區分大小寫"""
        row = {
            'ts_code': 'DUMMY002',
            'name': '測試',
            'enname': 'dummy test stock'
        }
        result = parse_stock_row(row, 'US')
        assert result is None

    def test_empty_ts_code(self):
        """測試空 ts_code 被過濾"""
        row = {
            'ts_code': '',
            'symbol': '000001',
            'name': '平安銀行'
        }
        result = parse_stock_row(row, 'CN')
        assert result is None

    def test_empty_name(self):
        """測試空名稱被過濾"""
        row = {
            'ts_code': '000001.SZ',
            'symbol': '000001',
            'name': ''
        }
        result = parse_stock_row(row, 'CN')
        assert result is None

    def test_us_empty_enname(self):
        """測試美股空 enname 被過濾"""
        row = {
            'ts_code': 'AAPL',
            'name': '蘋果',
            'enname': ''
        }
        result = parse_stock_row(row, 'US')
        assert result is None

    def test_us_delist_priority_prefers_blank_over_nat(self):
        """測試美股去重優先級：空 delist_date 優先於 NaT"""
        assert get_us_delist_priority({'delist_date': ''}) == 2
        assert get_us_delist_priority({'delist_date': 'NaT'}) == 1
        assert get_us_delist_priority({'delist_date': '20250131'}) == 0


class TestNormalizeStockNameForIndex:
    """測試索引名稱歸一化"""

    def test_strips_a_share_ex_rights_prefixes(self):
        assert normalize_stock_name_for_index('XD西藏藥', 'CN') == '西藏藥'
        assert normalize_stock_name_for_index('XR示例股', 'CN') == '示例股'
        assert normalize_stock_name_for_index('DR羅曼股', 'CN') == '羅曼股'
        assert normalize_stock_name_for_index('XD朱老六', 'BSE') == '朱老六'

    def test_preserves_a_share_new_stock_and_st_prefixes(self):
        assert normalize_stock_name_for_index('N惠康', 'CN') == 'N惠康'
        assert normalize_stock_name_for_index('C天海', 'CN') == 'C天海'
        assert normalize_stock_name_for_index('ST海王', 'CN') == 'ST海王'
        assert normalize_stock_name_for_index('*ST美麗', 'CN') == '*ST美麗'

    def test_does_not_strip_other_markets(self):
        assert normalize_stock_name_for_index('DRAGONFLY ENERGY', 'US') == 'DRAGONFLY ENERGY'
        assert normalize_stock_name_for_index('XD港股示例', 'HK') == 'XD港股示例'


class TestAliases:
    """測試別名生成函數"""

    def test_cn_aliases(self):
        """測試 A股別名"""
        result = generate_aliases('貴州茅臺', 'CN')
        assert '茅臺' in result

    def test_hk_aliases(self):
        """測試港股別名"""
        result = generate_aliases('騰訊控股', 'HK')
        assert '騰訊' in result or 'Tencent' in result

    def test_us_aliases(self):
        """測試美股別名"""
        result = generate_aliases('Apple Inc.', 'US')
        assert 'Apple' in result or 'AAPL' in result

    def test_no_aliases(self):
        """測試無別名的情況"""
        result = generate_aliases('未知股票', 'CN')
        assert result == []


class TestOutputFormat:
    """測試輸出格式"""

    def test_compress_index_field_order(self):
        """測試壓縮格式的字段順序"""
        index = [{
            "canonicalCode": "000001.SZ",
            "displayCode": "000001",
            "nameZh": "平安銀行",
            "pinyinFull": "pinganyinhang",
            "pinyinAbbr": "pyyh",
            "aliases": ["平銀"],
            "market": "CN",
            "assetType": "stock",
            "active": True,
            "popularity": 100,
        }]

        compressed = compress_index(index)

        assert len(compressed) == 1
        item = compressed[0]

        # 驗證字段順序
        assert item[0] == "000001.SZ"      # canonicalCode
        assert item[1] == "000001"         # displayCode
        assert item[2] == "平安銀行"       # nameZh
        assert item[3] == "pinganyinhang"  # pinyinFull
        assert item[4] == "pyyh"           # pinyinAbbr
        assert item[5] == ["平銀"]         # aliases
        assert item[6] == "CN"             # market
        assert item[7] == "stock"          # assetType
        assert item[8] == True             # active
        assert item[9] == 100              # popularity

    def test_compress_index_field_count(self):
        """測試壓縮格式的字段數量"""
        index = [{
            "canonicalCode": "AAPL",
            "displayCode": "AAPL",
            "nameZh": "Apple Inc.",
            "pinyinFull": None,
            "pinyinAbbr": None,
            "aliases": [],
            "market": "US",
            "assetType": "stock",
            "active": True,
            "popularity": 100,
        }]

        compressed = compress_index(index)
        assert len(compressed[0]) == 10  # 10個字段

    def test_json_serialization(self):
        """測試 JSON 序列化"""
        index = [{
            "canonicalCode": "00700.HK",
            "displayCode": "00700",
            "nameZh": "騰訊控股",
            "pinyinFull": "xunxiongkonggu",
            "pinyinAbbr": "xxkg",
            "aliases": ["騰訊"],
            "market": "HK",
            "assetType": "stock",
            "active": True,
            "popularity": 100,
        }]

        compressed = compress_index(index)

        # 應該能成功序列化爲 JSON
        json_str = json.dumps(compressed, ensure_ascii=False)
        assert json_str is not None

        # 應該能成功反序列化
        loaded = json.loads(json_str)
        assert len(loaded) == 1


class TestIntegration:
    """集成測試"""

    def test_full_workflow_tushare(self, tmp_path):
        """測試完整的 Tushare 工作流"""
        # 創建測試 CSV 文件
        a_csv = tmp_path / 'stock_list_a.csv'
        with open(a_csv, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['ts_code', 'symbol', 'name'])
            writer.writeheader()
            writer.writerow({
                'ts_code': '000001.SZ',
                'symbol': '000001',
                'name': '平安銀行'
            })

        hk_csv = tmp_path / 'stock_list_hk.csv'
        with open(hk_csv, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['ts_code', 'name', 'enname'])
            writer.writeheader()
            writer.writerow({
                'ts_code': '00700.HK',
                'name': '騰訊控股',
                'enname': 'Tencent'
            })

        us_csv = tmp_path / 'stock_list_us.csv'
        with open(us_csv, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['ts_code', 'name', 'enname'])
            writer.writeheader()
            writer.writerow({
                'ts_code': 'AAPL',
                'name': '蘋果',
                'enname': 'Apple Inc.'
            })

        jp_csv = tmp_path / 'stock_list_jp.csv'
        with open(jp_csv, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['ts_code', 'name', 'enname', 'aliases'])
            writer.writeheader()
            writer.writerow({
                'ts_code': '7203.T',
                'name': '豐田汽車',
                'enname': 'Toyota Motor Corporation',
                'aliases': 'Toyota|豐田'
            })

        kr_csv = tmp_path / 'stock_list_kr.csv'
        with open(kr_csv, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['ts_code', 'name', 'enname', 'aliases'])
            writer.writeheader()
            writer.writerow({
                'ts_code': '005930.KS',
                'name': '三星電子',
                'enname': 'Samsung Electronics',
                'aliases': 'Samsung|三星'
            })

        # 加載數據
        stocks = load_tushare_data(tmp_path)

        # 驗證數據
        assert len(stocks) == 5

        # 構建索引
        index = build_stock_index(stocks)

        # 驗證索引
        assert len(index) == 5
        assert next(item for item in index if item['canonicalCode'] == '7203.T')['aliases'] == ['Toyota', '豐田']
        assert next(item for item in index if item['canonicalCode'] == '005930.KS')['aliases'] == ['Samsung', '三星']

        # 壓縮索引
        compressed = compress_index(index)

        # 驗證壓縮
        assert len(compressed) == 5

        # 驗證字段數量
        for item in compressed:
            assert len(item) == 10

    def test_market_distribution(self, tmp_path):
        """測試市場分布統計"""
        # 創建測試數據
        csv_file = tmp_path / 'stock_list_a.csv'
        with open(csv_file, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['ts_code', 'symbol', 'name'])
            writer.writeheader()
            writer.writerow({'ts_code': '000001.SZ', 'symbol': '000001', 'name': '平安銀行'})
            writer.writerow({'ts_code': '600519.SH', 'symbol': '600519', 'name': '貴州茅臺'})
            writer.writerow({'ts_code': '832566.BJ', 'symbol': '832566', 'name': '梓撞科技'})

        stocks = load_tushare_data(tmp_path)
        index = build_stock_index(stocks)

        # 統計市場分布
        market_stats = {}
        for item in index:
            market = item['market']
            market_stats[market] = market_stats.get(market, 0) + 1

        # 驗證統計
        assert market_stats.get('CN', 0) == 2  # SZ, SH
        assert market_stats.get('BSE', 0) == 1  # BJ

    def test_us_reused_symbols_are_deduplicated(self, tmp_path):
        """測試美股復用 ticker 在加載時會先去重"""
        us_csv = tmp_path / 'stock_list_us.csv'
        with open(us_csv, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(
                f,
                fieldnames=['ts_code', 'name', 'enname', 'list_date', 'delist_date']
            )
            writer.writeheader()
            writer.writerow({
                'ts_code': 'B',
                'name': '',
                'enname': 'BARNES GROUP',
                'list_date': '19631014',
                'delist_date': 'NaT',
            })
            writer.writerow({
                'ts_code': 'B',
                'name': '',
                'enname': 'BARRICK MINING (NYS)',
                'list_date': '19850213',
                'delist_date': '',
            })
            writer.writerow({
                'ts_code': 'DOC',
                'name': '',
                'enname': 'HEALTHPEAK PROPERTIES',
                'list_date': '19850523',
                'delist_date': '',
            })
            writer.writerow({
                'ts_code': 'DOC',
                'name': '',
                'enname': 'PHYSICIANS REALTY TST.',
                'list_date': '20130719',
                'delist_date': '',
            })
            writer.writerow({
                'ts_code': 'SPWR',
                'name': '',
                'enname': 'COMPLETE SOLARIA',
                'list_date': '20210419',
                'delist_date': '',
            })
            writer.writerow({
                'ts_code': 'SPWR',
                'name': '',
                'enname': 'SUNPOWER',
                'list_date': '20051109',
                'delist_date': 'NaT',
            })

        stocks = load_tushare_data(tmp_path)

        assert len(stocks) == 3
        assert {stock['ts_code'] for stock in stocks} == {'B', 'DOC', 'SPWR'}
        assert next(stock for stock in stocks if stock['ts_code'] == 'B')['name'] == 'BARRICK MINING (NYS)'
        assert next(stock for stock in stocks if stock['ts_code'] == 'DOC')['name'] == 'HEALTHPEAK PROPERTIES'
        assert next(stock for stock in stocks if stock['ts_code'] == 'SPWR')['name'] == 'COMPLETE SOLARIA'


class TestPinyin:
    """測試拼音生成"""

    def test_normalize_name(self):
        """測試名稱標準化"""
        # 測試 ST 前綴去除
        result = normalize_name_for_pinyin('*ST平安')
        assert 'ST' not in result

        # 測試 N 前綴去除
        result = normalize_name_for_pinyin('N平安銀行')
        assert 'N' not in result

    def test_generate_pinyin(self):
        """測試拼音生成"""
        pinyin_full, pinyin_abbr = generate_pinyin('平安銀行')
        assert pinyin_full == 'pinganyinhang'
        assert pinyin_abbr == 'payh'

    def test_generate_pinyin_requires_dependency(self, monkeypatch):
        """測試缺少 pypinyin 時不會生成降級拼音字段"""
        import generate_index_from_csv

        monkeypatch.setattr(generate_index_from_csv, 'PYPINYIN_AVAILABLE', False)

        with pytest.raises(RuntimeError, match='pypinyin is required'):
            generate_index_from_csv.generate_pinyin('平安銀行')

    def test_main_fails_without_pypinyin(self, monkeypatch):
        """測試正式生成索引前必須具備 pypinyin"""
        import generate_index_from_csv

        monkeypatch.setattr(generate_index_from_csv, 'PYPINYIN_AVAILABLE', False)
        monkeypatch.setattr(sys, 'argv', ['generate_index_from_csv.py'])

        assert main() == 1
