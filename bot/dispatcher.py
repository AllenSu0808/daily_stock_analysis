# -*- coding: utf-8 -*-
"""
===================================
命令分發器
===================================

負責解析命令、匹配處理器、分發執行。
"""

import asyncio
import logging
import re
import threading
import time
from collections import defaultdict
from typing import Dict, List, Optional, Type, Callable

from bot.models import BotMessage, BotResponse
from bot.commands.base import BotCommand

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    簡單的頻率限制器

    基於滑動窗口算法，限制每個用戶的請求頻率。
    """

    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        """
        Args:
            max_requests: 窗口內最大請求數
            window_seconds: 窗口時間（秒）
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: Dict[str, List[float]] = defaultdict(list)

    def is_allowed(self, user_id: str) -> bool:
        """
        檢查用戶是否允許請求

        Args:
            user_id: 用戶標識

        Returns:
            是否允許
        """
        now = time.time()
        window_start = now - self.window_seconds

        # 清理過期記錄
        self._requests[user_id] = [
            t for t in self._requests[user_id]
            if t > window_start
        ]

        # 檢查是否超限
        if len(self._requests[user_id]) >= self.max_requests:
            return False

        # 記錄本次請求
        self._requests[user_id].append(now)
        return True

    def get_remaining(self, user_id: str) -> int:
        """獲取剩餘可用請求數"""
        now = time.time()
        window_start = now - self.window_seconds

        # 清理過期記錄
        self._requests[user_id] = [
            t for t in self._requests[user_id]
            if t > window_start
        ]

        return max(0, self.max_requests - len(self._requests[user_id]))


