# -*- coding: utf-8 -*-
"""
===================================
平臺適配器模塊
===================================

包含各平臺的 Webhook 處理和消息解析邏輯。

支持兩種接入模式：
1. Webhook 模式：需要公網 IP，配置回調 URL
2. Stream 模式：無需公網 IP，通過 WebSocket 長連接（釘釘、飛書支持）
"""

from bot.platforms.base import BotPlatform
from bot.platforms.dingtalk import DingtalkPlatform

# 所有可用平臺（Webhook 模式）
ALL_PLATFORMS = {
    'dingtalk': DingtalkPlatform,
}

# 釘釘 Stream 模式（可選）
try:
    from bot.platforms.dingtalk_stream import (
        DingtalkStreamClient,
        DingtalkStreamHandler,
        get_dingtalk_stream_client,
        start_dingtalk_stream_background,
        DINGTALK_STREAM_AVAILABLE,
    )
except ImportError:
    DINGTALK_STREAM_AVAILABLE = False
    DingtalkStreamClient = None
    DingtalkStreamHandler = None
    get_dingtalk_stream_client = lambda: None
    start_dingtalk_stream_background = lambda: False

# 飛書 Stream 模式（可選）
try:
    from bot.platforms.feishu_stream import (
        FeishuStreamClient,
        FeishuStreamHandler,
        FeishuReplyClient,
        get_feishu_stream_client,
        start_feishu_stream_background,
        FEISHU_SDK_AVAILABLE,
    )
except ImportError:
    FEISHU_SDK_AVAILABLE = False
    FeishuStreamClient = None
    FeishuStreamHandler = None
    FeishuReplyClient = None
    get_feishu_stream_client = lambda: None
    start_feishu_stream_background = lambda: False

__all__ = [
    'BotPlatform',
    'DingtalkPlatform',
    'ALL_PLATFORMS',
    # 釘釘 Stream 模式
    'DingtalkStreamClient',
    'DingtalkStreamHandler',
    'get_dingtalk_stream_client',
    'start_dingtalk_stream_background',
    'DINGTALK_STREAM_AVAILABLE',
    # 飛書 Stream 模式
    'FeishuStreamClient',
    'FeishuStreamHandler',
    'FeishuReplyClient',
    'get_feishu_stream_client',
    'start_feishu_stream_background',
    'FEISHU_SDK_AVAILABLE',
]
