# -*- coding: utf-8 -*-
"""
Server醬3 發送提醒服務

職責：
1. 通過 Server醬3 API 發送 Server醬3 消息
"""
import logging
from typing import Optional
import requests
from datetime import datetime
import re

from src.config import Config


logger = logging.getLogger(__name__)


class Serverchan3Sender:
    
    def __init__(self, config: Config):
        """
        初始化 Server醬3 配置

        Args:
            config: 配置對象
        """
        self._serverchan3_sendkey = getattr(config, 'serverchan3_sendkey', None)
        
    def send_to_serverchan3(
        self,
        content: str,
        title: Optional[str] = None,
        *,
        timeout_seconds: Optional[float] = None,
    ) -> bool:
        """
        推送消息到 Server醬3

        Server醬3 API 格式：
        POST https://sctapi.ftqq.com/{sendkey}.send
        或
        POST https://{num}.push.ft07.com/send/{sendkey}.send
        {
            "title": "消息標題",
            "desp": "消息內容",
            "options": {}
        }

        Server醬3 特點：
        - 國內推送服務，支持多家國產系統推送通道，可無後臺推送
        - 簡單易用的 API 接口

        Args:
            content: 消息內容（Markdown 格式）
            title: 消息標題（可選）

        Returns:
            是否發送成功
        """
        if not self._serverchan3_sendkey:
            logger.warning("Server醬3 SendKey 未配置，跳過推送")
            return False

        # 處理消息標題
        if title is None:
            date_str = datetime.now().strftime('%Y-%m-%d')
            title = f"📈 股票分析報告 - {date_str}"

        try:
            # 根據 sendkey 格式構造 URL
            sendkey = self._serverchan3_sendkey
            if sendkey.startswith('sctp'):
                match = re.match(r'sctp(\d+)t', sendkey)
                if match:
                    num = match.group(1)
                    url = f"https://{num}.push.ft07.com/send/{sendkey}.send"
                else:
                    logger.error("Invalid sendkey format for sctp")
                    return False
            else:
                url = f"https://sctapi.ftqq.com/{sendkey}.send"

            # 構建請求參數
            params = {
                'title': title,
                'desp': content,
                'options': {}
            }

            # 發送請求
            headers = {
                'Content-Type': 'application/json;charset=utf-8'
            }
            response = requests.post(url, json=params, headers=headers, timeout=timeout_seconds or 10)

            if response.status_code == 200:
                result = response.json()
                logger.info(f"Server醬3 消息發送成功: {result}")
                return True
            else:
                logger.error(f"Server醬3 請求失敗: HTTP {response.status_code}")
                logger.error(f"響應內容: {response.text}")
                return False

        except Exception as e:
            logger.error(f"發送 Server醬3 消息失敗: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return False