class CommandDispatcher:
    """
    命令分發器

    職責：
    1. 註冊和管理命令處理器
    2. 解析消息中的命令和參數
    3. 分發命令到對應處理器
    4. 處理未知命令和錯誤

    使用示例：
        dispatcher = CommandDispatcher()
        dispatcher.register(AnalyzeCommand())
        dispatcher.register(HelpCommand())

        response = dispatcher.dispatch(message)
    """

    def __init__(
        self,
        command_prefix: str = "/",
        rate_limit_requests: int = 10,
        rate_limit_window: int = 60,
        admin_users: Optional[List[str]] = None
    ):
        """
        Args:
            command_prefix: 命令前綴，默認 "/"
            rate_limit_requests: 頻率限制：窗口內最大請求數
            rate_limit_window: 頻率限制：窗口時間（秒）
            admin_users: 管理員用戶 ID 列表
        """
        self.command_prefix = command_prefix
        self.admin_users = set(admin_users or [])

        self._commands: Dict[str, BotCommand] = {}
        self._aliases: Dict[str, str] = {}
        self._rate_limiter = RateLimiter(rate_limit_requests, rate_limit_window)

        # 回調函數：獲取幫助命令的命令列表
        self._help_command_getter: Optional[Callable] = None

    def register(self, command: BotCommand) -> None:
        """
        註冊命令

        Args:
            command: 命令實例
        """
        name = command.name.lower()

        if name in self._commands:
            logger.warning(f"[Dispatcher] 命令 '{name}' 已存在，將被覆蓋")

        self._commands[name] = command
        logger.debug(f"[Dispatcher] 註冊命令: {name}")

        # 註冊別名
        for alias in command.aliases:
            alias_lower = alias.lower()
            if alias_lower in self._aliases:
                logger.warning(f"[Dispatcher] 別名 '{alias_lower}' 已存在，將被覆蓋")
            self._aliases[alias_lower] = name
            logger.debug(f"[Dispatcher] 註冊別名: {alias_lower} -> {name}")

    def register_class(self, command_class: Type[BotCommand]) -> None:
        """
        註冊命令類（自動實例化）

        Args:
            command_class: 命令類
        """
        self.register(command_class())

    def unregister(self, name: str) -> bool:
        """
        註銷命令

        Args:
            name: 命令名稱

        Returns:
            是否成功註銷
        """
        name = name.lower()

        if name not in self._commands:
            return False

        command = self._commands.pop(name)

        # 移除別名
        for alias in command.aliases:
            self._aliases.pop(alias.lower(), None)

        logger.debug(f"[Dispatcher] 註銷命令: {name}")
        return True

    def get_command(self, name: str) -> Optional[BotCommand]:
        """
        獲取命令

        支持命令名和別名查詢。

        Args:
            name: 命令名或別名

        Returns:
            命令實例，或 None
        """
        name = name.lower()

        # 先查命令名
        if name in self._commands:
            return self._commands[name]

        # 再查別名
        if name in self._aliases:
            return self._commands.get(self._aliases[name])

        return None

    def list_commands(self, include_hidden: bool = False) -> List[BotCommand]:
        """
        列出所有命令

        Args:
            include_hidden: 是否包含隱藏命令

        Returns:
            命令列表
        """
        commands = list(self._commands.values())

        if not include_hidden:
            commands = [c for c in commands if not c.hidden]

        return sorted(commands, key=lambda c: c.name)

    def is_admin(self, user_id: str) -> bool:
        """檢查用戶是否是管理員"""
        return user_id in self.admin_users

    def add_admin(self, user_id: str) -> None:
        """添加管理員"""
        self.admin_users.add(user_id)

    def remove_admin(self, user_id: str) -> None:
        """移除管理員"""
        self.admin_users.discard(user_id)

    def dispatch(self, message: BotMessage) -> BotResponse:
        """同步分發消息。

        保持現有同步調用方兼容，實際邏輯委託給 `dispatch_async()`。
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return self._dispatch_sync(message)

        result_holder: Dict[str, BotResponse] = {}
        error_holder: Dict[str, BaseException] = {}

        def _runner() -> None:
            try:
                result_holder["response"] = self._dispatch_sync(message)
            except BaseException as exc:  # pragma: no cover
                error_holder["error"] = exc

        worker = threading.Thread(target=_runner, daemon=True)
        worker.start()
        worker.join()

        if "error" in error_holder:
            raise error_holder["error"]

        return result_holder.get("response", BotResponse.error_response("命令執行失敗"))

    def _prepare_dispatch(self, message: BotMessage) -> tuple[Optional[str], List[str], Optional[BotCommand], Optional[BotResponse]]:
        """Run shared dispatch pre-checks for sync/async entrypoints."""
        if not self._rate_limiter.is_allowed(message.user_id):
            remaining_time = self._rate_limiter.window_seconds
            return None, [], None, BotResponse.error_response(
                f"請求過於頻繁，請 {remaining_time} 秒後再試"
            )

        cmd_name, args = message.get_command_and_args(self.command_prefix)
        if cmd_name is None:
            return None, args, None, None

        logger.info(f"[Dispatcher] 收到命令: {cmd_name}, 參數: {args}, 用戶: {message.user_name}")

        command = self.get_command(cmd_name)
        if command is None:
            return cmd_name, args, None, BotResponse.error_response(
                f"未知命令: {cmd_name}\n"
                f"發送 `{self.command_prefix}help` 查看可用命令。"
            )

        if command.admin_only and not self.is_admin(message.user_id):
            return cmd_name, args, None, BotResponse.error_response("此命令需要管理員權限")

        error_msg = command.validate_args(args)
        if error_msg:
            return cmd_name, args, None, BotResponse.error_response(
                f"{error_msg}\n用法: `{command.usage}`"
            )

        return cmd_name, args, command, None

    def _dispatch_sync(self, message: BotMessage) -> BotResponse:
        """Pure synchronous dispatch path for webhook/stream integrations."""
        cmd_name, args, command, early_response = self._prepare_dispatch(message)
        if early_response is not None:
            return early_response

        if cmd_name is None:
            nl_result = self._try_nl_routing_sync(message)
            if nl_result is not None:
                return nl_result
            if message.mentioned:
                return BotResponse.text_response(
                    "你好！我是股票分析助手。\n"
                    f"發送 `{self.command_prefix}help` 查看可用命令。"
                )
            return BotResponse.text_response("")

        if command is None:
            return BotResponse.error_response("命令執行失敗")

        try:
            response = command.execute(message, args)
            logger.info(f"[Dispatcher] 命令 {cmd_name} 執行成功")
            return response
        except Exception as e:
            logger.error(f"[Dispatcher] 命令 {cmd_name} 執行失敗: {e}")
            logger.exception(e)
            return BotResponse.error_response(f"命令執行失敗: {str(e)[:100]}")

    async def dispatch_async(self, message: BotMessage) -> BotResponse:
        """
        異步分發消息到對應命令

        Args:
            message: 消息對象

        Returns:
            響應對象
        """
        cmd_name, args, command, early_response = self._prepare_dispatch(message)
        if early_response is not None:
            return early_response

        if cmd_name is None:
            # Not a command — try natural language routing before falling back
            nl_result = await self._try_nl_routing(message)
            if nl_result is not None:
                return nl_result
            # No NL match — check if @mentioned for a help hint
            if message.mentioned:
                return BotResponse.text_response(
                    "你好！我是股票分析助手。\n"
                    f"發送 `{self.command_prefix}help` 查看可用命令。"
                )
            # 非命令消息，不處理
            return BotResponse.text_response("")

        if command is None:
            return BotResponse.error_response("命令執行失敗")

        # 6. 執行命令
        try:
            response = await command.execute_async(message, args)
            logger.info(f"[Dispatcher] 命令 {cmd_name} 執行成功")
            return response
        except Exception as e:
            logger.error(f"[Dispatcher] 命令 {cmd_name} 執行失敗: {e}")
            logger.exception(e)
            return BotResponse.error_response(f"命令執行失敗: {str(e)[:100]}")

    def set_help_command_getter(self, getter: Callable) -> None:
        """
        設置幫助命令的命令列表獲取器

        用於讓 HelpCommand 獲取命令列表。

        Args:
            getter: 回調函數，返回命令列表
        """
        self._help_command_getter = getter

    # ------------------------------------------------------------------ #
    #  Natural language routing (LLM-based)                              #
    # ------------------------------------------------------------------ #

    # Lightweight intent-parsing prompt.  Asks the LLM to output a small
    # JSON object so we can route to the right command.
    _NL_PARSE_PROMPT = """\
