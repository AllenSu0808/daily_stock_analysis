# -*- coding: utf-8 -*-
"""
===================================
命令基類
===================================

定義命令處理器的抽象基類，所有命令都必須繼承此類。
"""

import asyncio
from abc import ABC, abstractmethod
from typing import List, Optional

from bot.models import BotMessage, BotResponse


class BotCommand(ABC):
    """
    命令處理器抽象基類

    所有命令都必須繼承此類並實現抽象方法。

    使用示例：
        class MyCommand(BotCommand):
            @property
            def name(self) -> str:
                return "mycommand"

            @property
            def aliases(self) -> List[str]:
                return ["mc", "我的命令"]

            @property
            def description(self) -> str:
                return "這是我的命令"

            @property
            def usage(self) -> str:
                return "/mycommand [參數]"

            def execute(self, message: BotMessage, args: List[str]) -> BotResponse:
                return BotResponse.text_response("命令執行成功")
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        命令名稱（不含前綴）

        例如 "analyze"，用戶輸入 "/analyze" 觸發
        """
        pass

    @property
    @abstractmethod
    def aliases(self) -> List[str]:
        """
        命令別名列表

        例如 ["a", "分析"]，用戶輸入 "/a" 或 "分析" 也能觸發
        """
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """命令描述（用於幫助信息）"""
        pass

    @property
    @abstractmethod
    def usage(self) -> str:
        """
        使用說明（用於幫助信息）

        例如 "/analyze <股票代碼>"
        """
        pass

    @property
    def hidden(self) -> bool:
        """
        是否在幫助列表中隱藏

        默認 False，設爲 True 則不顯示在 /help 列表中
        """
        return False

    @property
    def admin_only(self) -> bool:
        """
        是否僅管理員可用

        默認 False，設爲 True 則需要管理員權限
        """
        return False

    @abstractmethod
    def execute(self, message: BotMessage, args: List[str]) -> BotResponse:
        """
        執行命令

        Args:
            message: 原始消息對象
            args: 命令參數列表（已分割）

        Returns:
            BotResponse 響應對象
        """
        pass

    async def execute_async(self, message: BotMessage, args: List[str]) -> BotResponse:
        """異步執行命令。

        默認將同步 `execute()` 下沉到線程池，避免在異步分發鏈路中阻塞事件循環。
        """
        return await asyncio.to_thread(self.execute, message, args)

    def validate_args(self, args: List[str]) -> Optional[str]:
        """
        驗證參數

        子類可重寫此方法進行參數校驗。

        Args:
            args: 命令參數列表

        Returns:
            如果參數有效返回 None，否則返回錯誤信息
        """
        return None

    def get_help_text(self) -> str:
        """獲取幫助文本"""
        return f"**{self.name}** - {self.description}\n用法: `{self.usage}`"
