# -*- coding: utf-8 -*-
"""
===================================
飛書 Stream 模式適配器
===================================

使用飛書官方 lark-oapi SDK 的 WebSocket 長連接模式接入機器人，
無需公網 IP 和 Webhook 配置。

優勢：
- 不需要公網 IP 或域名
- 不需要配置 Webhook URL
- 通過 WebSocket 長連接接收消息
- 更簡單的接入方式
- 內置自動重連和心跳保活

依賴：
pip install lark-oapi

飛書長連接文檔：
https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/server-side-sdk/python--sdk/handle-events
"""

import json
import logging
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional, Callable
import time

logger = logging.getLogger(__name__)

# 嘗試導入飛書 SDK
try:
    import lark_oapi as lark
    from lark_oapi import ws
    from lark_oapi.api.im.v1 import (
        P2ImMessageReceiveV1,
        ReplyMessageRequest,
        ReplyMessageRequestBody,
        CreateMessageRequest,
        CreateMessageRequestBody,
    )

    FEISHU_SDK_AVAILABLE = True
except ImportError:
    FEISHU_SDK_AVAILABLE = False
    logger.warning("[Feishu Stream] lark-oapi SDK 未安裝，Stream 模式不可用")
    logger.warning("[Feishu Stream] 請運行: pip install lark-oapi")

from bot.models import BotMessage, BotResponse, ChatType
from src.formatters import format_feishu_markdown, chunk_content_by_max_bytes
from src.config import get_config