You are a stock analysis assistant router.  Given a user's natural-language
message, determine whether it contains a stock-analysis request.

Return a JSON object (and NOTHING else) with these fields:
- "intent": one of "analysis", "chat", "none"
  * "analysis" → the user wants stock analysis / diagnosis / comparison
  * "chat" → the user is asking a general question related to finance
  * "none" → the message is irrelevant or you are unsure
- "codes": a list of stock codes mentioned (may be empty).
  Format: A-share 6-digit ("600519"), HK with prefix ("hk00700"), US ticker uppercase ("AAPL").
- "strategy": strategy/technique name if the user specified one, else null.
  e.g. "纏論", "MACD", "趨勢跟蹤", "chan_theory", etc.

Examples:
User: "幫我分析一下600519和000858"
{"intent":"analysis","codes":["600519","000858"],"strategy":null}

User: "用纏論看看AAPL"
{"intent":"analysis","codes":["AAPL"],"strategy":"纏論"}

User: "今天大盤怎麼樣"
{"intent":"chat","codes":[],"strategy":null}

User: "明天天氣如何"
{"intent":"none","codes":[],"strategy":null}

User: "600519"
{"intent":"analysis","codes":["600519"],"strategy":null}

User: "幫我分析茅臺"
{"intent":"analysis","codes":[],"strategy":null}

