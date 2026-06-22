# -*- coding: utf-8 -*-
"""
===================================
釘釘平臺適配器
===================================

處理釘釘機器人的 Webhook 回調。

釘釘機器人文檔：
https://open.dingtalk.com/document/robots/robot-overview
"""

import hashlib
import hmac
import base64
import time
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from urllib.parse import quote_plus

from bot.platforms.base import BotPlatform
from bot.models import BotMessage, BotResponse, WebhookResponse, ChatType

logger = logging.getLogger(__name__)


class DingtalkPlatform(BotPlatform):
    """
    釘釘平臺適配器
    
    支持：
    - 企業內部機器人回調
    - 羣機器人 Outgoing 回調
    - 消息籤名驗證
    
    配置要求：
    - DINGTALK_APP_KEY: 應用 AppKey
    - DINGTALK_APP_SECRET: 應用 AppSecret（用於籤名驗證）
    """
    
    def __init__(self):
        from src.config import get_config
        config = get_config()
        
        self._app_key = getattr(config, 'dingtalk_app_key', None)
        self._app_secret = getattr(config, 'dingtalk_app_secret', None)
    
    @property
    def platform_name(self) -> str:
        return "dingtalk"
    
    def verify_request(self, headers: Dict[str, str], body: bytes) -> bool:
        """
        驗證釘釘請求籤名
        
        釘釘籤名算法：
        1. 獲取 timestamp 和 sign
        2. 計算：base64(hmac_sha256(timestamp + "\n" + app_secret))
        3. 比對籤名
        """
        if not self._app_secret:
            logger.warning("[DingTalk] 未配置 app_secret，跳過籤名驗證")
            return True
        
        timestamp = headers.get('timestamp', '')
        sign = headers.get('sign', '')
        
        if not timestamp or not sign:
            logger.warning("[DingTalk] 缺少籤名參數")
            return True  # 可能是不需要籤名的請求
        
        # 驗證時間戳（1小時內有效）
        try:
            request_time = int(timestamp)
            current_time = int(time.time() * 1000)
            if abs(current_time - request_time) > 3600 * 1000:
                logger.warning("[DingTalk] 時間戳過期")
                return False
        except ValueError:
            logger.warning("[DingTalk] 無效的時間戳")
            return False
        
        # 計算籤名
        string_to_sign = f"{timestamp}\n{self._app_secret}"
        hmac_code = hmac.new(
            self._app_secret.encode('utf-8'),
            string_to_sign.encode('utf-8'),
            digestmod=hashlib.sha256
        ).digest()
        expected_sign = base64.b64encode(hmac_code).decode('utf-8')
        
        if sign != expected_sign:
            logger.warning(f"[DingTalk] 籤名驗證失敗")
            return False
        
        return True
    
    def handle_challenge(self, data: Dict[str, Any]) -> Optional[WebhookResponse]:
        """釘釘不需要 URL 驗證"""
        return None
    
    def parse_message(self, data: Dict[str, Any]) -> Optional[BotMessage]:
        """
        解析釘釘消息
        
        釘釘 Outgoing 機器人消息格式：
        {
            "msgtype": "text",
            "text": {
                "content": "@機器人 /analyze 600519"
            },
            "msgId": "xxx",
            "createAt": "1234567890",
            "conversationType": "2",  # 1=單聊, 2=羣聊
            "conversationId": "xxx",
            "conversationTitle": "羣名",
            "senderId": "xxx",
            "senderNick": "用戶暱稱",
            "senderCorpId": "xxx",
            "senderStaffId": "xxx",
            "chatbotUserId": "xxx",
            "atUsers": [{"dingtalkId": "xxx", "staffId": "xxx"}],
            "isAdmin": false,
            "sessionWebhook": "https://oapi.dingtalk.com/robot/sendBySession?session=xxx",
            "sessionWebhookExpiredTime": 1234567890
        }
        """
        # 檢查消息類型
        msg_type = data.get('msgtype', '')
        if msg_type != 'text':
            logger.debug(f"[DingTalk] 忽略非文本消息: {msg_type}")
            return None
        
        # 獲取消息內容
        text_content = data.get('text', {})
        raw_content = text_content.get('content', '')
        
        # 提取命令（去除 @機器人）
        content = self._extract_command(raw_content)
        
        # 檢查是否 @了機器人
        at_users = data.get('atUsers', [])
        mentioned = len(at_users) > 0
        
        # 會話類型
        conversation_type = data.get('conversationType', '')
        if conversation_type == '1':
            chat_type = ChatType.PRIVATE
        elif conversation_type == '2':
            chat_type = ChatType.GROUP
        else:
            chat_type = ChatType.UNKNOWN
        
        # 創建時間
        create_at = data.get('createAt', '')
        try:
            timestamp = datetime.fromtimestamp(int(create_at) / 1000)
        except (ValueError, TypeError):
            timestamp = datetime.now()
        
        # 保存 session webhook 用於回復
        session_webhook = data.get('sessionWebhook', '')
        
        return BotMessage(
            platform=self.platform_name,
            message_id=data.get('msgId', ''),
            user_id=data.get('senderId', ''),
            user_name=data.get('senderNick', ''),
            chat_id=data.get('conversationId', ''),
            chat_type=chat_type,
            content=content,
            raw_content=raw_content,
            mentioned=mentioned,
            mentions=[u.get('dingtalkId', '') for u in at_users],
            timestamp=timestamp,
            raw_data={
                **data,
                '_session_webhook': session_webhook,
            },
        )
    
    def _extract_command(self, text: str) -> str:
        """
        提取命令內容（去除 @機器人）
        
        釘釘的 @用戶 格式通常是 @暱稱 後跟空格
        """
        # 簡單處理：移除開頭的 @xxx 部分
        import re
        # 匹配開頭的 @xxx（中英文都可能）
        text = re.sub(r'^@[\S]+\s*', '', text.strip())
        return text.strip()
    
    def format_response(
        self, 
        response: BotResponse, 
        message: BotMessage
    ) -> WebhookResponse:
        """
        格式化釘釘響應
        
        釘釘 Outgoing 機器人可以直接在響應中返回消息。
        也可以使用 sessionWebhook 異步發送。
        
        響應格式：
        {
            "msgtype": "text" | "markdown",
            "text": {"content": "xxx"},
            "markdown": {"title": "xxx", "text": "xxx"},
            "at": {"atUserIds": ["xxx"], "isAtAll": false}
        }
        """
        if not response.text:
            return WebhookResponse.success()
        
        # 構建響應
        if response.markdown:
            body = {
                "msgtype": "markdown",
                "markdown": {
                    "title": "股票分析助手",
                    "text": response.text,
                }
            }
        else:
            body = {
                "msgtype": "text",
                "text": {
                    "content": response.text,
                }
            }
        
        # @發送者
        if response.at_user and message.user_id:
            body["at"] = {
                "atUserIds": [message.user_id],
                "isAtAll": False,
            }
        
        return WebhookResponse.success(body)
    
    def send_by_session_webhook(
        self, 
        session_webhook: str, 
        response: BotResponse,
        message: BotMessage
    ) -> bool:
        """
        通過 sessionWebhook 發送消息
        
        適用於需要異步發送或多條消息的場景。
        
        Args:
            session_webhook: 釘釘提供的會話 Webhook URL
            response: 響應對象
            message: 原始消息對象
            
        Returns:
            是否發送成功
        """
        if not session_webhook:
            logger.warning("[DingTalk] 沒有可用的 sessionWebhook")
            return False
        
        import requests
        
        try:
            # 構建消息
            if response.markdown:
                payload = {
                    "msgtype": "markdown",
                    "markdown": {
                        "title": "股票分析助手",
                        "text": response.text,
                    }
                }
            else:
                payload = {
                    "msgtype": "text",
                    "text": {
                        "content": response.text,
                    }
                }
            
            # @發送者
            if response.at_user and message.user_id:
                payload["at"] = {
                    "atUserIds": [message.user_id],
                    "isAtAll": False,
                }
            
            # 發送請求
            resp = requests.post(
                session_webhook,
                json=payload,
                timeout=10
            )
            
            if resp.status_code == 200:
                result = resp.json()
                if result.get('errcode') == 0:
                    logger.info("[DingTalk] sessionWebhook 發送成功")
                    return True
                else:
                    logger.error(f"[DingTalk] sessionWebhook 發送失敗: {result}")
                    return False
            else:
                logger.error(f"[DingTalk] sessionWebhook 請求失敗: {resp.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"[DingTalk] sessionWebhook 發送異常: {e}")
            return False
