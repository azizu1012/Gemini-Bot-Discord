import discord
from discord.ext import commands
import asyncio
import google.generativeai as genai
import time
from datetime import datetime, timedelta
from collections import defaultdict, deque
from typing import Any, Optional, Dict, List
import json
import threading
import re
import random

from src.core.config import logger, Config
from src.core.system_prompt import AZURIS_SYSTEM_PROMPT
from src.database.repository import DatabaseRepository
from src.services.memory_service import MemoryService
from src.services.file_parser import FileParserService
from src.managers.cleanup_manager import CleanupManager
from src.managers.cache_manager import CacheManager
from src.managers.note_manager import NoteManager
from src.managers.premium_manager import PremiumManager
from src.tools.tools import ToolsManager


class MessageHandler:
    """Core message processing with Gemini API integration."""
    
    # ✅ Global API Request Queue (to avoid 429 - Google Gemini 20 req/min limit)
    API_REQUEST_QUEUE = asyncio.Queue()
    API_REQUEST_SEMAPHORE = asyncio.Semaphore(1)  # 1 request at a time
    LAST_API_REQUEST_TIME = 0.0
    MIN_REQUEST_INTERVAL = 2.0  # Minimum 2 seconds between requests (reduced for faster rotation)
    COOLDOWN_WINDOW = 1800  # 30 minutes
    MAX_REQUESTS_PER_WINDOW = 15  # 15 requests per 30 minutes warning threshold
    
    def __init__(self, bot_core, config: Config):
        self.bot_core = bot_core
        self.config = config
        self.logger = logger
        self.db_repo = DatabaseRepository()
        self.memory_service = MemoryService()
        self.cache_mgr = CacheManager()
        self.note_mgr = NoteManager(self.db_repo)
        
        # Initialize FileParser with CleanupManager
        self.file_parser = FileParserService(cleanup_mgr=CleanupManager())
        self.tools_mgr = ToolsManager()
        self.premium_mgr = PremiumManager()
        
        # Rate limiting (per user)
        self.user_queue: Dict[str, deque] = defaultdict(deque)
        self.RATE_LIMIT_THRESHOLD = 3  # Max 3 messages
        self.RATE_LIMIT_WINDOW = 120  # Per 2 minutes
        
        # --- API KEY MANAGEMENT ---
        # 1. Track usage stats (Load Balancing + 429 Failover)
        self.key_status = {k: {'usage': 0, 'frozen_until': 0.0} for k in self.config.GEMINI_API_KEYS}
        self.key_lock = threading.Lock()
        
        # 2. Track request history for rate limit warnings (Throttling)
        self.api_key_request_history: Dict[str, List[float]] = {}
        self.api_key_history_lock = threading.Lock()
    
    async def handle_message(self, message: discord.Message, bot: commands.Bot):
        """Main message handler."""
        try:
            # Skip bot messages
            if message.author == bot.user or message.author.bot:
                return
            
            user_id = str(message.author.id)
            is_admin = user_id in self.config.ADMIN_USER_IDS
            
            # ✅ Check rate limiting (BYPASS for ADMIN)
            if not is_admin:
                now = datetime.now()
                self.user_queue[user_id].append(now)
                
                # Remove old timestamps outside window
                while self.user_queue[user_id] and self.user_queue[user_id][0] < now - timedelta(seconds=self.RATE_LIMIT_WINDOW):
                    self.user_queue[user_id].popleft()
                
                # If user has more than threshold -> rate limit
                if len(self.user_queue[user_id]) > self.RATE_LIMIT_THRESHOLD:
                    self.logger.warning(f"User {user_id} rate limited (spam: {len(self.user_queue[user_id])}/{self.RATE_LIMIT_THRESHOLD} in window)")
                    return
            
            # Check for DM
            if isinstance(message.channel, discord.DMChannel):
                await self._handle_dm(message)
            else:
                # Check for mention
                if bot.user in message.mentions:
                    await self._handle_mention(message)
            
            # Check for confirmation pending (Reset Chat)
            if user_id in self.bot_core.confirmation_pending and self.bot_core.confirmation_pending[user_id]['awaiting']:
                if message.content.lower() in ['yes', 'y']:
                    await self._clear_user_history(message, user_id)
                self.bot_core.confirmation_pending[user_id]['awaiting'] = False
                return
            
            # Check for admin confirmation (Reset All)
            if user_id in self.bot_core.admin_confirmation_pending and self.bot_core.admin_confirmation_pending[user_id]['awaiting']:
                if message.content.upper() == 'YES RESET':
                    await self._clear_all_data(message, user_id)
                self.bot_core.admin_confirmation_pending[user_id]['awaiting'] = False
                return
        
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
            # 1. Clean content
            content = message.content
            if message.mentions:
                for mention in message.mentions:
                    content = content.replace(f"<@{mention.id}>", "").replace(f"<@!{mention.id}>", "")
            content = content.strip()
            
            # 2. Handle Reply Context (Smart Reply)
            reply_context = ""
            if not is_dm and message.reference:
                try:
                    replied_msg = await message.channel.fetch_message(message.reference.message_id)
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
                            if "error" in parsed:
                                attachment_data += f"\n[System Error: Lỗi khi đọc file {attachment.filename}: {parsed.get('error')}]\n"
                            else:
                                attachment_data += f"\n[File Content: {parsed['filename']}]\n{parsed['content']}\n"
                        except Exception as e:
                            self.logger.error(f"Error parsing text file: {e}")
                            attachment_data += f"\n[System Error: Không thể đọc file {attachment.filename}]\n"
                        continue

                    # CASE C: UNSUPPORTED
                    attachment_data += f"\n[System Note: User uploaded file '{attachment.filename}' but format is NOT supported.]\n"
            
            # 5. Build History & Messages
            history = await self.memory_service.get_user_history_async(user_id)
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
            
            # 7. Log to memory and DB
            await self.memory_service.log_message_memory(user_id, "user", user_message)
            await self.memory_service.log_message_memory(user_id, "assistant", response_text)
            
            await self.db_repo.log_message_db(user_id, "user", user_message)
            await self.db_repo.log_message_db(user_id, "assistant", response_text)
            
            # 8. Send Response (Chunking)
            if len(response_text) > 2000:
                for i in range(0, len(response_text), 1900):
                    chunk = response_text[i:i+1900]
                    await message.reply(chunk, mention_author=False)
            else:
                await message.reply(response_text, mention_author=False)
        
        except Exception as e:
            self.logger.error(f"Error processing message: {e}")
            await message.reply(f"Hệ thống đang bận, vui lòng thử lại sau! 😓", mention_author=False)

    # --- SMART KEY MANAGEMENT METHODS ---
    
    def _get_best_api_key(self) -> Optional[str]:
        """Load balancing: Choose available key with least usage."""
        with self.key_lock:
            now = time.time()
            # Filter active keys (not frozen)
            active_keys = [k for k, v in self.key_status.items() if v['frozen_until'] < now]
            
            if not active_keys:
                self.logger.error("ALL API KEYS ARE FROZEN (429)!")
                return None
            
            # Find min usage among active keys to balance load
            min_usage = min(self.key_status[k]['usage'] for k in active_keys)
            best_candidates = [k for k in active_keys if self.key_status[k]['usage'] == min_usage]
            
            # Pick one randomly
            chosen_key = random.choice(best_candidates)
            self.key_status[chosen_key]['usage'] += 1
            return chosen_key

    def _mark_key_as_failed(self, key: str, duration: int = 60):
        """Freeze key for duration seconds (Failover)."""
        with self.key_lock:
            if key in self.key_status:
                self.key_status[key]['frozen_until'] = time.time() + duration
                self.logger.warning(f"❄️ API Key ...{key[-4:]} frozen for {duration}s due to 429.")

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

    async def _call_gemini_api(self, messages: List[Dict[str, Any]], user_id: str) -> str:
        """Call Gemini API with Auto-Retry and Failover."""
        MAX_RETRIES = 5  # Try up to 5 keys
        
        for attempt in range(MAX_RETRIES):
            # 1. Get Best Key
            api_key = self._get_best_api_key()
            if not api_key:
                return "Hệ thống đang quá tải (Hết API Key), vui lòng chờ 1 phút."
            
            try:
                # 2. Configure GenAI
                genai.configure(api_key=api_key)
                
                # --- CẬP NHẬT THỜI GIAN THỰC TẾ TỪ OS ---
                # Lấy giờ hiện tại format rõ ràng (Ví dụ: "Friday, 24/12/2025 14:30")
                current_time_str = datetime.now().strftime("%A, %d/%m/%Y %H:%M")
                
                # Chèn dòng này lên đầu Prompt để "tẩy não" bot về thời gian
                time_context = (
                    f"SYSTEM ALERT: Current Date/Time is {current_time_str}.\n"
                    f"You MUST use this date to determine what is 'latest', 'current', 'newest'.\n"
                    f"Example: If today is 2025, TGA 2024 is PAST, TGA 2025 is CURRENT/FUTURE.\n\n"
                )
                
                # Ghép với prompt gốc
                system_instruction = time_context + AZURIS_SYSTEM_PROMPT
                tools = self.tools_mgr.get_all_tools()
                
                generation_config = {
                    "temperature": 1.0,
                    "top_p": 0.95,
                    "top_k": 40,
                    "max_output_tokens": 8000,
                }
                
                model = genai.GenerativeModel(
                    model_name=self.config.MODEL_NAME,
                    system_instruction=system_instruction,
                    tools=tools,
                    safety_settings=self.config.SAFETY_SETTINGS,
                    generation_config=generation_config
                )
                
                # 3. Throttle (Wait if needed)
                await self._throttle_api_request(api_key)
                
                # 4. Generate with Tool Loop
                iteration = 0
                while iteration < 5:
                    iteration += 1
                    self.logger.info(f"Gemini iteration {iteration} for user {user_id} (Key: ...{api_key[-4:]})")
                    
                    response = await asyncio.to_thread(model.generate_content, messages, stream=False)
                    
                    candidate = response.candidates[0] if response.candidates else None
                    if not (candidate and candidate.content and candidate.content.parts):
                        return "No response from model"

                    part = candidate.content.parts[0]
                    
                    # Tool Call
                    if part.function_call and part.function_call.name:
                        fc = part.function_call
                        args = dict(fc.args) if fc.args else {}
                        self.logger.info(f"Tool call: {fc.name} args={args}")
                        
                        tool_res = await self.tools_mgr.call_tool(fc, user_id)
                        
                        messages.append({"role": "model", "parts": [part]})
                        messages.append({
                            "role": "function", 
                            "parts": [{"function_response": {"name": fc.name, "response": {"content": str(tool_res)}}}]
                        })
                        continue
                    
                    # Text Response
                    elif part.text:
                        text = part.text
                        # ✅ Clean THINKING tags
                        if text:
                            text = re.sub(r'<THINKING>.*?</THINKING>', '', text, flags=re.DOTALL).strip()
                        
                        if not text:
                            return "..."  # Fallback
                        return text
                
                return "Max iterations reached."

            except Exception as e:
                error_str = str(e)
                # 5. Handle 429 Errors (Quota Exceeded)
                if "429" in error_str or "quota" in error_str.lower() or "resource exhausted" in error_str.lower():
                    self.logger.warning(f"⚠️ Key ...{api_key[-4:]} failed (429). Retrying ({attempt+1}/{MAX_RETRIES})...")
                    self._mark_key_as_failed(api_key)  # Freeze this key
                    continue  # Retry loop will pick a NEW key
                
                # Other errors
                self.logger.error(f"Gemini API Error (Non-429): {e}")
                if attempt < 1: continue  # Retry once for network blips
                return "Xin lỗi, hệ thống gặp lỗi kỹ thuật."

        return "Hiện tại tất cả các cổng kết nối đều đang bận. Vui lòng thử lại sau."
    
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