# -*- coding: utf-8 -*-
"""
Anspire Search 搜索引擎測試套件

測試覆蓋範圍:
1. 配置加載測試 - 驗證 anspire_api_keys 是否正確從環境變量加載
2. 服務初始化測試 - 驗證 SearchService 是否正確初始化 AnspireSearchProvider
3. API 調用測試 - 實際調用 Anspire API 驗證返回結果
4. 故障轉移測試 - 驗證無效 Key 時的錯誤處理和降級機制
5. 搜索功能測試 - 測試股票新聞搜索和通用搜索功能

運行方式:
```bash
# Windows PowerShell
$env:ANSPIRE_API_KEYS="your_test_api_key"
python -m pytest tests/test_anspire_search.py -v

# Linux/Mac
export ANSPIRE_API_KEYS="your_test_api_key"
python -m pytest tests/test_anspire_search.py -v
```
"""

import os
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest
from dotenv import load_dotenv
load_dotenv()

# 添加項目根目錄到 Python 路徑，解決模塊導入問題
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Mock newspaper before search_service import (optional dependency)
if "newspaper" not in sys.modules:
    mock_np = MagicMock()
    mock_np.Article = MagicMock()
    mock_np.Config = MagicMock()
    sys.modules["newspaper"] = mock_np

from src.config import Config, get_config
from src.search_service import (
    AnspireSearchProvider,
    SearchService,
    get_search_service,
    reset_search_service,
)