class FeishuReplyClient:
    """
    飛書消息回復客戶端

    使用飛書 API 發送回復消息。
    """

    def __init__(self, app_id: str, app_secret: str):
        """
        Args:
            app_id: 飛書應用 ID
            app_secret: 飛書應用密鑰
        """
        if not FEISHU_SDK_AVAILABLE:
            raise ImportError("lark-oapi SDK 未安裝")

        self._client = lark.Client.builder() \
            .app_id(app_id) \
            .app_secret(app_secret) \
            .log_level(lark.LogLevel.WARNING) \
            .build()

        # 獲取配置的最大字節數
        config = get_config()
        self._max_bytes = getattr(config, 'feishu_max_bytes', 20000)

    def _send_interactive_card(self, content: str, message_id: Optional[str] = None,
                               chat_id: Optional[str] = None,
                               receive_id_type: str = "chat_id",
                               at_user: bool = False, user_id: Optional[str] = None) -> bool:
        """
        發送交互卡片消息（支持 Markdown 渲染）

        Args:
            content: Markdown 格式的內容
            message_id: 原消息 ID（回復時使用）
            chat_id: 會話 ID（主動發送時使用）
            receive_id_type: 接收者 ID 類型
            at_user: 是否 @用戶
            user_id: 用戶 open_id（at_user=True 時需要）

        Returns:
            是否發送成功
        """
        try:
            # 如果需要 @用戶，在內容前添加 @ 標記
            final_content = content
            if at_user and user_id:
                final_content = f"<at user_id=\"{user_id}\"></at> {content}"

            # 構建交互卡片 payload
            card_data = {
                "config": {"wide_screen_mode": True},
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": final_content
                        }
                    }
                ]
            }

            content_json = json.dumps(card_data)

            if message_id:
                # 回復消息
                request = ReplyMessageRequest.builder() \
                    .message_id(message_id) \
                    .request_body(
                    ReplyMessageRequestBody.builder()
                    .content(content_json)
                    .msg_type("interactive")
                    .build()
                ) \
                    .build()
                response = self._client.im.v1.message.reply(request)
            else:
                # 主動發送消息
                request = CreateMessageRequest.builder() \
                    .receive_id_type(receive_id_type) \
                    .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .content(content_json)
                    .msg_type("interactive")
                    .build()
                ) \
                    .build()
                response = self._client.im.v1.message.create(request)

            if not response.success():
                logger.error(
                    f"[Feishu Stream] 發送交互卡片失敗: code={response.code}, "
                    f"msg={response.msg}, log_id={response.get_log_id()}"
                )
                return False

            logger.debug("[Feishu Stream] 發送交互卡片成功")
            return True

        except Exception as e:
            logger.error(f"[Feishu Stream] 發送交互卡片異常: {e}")
            return False

    def reply_text(self, message_id: str, text: str, at_user: bool = False,
                   user_id: Optional[str] = None) -> bool:
        """
        回復文本消息（支持交互卡片和分段發送）

        Args:
            message_id: 原消息 ID
            text: 回復文本
            at_user: 是否 @用戶
            user_id: 用戶 open_id（at_user=True 時需要）

        Returns:
            是否發送成功
        """
        # 將文本轉換爲飛書 Markdown 格式
        formatted_text = format_feishu_markdown(text)

        # 檢查是否需要分段發送
        content_bytes = len(formatted_text.encode('utf-8'))
        if content_bytes > self._max_bytes:
            logger.info(
                f"[Feishu Stream] 回復消息內容超長({content_bytes}字節)，將分批發送"
            )
            return self._send_to_chat_chunked(
                formatted_text,
                lambda chunk: self._send_interactive_card(
                    chunk,
                    message_id=message_id,
                    at_user=at_user,
                    user_id=user_id,
                ),
            )

        # 單條消息，使用交互卡片
        return self._send_interactive_card(
            formatted_text, message_id=message_id, at_user=at_user, user_id=user_id
        )

    def send_to_chat(self, chat_id: str, text: str,
                     receive_id_type: str = "chat_id") -> bool:
        """
        發送消息到指定會話（支持交互卡片和分段發送）

        Args:
            chat_id: 會話 ID
            text: 消息文本
            receive_id_type: 接收者 ID 類型，默認 chat_id

        Returns:
            是否發送成功
        """
        # 將文本轉換爲飛書 Markdown 格式
        formatted_text = format_feishu_markdown(text)

        # 檢查是否需要分段發送
        content_bytes = len(formatted_text.encode('utf-8'))
        if content_bytes > self._max_bytes:
            logger.info(
                f"[Feishu Stream] 發送消息內容超長({content_bytes}字節)，將分批發送"
            )
            return self._send_to_chat_chunked(
                formatted_text,
                lambda chunk: self._send_interactive_card(
                    chunk,
                    chat_id=chat_id,
                    receive_id_type=receive_id_type,
                ),
            )

        # 單條消息，使用交互卡片
        return self._send_interactive_card(formatted_text, chat_id=chat_id, receive_id_type=receive_id_type)

    def _send_to_chat_chunked(self, content: str, send_func: Callable[[str], bool]) -> bool:
        """
        分批發送消息（支持交互卡片和分段發送）

        Args:
            content: 消息文本
            send_func: 發送單個分片的函數，返回是否發送成功

        Returns:
            是否全部發送成功
        """
        chunks = chunk_content_by_max_bytes(content, self._max_bytes, add_page_marker=True)
        success_count = 0
        for i, chunk in enumerate(chunks):
            if send_func(chunk):
                success_count += 1
            else:
                logger.error(f"[Feishu Stream] 發送消息失敗: {chunk}")
            if i < len(chunks) - 1:
                time.sleep(1)
        return success_count == len(chunks)


