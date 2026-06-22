# -*- coding: utf-8 -*-
"""
Slack 發送提醒服務

職責：
1. 通過 Slack Bot API 或 Incoming Webhook 發送 Slack 消息
   （同時配置時優先使用 Bot API，確保文本與圖片發送到同一頻道）
"""
import logging
import json
from typing import Optional

import requests

from src.config import Config
from src.formatters import chunk_content_by_max_bytes

logger = logging.getLogger(__name__)

# Slack Block Kit 中單個 section block 的 text 字段上限爲 3000 字符
_BLOCK_TEXT_LIMIT = 3000
# Slack chat.postMessage / Webhook 的 text 字段上限約 40000 字符，保守取 39000
_TEXT_LIMIT = 39000


class SlackSender:

    def __init__(self, config: Config):
        """
        初始化 Slack 配置

        Args:
            config: 配置對象
        """
        self._slack_webhook_url = getattr(config, 'slack_webhook_url', None)
        self._slack_bot_token = getattr(config, 'slack_bot_token', None)
        self._slack_channel_id = getattr(config, 'slack_channel_id', None)
        self._webhook_verify_ssl = getattr(config, 'webhook_verify_ssl', True)

    @property
    def _use_bot(self) -> bool:
        """Bot 配置完整時優先走 Bot API，保證文本和圖片使用同一傳輸通道。"""
        return bool(self._slack_bot_token and self._slack_channel_id)

    def _is_slack_configured(self) -> bool:
        """檢查 Slack 配置是否完整（支持 Webhook 或 Bot API）"""
        return self._use_bot or bool(self._slack_webhook_url)

    def send_to_slack(self, content: str, *, timeout_seconds: Optional[float] = None) -> bool:
        """
        推送消息到 Slack（支持 Webhook 和 Bot API）

        傳輸優先級與 _send_slack_image() 保持一致：Bot > Webhook，
        避免文本走 Webhook、圖片走 Bot 導致消息落入不同頻道。

        Args:
            content: Markdown 格式的消息內容

        Returns:
            是否發送成功
        """
        # 按字節分塊，避免單條消息超限
        try:
            chunks = chunk_content_by_max_bytes(content, _TEXT_LIMIT, add_page_marker=True)
        except Exception as e:
            logger.error(f"分割 Slack 消息失敗: {e}, 嘗試整段發送。")
            chunks = [content]

        # 優先使用 Bot API（與 _send_slack_image 保持一致）
        if self._use_bot:
            return all(self._send_slack_bot(chunk, timeout_seconds=timeout_seconds) for chunk in chunks)

        # 其次使用 Webhook
        if self._slack_webhook_url:
            return all(self._send_slack_webhook(chunk, timeout_seconds=timeout_seconds) for chunk in chunks)

        logger.warning("Slack 配置不完整，跳過推送")
        return False

    def _build_blocks(self, content: str) -> list:
        """
        將內容構建爲 Slack Block Kit 格式

        如果內容超過單個 section block 限制，會自動拆分爲多個 block。
        """
        blocks = []
        # 按 block text 上限拆分
        pos = 0
        while pos < len(content):
            segment = content[pos:pos + _BLOCK_TEXT_LIMIT]
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": segment
                }
            })
            pos += _BLOCK_TEXT_LIMIT
        return blocks

    def _send_slack_webhook(self, content: str, *, timeout_seconds: Optional[float] = None) -> bool:
        """
        使用 Incoming Webhook 發送消息到 Slack

        Args:
            content: 消息內容

        Returns:
            是否發送成功
        """
        try:
            payload = {
                "text": content,
                "blocks": self._build_blocks(content),
            }
            response = requests.post(
                self._slack_webhook_url,
                data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                headers={'Content-Type': 'application/json; charset=utf-8'},
                timeout=timeout_seconds or 15,
                verify=self._webhook_verify_ssl,
            )
            if response.status_code == 200 and response.text == "ok":
                logger.info("Slack Webhook 消息發送成功")
                return True
            logger.error(f"Slack Webhook 發送失敗: HTTP {response.status_code} {response.text[:200]}")
            return False
        except Exception as e:
            logger.error(f"Slack Webhook 發送異常: {e}")
            return False

    def _send_slack_bot(self, content: str, *, timeout_seconds: Optional[float] = None) -> bool:
        """
        使用 Bot API (chat.postMessage) 發送消息到 Slack

        Args:
            content: 消息內容

        Returns:
            是否發送成功
        """
        try:
            headers = {
                'Authorization': f'Bearer {self._slack_bot_token}',
                'Content-Type': 'application/json; charset=utf-8',
            }
            payload = {
                "channel": self._slack_channel_id,
                "text": content,
                "blocks": self._build_blocks(content),
            }
            response = requests.post(
                'https://slack.com/api/chat.postMessage',
                data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                headers=headers,
                timeout=timeout_seconds or 15,
            )
            result = response.json()
            if result.get("ok"):
                logger.info("Slack Bot 消息發送成功")
                return True
            logger.error(f"Slack Bot 發送失敗: {result.get('error', 'unknown')}")
            return False
        except Exception as e:
            logger.error(f"Slack Bot 發送異常: {e}")
            return False

    def _send_slack_image(self, image_bytes: bytes, fallback_content: str = "") -> bool:
        """
        發送圖片到 Slack

        Bot 模式下使用 files.getUploadURLExternal + files.completeUploadExternal
        (Slack 新版文件上傳 API)；Webhook 模式下回退爲文本。

        Args:
            image_bytes: PNG 圖片字節
            fallback_content: 圖片發送失敗時的回退文本

        Returns:
            是否發送成功
        """
        # Bot 模式：使用新版文件上傳 API
        if self._use_bot:
            headers = {'Authorization': f'Bearer {self._slack_bot_token}'}
            try:
                # Step 1: 獲取上傳 URL
                resp1 = requests.post(
                    'https://slack.com/api/files.getUploadURLExternal',
                    headers=headers,
                    data={
                        'filename': 'report.png',
                        'length': len(image_bytes),
                    },
                    timeout=30,
                )
                result1 = resp1.json()
                if not result1.get("ok"):
                    logger.error("Slack 獲取上傳 URL 失敗: %s", result1.get('error', 'unknown'))
                    raise RuntimeError(result1.get('error', 'unknown'))

                upload_url = result1['upload_url']
                file_id = result1['file_id']

                # Step 2: 上傳文件內容（raw body，不能用 multipart）
                resp2 = requests.post(
                    upload_url,
                    data=image_bytes,
                    headers={'Content-Type': 'application/octet-stream'},
                    timeout=30,
                )
                if resp2.status_code != 200:
                    logger.error("Slack 文件上傳失敗: HTTP %s", resp2.status_code)
                    raise RuntimeError(f"HTTP {resp2.status_code}")

                # Step 3: 完成上傳並分享到頻道
                resp3 = requests.post(
                    'https://slack.com/api/files.completeUploadExternal',
                    headers={**headers, 'Content-Type': 'application/json'},
                    json={
                        'files': [{'id': file_id, 'title': '股票分析報告'}],
                        'channel_id': self._slack_channel_id,
                    },
                    timeout=30,
                )
                result3 = resp3.json()
                if result3.get("ok"):
                    logger.info("Slack Bot 圖片發送成功")
                    return True
                logger.error("Slack 完成上傳失敗: %s", result3.get('error', 'unknown'))
            except Exception as e:
                logger.error("Slack Bot 圖片發送異常: %s", e)

        # Webhook 模式或 Bot 上傳失敗：回退爲文本
        if fallback_content:
            logger.info("Slack 圖片不支持或失敗，回退爲文本發送")
            return self.send_to_slack(fallback_content)

        logger.warning("Slack 圖片發送失敗，且無回退內容")
        return False
