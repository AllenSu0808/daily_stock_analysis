# -*- coding: utf-8 -*-
"""
Wechat 發送提醒服務

職責：
1. 通過企業微信 Webhook 發送文本消息
2. 通過企業微信 Webhook 發送圖片消息
"""
import logging
import base64
import hashlib
import requests
import time
from typing import Optional

from src.config import Config
from src.formatters import chunk_content_by_max_bytes


logger = logging.getLogger(__name__)


# WeChat Work image msgtype limit ~2MB (base64 payload)
WECHAT_IMAGE_MAX_BYTES = 2 * 1024 * 1024

class WechatSender:
    
    def __init__(self, config: Config):
        """
        初始化企業微信配置

        Args:
            config: 配置對象
        """
        self._wechat_url = config.wechat_webhook_url
        self._wechat_max_bytes = getattr(config, 'wechat_max_bytes', 4000)
        self._wechat_msg_type = getattr(config, 'wechat_msg_type', 'markdown')
        self._webhook_verify_ssl = getattr(config, 'webhook_verify_ssl', True)
        
    def send_to_wechat(self, content: str, *, timeout_seconds: Optional[float] = None) -> bool:
        """
        推送消息到企業微信機器人
        
        企業微信 Webhook 消息格式：
        支持 markdown 類型以及 text 類型, markdown 類型在微信中無法展示，可以使用 text 類型,
        markdown 類型會解析 markdown 格式,text 類型會直接發送純文本。

        markdown 類型示例：
        {
            "msgtype": "markdown",
            "markdown": {
                "content": "## 標題\n\n內容"
            }
        }
        
        text 類型示例：
        {
            "msgtype": "text",
            "text": {
                "content": "內容"
            }
        }

        注意：企業微信 Markdown 限制 4096 字節（非字符）, Text 類型限制 2048 字節，超長內容會自動分批發送
        可通過環境變量 WECHAT_MAX_BYTES 調整限制值
        
        Args:
            content: Markdown 格式的消息內容
            
        Returns:
            是否發送成功
        """
        if not self._wechat_url:
            logger.warning("企業微信 Webhook 未配置，跳過推送")
            return False
        
        # 根據消息類型動態限制上限，避免 text 類型超過企業微信 2048 字節限制
        if self._wechat_msg_type == 'text':
            max_bytes = min(self._wechat_max_bytes, 2000)  # 預留一定字節給系統/分頁標記
        else:
            max_bytes = self._wechat_max_bytes  # markdown 默認 4000 字節
        
        # 檢查字節長度，超長則分批發送
        content_bytes = len(content.encode('utf-8'))
        if content_bytes > max_bytes:
            logger.info(f"消息內容超長({content_bytes}字節/{len(content)}字符)，將分批發送")
            return self._send_wechat_chunked(content, max_bytes)
        
        try:
            return self._send_wechat_message(content, timeout_seconds=timeout_seconds)
        except Exception as e:
            logger.error(f"發送企業微信消息失敗: {e}")
            return False

    def _send_wechat_image(self, image_bytes: bytes) -> bool:
        """Send image via WeChat Work webhook msgtype image (Issue #289)."""
        if not self._wechat_url:
            return False
        if len(image_bytes) > WECHAT_IMAGE_MAX_BYTES:
            logger.warning(
                "企業微信圖片超限 (%d > %d bytes)，拒絕發送，調用方應 fallback 爲文本",
                len(image_bytes), WECHAT_IMAGE_MAX_BYTES,
            )
            return False
        try:
            b64 = base64.b64encode(image_bytes).decode("ascii")
            md5_hash = hashlib.md5(image_bytes).hexdigest()
            payload = {
                "msgtype": "image",
                "image": {"base64": b64, "md5": md5_hash},
            }
            response = requests.post(
                self._wechat_url, json=payload, timeout=30, verify=self._webhook_verify_ssl
            )
            if response.status_code == 200:
                result = response.json()
                if result.get("errcode") == 0:
                    logger.info("企業微信圖片發送成功")
                    return True
                logger.error("企業微信圖片發送失敗: %s", result.get("errmsg", ""))
            else:
                logger.error("企業微信請求失敗: HTTP %s", response.status_code)
            return False
        except Exception as e:
            logger.error("企業微信圖片發送異常: %s", e)
            return False
    
    def _send_wechat_message(self, content: str, *, timeout_seconds: Optional[float] = None) -> bool:
        """發送企業微信消息"""
        payload = self._gen_wechat_payload(content)
        
        response = requests.post(
            self._wechat_url,
            json=payload,
            timeout=timeout_seconds or 10,
            verify=self._webhook_verify_ssl
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get('errcode') == 0:
                logger.info("企業微信消息發送成功")
                return True
            else:
                logger.error(f"企業微信返回錯誤: {result}")
                return False
        else:
            logger.error(f"企業微信請求失敗: {response.status_code}")
            return False
        
    def _send_wechat_chunked(self, content: str, max_bytes: int) -> bool:
        """
        分批發送長消息到企業微信
        
        按股票分析塊（以 --- 或 ### 分隔）智能分割，確保每批不超過限制
        
        Args:
            content: 完整消息內容
            max_bytes: 單條消息最大字節數
            
        Returns:
            是否全部發送成功
        """
        chunks = chunk_content_by_max_bytes(content, max_bytes, add_page_marker=True)
        total_chunks = len(chunks)
        success_count = 0
        for i, chunk in enumerate(chunks):
            if self._send_wechat_message(chunk):
                success_count += 1
            else:
                logger.error(f"企業微信第 {i+1}/{total_chunks} 批發送失敗")
            if i < total_chunks - 1:
                time.sleep(1)
        return success_count == len(chunks)

    def _gen_wechat_payload(self, content: str) -> dict:
        """生成企業微信消息 payload"""
        if self._wechat_msg_type == 'text':
            return {
                "msgtype": "text",
                "text": {
                    "content": content
                }
            }
        else:
            return {
                "msgtype": "markdown",
                "markdown": {
                    "content": content
                }
            }
