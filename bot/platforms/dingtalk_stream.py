# -*- coding: utf-8 -*-
"""
===================================
釘釘 Stream 模式適配器
===================================

使用釘釘官方 Stream SDK 接入機器人，無需公網 IP 和 Webhook 配置。

優勢：
- 不需要公網 IP 或域名
- 不需要配置 Webhook URL
- 通過 WebSocket 長連接接收消息
- 更簡單的接入方式

依賴：
pip install dingtalk-stream

釘釘 Stream SDK：
https://github.com/open-dingtalk/dingtalk-stream-sdk-python
"""

import logging
import inspect
import threading
from datetime import datetime
from typing import Optional, Callable, Any

logger = logging.getLogger(__name__)

# 嘗試導入釘釘 Stream SDK
try:
    import dingtalk_stream
    from dingtalk_stream import AckMessage

    DINGTALK_STREAM_AVAILABLE = True
except ImportError:
    DINGTALK_STREAM_AVAILABLE = False
    logger.warning("[DingTalk Stream] dingtalk-stream SDK 未安裝，Stream 模式不可用")
    logger.warning("[DingTalk Stream] 請運行: pip install dingtalk-stream")

from bot.models import BotMessage, BotResponse, ChatType


class DingtalkStreamHandler:
    """
    釘釘 Stream 模式消息處理器

    將 Stream SDK 的回調轉換爲統一的 BotMessage 格式，
    並調用命令分發器處理。
    """

    def __init__(self, on_message: Callable[[BotMessage], Any]):
        """
        Args:
            on_message: 消息處理回調函數，接收 BotMessage 返回 BotResponse
        """
        self._on_message = on_message
        self._logger = logger

    @staticmethod
    def _truncate_log_content(text: str, max_len: int = 200) -> str:
        cleaned = text.replace("\n", " ").strip()
        if len(cleaned) > max_len:
            return f"{cleaned[:max_len]}..."
        return cleaned

    def _log_incoming_message(self, message: BotMessage) -> None:
        content = message.raw_content or message.content or ""
        summary = self._truncate_log_content(content)
        self._logger.info(
            "[DingTalk Stream] Incoming message: msg_id=%s user_id=%s chat_id=%s chat_type=%s content=%s",
            message.message_id,
            message.user_id,
            message.chat_id,
            getattr(message.chat_type, "value", message.chat_type),
            summary,
        )

    if DINGTALK_STREAM_AVAILABLE:
        class _ChatbotHandler(dingtalk_stream.ChatbotHandler):
            """內部消息處理器"""

            def __init__(self, parent: 'DingtalkStreamHandler'):
                super().__init__()
                self._parent = parent
                self.logger = logger

            async def process(self, callback: dingtalk_stream.CallbackMessage):
                """處理收到的消息"""
                try:
                    # 解析消息
                    incoming = dingtalk_stream.ChatbotMessage.from_dict(callback.data)

                    # 轉換爲統一格式
                    bot_message = self._parent._parse_stream_message(incoming, callback.data)

                    if bot_message:
                        self._parent._log_incoming_message(bot_message)
                        # 調用消息處理回調
                        response = self._parent._on_message(bot_message)
                        if inspect.isawaitable(response):
                            response = await response

                        # 發送回復
                        if response and response.text:
                            # 構建 @用戶 前綴（羣聊場景下需要在文本中包含 @用戶名）
                            if response.at_user and incoming.sender_nick:
                                if response.markdown:
                                    self.reply_markdown(
                                        title="股票分析助手",
                                        text=f"@{incoming.sender_nick} " + response.text,
                                        incoming_message=incoming
                                    )
                                else:
                                    self.reply_text(response.text, incoming)

                    return AckMessage.STATUS_OK, 'OK'

                except Exception as e:
                    self.logger.error(f"[DingTalk Stream] 處理消息失敗: {e}")
                    self.logger.exception(e)
                    return AckMessage.STATUS_SYSTEM_EXCEPTION, str(e)

        def create_handler(self) -> '_ChatbotHandler':
            """創建 SDK 需要的處理器實例"""
            return self._ChatbotHandler(self)

    def _parse_stream_message(self, incoming: Any, raw_data: dict) -> Optional[BotMessage]:
        """
        解析 Stream 消息爲統一格式

        Args:
            incoming: ChatbotMessage 對象
            raw_data: 原始回調數據
        """
        try:
            raw_data = dict(raw_data or {})

            # 獲取消息內容
            raw_content = incoming.text.content if incoming.text else ''

            # 提取命令（去除 @機器人）
            content = self._extract_command(raw_content)

            # 會話類型
            conversation_type = getattr(incoming, 'conversation_type', None)
            if conversation_type == '1':
                chat_type = ChatType.PRIVATE
            elif conversation_type == '2':
                chat_type = ChatType.GROUP
            else:
                chat_type = ChatType.UNKNOWN

            # 是否 @了機器人（Stream 模式下收到的消息一般都是 @機器人的）
            mentioned = True

            # 提取 sessionWebhook，便於異步推送
            session_webhook = (
                    getattr(incoming, 'session_webhook', None)
                    or raw_data.get('sessionWebhook')
                    or raw_data.get('session_webhook')
            )
            if session_webhook:
                raw_data['_session_webhook'] = session_webhook

            return BotMessage(
                platform='dingtalk',
                message_id=getattr(incoming, 'msg_id', '') or '',
                user_id=getattr(incoming, 'sender_id', '') or '',
                user_name=getattr(incoming, 'sender_nick', '') or '',
                chat_id=getattr(incoming, 'conversation_id', '') or '',
                chat_type=chat_type,
                content=content,
                raw_content=raw_content,
                mentioned=mentioned,
                mentions=[],
                timestamp=datetime.now(),
                raw_data=raw_data,
            )

        except Exception as e:
            logger.error(f"[DingTalk Stream] 解析消息失敗: {e}")
            return None

    def _extract_command(self, text: str) -> str:
        """提取命令內容（去除 @機器人）"""
        import re
        text = re.sub(r'^@[\S]+\s*', '', text.strip())
        return text.strip()


