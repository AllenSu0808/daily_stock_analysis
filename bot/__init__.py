# -*- coding: utf-8 -*-
"""
===================================
機器人命令觸發系統
===================================

通過 @機器人 或發送命令觸發股票分析等功能。
支持飛書、釘釘、企業微信、Telegram 等多平臺。

模塊結構：
- models.py: 統一的消息/響應模型
- dispatcher.py: 命令分發器
- commands/: 命令處理器
- platforms/: 平臺適配器
- handler.py: Webhook 處理器

使用方式：
1. 配置環境變量（各平臺的 Token 等）
2. 啓動 WebUI 服務
3. 在各平臺配置 Webhook URL：
   - 飛書: http://your-server/bot/feishu
   - 釘釘: http://your-server/bot/dingtalk
   - 企業微信: http://your-server/bot/wecom
   - Telegram: http://your-server/bot/telegram

支持的命令：
- /analyze <股票代碼>  - 分析指定股票
- /market             - 大盤復盤
- /batch              - 批量分析自選股
- /help               - 顯示幫助
- /status             - 系統狀態
"""

from bot.models import BotMessage, BotResponse, ChatType, WebhookResponse
from bot.dispatcher import CommandDispatcher, get_dispatcher

__all__ = [
    'BotMessage',
    'BotResponse',
    'ChatType',
    'WebhookResponse',
    'CommandDispatcher',
    'get_dispatcher',
]
