import discord
from discord.ext import commands
import asyncio
import os
import re
import unicodedata
from datetime import datetime, timedelta
from collections import defaultdict, deque
from typing import Any, Optional, Dict, List, Tuple, Set

from src.core.config import logger, Config
from src.core.api_router import get_api_router
from src.core.api_config import AVAILABLE_MODELS, MODEL_PRIORITY
from src.database.repository import DatabaseRepository
from src.services.file_parser import FileParserService
from src.services.file_index_service import (
    FileIndexService,
    build_index_base_name,
    write_index_json,
    read_index_json,
    should_use_last_index,
    build_index_context,
)
from src.managers.cleanup_manager import CleanupManager
from src.managers.cache_manager import CacheManager
from src.managers.note_manager import NoteManager
from src.managers.premium_manager import PremiumManager
from src.tools.tools import ToolsManager

from src.core.gemini_api_manager import GeminiApiManager
from src.core.gemini_pipeline import GeminiPipeline


def _resolve_model_aliases() -> Tuple[str, str, str]:
    """Resolve router model aliases from env with safe defaults/validation.

    Uses router alias names (not raw model IDs), e.g.:
    - gemini-flash-35
    - gemini-flash-lite
    """
    priority = [alias for alias in MODEL_PRIORITY if alias in AVAILABLE_MODELS]

    # Reload environment variable cache forcefully here because
    # it gets mutated via the /enable_custom_api slash command
    custom_enabled = os.environ.get("ENABLE_CUSTOM_ENDPOINT", "false").lower() == "true"

    # Filter priority list based on custom endpoint toggle
    if custom_enabled:
        priority = [alias for alias in priority if alias.startswith("custom-")]
        if not priority:
            priority = ["custom-flash-high"] # Fail-safe fallback if config is broken
    else:
        priority = [alias for alias in priority if not alias.startswith("custom-")]
        if not priority:
            priority = ["gemini-flash-35"] # Fail-safe fallback

    # We want final output to be a high capacity/quality model (priority 0 or 1 usually).
    final_default = priority[0] if priority else "gemini-flash-35"

    # We want reasoning to be a fast lite model (like custom-flash-lite or gemini-flash-lite).
    # Since priority list is sorted by general quality, lite models are usually near the end.
    lite_models = [alias for alias in priority if "lite" in alias.lower()]
    reasoning_default = lite_models[0] if lite_models else (priority[1] if len(priority) > 1 else final_default)

    fallback_default = reasoning_default

    # We don't read FINAL_MODEL_ALIAS from env here if custom toggle enforces a specific prefix pool.
    # We strictly enforce the aliases so that they don't leak across the custom/standard boundary.
    final_alias = final_default
    reasoning_alias = reasoning_default
    fallback_alias = fallback_default

    return reasoning_alias, final_alias, fallback_alias


# We don't want global constants statically assigned at import time anymore,
# because the custom endpoint toggle changes them at runtime.