User: "analyze TSLA and NVDA using trend strategy"
{"intent":"analysis","codes":["TSLA","NVDA"],"strategy":"trend"}
"""

    # Cheap pre-filter: only invoke LLM when the message plausibly contains
    # stock-related content.  This regex checks for:
    #   - 6-digit A-share / BSE codes (0/3/6 and 43/83/87/88/92 prefixes)
    #   - HK codes like hk00700
    #   - 2-5 uppercase ASCII letters (US tickers)
    #   - Common finance/analysis keywords (Chinese and English)
    _NL_PREFILTER = re.compile(
        r'(?:[036]\d{5}|(?:43|83|87|88|92)\d{4})'  # A-share / BSE 6-digit codes
        r'|(?:hk|HK)\d{5}'                    # HK code
        r'|(?<![a-zA-Z])[A-Z]{2,5}(?![a-zA-Z])'  # US ticker — UPPERCASE only, no IGNORECASE
        r'|分析|看看|查一?下|研究|診斷|怎麼樣|走勢|趨勢'
        r'|能買|可以買|漲還是跌|怎麼看|能追|建議|目標價'
        r'|支撐|壓力|阻力|止損|買點|賣點|技術面|基本面|籌碼'
        r'|(?i:analyz|stock|buy|sell|trend|backtest|strateg)',
    )

    _NL_NAME_CLEANUP_PATTERNS = (
        r'[，,。.!！?？:：;；`\'"「」『』（）()\[\]{}<>]+',
        r'(?i:\b(?:please|analy[sz]e|analysis|research|check|look\s+at|stock|ticker|trend|price)\b)',
        r'(?:幫我|幫忙|麻煩|請|想請你|我想|想|用|按照|基於|關於|對)\s*',
        r'(?:分析|看看|研究|診斷|查一?下|聊聊|說說|問問|評估)\s*',
        r'(?:最近|近期|當前|今天|這隻|這個|個股|股票)\s*',
        r'(?:走勢|情況|表現|如何|怎麼樣|怎麼看|可以嗎|能買嗎|值不值得買|技術面|基本面|策略)\s*',
        r'\s+',
    )

    @classmethod
    def _passes_nl_prefilter(cls, text: str) -> bool:
        """Return whether the message is worth the LLM intent-routing cost."""
        if cls._NL_PREFILTER.search(text):
            return True

        stripped = (text or "").strip()
        if " " in stripped or len(stripped) > 10:
            return False

        from src.agent.orchestrator import _extract_stock_code

        return bool(_extract_stock_code(stripped))

    async def _try_nl_routing(self, message: BotMessage) -> Optional[BotResponse]:
        """Route a non-command message to the appropriate command via LLM intent parsing.

        Two-layer approach to balance cost and accuracy:
        1. **Cheap regex pre-filter**: skip messages that clearly have no stock
           or finance content (avoids LLM cost for irrelevant messages).
        2. **LLM intent parsing**: extract intent, stock codes, and strategy
           from the user text with full multilingual support.

        Only activates when:
        - ``AGENT_NL_ROUTING=true`` in config, **and**
        - the message is in a private chat, **or** the bot was @mentioned.

        Returns ``BotResponse`` if a route was found, ``None`` otherwise.
        """
        from src.config import get_config
        config = get_config()

        if not getattr(config, 'agent_nl_routing', False):
            return None

        # Only handle private chat or @mentioned messages to avoid hijacking
        is_private = message.chat_type.value == "private"
        if not is_private and not message.mentioned:
            return None

        # Keep Bot-side Agent entrypoints behind explicit opt-in so NL routing
        # cannot bypass AGENT_MODE=false.
        if not getattr(config, 'agent_mode', False):
            return None

        text = message.content.strip()
        if not text or len(text) > 500:
            return None

        # Layer 1: cheap pre-filter — skip obviously irrelevant messages
        if not self._passes_nl_prefilter(text):
            return None

        # Layer 2: LLM intent parsing — extract codes, intent, strategy
        parsed = await self._parse_intent_via_llm(text, config)
        if parsed is None:
            return None

        intent = parsed.get("intent", "none")
        codes = parsed.get("codes") or []
        strategy = parsed.get("strategy")

        if intent == "none":
            return None

        if intent == "analysis" and not codes:
            resolved_code = self._resolve_stock_code_from_text(text)
            if resolved_code:
                codes = [resolved_code]

        # "chat" intent → route to /chat with original text
        if intent == "chat":
            chat_cmd = self.get_command("chat")
            if chat_cmd:
                logger.info("[Dispatcher] NL routing → /chat: %s", text[:60])
                return await chat_cmd.execute_async(message, [text])
            return None

        # "analysis" intent → route to /ask
        if intent == "analysis" and codes:
            ask_cmd = self.get_command("ask")
            if not ask_cmd:
                return None

            # Build args: "code1,code2 [strategy]"
            code_str = ",".join(codes[:5])  # cap at 5
            args = [code_str]
            if strategy:
                args.append(strategy)

            logger.info(
                "[Dispatcher] NL routing → /ask %s (strategy=%s, text=%s)",
                code_str, strategy, text[:60],
            )
            return await ask_cmd.execute_async(message, args)

        return None

    def _try_nl_routing_sync(self, message: BotMessage) -> Optional[BotResponse]:
        """Synchronous companion to `_try_nl_routing` for legacy call sites."""
        from src.config import get_config

        config = get_config()
        if not getattr(config, 'agent_nl_routing', False):
            return None

        is_private = message.chat_type.value == "private"
        if not is_private and not message.mentioned:
            return None

        if not getattr(config, 'agent_mode', False):
            return None

        text = message.content.strip()
        if not text or len(text) > 500:
            return None

        if not self._passes_nl_prefilter(text):
            return None

        parsed = self._parse_intent_via_llm_sync(text, config)
        if parsed is None:
            return None

        intent = parsed.get("intent", "none")
        codes = parsed.get("codes") or []
        strategy = parsed.get("strategy")

        if intent == "none":
            return None

        if intent == "analysis" and not codes:
            resolved_code = self._resolve_stock_code_from_text(text)
            if resolved_code:
                codes = [resolved_code]

        if intent == "chat":
            chat_cmd = self.get_command("chat")
            if chat_cmd:
                logger.info("[Dispatcher] NL routing → /chat: %s", text[:60])
                return chat_cmd.execute(message, [text])
            return None

        if intent == "analysis" and codes:
            ask_cmd = self.get_command("ask")
            if not ask_cmd:
                return None

            code_str = ",".join(codes[:5])
            args = [code_str]
            if strategy:
                args.append(strategy)

            logger.info(
                "[Dispatcher] NL routing → /ask %s (strategy=%s, text=%s)",
                code_str, strategy, text[:60],
            )
            return ask_cmd.execute(message, args)

        return None

    @staticmethod
    async def _parse_intent_via_llm(text: str, config) -> Optional[dict]:
        """Call LLM to parse user intent.  Returns parsed dict or None on failure."""
        try:
            from src.agent.llm_adapter import LLMToolAdapter

            messages = [
                {"role": "system", "content": CommandDispatcher._NL_PARSE_PROMPT},
                {"role": "user", "content": text},
            ]
            adapter = LLMToolAdapter(config)
            resp = await asyncio.to_thread(
                adapter.call_text,
                messages,
                temperature=0,
                max_tokens=200,
                timeout=10,
            )
            return CommandDispatcher._parse_intent_payload(resp.content or "")
        except Exception as exc:
            logger.debug("[Dispatcher] NL parse LLM call failed: %s", exc)
            return None

    @staticmethod
    def _parse_intent_via_llm_sync(text: str, config) -> Optional[dict]:
        """Synchronous variant for webhook/stream integrations."""
        try:
            from src.agent.llm_adapter import LLMToolAdapter

            messages = [
                {"role": "system", "content": CommandDispatcher._NL_PARSE_PROMPT},
                {"role": "user", "content": text},
            ]
            adapter = LLMToolAdapter(config)
            resp = adapter.call_text(
                messages,
                temperature=0,
                max_tokens=200,
                timeout=10,
            )
            return CommandDispatcher._parse_intent_payload(resp.content or "")
        except Exception as exc:
            logger.debug("[Dispatcher] NL parse LLM call failed: %s", exc)
            return None

    @staticmethod
    def _parse_intent_payload(raw: str) -> Optional[dict]:
        """Parse the JSON payload returned by the intent-routing LLM call."""
        import json as _json

        cleaned = (raw or "").strip()
        if not cleaned:
            return None

        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned)

        try:
            result = _json.loads(cleaned)
        except _json.JSONDecodeError:
            logger.debug("[Dispatcher] NL parse: invalid JSON from LLM: %s", cleaned[:200])
            return None

        if isinstance(result, dict) and "intent" in result:
            return result

        logger.debug("[Dispatcher] NL parse: unexpected structure: %s", cleaned[:200])
        return None

    @classmethod
    def _resolve_stock_code_from_text(cls, text: str) -> Optional[str]:
        """Best-effort stock name/code resolution for NL-routed analysis requests."""
        from data_provider.base import canonical_stock_code
        from src.data.stock_mapping import STOCK_NAME_MAP
        from src.services.name_to_code_resolver import resolve_name_to_code

        def _iter_candidates(raw_text: str) -> List[str]:
            candidates: List[str] = []
            stripped = (raw_text or "").strip()
            if stripped:
                candidates.append(stripped)

            cleaned = stripped
            for pattern in cls._NL_NAME_CLEANUP_PATTERNS:
                cleaned = re.sub(pattern, " ", cleaned)
            cleaned = cleaned.strip(" 的").strip()
            if cleaned and cleaned not in candidates:
                candidates.append(cleaned)

            for source in list(candidates):
                for token in re.findall(r'[A-Za-z][A-Za-z0-9\.]{0,9}|[\u4e00-\u9fff]{2,12}', source):
                    normalized = token.strip(" 的").strip()
                    if normalized and normalized not in candidates:
                        candidates.append(normalized)

            return sorted(candidates, key=len, reverse=True)

        def _unique_partial_match(candidate: str) -> Optional[str]:
            if not re.search(r'[\u4e00-\u9fff]', candidate):
                return None
            matches = [
                code for code, stock_name in STOCK_NAME_MAP.items()
                if candidate and candidate in stock_name
            ]
            unique_matches = list(dict.fromkeys(matches))
            if len(unique_matches) == 1:
                return canonical_stock_code(unique_matches[0])
            return None

        candidates = _iter_candidates(text)

        # Prefer deterministic local alias/partial-name matches before any
        # resolver path that may touch online market data providers.
        for candidate in candidates:
            partial = _unique_partial_match(candidate)
            if partial:
                return partial

        for candidate in candidates:
            resolved = resolve_name_to_code(candidate)
            if resolved:
                return canonical_stock_code(resolved)

        return None


# 全局分發器實例
_dispatcher: Optional[CommandDispatcher] = None


def get_dispatcher() -> CommandDispatcher:
    """
    獲取全局分發器實例

    使用單例模式，首次調用時自動初始化並註冊所有命令。
    """
    global _dispatcher

    if _dispatcher is None:
        from src.config import get_config

        config = get_config()

        # 創建分發器
        _dispatcher = CommandDispatcher(
            command_prefix=getattr(config, 'bot_command_prefix', '/'),
            rate_limit_requests=getattr(config, 'bot_rate_limit_requests', 10),
            rate_limit_window=getattr(config, 'bot_rate_limit_window', 60),
            admin_users=getattr(config, 'bot_admin_users', []),
        )

        # 自動註冊所有命令
        from bot.commands import ALL_COMMANDS
        for command_class in ALL_COMMANDS:
            _dispatcher.register_class(command_class)

        logger.info(f"[Dispatcher] 初始化完成，已註冊 {len(_dispatcher._commands)} 個命令")

    return _dispatcher


def reset_dispatcher() -> None:
    """重置全局分發器（主要用於測試）"""
    global _dispatcher
    _dispatcher = None
