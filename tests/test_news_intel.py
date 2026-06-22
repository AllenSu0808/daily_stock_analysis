# -*- coding: utf-8 -*-
"""
===================================
A股自選股智能分析系統 - 新聞情報存儲單元測試
===================================

職責：
1. 驗證新聞情報的保存與去重邏輯
2. 驗證無 URL 情況下的兜底去重鍵
"""

import os
import sqlite3
import tempfile
import unittest

from datetime import datetime
from unittest.mock import patch

from sqlalchemy.exc import OperationalError

from src.config import Config
from src.storage import DatabaseManager, NewsIntel
from src.search_service import SearchResponse, SearchResult


class NewsIntelStorageTestCase(unittest.TestCase):
    """新聞情報存儲測試"""

    def setUp(self) -> None:
        """爲每個用例初始化獨立數據庫"""
        self._temp_dir = tempfile.TemporaryDirectory()
        self._db_path = os.path.join(self._temp_dir.name, "test_news_intel.db")
        os.environ["DATABASE_PATH"] = self._db_path

        # 重置配置與數據庫單例，確保使用臨時庫
        Config._instance = None
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()

    def tearDown(self) -> None:
        """清理資源"""
        DatabaseManager.reset_instance()
        self._temp_dir.cleanup()

    def _build_response(self, results) -> SearchResponse:
        """構造 SearchResponse 快捷函數"""
        return SearchResponse(
            query="貴州茅臺 最新消息",
            results=results,
            provider="Bocha",
            success=True,
        )

    def test_save_news_intel_with_url_dedup(self) -> None:
        """相同 URL 去重，僅保留一條記錄"""
        result = SearchResult(
            title="茅臺發布新產品",
            snippet="公司發布新品...",
            url="https://news.example.com/a",
            source="example.com",
            published_date="2025-01-02"
        )
        response = self._build_response([result])

        query_context = {
            "query_id": "task_001",
            "query_source": "bot",
            "requester_platform": "feishu",
            "requester_user_id": "u_123",
            "requester_user_name": "測試用戶",
            "requester_chat_id": "c_456",
            "requester_message_id": "m_789",
            "requester_query": "/analyze 600519",
        }

        saved_first = self.db.save_news_intel(
            code="600519",
            name="貴州茅臺",
            dimension="latest_news",
            query=response.query,
            response=response,
            query_context=query_context
        )
        saved_second = self.db.save_news_intel(
            code="600519",
            name="貴州茅臺",
            dimension="latest_news",
            query=response.query,
            response=response,
            query_context=query_context
        )

        self.assertEqual(saved_first, 1)
        self.assertEqual(saved_second, 0)

        with self.db.get_session() as session:
            total = session.query(NewsIntel).count()
            row = session.query(NewsIntel).first()
        self.assertEqual(total, 1)
        if row is None:
            self.fail("未找到保存的新聞記錄")
        self.assertEqual(row.query_id, "task_001")
        self.assertEqual(row.requester_user_name, "測試用戶")

    def test_save_news_intel_without_url_fallback_key(self) -> None:
        """無 URL 時使用兜底鍵去重"""
        result = SearchResult(
            title="茅臺業績預告",
            snippet="業績大幅增長...",
            url="",
            source="example.com",
            published_date="2025-01-03"
        )
        response = self._build_response([result])

        saved_first = self.db.save_news_intel(
            code="600519",
            name="貴州茅臺",
            dimension="earnings",
            query=response.query,
            response=response
        )
        saved_second = self.db.save_news_intel(
            code="600519",
            name="貴州茅臺",
            dimension="earnings",
            query=response.query,
            response=response
        )

        self.assertEqual(saved_first, 1)
        self.assertEqual(saved_second, 0)

        with self.db.get_session() as session:
            row = session.query(NewsIntel).first()
            if row is None:
                self.fail("未找到保存的新聞記錄")
            self.assertTrue(row.url.startswith("no-url:"))

    def test_get_recent_news(self) -> None:
        """可按時間範圍查詢最新新聞"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        result = SearchResult(
            title="茅臺股價震蕩",
            snippet="盤中波動較大...",
            url="https://news.example.com/b",
            source="example.com",
            published_date=now
        )
        response = self._build_response([result])

        self.db.save_news_intel(
            code="600519",
            name="貴州茅臺",
            dimension="market_analysis",
            query=response.query,
            response=response
        )

        recent_news = self.db.get_recent_news(code="600519", days=7, limit=10)
        self.assertEqual(len(recent_news), 1)
        self.assertEqual(recent_news[0].title, "茅臺股價震蕩")

    def test_save_news_intel_retries_on_sqlite_locked_execute(self) -> None:
        result = SearchResult(
            title="茅臺鎖競爭重試",
            snippet="模擬 SQLite locked...",
            url="https://news.example.com/retry",
            source="example.com",
            published_date="2025-01-05",
        )
        response = self._build_response([result])

        first_session = self.db.get_session()
        second_session = self.db.get_session()
        stmt_exc = OperationalError(
            "COMMIT",
            None,
            sqlite3.OperationalError("database is locked"),
        )

        with patch.object(self.db, "get_session", side_effect=[first_session, second_session]):
            with patch.object(first_session, "execute", side_effect=stmt_exc):
                with patch("src.storage.time.sleep") as mock_sleep:
                    saved_count = self.db.save_news_intel(
                        code="600519",
                        name="貴州茅臺",
                        dimension="latest_news",
                        query=response.query,
                        response=response,
                    )

        self.assertEqual(saved_count, 1)
        self.assertEqual(mock_sleep.call_count, 1)
        self.assertAlmostEqual(mock_sleep.call_args.args[0], self.db._sqlite_write_retry_base_delay, places=6)

        with self.db.get_session() as session:
            total = session.query(NewsIntel).count()
        self.assertEqual(total, 1)


if __name__ == "__main__":
    unittest.main()