class MessageHandler:
    """Core message processing with Gemini API integration."""

    def __init__(self, bot_core, config: Config):
        self.bot_core = bot_core
        self.config = config
        self.logger = logger
        self.bot = None  # Will be set via handle_message()
        self.db_repo = DatabaseRepository()
        self.cache_mgr = CacheManager()
        self.note_mgr = NoteManager(self.db_repo)

        # Initialize FileParser with CleanupManager
        self.file_parser = FileParserService(cleanup_mgr=CleanupManager())
        self.tools_mgr = ToolsManager(note_mgr=self.note_mgr)
        self.premium_mgr = PremiumManager()
        self.file_index_dir = self.config.FILE_INDEX_DIR
        self.file_chunk_dir = self.config.FILE_CHUNK_DIR

        # FileIndexService will be initialised lazily (needs API helpers bound to self)
        self._file_index_svc: Optional[FileIndexService] = None

        # Rate limiting (per user)
        self.user_queue: Dict[str, deque] = defaultdict(deque)
        self.RATE_LIMIT_THRESHOLD = 6  # Max messages
        self.RATE_LIMIT_WINDOW = 90  # Per x seconds
        
        # Premium/Admin limit config overrides
        self.PREMIUM_RATE_LIMIT_THRESHOLD = int(self.config.PREMIUM_RATE_LIMIT.split('/')[0]) if hasattr(self.config, 'PREMIUM_RATE_LIMIT') else 20
        self.PREMIUM_RATE_LIMIT_WINDOW = int(self.config.PREMIUM_RATE_LIMIT.split('/')[1]) if hasattr(self.config, 'PREMIUM_RATE_LIMIT') else 60
        self.ADMIN_RATE_LIMIT_THRESHOLD = 100
        self.ADMIN_RATE_LIMIT_WINDOW = 60
        
        # PremiumManager setup
        self.premium_mgr = __import__('src.managers.premium_manager', fromlist=['PremiumManager']).PremiumManager()

        # --- API ROUTER (Daily Quota + global limiter) ---
        self.api_router = get_api_router()

        # --- Gemini API Manager & Pipeline (lazy init) ---
        self._api_mgr: Optional[GeminiApiManager] = None
        self._pipeline: Optional[GeminiPipeline] = None

    @property
    def api_mgr(self) -> GeminiApiManager:
        if self._api_mgr is None:
            self._api_mgr = GeminiApiManager(config=self.config, api_router=self.api_router)
        return self._api_mgr

    @property
    def pipeline(self) -> GeminiPipeline:
        # Every time we grab pipeline, we resolve aliases dynamically
        # so that when the custom api toggle flips, the pipeline uses the correct models.
        reasoning_alias, final_alias, fallback_alias = _resolve_model_aliases()
        if self._pipeline is None or self._pipeline.reasoning_model_alias != reasoning_alias:
            self._pipeline = GeminiPipeline(
                config=self.config,
                api_mgr=self.api_mgr,
                tools_mgr=self.tools_mgr,
                identity_builder=self._build_identity_capability_instruction,
                reasoning_model_alias=reasoning_alias,
                final_model_alias=final_alias,
                fallback_model_alias=fallback_alias,
            )
        return self._pipeline

    @property
    def file_index_svc(self) -> FileIndexService:
        reasoning_alias, final_alias, fallback_alias = _resolve_model_aliases()
        if self._file_index_svc is None or self._file_index_svc._reasoning_alias != reasoning_alias:
            self._file_index_svc = FileIndexService(
                config=self.config,
                file_parser=self.file_parser,
                api_generate_fn=self.api_mgr._generate_gemini_content,
                api_get_key_fn=self.api_mgr._get_best_api_key,
                api_commit_key_fn=self.api_mgr._commit_selected_key,
                api_throttle_fn=self.api_mgr._throttle_api_request,
                api_acquire_quota_fn=self.api_mgr._acquire_gemini_quota,
                api_log_exception_fn=self.api_mgr._log_gemini_exception,
                reasoning_model_alias=reasoning_alias,
                final_model_alias=final_alias,
            )
        return self._file_index_svc

    async def close_gemini_clients(self) -> None:
        if self._api_mgr is not None:
            await self._api_mgr.close_gemini_clients()

    def _sanitize_mentions(self, text: str) -> str:
        text = text.replace('@', '\\@')
        return text

    # --- Smart Reply (split & chain) ---

    async def send_smart_reply(self, message: discord.Message, text: str):
        text = self._sanitize_mentions(text)

        limit = 1900
        chunks = []
        current_text = text.strip()

        while len(current_text) > limit:
            split_idx = current_text.rfind('\n', 0, limit)
            if split_idx == -1:
                split_idx = current_text.rfind(' ', 0, limit)
            if split_idx == -1:
                split_idx = limit

            chunk = current_text[:split_idx].strip()
            if chunk:
                chunks.append(chunk)
            current_text = current_text[split_idx:].strip()

        if current_text:
            chunks.append(current_text)

        last_bot_message = None

        for i, chunk in enumerate(chunks):
            try:
                if i == 0:
                    last_bot_message = await message.reply(chunk, mention_author=False)
                else:
                    if last_bot_message:
                        last_bot_message = await last_bot_message.reply(chunk, mention_author=False)
                    else:
                        last_bot_message = await message.channel.send(chunk)

                if i < len(chunks) - 1:
                    await asyncio.sleep(1.0)

            except Exception as e:
                self.logger.error(f"Lỗi khi gửi chunk {i}: {e}")

    # --- Main message routing ---

    async def handle_message(self, message: discord.Message, bot: commands.Bot):
            try:
                self.bot = bot

                if message.author.bot:
                    return

                user_id = str(message.author.id)

                # Check for duplicate processing
                if user_id in self.bot_core.processing_users:
                    self.logger.warning(f"User {user_id} already processing, ignoring concurrent message: '{message.content}'")
                    return

                self.bot_core.processing_users.add(user_id)
                try:
                    is_admin = user_id in self.config.ADMIN_USER_IDS
                    is_premium = self.premium_mgr.is_premium_user(user_id)

                    is_dm = isinstance(message.channel, discord.DMChannel)
                    is_mentioned = self.bot.user in message.mentions

                    if not is_dm and not is_mentioned:
                        return

                    if not is_admin and not is_premium:
                        now = datetime.now()
                        self.user_queue[user_id].append(now)
                        while self.user_queue[user_id] and self.user_queue[user_id][0] < now - timedelta(seconds=self.RATE_LIMIT_WINDOW):
                            self.user_queue[user_id].popleft()

                        if len(self.user_queue[user_id]) > self.RATE_LIMIT_THRESHOLD:
                            await message.add_reaction("⏳")
                            return

                        daily_msg_count = await self.db_repo.count_user_messages_today_db(user_id)
                        DAILY_LIMIT = 50
                        
                        if daily_msg_count >= DAILY_LIMIT:
                            await message.reply(
                                "Bạn đã sử dụng hết giới hạn tin nhắn hôm nay (50/50). Hãy nâng cấp Premium bằng lệnh `/premium buy` để tiếp tục dùng không giới hạn nhé! 🛑", 
                                mention_author=False
                            )
                            return

                    if user_id in self.bot_core.confirmation_pending and self.bot_core.confirmation_pending[user_id]['awaiting']:
                        if message.content.lower() in ['yes', 'y']:
                            await self._clear_user_history(message, user_id)
                        self.bot_core.confirmation_pending[user_id]['awaiting'] = False
                        return

                    if user_id in self.bot_core.admin_confirmation_pending and self.bot_core.admin_confirmation_pending[user_id]['awaiting']:
                        if message.content.upper() == 'YES RESET':
                            await self._clear_all_data(message, user_id)
                        self.bot_core.admin_confirmation_pending[user_id]['awaiting'] = False
                        return

                    if is_dm:
                        await self._handle_dm(message)
                    else:
                        await self._handle_mention(message)
                finally:
                    # Always clean up the processing set when done (or on error)
                    if user_id in self.bot_core.processing_users:
                        self.bot_core.processing_users.remove(user_id)

            except Exception as e:
                self.logger.error(f"Error in handle_message: {e}")

    async def _handle_dm(self, message: discord.Message):
        user_id = str(message.author.id)

        premium = self.premium_mgr.is_premium_user(user_id)
        if not premium and user_id not in self.config.ADMIN_USER_IDS:
            await message.reply("You do not have access to DM mode. 😔", mention_author=False)
            return

        await self._process_message_with_gemini(message, is_dm=True)

    async def _handle_mention(self, message: discord.Message):
        await self._process_message_with_gemini(message, is_dm=False)

    # --- Intent detection ---

    def _normalize_intent_text(self, text: str) -> str:
        lowered = (text or "").lower()
        no_diacritics = "".join(
            ch for ch in unicodedata.normalize("NFD", lowered)
            if unicodedata.category(ch) != "Mn"
        )
        normalized = re.sub(r"[^a-z0-9\s]", " ", no_diacritics)
        return re.sub(r"\s+", " ", normalized).strip()

    def _is_identity_question(self, text: str) -> bool:
        normalized = self._normalize_intent_text(text)
        if not normalized:
            return False
        patterns = [
            "bạn là ai", "ban la ai", "ai vậy", "ai vay",
            "tên bạn là gì", "ten ban la gi", "tên bạn là ai", "ten ban la ai",
            "who are you", "what is your name", "your name",
        ]
        return any(pattern in normalized for pattern in patterns)

    def _is_capability_question(self, text: str) -> bool:
        normalized = self._normalize_intent_text(text)
        if not normalized:
            return False
        patterns = [
            "bạn làm được gì", "ban lam duoc gi", "bạn có thể làm gì", "ban co the lam gi",
            "khả năng của bạn", "kha nang cua ban",
            "what can you do", "your capabilities", "your features",
        ]
        return any(pattern in normalized for pattern in patterns)

    def _is_cross_user_presence_question(self, text: str) -> bool:
        normalized = self._normalize_intent_text(text)
        if not normalized:
            return False
        patterns = [
            "đã chat với ai khác", "da chat voi ai khac",
            "chat với ai khác", "chat voi ai khac",
            "từng chat với ai khác", "tung chat voi ai khac",
            "đã nói chuyện với ai khác", "da noi chuyen voi ai khac",
            "have you chatted with others", "have you talked to other users",
        ]
        return any(pattern in normalized for pattern in patterns)

    def _is_admin_cross_user_detail_query(self, text: str) -> bool:
        raw = (text or "").strip()
        normalized = self._normalize_intent_text(raw)
        if not raw and not normalized:
            return False

        detail_markers = [
            "da hoi gi ve toi", "hoi gi ve toi", "ai da hoi ve toi",
            "asked about me", "what did", "who asked about me",
        ]
        if any(marker in normalized for marker in detail_markers):
            return True

        raw_lower = raw.lower()
        tokens = normalized.split()

        has_user_anchor = (
            " user " in f" {normalized} "
            or " uid " in f" {normalized} "
            or " userid " in f" {normalized} "
            or " ai " in f" {normalized} "
            or "@" in raw_lower
        )

        has_query_action = any(
            keyword in tokens
            for keyword in {"hoi", "asked", "ask", "chat", "noi", "talk", "message"}
        ) or any(fragment in raw_lower for fragment in {"hỏi", "asked", "ask", "chat", "h?i"})

        has_about_me = (
            any(phrase in normalized for phrase in {"ve toi", "ve minh", "about me"})
            or any(fragment in raw_lower for fragment in {"về tôi", "về mình", "about me", "tôi", "mình", " me "})
            or ("t?i" in raw_lower and ("h?i" in raw_lower or "v?" in raw_lower))
        )

        return has_user_anchor and has_query_action and has_about_me

    # --- Admin cross-user evidence ---

    async def _build_admin_cross_user_evidence(self, message: discord.Message, content: str, user_id: str) -> str:
        if not self._is_admin_cross_user_detail_query(content):
            return ""

        candidates = [
            (message.author.display_name or "").strip(),
            (message.author.name or "").strip(),
            user_id,
            "@" + (message.author.display_name or "").strip(),
            "@" + (message.author.name or "").strip(),
        ]
        query_terms: List[str] = []
        for term in candidates:
            if term and len(term) >= 2 and term.lower() not in {"toi", "tôi", "me"}:
                query_terms.append(term)

        if not query_terms:
            return ""

        collected: List[Dict[str, Any]] = []
        seen = set()
        for term in query_terms:
            rows = await self.db_repo.search_user_messages_db(term, limit=20, exclude_user_id=user_id)
            for row in rows:
                key = (row.get("user_id"), row.get("timestamp"), row.get("content"))
                if key in seen:
                    continue
                seen.add(key)
                collected.append(row)

        if not collected:
            return "[ADMIN CROSS-USER EVIDENCE]\nNo matching cross-user messages were found for this query in DB."

        collected.sort(key=lambda item: (item.get("timestamp") or ""), reverse=True)
        lines = ["[ADMIN CROSS-USER EVIDENCE]", "Verified message records from other users:"]
        for idx, row in enumerate(collected[:25], start=1):
            content_text = str(row.get("content", "")).strip()
            if len(content_text) > 260:
                content_text = f"{content_text[:260]}..."
            lines.append(
                f"{idx}. user_id={row.get('user_id', 'unknown')} | timestamp={row.get('timestamp', 'unknown')} | content={content_text}"
            )

        return "\n".join(lines)

    # --- Identity & capability contract ---

    def _get_runtime_tool_capabilities(self) -> List[Tuple[str, str]]:
        capabilities: List[Tuple[str, str]] = []
        seen_names: Set[str] = set()
        try:
            tools = self.tools_mgr.get_all_tools() or []
        except Exception:
            return capabilities

        for tool in tools:
            declarations = getattr(tool, "function_declarations", None)
            if declarations is None and isinstance(tool, dict):
                declarations = tool.get("function_declarations", [])
            if not declarations:
                continue

            for decl in declarations:
                if isinstance(decl, dict):
                    name = str(decl.get("name", "")).strip()
                    description = str(decl.get("description", "")).strip()
                else:
                    name = str(getattr(decl, "name", "")).strip()
                    description = str(getattr(decl, "description", "")).strip()

                if not name or name in seen_names:
                    continue
                seen_names.add(name)
                description = re.sub(r"\s+", " ", description)
                if len(description) > 180:
                    description = description[:177].rstrip() + "..."
                capabilities.append((name, description or "Tool available in runtime"))

        capabilities.sort(key=lambda item: item[0])
        return capabilities

    def _build_identity_capability_instruction(self, privacy_context: Dict[str, Any]) -> str:
        capabilities = self._get_runtime_tool_capabilities()
        if capabilities:
            tool_lines = "\n".join([f"- {name}: {desc}" for name, desc in capabilities])
        else:
            tool_lines = "- No runtime tools detected."

        is_admin = bool(privacy_context.get("is_admin"))
        distinct_user_count = int(privacy_context.get("distinct_user_count") or 0)
        has_other_users = bool(privacy_context.get("has_other_users"))

        from src.core.prompt_loader import build_identity_capability_prompt
        return build_identity_capability_prompt(
            is_admin=is_admin,
            has_other_users=has_other_users,
            distinct_user_count=distinct_user_count,
            tool_lines=tool_lines
        )

    # --- Core message processing ---

    async def _process_message_with_gemini(self, message: discord.Message, is_dm: bool = False):
        user_id = str(message.author.id)
        is_admin = user_id in self.config.ADMIN_USER_IDS

        try:
            content = message.content.strip()

            bot_mention = f"<@{self.bot.user.id}>"
            bot_mention_mobile = f"<@!{self.bot.user.id}>"
            content = content.replace(bot_mention, "").replace(bot_mention_mobile, "")

            if message.mentions:
                for mention in message.mentions:
                    if mention.id != self.bot.user.id:
                        content = content.replace(f"<@{mention.id}>", mention.display_name)
                        content = content.replace(f"<@!{mention.id}>", mention.display_name)

            content = content.replace('@', '')
            content = re.sub(r'\s+', ' ', content).strip()

            content = content.strip()

            reply_context = ""
            if not is_dm and message.reference:
                try:
                    reference_id = message.reference.message_id
                    if reference_id is None:
                        raise ValueError("Missing reply message id")
                    replied_msg = await message.channel.fetch_message(reference_id)
                    replied_content = replied_msg.content

                    if replied_msg.attachments:
                        replied_content += f" [Kèm {len(replied_msg.attachments)} đính kèm: {[a.url for a in replied_msg.attachments]}]"

                    reply_context = (
                        f"\n\n[SYSTEM CONTEXT: User is replying to a message from '{replied_msg.author.display_name}']\n"
                        f"[Replied Message Content]: \"{replied_content}\"\n"
                    )
                except Exception as e:
                    self.logger.warning(f"Failed to fetch replied message: {e}")

            if not content:
                if message.attachments:
                    pass
                elif reply_context:
                    content = "Hãy phân tích tin nhắn tôi vừa reply."
                elif not is_dm and message.guild.me in message.mentions:
                    content = "Xin chào Chad Gibiti"
                else:
                    await message.reply("Bạn cần gửi kèm nội dung hoặc file! 😐", mention_author=False)
                    return

            content = content + reply_context

            intent_cues: List[str] = []
            if self._is_identity_question(content):
                intent_cues.append(
                    "[SYSTEM NOTE: Identity intent only. Reply in 1-2 short sentences, no bullet list, no feature catalog, and do not use generic 'trained by Google/OpenAI' phrasing.]"
                )
            if self._is_capability_question(content):
                intent_cues.append(
                    "[SYSTEM NOTE: Capability intent. Provide concise but complete capability overview (4-8 bullets) based on runtime tools and assistant strengths.]"
                )
            if intent_cues:
                content = f"{content}\n\n" + "\n".join(intent_cues)

            if not message.attachments and not reply_context:
                normalized_ping = re.sub(r"[^\w\s]", " ", content.lower()).strip()
                tokens = [token for token in normalized_ping.split() if token]
                greeting_tokens = {"alo", "hi", "hello", "chào", "chao", "ping"}
                filler_tokens = {"bạn", "ban", "ơi", "oi"}
                if (
                    tokens
                    and len(tokens) <= 4
                    and all(token in greeting_tokens or token in filler_tokens for token in tokens)
                    and any(token in greeting_tokens for token in tokens)
                ):
                    await message.reply("Mình đây. Bạn cần mình hỗ trợ cụ thể gì?", mention_author=False)
                    return

            attachment_data = ""
            index_contexts: List[str] = []
            if message.attachments:
                for attachment in message.attachments:
                    filename_lower = attachment.filename.lower()

                    if filename_lower.endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp')):
                        image_url = attachment.url
                        attachment_data += f"\n[System Note: User uploaded an image. URL: {image_url}]\n"
                        self.logger.info(f"Image detected. URL passed to context: {image_url}")
                        continue

                    SUPPORTED_TEXT_EXTS = (
                        '.pdf', '.txt', '.md', '.py', '.json', '.js', '.html', '.css',
                        '.csv', '.xml', '.yaml', '.yml', '.log', '.env', '.ini', '.sh', '.bat'
                    )

                    if filename_lower.endswith(SUPPORTED_TEXT_EXTS):
                        try:
                            base_name = build_index_base_name(attachment.filename, user_id)
                            chunk_dir = os.path.join(self.file_chunk_dir, base_name)
                            index_path = os.path.join(self.file_index_dir, f"{base_name}.json")

                            file_meta = await self.file_parser.prepare_file_for_indexing(attachment, chunk_dir, base_name=base_name)
                            if not file_meta or file_meta.get("error"):
                                error_msg = file_meta.get("error") if file_meta else "empty parser response"
                                attachment_data += f"\n[System Error: Lỗi khi đọc file {attachment.filename}: {error_msg}]\n"
                                continue

                            index_data = await self.file_index_svc.build_file_index(
                                file_meta=file_meta,
                                index_path=index_path,
                                user_id=user_id,
                            )
                            validation = await self.file_index_svc.validate_file_index(index_data, user_id)
                            index_data["validation"] = validation
                            write_index_json(index_path, index_data)
                            self.file_index_svc.set_latest_index(user_id, index_path, attachment.filename)

                            if validation.get("status") == "block":
                                attachment_data += (
                                    f"\n[System Note: File index blocked for safety. Reason: "
                                    f"{validation.get('reason', '')}]\n"
                                )
                            else:
                                index_contexts.append(
                                    build_index_context(
                                        index_data, validation, content,
                                        file_parser=self.file_parser,
                                    )
                                )
                        except Exception as e:
                            self.logger.error(f"Error parsing text file: {e}")
                            attachment_data += f"\n[System Error: Không thể đọc file {attachment.filename}]\n"
                        continue

                    attachment_data += f"\n[System Note: User uploaded file '{attachment.filename}' but format is NOT supported.]\n"

            if index_contexts:
                attachment_data += "\n".join(index_contexts)

            if (not message.attachments) and should_use_last_index(content):
                last_index = self.file_index_svc.get_latest_index_for_user(user_id)
                if last_index and last_index.get("index_path"):
                    index_data = read_index_json(last_index["index_path"])
                    if index_data:
                        validation = index_data.get("validation") or await self.file_index_svc.validate_file_index(index_data, user_id)
                        if not index_data.get("validation"):
                            index_data["validation"] = validation
                            write_index_json(last_index["index_path"], index_data)

                        if validation.get("status") == "block":
                            attachment_data += (
                                "\n[System Note: Previous file index blocked for safety. "
                                f"Reason: {validation.get('reason', '')}]\n"
                            )
                        else:
                            attachment_data += build_index_context(
                                index_data, validation, content,
                                file_parser=self.file_parser,
                            )

            distinct_user_count = await self.db_repo.count_distinct_message_users_db()
            has_other_users = await self.db_repo.has_other_users_history_db(user_id)
            admin_cross_user_evidence = ""
            if is_admin:
                admin_cross_user_evidence = await self._build_admin_cross_user_evidence(message, content, user_id)

            privacy_context: Dict[str, Any] = {
                "is_admin": is_admin,
                "discord_display_name": (message.author.display_name or message.author.name or "").strip(),
                "distinct_user_count": distinct_user_count,
                "has_other_users": has_other_users,
                "admin_cross_user_evidence": admin_cross_user_evidence,
                "is_cross_user_presence_question": self._is_cross_user_presence_question(content),
            }

            history = await self.db_repo.get_user_history_from_db(user_id, limit=12)
            self.logger.info(f"Loaded chat history from DB for {user_id}: {len(history)} messages")

            messages = []
            for msg in history:
                role = "model" if msg["role"] == "assistant" else msg["role"]
                messages.append({
                    "role": role,
                    "parts": [{"text": msg["content"]}]
                })

            user_message = content + attachment_data
            messages.append({
                "role": "user",
                "parts": [{"text": user_message}]
            })

            async with message.channel.typing():
                response_text = await self.pipeline.call_gemini_api(messages, user_id, privacy_context)

            await self.db_repo.log_message_db(user_id, "user", user_message)
            await self.db_repo.log_message_db(user_id, "assistant", response_text)

            await self.send_smart_reply(message, response_text)

        except Exception as e:
            self.logger.error(f"Error processing message: {e}")
            await message.reply(f"Hệ thống đang bận, vui lòng thử lại sau! 😓", mention_author=False)

    # --- History management ---

    async def _clear_user_history(self, message: discord.Message, user_id: str):
        try:
            await self.db_repo.clear_user_data_db(user_id)
            await message.reply("✅ Đã xóa lịch sử chat!", mention_author=False)
        except Exception as e:
            self.logger.error(f"Error clearing user history: {e}")
            await message.reply("Error clearing history! 😞", mention_author=False)

    async def _clear_all_data(self, message: discord.Message, user_id: str):
        try:
            await self.db_repo.clear_all_data_db()

            await message.reply("⚠️ **ALL DATA CLEARED!** Database reset complete.", mention_author=False)
            self.logger.warning(f"Admin {user_id} cleared all database!")
        except Exception as e:
            self.logger.error(f"Error clearing all data: {e}")
            await message.reply("Error clearing data! 😞", mention_author=False)