class FeishuStreamHandler:
    """
    飛書 Stream 模式消息處理器

    將 SDK 的事件轉換爲統一的 BotMessage 格式，
    並調用命令分發器處理。
    """

    def __init__(
            self,
            on_message: Callable[[BotMessage], BotResponse],
            reply_client: FeishuReplyClient
    ):
        """
        Args:
            on_message: 消息處理回調函數，接收 BotMessage 返回 BotResponse
            reply_client: 飛書回復客戶端
        """
        self._on_message = on_message
        self._reply_client = reply_client
        self._logger = logger
        # Different conversations can run in parallel, but one conversation
        # must stay FIFO so multi-turn chat and replies do not get reordered.
        self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="feishu-msg")
        self._pending_messages: dict[str, deque[BotMessage]] = {}
        self._active_conversations: set[str] = set()
        self._queue_lock = threading.Lock()
        self._shutdown = False

    def _conversation_key(self, bot_message: BotMessage) -> str:
        """Return the ordering key used for per-conversation FIFO processing."""
        if bot_message.chat_type == ChatType.PRIVATE:
            return bot_message.chat_id or bot_message.user_id or bot_message.message_id

        chat_id = bot_message.chat_id or "unknown-chat"
        user_id = bot_message.user_id or "unknown-user"
        return f"{chat_id}:{user_id}"

    def _enqueue_message(self, bot_message: BotMessage) -> None:
        """Queue a message and start a worker when its conversation is idle."""
        if self._shutdown:
            self._logger.debug("[Feishu Stream] Handler already stopped, dropping message")
            return

        conversation_key = self._conversation_key(bot_message)
        should_start_worker = False

        with self._queue_lock:
            self._pending_messages.setdefault(conversation_key, deque()).append(bot_message)
            if conversation_key not in self._active_conversations:
                self._active_conversations.add(conversation_key)
                should_start_worker = True

        if should_start_worker:
            try:
                self._executor.submit(self._drain_conversation, conversation_key)
            except RuntimeError as exc:
                with self._queue_lock:
                    self._active_conversations.discard(conversation_key)
                    self._pending_messages.pop(conversation_key, None)
                self._logger.error("[Feishu Stream] 無法啓動消息處理線程: %s", exc)

    def _drain_conversation(self, conversation_key: str) -> None:
        """Drain one conversation queue in FIFO order."""
        while True:
            with self._queue_lock:
                queue = self._pending_messages.get(conversation_key)
                if not queue:
                    self._pending_messages.pop(conversation_key, None)
                    self._active_conversations.discard(conversation_key)
                    return
                bot_message = queue.popleft()

            self._process_message(bot_message)

    def _process_message(self, bot_message: BotMessage) -> None:
        """Execute command handling off the SDK callback thread."""
        try:
            response = self._on_message(bot_message)

            if response and response.text:
                self._reply_client.reply_text(
                    message_id=bot_message.message_id,
                    text=response.text,
                    at_user=response.at_user,
                    user_id=bot_message.user_id if response.at_user else None,
                )
        except Exception as e:
            self._logger.error(f"[Feishu Stream] 異步處理消息失敗: {e}")
            self._logger.exception(e)

    @staticmethod
    def _truncate_log_content(text: str, max_len: int = 200) -> str:
        """截斷日誌內容"""
        cleaned = text.replace("\n", " ").strip()
        if len(cleaned) > max_len:
            return f"{cleaned[:max_len]}..."
        return cleaned

    def _log_incoming_message(self, message: BotMessage) -> None:
        """記錄收到的消息日誌"""
        content = message.raw_content or message.content or ""
        summary = self._truncate_log_content(content)
        self._logger.info(
            "[Feishu Stream] Incoming message: msg_id=%s user_id=%s "
            "chat_id=%s chat_type=%s content=%s",
            message.message_id,
            message.user_id,
            message.chat_id,
            getattr(message.chat_type, "value", message.chat_type),
            summary,
        )

    def handle_message(self, event: 'P2ImMessageReceiveV1') -> None:
        """
        處理接收到的消息事件

        Args:
            event: 飛書消息接收事件
        """
        try:
            # 解析消息
            bot_message = self._parse_event_message(event)

            if bot_message is None:
                return

            self._log_incoming_message(bot_message)

            self._enqueue_message(bot_message)

        except Exception as e:
            self._logger.error(f"[Feishu Stream] 處理消息失敗: {e}")
            self._logger.exception(e)

    def _parse_event_message(self, event: 'P2ImMessageReceiveV1') -> Optional[BotMessage]:
        """
        解析飛書事件消息爲統一格式

        Args:
            event: P2ImMessageReceiveV1 事件對象
        """
        try:
            event_data = event.event
            if event_data is None:
                return None

            message_data = event_data.message
            sender_data = event_data.sender

            if message_data is None:
                return None

            # 只處理文本消息
            message_type = message_data.message_type or ""
            if message_type != "text":
                self._logger.debug(f"[Feishu Stream] 忽略非文本消息: {message_type}")
                return None

            # 解析消息內容
            content_str = message_data.content or "{}"
            try:
                content_json = json.loads(content_str)
                raw_content = content_json.get("text", "")
            except json.JSONDecodeError:
                raw_content = content_str

            # 提取命令（去除 @機器人）
            content = self._extract_command(raw_content, message_data.mentions)
            mentioned = "@" in raw_content or bool(message_data.mentions)

            # 獲取發送者信息
            user_id = ""
            if sender_data and sender_data.sender_id:
                user_id = sender_data.sender_id.open_id or sender_data.sender_id.user_id or ""

            # 獲取會話類型
            chat_type_str = message_data.chat_type or ""
            if chat_type_str == "group":
                chat_type = ChatType.GROUP
            elif chat_type_str == "p2p":
                chat_type = ChatType.PRIVATE
            else:
                chat_type = ChatType.UNKNOWN

            # 創建時間
            create_time = message_data.create_time
            try:
                if create_time:
                    timestamp = datetime.fromtimestamp(int(create_time) / 1000)
                else:
                    timestamp = datetime.now()
            except (ValueError, TypeError):
                timestamp = datetime.now()

            # 構建原始數據
            raw_data = {
                "header": {
                    "event_id": event.header.event_id if event.header else "",
                    "event_type": event.header.event_type if event.header else "",
                    "create_time": event.header.create_time if event.header else "",
                    "token": event.header.token if event.header else "",
                    "app_id": event.header.app_id if event.header else "",
                },
                "event": {
                    "message_id": message_data.message_id,
                    "chat_id": message_data.chat_id,
                    "chat_type": message_data.chat_type,
                    "content": message_data.content,
                }
            }

            return BotMessage(
                platform="feishu",
                message_id=message_data.message_id or "",
                user_id=user_id,
                user_name=user_id,  # 飛書不直接返回用戶名
                chat_id=message_data.chat_id or "",
                chat_type=chat_type,
                content=content,
                raw_content=raw_content,
                mentioned=mentioned,
                mentions=[m.key or "" for m in (message_data.mentions or [])],
                timestamp=timestamp,
                raw_data=raw_data,
            )

        except Exception as e:
            self._logger.error(f"[Feishu Stream] 解析消息失敗: {e}")
            return None

    def _extract_command(self, text: str, mentions: list) -> str:
        """
        提取命令內容（去除 @機器人）

        飛書的 @用戶 格式是：@_user_1, @_user_2 等

        Args:
            text: 原始消息文本
            mentions: @提及列表
        """
        import re

        # 方式1: 通過 mentions 列表移除（精確匹配）
        for mention in (mentions or []):
            key = getattr(mention, 'key', '') or ''
            if key:
                text = text.replace(key, '')

        # 方式2: 正則兜底，移除飛書 @用戶 格式（@_user_N）
        # 當 mentions 爲空或未正確傳遞時生效
        text = re.sub(r'@_user_\d+\s*', '', text)

        # 清理多餘空格
        return ' '.join(text.split())

    def shutdown(self, wait: bool = False) -> None:
        """Stop accepting new messages and tear down worker threads."""
        self._shutdown = True
        with self._queue_lock:
            self._pending_messages.clear()
            self._active_conversations.clear()
        self._executor.shutdown(wait=wait)