class DingtalkStreamClient:
    """
    釘釘 Stream 模式客戶端

    封裝 dingtalk-stream SDK，提供簡單的啓動接口。

    使用方式：
        client = DingtalkStreamClient()
        client.start()  # 阻塞運行

        # 或者在後臺運行
        client.start_background()
    """

    def __init__(
            self,
            client_id: Optional[str] = None,
            client_secret: Optional[str] = None
    ):
        """
        Args:
            client_id: 應用 AppKey（不傳則從配置讀取）
            client_secret: 應用 AppSecret（不傳則從配置讀取）
        """
        if not DINGTALK_STREAM_AVAILABLE:
            raise ImportError(
                "dingtalk-stream SDK 未安裝。\n"
                "請運行: pip install dingtalk-stream"
            )

        from src.config import get_config
        config = get_config()

        self._client_id = client_id or getattr(config, 'dingtalk_app_key', None)
        self._client_secret = client_secret or getattr(config, 'dingtalk_app_secret', None)

        if not self._client_id or not self._client_secret:
            raise ValueError(
                "釘釘 Stream 模式需要配置 DINGTALK_APP_KEY 和 DINGTALK_APP_SECRET"
            )

        self._client: Optional[dingtalk_stream.DingTalkStreamClient] = None
        self._background_thread: Optional[threading.Thread] = None
        self._running = False

    def _create_message_handler(self) -> Callable[[BotMessage], Any]:
        """創建消息處理函數"""

        async def handle_message(message: BotMessage) -> BotResponse:
            from bot.dispatcher import get_dispatcher
            dispatcher = get_dispatcher()
            return await dispatcher.dispatch_async(message)

        return handle_message

    def start(self) -> None:
        """
        啓動 Stream 客戶端（阻塞）

        此方法會阻塞當前線程，直到客戶端停止。
        """
        logger.info("[DingTalk Stream] 正在啓動...")

        # 創建憑證
        credential = dingtalk_stream.Credential(
            self._client_id,
            self._client_secret
        )

        # 創建客戶端
        self._client = dingtalk_stream.DingTalkStreamClient(credential)

        # 註冊消息處理器
        handler = DingtalkStreamHandler(self._create_message_handler())
        self._client.register_callback_handler(
            dingtalk_stream.chatbot.ChatbotMessage.TOPIC,
            handler.create_handler()
        )

        self._running = True
        logger.info("[DingTalk Stream] 客戶端已啓動，等待消息...")

        # 啓動（阻塞）
        self._client.start_forever()

    def start_background(self) -> None:
        """
        在後臺線程啓動 Stream 客戶端（非阻塞）

        適用於與其他服務（如 WebUI）同時運行的場景。
        """
        if self._background_thread and self._background_thread.is_alive():
            logger.warning("[DingTalk Stream] 客戶端已在運行")
            return

        self._running = True
        self._background_thread = threading.Thread(
            target=self._run_in_background,
            daemon=True,
            name="DingtalkStreamClient"
        )
        self._background_thread.start()
        logger.info("[DingTalk Stream] 後臺客戶端已啓動")

    def _run_in_background(self) -> None:
        """後臺運行（處理異常和重連）"""
        import time

        while self._running:
            try:
                self.start()
            except Exception as e:
                logger.error(f"[DingTalk Stream] 運行異常: {e}")
                if self._running:
                    logger.info("[DingTalk Stream] 5 秒後重連...")
                    time.sleep(5)

    def stop(self) -> None:
        """停止客戶端"""
        self._running = False
        logger.info("[DingTalk Stream] 客戶端已停止")

    @property
    def is_running(self) -> bool:
        """是否正在運行"""
        return self._running


# 全局客戶端實例
_stream_client: Optional[DingtalkStreamClient] = None


def get_dingtalk_stream_client() -> Optional[DingtalkStreamClient]:
    """獲取全局 Stream 客戶端實例"""
    global _stream_client

    if _stream_client is None and DINGTALK_STREAM_AVAILABLE:
        try:
            _stream_client = DingtalkStreamClient()
        except (ImportError, ValueError) as e:
            logger.warning(f"[DingTalk Stream] 無法創建客戶端: {e}")
            return None

    return _stream_client


def start_dingtalk_stream_background() -> bool:
    """
    在後臺啓動釘釘 Stream 客戶端

    Returns:
        是否成功啓動
    """
    client = get_dingtalk_stream_client()
    if client:
        client.start_background()
        return True
    return False
