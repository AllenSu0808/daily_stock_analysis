# -*- coding: utf-8 -*-
"""
Discord 發送提醒服務

職責：
1. 通過 webhook 或 Discord bot API 發送 Discord 消息
"""
import logging
from typing import Optional

import requests

from src.config import Config
from src.formatters import chunk_content_by_max_words


logger = logging.getLogger(__name__)


class DiscordSender:
    
    def __init__(self, config: Config):
        """
        初始化 Discord 配置

        Args:
            config: 配置對象
        """
        self._discord_config = {
            'bot_token': getattr(config, 'discord_bot_token', None),
            'channel_id': getattr(config, 'discord_main_channel_id', None),
            'webhook_url': getattr(config, 'discord_webhook_url', None),
        }
        self._discord_max_words = getattr(config, 'discord_max_words', 2000)
        self._webhook_verify_ssl = getattr(config, 'webhook_verify_ssl', True)
    
    def _is_discord_configured(self) -> bool:
        """檢查 Discord 配置是否完整（支持 Bot 或 Webhook）"""
        # 只要配置了 Webhook 或完整的 Bot Token+Channel，即視爲可用
        bot_ok = bool(self._discord_config['bot_token'] and self._discord_config['channel_id'])
        webhook_ok = bool(self._discord_config['webhook_url'])
        return bot_ok or webhook_ok
    
    def send_to_discord(self, content: str, *, timeout_seconds: Optional[float] = None) -> bool:
        """
        推送消息到 Discord（支持 Webhook 和 Bot API）
        
        Args:
            content: Markdown 格式的消息內容
            
        Returns:
            是否發送成功
        """
        # 分割內容，避免單條消息超過 Discord 限制
        try:
            chunks = chunk_content_by_max_words(content, self._discord_max_words)
        except ValueError as e:
            logger.error(f"分割 Discord 消息失敗: {e}, 嘗試整段發送。")
            chunks = [content]

        # 優先使用 Webhook（配置簡單，權限低）
        if self._discord_config['webhook_url']:
            return all(self._send_discord_webhook(chunk, timeout_seconds=timeout_seconds) for chunk in chunks)

        # 其次使用 Bot API（權限高，需要 channel_id）
        if self._discord_config['bot_token'] and self._discord_config['channel_id']:
            return all(self._send_discord_bot(chunk, timeout_seconds=timeout_seconds) for chunk in chunks)

        logger.warning("Discord 配置不完整，跳過推送")
        return False

  
    def _send_discord_webhook(self, content: str, *, timeout_seconds: Optional[float] = None) -> bool:
        """
        使用 Webhook 發送消息到 Discord
        
        Discord Webhook 支持 Markdown 格式
        
        Args:
            content: Markdown 格式的消息內容
            
        Returns:
            是否發送成功
        """
        try:
            payload = {
                'content': content,
                'username': 'A股分析機器人',
                'avatar_url': 'https://picsum.photos/200'
            }
            
            response = requests.post(
                self._discord_config['webhook_url'],
                json=payload,
                timeout=timeout_seconds or 10,
                verify=self._webhook_verify_ssl
            )
            
            if response.status_code in [200, 204]:
                logger.info("Discord Webhook 消息發送成功")
                return True
            else:
                logger.error(f"Discord Webhook 發送失敗: {response.status_code} {response.text}")
                return False
        except Exception as e:
            logger.error(f"Discord Webhook 發送異常: {e}")
            return False
    
    def _send_discord_bot(self, content: str, *, timeout_seconds: Optional[float] = None) -> bool:
        """
        使用 Bot API 發送消息到 Discord
        
        Args:
            content: Markdown 格式的消息內容
            
        Returns:
            是否發送成功
        """
        try:
            headers = {
                'Authorization': f'Bot {self._discord_config["bot_token"]}',
                'Content-Type': 'application/json'
            }
            
            payload = {
                'content': content
            }
            
            url = f'https://discord.com/api/v10/channels/{self._discord_config["channel_id"]}/messages'
            response = requests.post(url, json=payload, headers=headers, timeout=timeout_seconds or 10)
            
            if response.status_code == 200:
                logger.info("Discord Bot 消息發送成功")
                return True
            else:
                logger.error(f"Discord Bot 發送失敗: {response.status_code} {response.text}")
                return False
        except Exception as e:
            logger.error(f"Discord Bot 發送異常: {e}")
            return False