class FeishuStreamClient:
    """
    飛書 Stream 模式客戶端

    封裝 lark-oapi SDK 的 WebSocket 客戶端，提供簡單的啓動接口。

    使用方式：
        client = FeishuStreamClient()
        client.start()  # 阻塞運行

        # 或者在後臺運行
        client.start_background()
    """

    def __init__(
            self,
            app_id: Optional[str] = None,
            app_secret: Optional[str] = None
    ):
        """
        Args:
            app_id: 應用 ID（不傳則從配置讀取）
            app_secret: 應用密鑰（不傳則從配置讀取）
        """
        if not FEISHU_SDK_AVAILABLE:
            raise ImportError(
                "lark-oapi SDK 未安裝。\n"
                "請運行: pip install lark-oapi"
            )

        from src.config import get_config
        config = get_config()

        self._app_id = app_id or getattr(config, 'feishu_app_id', None)
        self._app_secret = app_secret or getattr(config, 'feishu_app_secret', None)

        if not self._app_id or not self._app_secret:
            raise ValueError(
                "飛書 Stream 模式需要配置 FEISHU_APP_ID 和 FEISHU_APP_SECRET"
            )

        self._ws_client: Optional[ws.Client] = None
        self._reply_client: Optional[FeishuReplyClient] = None
        self._message_handler: Optional[FeishuStreamHandler] = None
        self._background_thread: Optional[threading.Thread] = None
        self._running = False

    def _create_message_handler(self) -> Callable[[BotMessage], BotResponse]:
        """創建消息處理函數"""

        def handle_message(message: BotMessage) -> BotResponse:
            from bot.dispatcher import get_dispatcher
            dispatcher = get_dispatcher()
            return dispatcher.dispatch(message)

        return handle_message

    def _create_event_handler(self) -> 'lark.EventDispatcherHandler':
        """創建事件分發處理器"""
        # 創建回復客戶端
        self._reply_client = FeishuReplyClient(self._app_id, self._app_secret)

        # 創建消息處理器
        handler = FeishuStreamHandler(
            self._create_message_handler(),
            self._reply_client
        )
        self._message_handler = handler

        # 創建並註冊事件處理器
        # 注意：encrypt_key 和 verification_token 在長連接模式下不是必需的
        # 但 SDK 要求傳入（可以爲空字符串）
        from src.config import get_config
        config = get_config()

        encrypt_key = getattr(config, 'feishu_encrypt_key', '') or ''
        verification_token = getattr(config, 'feishu_verification_token', '') or ''

        event_handler = lark.EventDispatcherHandler.builder(
            encrypt_key=encrypt_key,
            verification_token=verification_token,
            level=lark.LogLevel.WARNING
        ).register_p2_im_message_receive_v1(
            handler.handle_message
        ).build()

        return event_handler

    def start(self) -> None:
        """
        啓動 Stream 客戶端（阻塞）

        此方法會阻塞當前線程，直到客戶端停止。
        """
        logger.info("[Feishu Stream] 正在啓動...")

        # 創建事件處理器
        event_handler = self._create_event_handler()

        # 創建 WebSocket 客戶端
        self._ws_client = ws.Client(
            app_id=self._app_id,
            app_secret=self._app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.WARNING,
            auto_reconnect=True
        )

        self._running = True
        logger.info("[Feishu Stream] 客戶端已啓動，等待消息...")

        # 啓動（阻塞）
        self._ws_client.start()

    def start_background(self) -> None:
        """
        在後臺線程啓動 Stream 客戶端（非阻塞）

        適用於與其他服務（如 WebUI）同時運行的場景。
        """
        if self._background_thread and self._background_thread.is_alive():
            logger.warning("[Feishu Stream] 客戶端已在運行")
            return

        self._running = True
        self._background_thread = threading.Thread(
            target=self._run_in_background,
            daemon=True,
            name="FeishuStreamClient"
        )
        self._background_thread.start()
        logger.info("[Feishu Stream] 後臺客戶端已啓動")

    def _run_in_background(self) -> None:
        """後臺運行（處理異常和重連）"""
        import time

        while self._running:
            try:
                self.start()
            except Exception as e:
                logger.error(f"[Feishu Stream] 運行異常: {e}")
                if self._running:
                    logger.info("[Feishu Stream] 5 秒後重連...")
                    time.sleep(5)

    def stop(self) -> None:
        """停止客戶端"""
        self._running = False
        if self._message_handler is not None:
            self._message_handler.shutdown(wait=False)
        logger.info("[Feishu Stream] 客戶端已停止")

    @property
    def is_running(self) -> bool:
        """是否正在運行"""
        return self._running


# 全局客戶端實例
_stream_client: Optional[FeishuStreamClient] = None


def get_feishu_stream_client() -> Optional[FeishuStreamClient]:
    """獲取全局 Stream 客戶端實例"""
    global _stream_client

    if _stream_client is None and FEISHU_SDK_AVAILABLE:
        try:
            _stream_client = FeishuStreamClient()
        except (ImportError, ValueError) as e:
            logger.warning(f"[Feishu Stream] 無法創建客戶端: {e}")
            return None

    return _stream_client


def start_feishu_stream_background() -> bool:
    """
    在後臺啓動飛書 Stream 客戶端

    Returns:
        是否成功啓動
    """
    client = get_feishu_stream_client()
    if client:
        client.start_background()
        return True
    return False