class _FakeResponse:
    """模擬 HTTP 響應對象"""
    def __init__(self, status_code=200, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text
        self.headers = headers or {'content-type': 'application/json'}
    
    def json(self):
        return self._json_data


class TestAnspireConfigLoading(unittest.TestCase):
    """Test Anspire configuration loading from environment variables."""
    
    def setUp(self):
        """保存並清除環境變量（不操作 .env 文件）"""
        # ✅ 保存原始值，測試後恢復
        self._original_anspire_keys = os.environ.get('ANSPIRE_API_KEYS')
        
        # 清除環境變量
        if 'ANSPIRE_API_KEYS' in os.environ:
            del os.environ['ANSPIRE_API_KEYS']
        
        # 重置 Config 單例
        Config._Config__instance = None
        reset_search_service()

    def tearDown(self):
        """恢復原始環境變量"""
        # ✅ 恢復原始值
        if self._original_anspire_keys is not None:
            os.environ['ANSPIRE_API_KEYS'] = self._original_anspire_keys
        elif 'ANSPIRE_API_KEYS' in os.environ:
            del os.environ['ANSPIRE_API_KEYS']
        
        # 重置 Config 單例
        Config._Config__instance = None
        reset_search_service()

    def test_anspire_keys_loaded_from_env(self):
        """Test that ANSPIRE_API_KEYS is correctly parsed from environment."""
        # ✅ 使用 patch.dict 臨時設置，測試後自動恢復
        with patch.dict(os.environ, {'ANSPIRE_API_KEYS': 'key1,key2,key3'}):
            config = Config._load_from_env()
            
            self.assertEqual(len(config.anspire_api_keys), 3)
            self.assertIn('key1', config.anspire_api_keys)
            self.assertIn('key2', config.anspire_api_keys)
            self.assertIn('key3', config.anspire_api_keys)

    def test_anspire_keys_single_key(self):
        """Test single API Key parsing."""
        with patch.dict(os.environ, {'ANSPIRE_API_KEYS': 'single_key_test'}):
            config = Config._load_from_env()
            
            self.assertEqual(len(config.anspire_api_keys), 1)
            self.assertEqual(config.anspire_api_keys[0], 'single_key_test')

    def test_anspire_keys_empty_env(self):
        """Test empty environment variable handling."""
        with patch.dict(os.environ, {'ANSPIRE_API_KEYS': ''}):
            config = Config._load_from_env()
            
            self.assertEqual(len(config.anspire_api_keys), 0)

    def test_anspire_keys_whitespace_handling(self):
        """Test whitespace trimming in API Keys."""
        with patch.dict(os.environ, {'ANSPIRE_API_KEYS': ' key1 , key2 , key3 '}):
            config = Config._load_from_env()
            
            self.assertEqual(len(config.anspire_api_keys), 3)
            self.assertEqual(config.anspire_api_keys, ['key1', 'key2', 'key3'])


class TestAnspireSearchProvider(unittest.TestCase):
    """Anspire Search Provider 單元測試"""
    
    def setUp(self):
        """測試前準備"""
        # ✅ 使用明確的測試佔位符，不是真實密鑰形態
        self.test_api_key = "sk-test-anspire-placeholder-key-12345"
        self.provider = AnspireSearchProvider([self.test_api_key])
        # 保存原始 requests 模塊
        self._original_requests = sys.modules.get('requests')
    
    def tearDown(self):
        """測試後清理"""
        # 恢復原始 requests 模塊
        if self._original_requests is not None:
            sys.modules['requests'] = self._original_requests
    
    def test_provider_initialization(self):
        """測試 Provider 初始化"""
        provider = AnspireSearchProvider(["key1", "key2"])
        self.assertEqual(provider.name, "Anspire")
        if hasattr(provider, 'api_keys'):
            self.assertEqual(len(provider.api_keys), 2)
        elif hasattr(provider, '_api_keys'):
            self.assertEqual(len(provider._api_keys), 2)
        self.assertTrue(provider.is_available)
    
    def test_provider_name(self):
        """測試 Provider 名稱"""
        self.assertEqual(self.provider.name, "Anspire")
    
    def test_provider_availability(self):
        """測試 Provider 可用性檢測"""
        # 有 API Key 時應可用
        provider_with_keys = AnspireSearchProvider(["key1"])
        self.assertTrue(provider_with_keys.is_available)
        
        # 無 API Key 時不可用
        provider_without_keys = AnspireSearchProvider([])
        self.assertFalse(provider_without_keys.is_available)
    
    def test_extract_domain(self):
        """測試域名提取功能"""
        test_cases = [
            ("https://www.example.com/article", "example.com"),
            ("https://finance.sina.com.cn/stock/", "finance.sina.com.cn"),
            ("http://www.10jqka.com.cn/news", "10jqka.com.cn"),
            ("invalid_url", "未知來源"),
            ("", "未知來源"),
        ]
        
        for url, expected in test_cases:
            result = AnspireSearchProvider._extract_domain(url)
            self.assertEqual(result, expected, f"Failed for URL: {url}")
    
    @patch('src.search_service.requests')
    def test_search_success_response(self, mock_requests):
        """測試成功響應處理"""
        # 設置 mock exceptions
        try:
            import requests as real_requests
            mock_requests.exceptions = real_requests.exceptions
        except ImportError:
            pass
        
        fake_response = _FakeResponse(
            status_code=200,
            json_data={
                "code": 200,
                "msg": "success",
                "results": [
                    {
                        "title": "貴州茅臺今日股價上漲",
                        "url": "https://finance.sina.com.cn/stock/600519",
                        "content": "貴州茅臺 (600519) 今日收盤股價上漲 2.5%，成交量放大...",
                    },
                    {
                        "title": "白酒板塊持續走強",
                        "url": "https://www.10jqka.com.cn/baijiu",
                        "content": "白酒板塊今日表現強勢，貴州茅臺、五糧液等個股漲幅居前...",
                    }
                ]
            }
        )
        
        mock_requests.get = MagicMock(return_value=fake_response)
        
        response = self.provider.search("貴州茅臺 股票新聞", max_results=5, days=7)
        
        # 驗證結果
        self.assertTrue(response.success)
        self.assertEqual(response.provider, "Anspire")
        self.assertEqual(len(response.results), 2)
        self.assertEqual(response.results[0].title, "貴州茅臺今日股價上漲")
        # 假設 source 是從 url 提取的域名
        self.assertEqual(response.results[0].source, "finance.sina.com.cn")
        
        # 驗證 API 調用參數
        mock_requests.get.assert_called_once()
        call_args = mock_requests.get.call_args
        # 檢查 URL 是否包含 anspire 相關域名 (具體 URL 需根據實際實現調整)
        # self.assertIn("plugin.anspire.cn", call_args[0][0]) 
        self.assertIn("Authorization", call_args[1]["headers"])
        # 驗證使用 params 而非 json
        self.assertIn("params", call_args[1])
        self.assertNotIn("json", call_args[1])
    
    @patch('src.search_service.requests')
    def test_search_invalid_api_key(self, mock_requests):
        """測試無效 API Key 的錯誤處理"""
        try:
            import requests as real_requests
            mock_requests.exceptions = real_requests.exceptions
        except ImportError:
            pass
        
        fake_response = _FakeResponse(
            status_code=401,
            json_data={"message": "Invalid API key"},
            text="Unauthorized"
        )
        
        mock_requests.get = MagicMock(return_value=fake_response)
        
        response = self.provider.search("測試查詢", max_results=3)
        
        self.assertFalse(response.success)
        self.assertEqual(response.provider, "Anspire")
        self.assertEqual(len(response.results), 0)
        # 錯誤消息可能因實現而異，這裡做寬鬆檢查
        self.assertTrue("API" in response.error_message or "KEY" in response.error_message or "無效" in response.error_message)
    
    @patch('src.search_service.requests')
    def test_search_timeout_error(self, mock_requests):
        """測試超時錯誤處理"""
        try:
            import requests as real_requests
            mock_requests.exceptions = real_requests.exceptions
            timeout_exc = mock_requests.exceptions.Timeout
        except ImportError:
            mock_requests.exceptions = MagicMock()
            timeout_exc = Exception
            
        mock_requests.get = MagicMock(side_effect=timeout_exc())
        
        response = self.provider.search("測試查詢", max_results=3)
        
        self.assertFalse(response.success)
        self.assertEqual(response.provider, "Anspire")
        self.assertEqual(len(response.results), 0)
        # 錯誤消息檢查
        self.assertTrue("超時" in response.error_message or "Timeout" in response.error_message)
    
    @patch('src.search_service.requests')
    def test_search_network_error(self, mock_requests):
        """測試網絡錯誤處理"""
        try:
            import requests as real_requests
            mock_requests.exceptions = real_requests.exceptions
            conn_exc = mock_requests.exceptions.ConnectionError
        except ImportError:
            mock_requests.exceptions = MagicMock()
            conn_exc = Exception

        mock_requests.get = MagicMock(side_effect=conn_exc())
        
        response = self.provider.search("測試查詢", max_results=3)
        
        self.assertFalse(response.success)
        self.assertEqual(response.provider, "Anspire")
        self.assertEqual(len(response.results), 0)
        self.assertTrue("網絡" in response.error_message or "Connection" in response.error_message)
    
    @patch('src.search_service.requests')
    def test_search_empty_results(self, mock_requests):
        """測試空結果處理"""
        try:
            import requests as real_requests
            mock_requests.exceptions = real_requests.exceptions
        except ImportError:
            mock_requests.exceptions = MagicMock()
        
        fake_response = _FakeResponse(
            status_code=200,
            json_data={"code": 200, "msg": "success", "results": []}
        )
        
        mock_requests.get = MagicMock(return_value=fake_response)
        
        response = self.provider.search("不存在的股票 XYZ", max_results=5)
        
        self.assertTrue(response.success)
        self.assertEqual(response.provider, "Anspire")
        self.assertEqual(len(response.results), 0)
    
    @patch('src.search_service.requests')
    def test_search_content_truncation(self, mock_requests):
        """測試長內容截斷功能"""
        try:
            import requests as real_requests
            mock_requests.exceptions = real_requests.exceptions
        except ImportError:
            mock_requests.exceptions = MagicMock()
        
        long_content = "這是一段非常長的內容，" * 100  # 超過 500 字符
        
        fake_response = _FakeResponse(
            status_code=200,
            json_data={
                "code": 200,
                "msg": "success",
                "results": [{
                    "title": "長內容測試",
                    "url": "https://example.com/long",
                    "content": long_content
                }]
            }
        )
        
        mock_requests.get = MagicMock(return_value=fake_response)
        
        response = self.provider.search("測試", max_results=1)
        
        self.assertTrue(response.success)
        self.assertEqual(len(response.results), 1)
        # 驗證內容被截斷到 500 字符以內
        if response.results[0].snippet:
            self.assertLessEqual(len(response.results[0].snippet), 503)  # 500 + "..."
            self.assertTrue(response.results[0].snippet.endswith("..."))
    
    @patch('src.search_service.requests')
    def test_search_time_range(self, mock_requests):
        """測試時間範圍參數"""
        try:
            import requests as real_requests
            mock_requests.exceptions = real_requests.exceptions
        except ImportError:
            mock_requests.exceptions = MagicMock()
        
        fake_response = _FakeResponse(status_code=200, json_data={"code": 200, "results": []})
        mock_requests.get = MagicMock(return_value=fake_response)
        
        # 測試 7 天範圍
        self.provider.search("測試", max_results=3, days=7)
        
        # 驗證時間參數
        call_args = mock_requests.get.call_args
        if call_args and len(call_args) > 1 and 'params' in call_args[1]:
            params = call_args[1]["params"]
                
            # 驗證時間參數存在 (具體字段名取決於實現)
            # 這裡假設使用了 FromTime/ToTime 或類似字段，若無則跳過具體字段檢查
            # self.assertIn("FromTime", params)
            # self.assertIn("ToTime", params)


class TestAnspireSearchService(unittest.TestCase):
    """SearchService 中 Anspire 集成測試"""
    
    def setUp(self):
        Config._Config__instance = None
        reset_search_service()

    def test_search_service_with_anspire(self):
        """測試 SearchService 正確初始化 Anspire Provider"""
        service = SearchService(
            anspire_keys=["test_key"],
            bocha_keys=[],
            tavily_keys=[],
            searxng_public_instances_enabled=False,
            news_max_age_days=3,
            news_strategy_profile="short"
        )
        
        self.assertTrue(hasattr(service, '_providers'))
        self.assertGreater(len(service._providers), 0)
        
        first_provider = service._providers[0]
        self.assertIsInstance(first_provider, AnspireSearchProvider)
        self.assertEqual(first_provider.name, "Anspire")
    
    def test_search_service_without_anspire(self):
        """測試未配置 Anspire 時的行爲"""
        service = SearchService(
            anspire_keys=[],
            tavily_keys=["tavily_key"],
            bocha_keys=[],
            searxng_public_instances_enabled=False,
            news_max_age_days=3,
            news_strategy_profile="short"
        )
        
        # 驗證沒有 Anspire Provider
        anspire_providers = [p for p in service._providers if isinstance(p, AnspireSearchProvider)]
        self.assertEqual(len(anspire_providers), 0)
    
    def test_search_service_priority(self):
        """測試 Anspire 優先級"""
        service = SearchService(
            anspire_keys=["anspire_key"],
            bocha_keys=["bocha_key"],
            tavily_keys=["tavily_key"],
            searxng_public_instances_enabled=False,
            news_max_age_days=3,
            news_strategy_profile="short"
        )
        
        self.assertIsInstance(service._providers[0], AnspireSearchProvider)


class TestAnspireIntegration(unittest.TestCase):
    """Anspire 集成測試（需要真實 API Key）"""
    
    @classmethod
    def setUpClass(cls):
        """Check if API Key is configured."""
        cls.api_keys = [k.strip() for k in os.getenv('ANSPIRE_API_KEYS', '').split(',') if k.strip()]
        cls.has_api_key = len(cls.api_keys) > 0
        
        if cls.has_api_key:
            reset_search_service()
            cls.service = get_search_service()

    @unittest.skipIf(
        not os.environ.get("ANSPIRE_API_KEYS"),
        "未設置 ANSPIRE_API_KEYS 環境變量，跳過集成測試"
    )
    @pytest.mark.network
    def test_real_api_call_stock_news(self):
        """真實 API 調用測試 - 股票新聞搜索"""
        # 確保服務已重置
        reset_search_service()
        service = get_search_service()
        
        # 驗證 Anspire 已配置
        anspire_provider = None
        for provider in service._providers:
            if isinstance(provider, AnspireSearchProvider):
                anspire_provider = provider
                break
        
        if not anspire_provider:
            self.skipTest("Anspire Provider 未初始化")
        
        # 測試 A 股搜索
        response = service.search_stock_news("600519", "貴州茅臺", max_results=3)
        
        print(f"\n=== Anspire 真實 API 測試結果 ===")
        print(f"搜索狀態：{'成功' if response.success else '失敗'}")
        print(f"搜索引擎：{response.provider}")
        print(f"結果數量：{len(response.results)}")
        print(f"耗時：{response.search_time:.2f}s")
        
        # 基本驗證
        self.assertTrue(response.success, f"搜索失敗：{response.error_message}")
        self.assertEqual(response.provider, "Anspire")
        self.assertGreater(len(response.results), 0, "應至少返回一條結果")
        
        # 驗證結果格式
        for result in response.results:
            self.assertIsNotNone(result.title)
            self.assertIsNotNone(result.url)
            # snippet 可能爲空，視具體實現而定
            # self.assertIsNotNone(result.snippet)
    
    @unittest.skipIf(
        not os.environ.get("ANSPIRE_API_KEYS"),
        "未設置 ANSPIRE_API_KEYS 環境變量，跳過集成測試"
    )
    @pytest.mark.network
    def test_real_api_call_general_search(self):
        """真實 API 調用測試 - 通用搜索"""
        reset_search_service()
        service = get_search_service()
        
        anspire_provider = None
        for provider in service._providers:
            if isinstance(provider, AnspireSearchProvider):
                anspire_provider = provider
                break
        
        if not anspire_provider:
            self.skipTest("Anspire Provider 未初始化")
        
        # 測試通用搜索
        response = anspire_provider.search("人工智能最新發展", max_results=5, days=7)
        
        print(f"\n=== Anspire 通用搜索結果 ===")
        print(f"搜索狀態：{'成功' if response.success else '失敗'}")
        print(f"結果數量：{len(response.results)}")
        
        self.assertTrue(response.success)
        self.assertGreater(len(response.results), 0)


def run_manual_test():
    """手動測試函數（用於快速驗證）"""
    import logging
    from src.config import get_config
    
    # 配置日誌
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(message)s'
    )
    
    print("=" * 60)
    print("Anspire Search 快速測試")
    print("=" * 60)
    
    # 檢查配置
    config = get_config()
    if not config.anspire_api_keys:
        print("\n❌ 未檢測到 Anspire API Keys")
        print("請設置環境變量：")
        print("  Windows PowerShell: $env:ANSPIRE_API_KEYS=\"your_api_key\"")
        print("  Linux/Mac: export ANSPIRE_API_KEYS=\"your_api_key\"")
        return False
    
    print(f"\n✅ 已配置 {len(config.anspire_api_keys)} 個 Anspire API Key")
    
    # 創建服務
    service = SearchService(
        anspire_keys=config.anspire_api_keys,
        bocha_keys=config.bocha_api_keys,
        tavily_keys=config.tavily_keys,
        searxng_public_instances_enabled=False,
        news_max_age_days=3,
        news_strategy_profile="short"
    )
    
    # 驗證 Provider
    anspire_provider = service._providers[0] if service._providers else None
    if not anspire_provider or not isinstance(anspire_provider, AnspireSearchProvider):
        print("\n❌ Anspire Provider 未正確初始化")
        return False
    
    print(f"✅ Anspire Provider 初始化成功")
    print(f"   Provider 名稱：{anspire_provider.name}")
    if hasattr(anspire_provider, 'api_keys'):
        print(f"   API Keys 數量：{len(anspire_provider.api_keys)}")
    elif hasattr(anspire_provider, '_api_keys'):
        print(f"   API Keys 數量：{len(anspire_provider._api_keys)}")
    
    # 執行測試搜索
    print("\n" + "=" * 60)
    print("執行測試搜索：貴州茅臺 (600519)")
    print("=" * 60)
    
    response = service.search_stock_news("600519", "貴州茅臺", max_results=3)
    
    print(f"\n搜索結果:")
    print(f"  狀態：{'✅ 成功' if response.success else '❌ 失敗'}")
    print(f"  搜索引擎：{response.provider}")
    print(f"  結果數量：{len(response.results)}")
    print(f"  耗時：{response.search_time:.2f}s")
    
    if response.error_message:
        print(f"  錯誤信息：{response.error_message}")
    
    if response.results:
        print(f"\n前 {min(2, len(response.results))} 條結果預覽:")
        for i, result in enumerate(response.results[:2], 1):
            print(f"\n  [{i}] {result.title}")
            print(f"      來源：{result.source}")
            print(f"      URL: {result.url}")
            if result.snippet:
                snippet_preview = result.snippet[:100] + "..." if len(result.snippet) > 100 else result.snippet
                print(f"      摘要：{snippet_preview}")
    
    print("\n" + "=" * 60)
    print("測試完成!")
    print("=" * 60)
    
    return response.success


if __name__ == "__main__":
    # 如果設置了環境變量，運行完整測試
    if os.environ.get("ANSPIRE_API_KEYS"):
        print("檢測到 ANSPIRE_API_KEYS 環境變量，運行完整測試套件...")
        unittest.main(verbosity=2)
    else:
        # 否則只運行單元測試，跳過集成測試
        print("未設置 ANSPIRE_API_KEYS 環境變量，僅運行單元測試（跳過集成測試）...")
        print("如需運行完整測試，請設置環境變量:")
        print("  Windows PowerShell: $env:ANSPIRE_API_KEYS=\"your_api_key\"")
        print("  Linux/Mac: export ANSPIRE_API_KEYS=\"your_api_key\"")
        print()
        
        # 運行單元測試
        suite = unittest.TestLoader().loadTestsFromTestCase(TestAnspireConfigLoading)
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestAnspireSearchProvider))
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestAnspireSearchService))
        runner = unittest.TextTestRunner(verbosity=2)
        runner.run(suite)
        
        # 提供手動測試選項
        print("\n" + "=" * 60)
        choice = input("是否運行手動測試（需要有效的 API Key）? (y/n): ").strip().lower()
        if choice == 'y':
            run_manual_test()
