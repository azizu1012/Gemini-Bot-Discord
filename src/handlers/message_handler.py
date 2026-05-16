import discord
from discord.ext import commands
import asyncio
from google import genai
import time
from datetime import datetime, timedelta
from collections import defaultdict, deque
from typing import Any, Optional, Dict, List, Tuple
import json
import threading
import re
import random

from src.core.config import logger, Config
from src.core.prompt_loader import (
    get_azuris_system_prompt,
    get_lite_reasoning_prompt,
    get_fallback_system_prompt,
)
from src.core.api_router import get_api_router
from src.database.repository import DatabaseRepository
from src.services.memory_service import MemoryService
from src.services.file_parser import FileParserService
from src.managers.cleanup_manager import CleanupManager
from src.managers.cache_manager import CacheManager
from src.managers.note_manager import NoteManager
from src.managers.premium_manager import PremiumManager
from src.tools.tools import ToolsManager


REASONING_MODEL_ALIAS = "gemini-flash-lite-latest"
FINAL_MODEL_ALIAS = "gemini-flash-latest"
FALLBACK_MODEL_ALIAS = REASONING_MODEL_ALIAS


class MessageHandler:
    """Core message processing with Gemini API integration."""
    
    # ✅ Global API Request Queue (to avoid 429 - Google Gemini 20 req/min limit)
    API_REQUEST_QUEUE = asyncio.Queue()
    API_REQUEST_SEMAPHORE = asyncio.Semaphore(2)
    LAST_API_REQUEST_TIME = 0.0
    MIN_REQUEST_INTERVAL = 0.6
    COOLDOWN_WINDOW = 1800  # 30 minutes
    MAX_REQUESTS_PER_WINDOW = 15  # 15 requests per 30 minutes warning threshold
    
    def __init__(self, bot_core, config: Config):
        self.bot_core = bot_core
        self.config = config
        self.logger = logger
        self.bot = None  # Will be set via handle_message()
        self.db_repo = DatabaseRepository()
        self.memory_service = MemoryService()
        self.cache_mgr = CacheManager()
        self.note_mgr = NoteManager(self.db_repo)
        
        # Initialize FileParser with CleanupManager
        self.file_parser = FileParserService(cleanup_mgr=CleanupManager())
        self.tools_mgr = ToolsManager(note_mgr=self.note_mgr)
        self.premium_mgr = PremiumManager()
        
        # Rate limiting (per user)
        self.user_queue: Dict[str, deque] = defaultdict(deque)
        self.RATE_LIMIT_THRESHOLD = 6  # Max messages
        self.RATE_LIMIT_WINDOW = 90  # Per x seconds
        
        # --- API ROUTER (Daily Quota + global limiter) ---
        self.api_router = get_api_router()
        
        # Legacy fallback (kept for compatibility)
        self.key_status = {k: {'usage': 0, 'frozen_until': 0.0} for k in self.config.GEMINI_API_KEYS}
        self.key_lock = threading.Lock()
        self.api_key_request_history: Dict[str, List[float]] = {}
        self.api_key_history_lock = threading.Lock()
    
    def _sanitize_mentions(self, text: str) -> str:
        """Disable @mention by replacing @ with escaped \\@ to prevent pings.
        Handles: @everyone, @here, @username, <@ID>, <@&roleID>
        """
        # Replace @ with escaped @ to break mention parsing
        text = text.replace('@', '\\@')
        return text
    
    # --- HÀM MỚI: CẮT TEXT THÔNG MINH & TỰ REPLY (CHAINING) ---
    async def send_smart_reply(self, message: discord.Message, text: str):
        """
        Gửi tin nhắn dài với 3 tính năng:
        1. Cắt thông minh (Smart Split): Ưu tiên ngắt dòng (\n), rồi đến khoảng trắng.
        2. Tự Reply (Chain Reply): Tin sau reply tin trước của bot để tạo mạch.
        3. Sanitize Mentions: Loại bỏ @ từ @mention để tránh ping.
        """
        # Sanitize mentions first
        text = self._sanitize_mentions(text)
        
        limit = 1900 # Giới hạn an toàn của Discord (max 2000)
        chunks = []
        current_text = text.strip()

        # LOGIC CẮT TEXT
        while len(current_text) > limit:
            # Tìm dấu xuống dòng gần nhất trong giới hạn
            split_idx = current_text.rfind('\n', 0, limit)
            
            # Nếu không có xuống dòng, tìm dấu cách gần nhất
            if split_idx == -1:
                split_idx = current_text.rfind(' ', 0, limit)
            
            # Nếu chuỗi quá dài không có dấu cách (URL dài...), cắt cứng
            if split_idx == -1:
                split_idx = limit
            
            # Cắt đoạn
            chunk = current_text[:split_idx].strip()
            if chunk:
                chunks.append(chunk)
            
            # Cập nhật phần còn lại
            current_text = current_text[split_idx:].strip()
        
        if current_text:
            chunks.append(current_text)

        # LOGIC GỬI TIN (CHAIN REPLY)
        last_bot_message = None
        
        for i, chunk in enumerate(chunks):
            try:
                if i == 0:
                    # Tin đầu tiên: Reply vào câu hỏi của User
                    last_bot_message = await message.reply(chunk, mention_author=False)
                else:
                    # Tin tiếp theo: Reply vào tin trước đó của BOT
                    if last_bot_message:
                        last_bot_message = await last_bot_message.reply(chunk, mention_author=False)
                    else:
                        # Fallback nếu mất dấu tin trước
                        last_bot_message = await message.channel.send(chunk)
                
                # Delay nhẹ để Discord load kịp, tránh loạn thứ tự
                if i < len(chunks) - 1:
                    await asyncio.sleep(1.0)
                    
            except Exception as e:
                self.logger.error(f"Lỗi khi gửi chunk {i}: {e}")

    async def handle_message(self, message: discord.Message, bot: commands.Bot):
            """Main message handler - FIXED FOR DUPLICATE & LOOP"""
            try:
                # Store bot instance for use in other methods
                self.bot = bot
                
                # ✅ 1. CHỐT CHẶN: Bỏ qua tin nhắn từ BOT (Bao gồm chính nó)
                if message.author.bot:
                    return
                
                user_id = str(message.author.id)
                is_admin = user_id in self.config.ADMIN_USER_IDS
                is_premium = self.premium_mgr.is_premium_user(user_id)
                
                # ✅ 2. XÁC ĐỊNH NGỮ CẢNH: Chỉ xử lý nếu được TAG hoặc DM
                is_dm = isinstance(message.channel, discord.DMChannel)
                is_mentioned = self.bot.user in message.mentions
                
                if not is_dm and not is_mentioned:
                    return 

                # ✅ 3. CHECK RATE LIMIT (Per User)
                if not is_admin and not is_premium:
                    now = datetime.now()
                    self.user_queue[user_id].append(now)
                    while self.user_queue[user_id] and self.user_queue[user_id][0] < now - timedelta(seconds=self.RATE_LIMIT_WINDOW):
                        self.user_queue[user_id].popleft()
                    
                    if len(self.user_queue[user_id]) > self.RATE_LIMIT_THRESHOLD:
                        await message.add_reaction("⏳") 
                        return

                # ✅ 4. LOGIC RESET DATA (Xử lý xác nhận Reset)
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

                # ✅ 5. PHÂN LUỒNG XỬ LÝ (CHỈ CHẠY 1 TRONG 2)
                # Không được để lặp lại check is_dm/is_mentioned ở dưới nữa
                if is_dm:
                    await self._handle_dm(message)
                else:
                    await self._handle_mention(message)
            
            except Exception as e:
                self.logger.error(f"Error in handle_message: {e}")
    
    async def _handle_dm(self, message: discord.Message):
        """Handle direct messages."""
        user_id = str(message.author.id)
        
        # Check if user allowed (Premium or Admin)
        premium = self.premium_mgr.is_premium_user(user_id)
        if not premium and user_id not in self.config.ADMIN_USER_IDS:
            await message.reply("You do not have access to DM mode. 😔", mention_author=False)
            return
        
        await self._process_message_with_gemini(message, is_dm=True)
    
    async def _handle_mention(self, message: discord.Message):
        """Handle mentions in channels."""
        await self._process_message_with_gemini(message, is_dm=False)
    
    async def _process_message_with_gemini(self, message: discord.Message, is_dm: bool = False):
        """Process message with Gemini API."""
        user_id = str(message.author.id)
        
        try:
            # 1. Clean content (CHỈ XÓA TAG CỦA BOT, CLEAN MENTION)
            content = message.content.strip()
            
            # Step 1a: Xóa bot mention trước (cả format <@ID> và <@!ID>)
            bot_mention = f"<@{self.bot.user.id}>"
            bot_mention_mobile = f"<@!{self.bot.user.id}>"
            content = content.replace(bot_mention, "").replace(bot_mention_mobile, "")
            
            # Step 1b: Convert user mentions to readable format FIRST (before removing @)
            if message.mentions:
                for mention in message.mentions:
                    if mention.id != self.bot.user.id:  # Skip bot itself
                        # Replace mention IDs with user display name (for context)
                        content = content.replace(f"<@{mention.id}>", mention.display_name)
                        content = content.replace(f"<@!{mention.id}>", mention.display_name)
            
            # Step 1c: Xóa ký tự @ từ text bình thường (bot tự hiểu tên)
            # Remove @ symbol but keep the names - bot understands naturally
            content = content.replace('@', '')  # Remove @ symbol
            content = re.sub(r'\s+', ' ', content).strip()  # Normalize spaces
            
            content = content.strip()
            
            # 2. Handle Reply Context (Smart Reply)
            reply_context = ""
            if not is_dm and message.reference:
                try:
                    reference_id = message.reference.message_id
                    if reference_id is None:
                        raise ValueError("Missing reply message id")
                    replied_msg = await message.channel.fetch_message(reference_id)
                    replied_content = replied_msg.content
                    
                    # Add info about attachments in replied message
                    if replied_msg.attachments:
                        replied_content += f" [Kèm {len(replied_msg.attachments)} đính kèm: {[a.url for a in replied_msg.attachments]}]"
                    
                    reply_context = (
                        f"\n\n[SYSTEM CONTEXT: User is replying to a message from '{replied_msg.author.display_name}']\n"
                        f"[Replied Message Content]: \"{replied_content}\"\n"
                    )
                except Exception as e:
                    self.logger.warning(f"Failed to fetch replied message: {e}")

            # 3. Handle Empty Content / Only Tag
            if not content:
                if message.attachments:
                    pass # Has attachments, allowed
                elif reply_context:
                    content = "Hãy phân tích tin nhắn tôi vừa reply." # Default prompt for reply
                elif not is_dm and message.guild.me in message.mentions:
                    content = "Xin chào Chad Gibiti" # Default greeting
                else:
                    await message.reply("Bạn cần gửi kèm nội dung hoặc file! 😐", mention_author=False)
                    return
            
            # Merge context
            content = content + reply_context

            # Fast path for low-information ping messages to avoid unnecessary quota burn
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

            # 4. Handle Attachments (Images vs Files)
            attachment_data = ""
            if message.attachments:
                for attachment in message.attachments:
                    filename_lower = attachment.filename.lower()
                    
                    # CASE A: IMAGE (Get URL for HuggingFace)
                    if filename_lower.endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp')):
                        image_url = attachment.url
                        attachment_data += f"\n[System Note: User uploaded an image. URL: {image_url}]\n"
                        self.logger.info(f"Image detected. URL passed to context: {image_url}")
                        continue

                    # CASE B: TEXT/CODE FILES (Parse content)
                    SUPPORTED_TEXT_EXTS = (
                        '.pdf', '.txt', '.md', '.py', '.json', '.js', '.html', '.css', 
                        '.csv', '.xml', '.yaml', '.yml', '.log', '.env', '.ini', '.sh', '.bat'
                    )

                    if filename_lower.endswith(SUPPORTED_TEXT_EXTS):
                        try:
                            parsed = await self.file_parser.parse_attachment(attachment)
                            if not parsed:
                                attachment_data += f"\n[System Error: Lỗi khi đọc file {attachment.filename}: empty parser response]\n"
                            elif "error" in parsed:
                                attachment_data += f"\n[System Error: Lỗi khi đọc file {attachment.filename}: {parsed.get('error')}]\n"
                            else:
                                attachment_data += f"\n[File Content: {parsed['filename']}]\n{parsed['content']}\n"
                        except Exception as e:
                            self.logger.error(f"Error parsing text file: {e}")
                            attachment_data += f"\n[System Error: Không thể đọc file {attachment.filename}]\n"
                        continue

                    # CASE C: UNSUPPORTED
                    attachment_data += f"\n[System Note: User uploaded file '{attachment.filename}' but format is NOT supported.]\n"
            
            # 5. Build History & Messages (DB-first)
            history = await self.db_repo.get_user_history_from_db(user_id, limit=12)
            messages = []
            for msg in history:
                role = "model" if msg["role"] == "assistant" else msg["role"]
                messages.append({
                    "role": role,
                    "parts": [{"text": msg["content"]}]
                })
            
            # Add current message
            user_message = content + attachment_data
            messages.append({
                "role": "user",
                "parts": [{"text": user_message}]
            })
            
            # 6. Call API (With Typing Indicator)
            async with message.channel.typing():
                response_text = await self._call_gemini_api(messages, user_id)
            
            # 7. Log to DB (DB-first memory source)
            await self.db_repo.log_message_db(user_id, "user", user_message)
            await self.db_repo.log_message_db(user_id, "assistant", response_text)
            
            # 8. Send Response (Smart Chunking & Chain Reply)
            await self.send_smart_reply(message, response_text)
        
        except Exception as e:
            self.logger.error(f"Error processing message: {e}")
            await message.reply(f"Hệ thống đang bận, vui lòng thử lại sau! 😓", mention_author=False)

    # --- SMART KEY MANAGEMENT METHODS ---
    
    def _get_best_api_key(self, preferred_model_alias: Optional[str] = None) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[Dict[str, str]]]:
        """
        Get best API key + provider model id, optionally forcing a specific model alias.

        Returns:
            Tuple[api_key, model_id, model_alias, reservation_meta]
        """
        if preferred_model_alias:
            reservation = self.api_router.get_next_key_for_model_reservation(preferred_model_alias)
        else:
            reservation = self.api_router.get_next_key_reservation()

        if reservation:
            api_key = reservation.get("key")
            model_alias = reservation.get("model_alias")
            if api_key and model_alias:
                return api_key, self.api_router.get_model_id(model_alias), model_alias, reservation

        # Fallback to legacy method
        self.logger.warning("⚠️ Router exhausted, trying legacy key selection...")
        with self.key_lock:
            now = time.time()
            active_keys = [k for k, v in self.key_status.items() if v['frozen_until'] < now]

            if not active_keys:
                self.logger.error("ALL API KEYS ARE FROZEN!")
                return None, None, None, None

            min_usage = min(self.key_status[k]['usage'] for k in active_keys)
            best_candidates = [k for k in active_keys if self.key_status[k]['usage'] == min_usage]

            chosen_key = random.choice(best_candidates)
            self.key_status[chosen_key]['usage'] += 1
            fallback_alias = preferred_model_alias or self.api_router.get_preferred_model()
            legacy_reservation = {
                "key": chosen_key,
                "model_alias": fallback_alias,
                "pool": "legacy",
                "counter_key": chosen_key,
            }
            return chosen_key, self.api_router.get_model_id(fallback_alias), fallback_alias, legacy_reservation

    def _mark_key_as_failed(
        self,
        key: str,
        model_alias: Optional[str] = None,
        duration: int = 60,
        reason: str = "rate_limit",
        permanently_exhaust: bool = False,
        reservation: Optional[Dict[str, str]] = None,
    ):
        """Mark key as failed using router cooldown/exhaust policies."""
        model = model_alias or self.api_router.get_current_model()
        pool = (reservation or {}).get("pool", "main")
        counter_key = (reservation or {}).get("counter_key")

        if pool != "legacy":
            if permanently_exhaust:
                self.api_router.mark_key_exhausted(key, model, pool=pool, counter_key=counter_key)
            else:
                self.api_router.mark_key_cooldown(key, model, duration, pool=pool, counter_key=counter_key)

        with self.key_lock:
            if key in self.key_status:
                self.key_status[key]['frozen_until'] = time.time() + duration

        if reason == "invalid_key":
            self.logger.warning(f"🚫 API Key ...{key[-4:]} marked invalid and excluded for current quota cycle.")
        else:
            self.logger.warning(f"❄️ API Key ...{key[-4:]} frozen for {duration}s due to rate limit/quota.")

    def _commit_selected_key(self, reservation: Optional[Dict[str, str]]) -> None:
        if not reservation:
            return
        if reservation.get("pool") == "legacy":
            return
        self.api_router.commit_key_usage(reservation)

    def _is_rate_limit_error(self, error_str: str) -> bool:
        lowered = (error_str or "").lower()
        return any(token in lowered for token in [
            "429",
            "quota",
            "resource exhausted",
            "resource_exhausted",
            "rate limit",
            "503",
            "unavailable",
            "service unavailable",
            "overloaded",
        ])

    def _is_unavailable_error(self, error_str: str) -> bool:
        lowered = (error_str or "").lower()
        return any(token in lowered for token in [
            "503",
            "unavailable",
            "service unavailable",
            "overloaded",
        ])

    def _is_invalid_key_error(self, error_str: str) -> bool:
        lowered = (error_str or "").lower()
        strict_invalid_markers = [
            "api_key_invalid",
            "api key invalid",
            "invalid api key",
            "api key not found",
            "key not found",
            "invalid argument: api key",
            "provided api key is invalid",
        ]
        return any(token in lowered for token in strict_invalid_markers)


    async def _throttle_api_request(self, api_key: str) -> None:
        """
        ✅ Throttle API requests (Throttling logic from original code).
        Ensures minimum delay between requests and warns on rate limits.
        """
        async with self.API_REQUEST_SEMAPHORE:
            current_time = time.time()
            time_since_last = current_time - self.LAST_API_REQUEST_TIME
            
            if time_since_last < self.MIN_REQUEST_INTERVAL:
                sleep_duration = self.MIN_REQUEST_INTERVAL - time_since_last
                # self.logger.debug(f"API Throttling: waiting {sleep_duration:.1f}s")
                await asyncio.sleep(sleep_duration)
            
            self.LAST_API_REQUEST_TIME = time.time()
            
            # Track usage history for rate limit warnings
            with self.api_key_history_lock:
                now = time.time()
                if api_key not in self.api_key_request_history:
                    self.api_key_request_history[api_key] = []
                
                self.api_key_request_history[api_key].append(now)
                
                # Cleanup old history
                self.api_key_request_history[api_key] = [
                    ts for ts in self.api_key_request_history[api_key]
                    if now - ts < self.COOLDOWN_WINDOW
                ]
                
                # Warn if limit approaching
                if len(self.api_key_request_history[api_key]) > self.MAX_REQUESTS_PER_WINDOW:
                    self.logger.debug(
                        f"Key ...{api_key[-4:]} usage high: {len(self.api_key_request_history[api_key])}/{self.MAX_REQUESTS_PER_WINDOW} in 30m."
                    )

    def _flatten_prompt_text(self, messages: List[Dict[str, Any]]) -> str:
        chunks: List[str] = []
        for msg in messages:
            parts = msg.get("parts", [])
            for part in parts:
                text = part.get("text") if isinstance(part, dict) else None
                if text:
                    chunks.append(text)
        return "\n".join(chunks)

    def _prepare_user_input_block(self, user_input: str, max_chars: int = 2200) -> str:
        text = (user_input or "").strip()
        if len(text) <= max_chars:
            return text
        remaining = len(text) - max_chars
        return f"{text[:max_chars]}\n...[truncated {remaining} chars to fit context]"

    def _is_tool_result_sufficient(self, tool_results: str) -> bool:
        if not tool_results:
            return False

        lower = tool_results.lower()
        marker_groups = [
            ["top ranked sources", "required quality sources", "quality sources found"],
            ["top trusted sources", "required reputable sources", "reputable sources found"],
        ]
        if not any(all(marker in lower for marker in group) for group in marker_groups):
            return False

        req_matches = [
            int(v)
            for v in re.findall(r"required (?:quality|reputable) sources:\s*(\d+)", lower)
        ]
        found_matches = [
            int(v)
            for v in re.findall(r"(?:quality|reputable) sources found:\s*(\d+)", lower)
        ]
        if not req_matches or not found_matches:
            return False

        required = req_matches[-1]
        found = found_matches[-1]
        return found >= required and "chưa đủ nguồn chất lượng" not in lower and "chưa đủ nguồn uy tín" not in lower

    def _has_minimum_search_evidence(self, tool_results: str) -> bool:
        if not tool_results:
            return False

        lower = tool_results.lower()
        found_matches = [
            int(v)
            for v in re.findall(r"(?:quality|reputable) sources found:\s*(\d+)", lower)
        ]
        if found_matches and found_matches[-1] >= 1:
            return True

        if "additional corroborating sources:" in lower and "(không có nguồn bổ sung)" not in lower:
            return True

        return False

    def _build_fallback_system_prompt(self, user_input: str, reasoning_result: str, tool_results: str) -> str:
        prompt_template = get_fallback_system_prompt()
        prompt_text = prompt_template.replace("[USER_INPUT_HERE]", user_input.strip())
        prompt_text = prompt_text.replace("[REASONING_OUTPUT_HERE]", reasoning_result.strip())
        prompt_text = prompt_text.replace(
            "[TOOL_RESULTS_HERE]",
            tool_results.strip() if tool_results else "(Không có tool được gọi)",
        )
        return prompt_text

    async def _acquire_gemini_quota(
        self,
        messages: List[Dict[str, Any]],
        max_output_tokens: int,
        model_alias: Optional[str] = None,
        extra_text: str = "",
    ) -> bool:
        prompt_text = self._flatten_prompt_text(messages)
        if extra_text:
            prompt_text = f"{extra_text}\n{prompt_text}" if prompt_text else extra_text
        target_model = model_alias or self.api_router.get_preferred_model()
        return await self.api_router.acquire_gemini_quota(prompt_text, max_output_tokens, target_model)

    async def _generate_gemini_content(
        self,
        api_key: str,
        model_name: str,
        system_instruction: str,
        generation_config: Dict[str, Any],
        messages: List[Dict[str, Any]],
        tools: Optional[List[Any]] = None,
    ):
        request_config = dict(generation_config)
        request_config["system_instruction"] = system_instruction
        request_config["safety_settings"] = self.config.SAFETY_SETTINGS
        if tools:
            request_config["tools"] = tools

        client = genai.Client(api_key=api_key)
        return await asyncio.to_thread(
            client.models.generate_content,
            model=model_name,
            contents=messages,
            config=request_config,
        )

    async def _call_gemini_api(self, messages: List[Dict[str, Any]], user_id: str) -> str:
        """Two-Tier Model Strategy: Flash-Lite (reasoning) → Flash (final output).

        If Flash fails (429), fallback to Lite model with 3-block context + fallback prompt.
        """

        # TIER 1: Use Flash-Lite for reasoning loops + tool calls
        reasoning_result, tool_results = await self._call_gemini_reasoning_loop(messages, user_id)

        # Optional extra retrieval pass when evidence is weak
        if tool_results and not self._is_tool_result_sufficient(tool_results):
            partial_ok = self.config.SEARCH_ALLOW_PARTIAL_ANSWER and self._has_minimum_search_evidence(tool_results)
            if self.config.SEARCH_ENABLE_EXTRA_RETRIEVAL_PASS and not partial_ok:
                self.logger.info(f"Evidence insufficient for {user_id}. Running one additional retrieval pass.")
                followup_messages = [msg.copy() for msg in messages]
                followup_messages.append({
                    "role": "user",
                    "parts": [{"text": "Continue current request. Retrieve missing evidence with one focused web_search, prioritize authoritative/official sources, compare claims, and avoid asking user for extra links. Use [FORCE FALLBACK] only if needed."}],
                })

                retry_reasoning, retry_tool_results = await self._call_gemini_reasoning_loop(followup_messages, user_id)
                if retry_reasoning and retry_reasoning not in {"Reasoning completed", "Reasoning loop failed"}:
                    reasoning_result = retry_reasoning
                if retry_tool_results:
                    tool_results = f"{tool_results}\n\n[RETRY PASS]\n{retry_tool_results}" if tool_results else retry_tool_results
            else:
                self.logger.info(
                    f"Evidence below strict threshold for {user_id}, continuing with partial evidence mode={self.config.SEARCH_ALLOW_PARTIAL_ANSWER}."
                )

        # TIER 2: Use Flash for final output (with reasoning context, no thinking needed)
        final_output = await self._call_gemini_final(messages, reasoning_result, tool_results, user_id)

        return final_output
    
    async def _call_gemini_reasoning_loop(self, messages: List[Dict[str, Any]], user_id: str) -> Tuple[str, str]:
        """TIER 1: Flash-Lite model for reasoning loops and tool calls.

        Returns:
            tuple: (reasoning_output: str, tool_results: str)
        """
        MAX_RETRIES = self.config.REASONING_MAX_API_RETRIES
        reasoning_model_alias = REASONING_MODEL_ALIAS

        tools = self.tools_mgr.get_all_tools()
        generation_config = {
            "temperature": 0.35,
            "top_p": 0.9,
            "top_k": 40,
            "max_output_tokens": 2600,
        }

        reasoning_messages = [msg.copy() for msg in messages]
        tool_results_list: List[str] = []
        web_search_calls = 0
        iteration = 0

        for attempt in range(MAX_RETRIES):
            api_key: Optional[str] = None
            used_model_alias: Optional[str] = None
            key_reservation: Optional[Dict[str, str]] = None

            try:
                current_time_str = datetime.now().strftime("%A, %d/%m/%Y %H:%M")
                time_context = f"Current time: {current_time_str}\n"
                system_instruction = time_context + get_lite_reasoning_prompt()

                while iteration < self.config.REASONING_MAX_LOOPS:
                    iteration += 1
                    quota_ok = await self._acquire_gemini_quota(
                        reasoning_messages,
                        generation_config["max_output_tokens"],
                        reasoning_model_alias,
                        extra_text=system_instruction,
                    )
                    if not quota_ok:
                        return ("API busy, please retry shortly.", "")

                    api_key, model_name, used_model_alias, key_reservation = self._get_best_api_key(reasoning_model_alias)
                    if not api_key or not model_name:
                        return ("API unavailable, please retry shortly.", "")

                    self.logger.info(f"Reasoning loop {iteration} for user {user_id} ({model_name})")
                    await self._throttle_api_request(api_key)

                    response = await self._generate_gemini_content(
                        api_key=api_key,
                        model_name=model_name,
                        system_instruction=system_instruction,
                        generation_config=generation_config,
                        messages=reasoning_messages,
                        tools=tools,
                    )
                    self._commit_selected_key(key_reservation)

                    candidate = response.candidates[0] if response.candidates else None
                    if not (candidate and candidate.content and candidate.content.parts):
                        break
                    
                    part = candidate.content.parts[0]
                    
                    # Handle tool calls during reasoning
                    if part.function_call and part.function_call.name:
                        fc = part.function_call
                        tool_name = (fc.name or "").lower()
                        args = dict(fc.args) if fc.args else {}
                        self.logger.debug(f"Reasoning tool: {fc.name} args={args}")

                        if tool_name == "web_search" and web_search_calls >= 1:
                            budget_msg = "Search budget reached for this turn. Keep the current evidence and continue with cautious synthesis; do not request extra links from user."
                            reasoning_messages.append({"role": "model", "parts": [part]})
                            reasoning_messages.append({
                                "role": "function",
                                "parts": [{"function_response": {"name": "web_search", "response": {"content": budget_msg}}}],
                            })
                            continue

                        tool_res = await self.tools_mgr.call_tool(fc, user_id)
                        if tool_name == "web_search":
                            web_search_calls += 1
                            intent_query = (args.get("query") or "").strip()
                            tool_results_list.append(f"[{fc.name}|intent={intent_query}] {tool_res}")
                        else:
                            tool_results_list.append(f"[{fc.name}] {tool_res}")

                        reasoning_messages.append({"role": "model", "parts": [part]})
                        reasoning_messages.append({
                            "role": "function",
                            "parts": [{"function_response": {"name": fc.name, "response": {"content": str(tool_res)}}}]
                        })
                        continue
                    
                    # Text response = reasoning complete
                    elif part.text:
                        text = part.text.strip()
                        
                        # Parse text for tool calls in multiple formats:
                        # 1. Direct: calculate(equation='...')
                        # 2. In <tool_code>: <tool_code>print(calculate(...))</tool_code>
                        # 3. In markdown: ```calculate(...) ```
                        
                        # Strict fallback parser: only parse explicit tool_code or TOOL_CALL marker
                        tool_code_match = re.search(r'<tool_code>(.*?)</tool_code>', text, re.IGNORECASE | re.DOTALL)
                        tool_matches = []
                        if tool_code_match:
                            tool_code_content = tool_code_match.group(1)
                            tool_matches = re.findall(r'(web_search|calculate|get_weather|image_recognition|save_note|retrieve_notes)\s*\(\s*([^)]+)\)', tool_code_content, re.IGNORECASE)
                        elif text.strip().upper().startswith("TOOL_CALL:"):
                            tool_matches = re.findall(r'(web_search|calculate|get_weather|image_recognition|save_note|retrieve_notes)\s*\(\s*([^)]+)\)', text, re.IGNORECASE)
                        
                        if tool_matches:
                            # Found tool mentions in text - extract and call them
                            executed_tool = False
                            for tool_name, args_str in tool_matches:
                                self.logger.debug(f"Detected tool in text: {tool_name}({args_str})")
                                args_dict = {}
                                for arg_match in re.finditer(r'(\w+)\s*=\s*["\']([^"\']+)["\']', args_str):
                                    key, value = arg_match.groups()
                                    args_dict[key] = value

                                if not args_dict:
                                    continue

                                tool_name_l = tool_name.lower()
                                if tool_name_l == "web_search" and not args_dict.get("query"):
                                    continue

                                # Enforce one web search call per turn
                                if tool_name_l == "web_search" and web_search_calls >= 1:
                                    budget_msg = "Search budget reached for this turn. Keep the current evidence and continue with cautious synthesis; do not request extra links from user."
                                    reasoning_messages.append({"role": "model", "parts": [{"text": text}]})
                                    reasoning_messages.append({
                                        "role": "function",
                                        "parts": [{"function_response": {"name": "web_search", "response": {"content": budget_msg}}}]
                                    })
                                    executed_tool = True
                                    break

                                class FakeFunctionCall:
                                    def __init__(self, name, args):
                                        self.name = name
                                        self.args = args

                                fc = FakeFunctionCall(tool_name_l, args_dict)
                                tool_res = await self.tools_mgr.call_tool(fc, user_id)
                                if tool_name_l == "web_search":
                                    web_search_calls += 1
                                    intent_query = (args_dict.get("query") or "").strip()
                                    tool_results_list.append(f"[{tool_name_l}|intent={intent_query}] {tool_res}")
                                else:
                                    tool_results_list.append(f"[{tool_name_l}] {tool_res}")

                                reasoning_messages.append({"role": "model", "parts": [{"text": text}]})
                                reasoning_messages.append({
                                    "role": "function",
                                    "parts": [{"function_response": {"name": tool_name_l, "response": {"content": str(tool_res)}}}]
                                })
                                executed_tool = True
                                break

                            if executed_tool:
                                continue
                        
                        # No tools found - reasoning complete
                        if text and len(text) > 3:
                            tool_results_str = "\n".join(tool_results_list) if tool_results_list else ""
                            return (text, tool_results_str)
                        break
                    
                    break
                
                tool_results_str = "\n".join(tool_results_list) if tool_results_list else ""
                return ("Reasoning completed", tool_results_str)
                
            except Exception as e:
                error_str = str(e)

                if self._is_invalid_key_error(error_str):
                    if api_key:
                        self._mark_key_as_failed(
                            api_key,
                            used_model_alias,
                            duration=86400,
                            reason="invalid_key",
                            permanently_exhaust=True,
                            reservation=key_reservation,
                        )
                    self.logger.warning("Lite model received invalid API key error. Rotating key immediately.")
                    continue

                if self._is_rate_limit_error(error_str):
                    error_type = "unavailable" if self._is_unavailable_error(error_str) else "rate_limit"
                    wait_time = 2 + (attempt * 2)

                    if api_key:
                        self.logger.warning(
                            f"⚠️ Lite Key ...{api_key[-4:]} {error_type}. Retrying with preserved reasoning state "
                            f"(attempt {attempt + 1}/{MAX_RETRIES})."
                        )
                        self._mark_key_as_failed(api_key, used_model_alias, duration=60, reason=error_type, reservation=key_reservation)
                    else:
                        self.logger.warning(
                            f"⚠️ Lite transient {error_type} without selected key. Retrying with preserved reasoning state "
                            f"(attempt {attempt + 1}/{MAX_RETRIES})."
                        )

                    self.logger.info(
                        f"Reasoning state preserved: messages={len(reasoning_messages)} "
                        f"tool_results={len(tool_results_list)} web_search_calls={web_search_calls}"
                    )
                    self.logger.info(f"⏱️ Reasoning retry backoff {wait_time}s ({error_type}).")
                    await asyncio.sleep(wait_time)
                    continue

                self.logger.error(f"Lite model error (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
                await asyncio.sleep(1 + attempt)
                continue
        
        tool_results_str = "\n".join(tool_results_list) if tool_results_list else ""
        return "Reasoning loop failed", tool_results_str
    
    async def _call_gemini_final(self, original_messages: List[Dict[str, Any]], reasoning_result: str, tool_results: str, user_id: str) -> str:
        """TIER 2: Flash model for final output (uses reasoning from tier 1).
        
        Handles 429 with:
        1. Wait + Retry (up to 5 times)
        2. Fallback: Use Lite model with 3-block context + fallback prompt
        
        Args:
            original_messages: Original user messages
            reasoning_result: Output from tier 1 reasoning
            tool_results: Formatted results from tools called in tier 1
            user_id: User ID for logging
        """
        MAX_RETRIES = self.config.FINAL_MAX_API_RETRIES
        final_model_alias = FINAL_MODEL_ALIAS

        if tool_results and not self._is_tool_result_sufficient(tool_results):
            if self.config.SEARCH_ALLOW_PARTIAL_ANSWER and self._has_minimum_search_evidence(tool_results):
                self.logger.info(f"Using partial evidence response mode for user {user_id}.")
                reasoning_result = (
                    (reasoning_result or "")
                    + "\n\n[PARTIAL_EVIDENCE_MODE]\n"
                    "Evidence is below strict trust threshold, but enough signals exist to provide a cautious answer. "
                    "Respond with uncertainty markers and suggest official verification link for final confirmation."
                ).strip()
            else:
                self.logger.info(f"Evidence still limited for {user_id}; auto-switching to strict uncertainty response mode.")
                reasoning_result = (
                    (reasoning_result or "")
                    + "\n\n[AUTO_RETRIEVAL_LIMIT_REACHED]\n"
                    "Evidence remains below strict threshold after automatic retrieval. "
                    "Respond with uncertainty markers, provide the best supported comparison from current sources, "
                    "and avoid requesting additional links from user."
                ).strip()

        for attempt in range(MAX_RETRIES):
            api_key: Optional[str] = None
            model_name: Optional[str] = None
            used_model_alias: Optional[str] = None
            key_reservation: Optional[Dict[str, str]] = None

            try:
                
                current_time_str = datetime.now().strftime("%A, %d/%m/%Y %H:%M")
                time_context = f"SYSTEM ALERT: Current Date/Time is {current_time_str}.\n\n"
                
                # Extract raw user input for 3-block template
                user_input = ""
                if original_messages and original_messages[-1].get("role") == "user":
                    user_input = original_messages[-1].get("parts", [{}])[0].get("text", "")
                
                user_input_block = self._prepare_user_input_block(user_input)

                # Format 3-block context for injection
                three_block_context = f"""
=== CONTEXT FROM PRELIMINARY ANALYSIS ===
[BLOCK 1 - USER REQUEST]
{user_input_block}

[BLOCK 2 - REASONING OUTPUT]
{reasoning_result}

[BLOCK 3 - TOOL RESULTS]
{tool_results if tool_results else "(No tools were called)"}

=== YOUR TASK ===
Synthesize the above 3 blocks into a final response. Integrate naturally without saying "Based on tool results..." or mentioning technical details. Use your personality.
"""
                
                # Inject 3-block into system prompt
                system_with_context = (
                    time_context + get_azuris_system_prompt() +
                    three_block_context
                )
                
                generation_config = {
                    "temperature": 0.7,
                    "top_p": 0.9,
                    "top_k": 40,
                    "max_output_tokens": 2600,
                }
                
                # Create final messages: user asks model to synthesize
                final_messages = [{
                    "role": "user",
                    "parts": [{"text": "Dựa vào 3 block context ở trên, hãy đưa ra câu trả lời hoàn chỉnh cho yêu cầu của user."}]
                }]

                quota_ok = await self._acquire_gemini_quota(
                    final_messages,
                    generation_config["max_output_tokens"],
                    final_model_alias,
                    extra_text=system_with_context,
                )
                if not quota_ok:
                    self.logger.warning("Final model quota gate blocked; trying lite fallback finalizer.")
                    return await self._fallback_lite_as_flash(original_messages, reasoning_result, tool_results, user_id)

                api_key, model_name, used_model_alias, key_reservation = self._get_best_api_key(final_model_alias)
                if not api_key or not model_name:
                    self.logger.warning(f"⚠️ ALL KEYS FROZEN - Fallback to lite model for user {user_id}")
                    return await self._fallback_lite_as_flash(original_messages, reasoning_result, tool_results, user_id)

                await self._throttle_api_request(api_key)

                self.logger.info(f"Final output for user {user_id} ({model_name}, attempt {attempt + 1}/{MAX_RETRIES})")

                response = await self._generate_gemini_content(
                    api_key=api_key,
                    model_name=model_name,
                    system_instruction=system_with_context,
                    generation_config=generation_config,
                    messages=final_messages,
                )
                self._commit_selected_key(key_reservation)

                candidate = response.candidates[0] if response.candidates else None
                if not (candidate and candidate.content and candidate.content.parts):
                    return "No final response"
                
                part = candidate.content.parts[0]
                
                # Extract final text (no tools called at tier 2)
                if part.text:
                    text = part.text.strip()
                    
                    # Clean any leftover thinking/reasoning artifacts and tool blocks
                    text = re.sub(r'<THINKING>.*?</THINKING>', '', text, flags=re.IGNORECASE | re.DOTALL).strip()
                    text = re.sub(r'^THINKING\s*\n(.*?)(?=\n[A-Z]|\n\n|$)', '', text, flags=re.MULTILINE | re.IGNORECASE | re.DOTALL).strip()
                    text = re.sub(r'^\[REASONING CONTEXT:.*?\]', '', text, flags=re.MULTILINE | re.DOTALL).strip()
                    # Remove <tool_code> blocks - should never show to user
                    text = re.sub(r'<tool_code>.*?</tool_code>', '', text, flags=re.IGNORECASE | re.DOTALL).strip()
                    # Remove <tool_result> blocks - internal tool results should not be shown
                    text = re.sub(r'<tool_result>.*?</tool_result>', '', text, flags=re.IGNORECASE | re.DOTALL).strip()
                    # Also remove markdown code blocks with tool calls
                    text = re.sub(r'```(python|javascript|js|py)?\s*(web_search|calculate|get_weather|image_recognition|save_note|retrieve_notes).*?```', '', text, flags=re.IGNORECASE | re.DOTALL).strip()
                    
                    if text and len(text) > 5:
                        return text
                
                return "Empty final response"
                
            except Exception as e:
                error_str = str(e)

                if self._is_invalid_key_error(error_str):
                    if api_key:
                        self._mark_key_as_failed(
                            api_key,
                            used_model_alias,
                            duration=86400,
                            reason="invalid_key",
                            permanently_exhaust=True,
                            reservation=key_reservation,
                        )
                    self.logger.warning(f"⚠️ Flash model invalid key on attempt {attempt + 1}/{MAX_RETRIES}; rotating immediately.")
                    continue

                if self._is_rate_limit_error(error_str):
                    error_type = "unavailable" if self._is_unavailable_error(error_str) else "rate_limit"
                    if api_key:
                        self.logger.warning(
                            f"⚠️ Flash Key ...{api_key[-4:]} {error_type}. Attempt {attempt + 1}/{MAX_RETRIES}"
                        )
                        self._mark_key_as_failed(api_key, used_model_alias, duration=60, reason=error_type, reservation=key_reservation)

                    wait_time = 2 + (attempt * 2)
                    self.logger.info(f"⏱️ Waiting {wait_time}s before retry ({error_type})...")
                    await asyncio.sleep(wait_time)

                    if attempt == MAX_RETRIES - 1:
                        self.logger.warning(f"❌ Flash model exhausted ({MAX_RETRIES} retries). Fallback to lite model for {user_id}")
                        return await self._fallback_lite_as_flash(original_messages, reasoning_result, tool_results, user_id)

                    continue

                self.logger.error(f"Final model error: {e}")
                continue
        
        # Fallback if all retries exhausted
        self.logger.warning(f"❌ Final output completely failed. Using fallback lite model for {user_id}")
        return await self._fallback_lite_as_flash(original_messages, reasoning_result, tool_results, user_id)
    
    async def _fallback_lite_as_flash(self, original_messages: List[Dict[str, Any]], reasoning_result: str, tool_results: str, user_id: str) -> str:
        """Fallback: Use Lite model as Flash when Flash fails (429).
        
        Lite receives 3-block context + fallback prompt to produce final output.
        This ensures users always get a response, even under heavy API load.
        """
        MAX_RETRIES = self.config.FALLBACK_MAX_API_RETRIES
        fallback_model_alias = FALLBACK_MODEL_ALIAS

        for attempt in range(MAX_RETRIES):
            api_key: Optional[str] = None
            model_name: Optional[str] = None
            used_model_alias: Optional[str] = None
            key_reservation: Optional[Dict[str, str]] = None

            try:
                
                # Extract raw user input for context
                user_input = ""
                if original_messages and original_messages[-1].get("role") == "user":
                    user_input = original_messages[-1].get("parts", [{}])[0].get("text", "")
                
                current_time_str = datetime.now().strftime("%A, %d/%m/%Y %H:%M")
                time_context = f"SYSTEM ALERT: Current Date/Time is {current_time_str}.\n\n"
                user_input_block = self._prepare_user_input_block(user_input)
                system_with_context = time_context + self._build_fallback_system_prompt(
                    user_input_block,
                    reasoning_result,
                    tool_results,
                )
                
                generation_config = {
                    "temperature": 0.7,
                    "top_p": 0.9,
                    "top_k": 40,
                    "max_output_tokens": 2600,
                }
                
                final_messages = [{
                    "role": "user",
                    "parts": [{"text": "Dựa vào 3 block context ở trên, hãy đưa ra câu trả lời hoàn chỉnh cho yêu cầu của user."}],
                }]

                quota_ok = await self._acquire_gemini_quota(
                    final_messages,
                    generation_config["max_output_tokens"],
                    fallback_model_alias,
                    extra_text=system_with_context,
                )
                if not quota_ok:
                    return "[System] API is busy right now, please try again shortly."

                api_key, model_name, used_model_alias, key_reservation = self._get_best_api_key(fallback_model_alias)
                if not api_key or not model_name:
                    return "[System] API overloaded, please try again later."

                await self._throttle_api_request(api_key)

                self.logger.info(f"Fallback: Using {model_name} for {user_id} (attempt {attempt + 1}/3)")

                response = await self._generate_gemini_content(
                    api_key=api_key,
                    model_name=model_name,
                    system_instruction=system_with_context,
                    generation_config=generation_config,
                    messages=final_messages,
                )
                self._commit_selected_key(key_reservation)

                candidate = response.candidates[0] if response.candidates else None
                if not (candidate and candidate.content and candidate.content.parts):
                    continue
                
                part = candidate.content.parts[0]
                if part.text:
                    text = part.text.strip()
                    
                    # Clean any artifacts (same as tier 2)
                    text = re.sub(r'<THINKING>.*?</THINKING>', '', text, flags=re.IGNORECASE | re.DOTALL).strip()
                    text = re.sub(r'^THINKING\s*\n(.*?)(?=\n[A-Z]|\n\n|$)', '', text, flags=re.MULTILINE | re.IGNORECASE | re.DOTALL).strip()
                    text = re.sub(r'^\[REASONING CONTEXT:.*?\]', '', text, flags=re.MULTILINE | re.DOTALL).strip()
                    text = re.sub(r'<tool_code>.*?</tool_code>', '', text, flags=re.IGNORECASE | re.DOTALL).strip()
                    text = re.sub(r'<tool_result>.*?</tool_result>', '', text, flags=re.IGNORECASE | re.DOTALL).strip()
                    text = re.sub(r'```(python|javascript|js|py)?\s*(web_search|calculate|get_weather|image_recognition|save_note|retrieve_notes).*?```', '', text, flags=re.IGNORECASE | re.DOTALL).strip()
                    
                    if text and len(text) > 5:
                        self.logger.info(f"✅ Fallback success for {user_id}")
                        return text
                
            except Exception as e:
                error_str = str(e)

                if self._is_invalid_key_error(error_str):
                    if api_key:
                        self._mark_key_as_failed(
                            api_key,
                            used_model_alias,
                            duration=86400,
                            reason="invalid_key",
                            permanently_exhaust=True,
                            reservation=key_reservation,
                        )
                    self.logger.warning(f"⚠️ Lite fallback invalid key on attempt {attempt + 1}/3; rotating immediately.")
                    continue

                if self._is_rate_limit_error(error_str):
                    error_type = "unavailable" if self._is_unavailable_error(error_str) else "rate_limit"
                    self.logger.warning(f"⚠️ Lite fallback transient {error_type}. Attempt {attempt + 1}/3")
                    if api_key:
                        self._mark_key_as_failed(api_key, used_model_alias, duration=60, reason=error_type, reservation=key_reservation)
                    await asyncio.sleep(2 + attempt * 2)
                    continue

                self.logger.error(f"Fallback lite error: {e}")
                continue
        
        return "[System] Model unavailable, please try again later."
    
    async def _clear_user_history(self, message: discord.Message, user_id: str):
        """Clear user chat history."""
        try:
            await self.memory_service.clear_user_data_memory(user_id)
            await self.db_repo.clear_user_data_db(user_id)
            await message.reply("✅ Đã xóa lịch sử chat!", mention_author=False)
        except Exception as e:
            self.logger.error(f"Error clearing user history: {e}")
            await message.reply("Error clearing history! 😞", mention_author=False)
    
    async def _clear_all_data(self, message: discord.Message, user_id: str):
        """Clear all database (admin only)."""
        try:
            # Full reset
            await self.memory_service.clear_all_data_memory()
            await self.db_repo.clear_all_data_db()
            
            await message.reply("⚠️ **ALL DATA CLEARED!** Database reset complete.", mention_author=False)
            self.logger.warning(f"Admin {user_id} cleared all database!")
        except Exception as e:
            self.logger.error(f"Error clearing all data: {e}")
            await message.reply("Error clearing data! 😞", mention_author=False)