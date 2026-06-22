# -*- coding: utf-8 -*-
"""
===================================
大盤復盤命令
===================================

執行大盤復盤分析，生成市場概覽報告。
"""

import logging
import threading
from typing import Any, List, Optional

from bot.commands.base import BotCommand
from bot.models import BotMessage, BotResponse

logger = logging.getLogger(__name__)


class MarketCommand(BotCommand):
    """
    大盤復盤命令

    執行大盤復盤分析，包括：
    - 主要指數表現
    - 板塊熱點
    - 市場情緒
    - 後市展望

    用法：
        /market - 執行大盤復盤
    """

    @property
    def name(self) -> str:
        return "market"

    @property
    def aliases(self) -> List[str]:
        return ["m", "大盤", "復盤", "行情"]

    @property
    def description(self) -> str:
        return "大盤復盤分析"

    @property
    def usage(self) -> str:
        return "/market"

    def execute(self, message: BotMessage, args: List[str]) -> BotResponse:
        """執行大盤復盤命令"""
        config = self._get_config()
        lock_token = self._try_acquire_market_review_lock(config)
        if lock_token is None:
            return BotResponse.markdown_response("⚠️ 大盤復盤正在執行中，請稍後再試。")

        thread = threading.Thread(
            target=self._run_market_review,
            args=(message, config, lock_token),
            daemon=True,
        )
        try:
            thread.start()
        except Exception as exc:
            logger.error(
                "[MarketCommand] 大盤復盤後臺線程啓動失敗: %s",
                exc,
            )
            self._release_market_review_lock(lock_token)
            return BotResponse.error_response(
                "大盤復盤啓動失敗，已釋放運行鎖；請稍後重試"
            )

        return BotResponse.markdown_response(
            "✅ **大盤復盤任務已啓動**\n\n"
            "正在分析：\n"
            "• 主要指數表現\n"
            "• 板塊熱點分析\n"
            "• 市場情緒判斷\n"
            "• 後市展望\n\n"
            "分析完成後將自動推送結果。"
        )

    def _get_config(self):
        from src.config import get_config
        return get_config()

    def _try_acquire_market_review_lock(self, config):
        from src.core.market_review_lock import try_acquire_market_review_lock
        return try_acquire_market_review_lock(config)

    def _release_market_review_lock(self, lock_token: Optional[Any]) -> None:
        from src.core.market_review_lock import release_market_review_lock
        release_market_review_lock(lock_token)

    def _compute_market_review_override_region(self, config) -> Optional[str]:
        if not getattr(config, "trading_day_check_enabled", True):
            return None

        try:
            from src.core.trading_calendar import (
                get_open_markets_today,
                compute_effective_region,
            )

            open_markets = get_open_markets_today()
            return compute_effective_region(
                getattr(config, "market_review_region", "cn") or "cn",
                open_markets,
            )
        except Exception as exc:
            logger.warning("交易日過濾失敗，按配置繼續執行大盤復盤: %s", exc)
            return None

    def _run_market_review(
        self,
        message: BotMessage,
        config,
        lock_token: Optional[Any],
    ) -> None:
        """後臺執行大盤復盤"""
        try:
            override_region = self._compute_market_review_override_region(config)
            if override_region == "":
                from src.notification import NotificationService
                notifier = NotificationService(source_message=message)
                logger.info("[MarketCommand] 今日相關市場休市，跳過大盤復盤")
                if notifier.is_available():
                    notifier.send(
                        "🎯 大盤復盤\n\n今日相關市場休市，已跳過大盤復盤。",
                        email_send_to_all=True,
                        route_type="report",
                    )
                return

            from src.core.market_review_runtime import build_market_review_runtime
            from src.core.market_review import run_market_review

            notifier, analyzer, search_service = build_market_review_runtime(
                config,
                source_message=message,
            )
            review_report = run_market_review(
                notifier=notifier,
                analyzer=analyzer,
                search_service=search_service,
                send_notification=True,
                override_region=override_region,
                trigger_source="bot",
            )
            if review_report:
                logger.info("[MarketCommand] 大盤復盤完成並已推送")
            else:
                logger.warning("[MarketCommand] 大盤復盤返回空結果")
        except Exception as e:
            logger.error("[MarketCommand] 大盤復盤失敗: %s", e)
            logger.exception(e)
        finally:
            self._release_market_review_lock(lock_token)
