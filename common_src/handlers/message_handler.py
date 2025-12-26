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

from core.config import logger, Config
from core.system_prompt import AZURIS_SYSTEM_PROMPT
from core.lite_sys_prompt import LITE_SYSTEM_PROMPT
from database.repository import DatabaseRepository
from services.memory_service import MemoryService
from services.file_parser import FileParserService
from managers.cleanup_manager import CleanupManager
from managers.cache_manager import CacheManager
from managers.note_manager import NoteManager
from managers.premium_manager import PremiumManager
from tools.tools import ToolsManager


class MessageHandler:
    """Core message processing with Gemini API integration."""
    
    # ✅ Global API Request Queue (to avoid 429 - Google Gemini 20 req/min limit)
    API_REQUEST_QUEUE = asyncio.Queue()
    API_REQUEST_SEMAPHORE = asyncio.Semaphore(5)  # 1 request at a time
    LAST_API_REQUEST_TIME = 0.0
    MIN_REQUEST_INTERVAL = 2.0  # Minimum 2 seconds between requests (reduced for faster rotation)
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
        self.tools_mgr = ToolsManager()
        self.premium_mgr = PremiumManager()
        
        # Rate limiting (per user)
        self.user_queue: Dict[str, deque] = defaultdict(deque)
        self.RATE_LIMIT_THRESHOLD = 6  # Max messages
        self.RATE_LIMIT_WINDOW = 90  # Per x seconds
        
        # --- API KEY MANAGEMENT ---
        # 1. Track usage stats (Load Balancing + 429 Failover)
        self.key_status = {k: {'usage': 0, 'frozen_until': 0.0} for k in self.config.GEMINI_API_KEYS}
        self.key_lock = threading.Lock()
        
        # 2. Track request history for rate limit warnings (Throttling)
        self.api_key_request_history: Dict[str, List[float]] = {}
        self.api_key_history_lock = threading.Lock()
    
    def _sanitize_mentions(self, text: str) -> str:
        """
        Disable @mention by replacing @ with escaped \\@ to prevent pings.
        This prevents Discord from parsing mentions while keeping text readable.
        Examples:
          @everyone → \\@everyone (not a ping)
          @username → \\@username
          <@123> → <\\@123>
        """
        # Replace @ with escaped @ to break mention parsing
        text = text.replace('@', '\\@')
        
        return text
    
    
    # --- HÀM MỚI: CẮT TEXT THÔNG MINH & TỰ REPLY (CHAINING) ---
    async def send_smart_reply(self, message: discord.Message, text: str):
        """
        Gửi tin nhắn dài với 2 tính năng:
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
            
            # 8. Send Response (Smart Chunking & Chain Reply)
            await self.send_smart_reply(message, response_text)
        
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
        """Two-Tier Model Strategy: Flash-Lite (reasoning) → Flash (final output)."""
        
        # TIER 1: Use Flash-Lite for reasoning loops + tool calls
        reasoning_result = await self._call_gemini_reasoning_loop(messages, user_id)
        
        # TIER 2: Use Flash for final output (with reasoning context, no thinking needed)
        final_output = await self._call_gemini_final(messages, reasoning_result, user_id)
        
        return final_output
    
    async def _call_gemini_reasoning_loop(self, messages: List[Dict[str, Any]], user_id: str) -> str:
        """TIER 1: Flash-Lite model for reasoning loops and tool calls."""
        MAX_RETRIES = 5
        
        for attempt in range(MAX_RETRIES):
            api_key = self._get_best_api_key()
            if not api_key:
                return "API quota exceeded"
            
            try:
                genai.configure(api_key=api_key)
                
                current_time_str = datetime.now().strftime("%A, %d/%m/%Y %H:%M")
                time_context = f"Current time: {current_time_str}\n"
                
                # Use LITE prompt (simple reasoning, not optimized output)
                system_instruction = time_context + LITE_SYSTEM_PROMPT
                tools = self.tools_mgr.get_all_tools()
                
                # TIER 1: Flash-Lite (cheaper, reasoning only)
                generation_config = {
                    "temperature": 0.7,  # Lower temp for focused reasoning
                    "top_p": 0.9,
                    "top_k": 40,
                    "max_output_tokens": 2000,  # Lite model shorter output
                }
                
                model = genai.GenerativeModel(
                    model_name="gemini-2.5-flash-lite",  # Lite model for reasoning
                    system_instruction=system_instruction,
                    tools=tools,
                    safety_settings=self.config.SAFETY_SETTINGS,
                    generation_config=generation_config
                )
                
                await self._throttle_api_request(api_key)
                
                # Reasoning loop (up to 5 iterations)
                iteration = 0
                reasoning_messages = [msg.copy() for msg in messages]  # Copy for tier 1
                
                while iteration < 5:
                    iteration += 1
                    self.logger.info(f"Reasoning loop {iteration} for user {user_id} (Lite model)")
                    
                    response = await asyncio.to_thread(
                        model.generate_content, 
                        reasoning_messages, 
                        stream=False
                    )
                    
                    candidate = response.candidates[0] if response.candidates else None
                    if not (candidate and candidate.content and candidate.content.parts):
                        break
                    
                    part = candidate.content.parts[0]
                    
                    # Handle tool calls during reasoning
                    if part.function_call and part.function_call.name:
                        fc = part.function_call
                        args = dict(fc.args) if fc.args else {}
                        self.logger.debug(f"Reasoning tool: {fc.name} args={args}")
                        
                        tool_res = await self.tools_mgr.call_tool(fc, user_id)
                        
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
                        
                        # First check for <tool_code> blocks
                        tool_code_match = re.search(r'<tool_code>(.*?)</tool_code>', text, re.IGNORECASE | re.DOTALL)
                        if tool_code_match:
                            tool_code_content = tool_code_match.group(1)
                            # Extract tool calls from code
                            tool_matches = re.findall(r'(web_search|calculate|get_weather|image_recognition|save_note|retrieve_notes)\s*\(\s*([^)]+)\)', tool_code_content, re.IGNORECASE)
                        else:
                            # Fall back to direct pattern matching
                            tool_matches = re.findall(r'(web_search|calculate|get_weather|image_recognition|save_note|retrieve_notes)\s*\(\s*([^)]+)\)', text, re.IGNORECASE)
                        
                        if tool_matches:
                            # Found tool mentions in text - extract and call them
                            for tool_name, args_str in tool_matches:
                                self.logger.debug(f"Detected tool in text: {tool_name}({args_str})")
                                # Parse arguments (simple key="value" extraction)
                                args_dict = {}
                                for arg_match in re.finditer(r'(\w+)\s*=\s*["\']([^"\\]+)["\\]', args_str):
                                    key, value = arg_match.groups()
                                    args_dict[key] = value
                                
                                if args_dict:
                                    # Create fake function_call object
                                    class FakeFunctionCall:
                                        def __init__(self, name, args):
                                            self.name = name
                                            self.args = args
                                    
                                    fc = FakeFunctionCall(tool_name.lower(), args_dict)
                                    tool_res = await self.tools_mgr.call_tool(fc, user_id)
                                    
                                    # Add to message history
                                    reasoning_messages.append({"role": "model", "parts": [{"text": text}]})
                                    reasoning_messages.append({
                                        "role": "function",
                                        "parts": [{"function_response": {"name": tool_name.lower(), "response": {"content": str(tool_res)}}}]
                                    })
                                    break  # Continue loop for next tool
                            continue
                        
                        # No tools found - reasoning complete
                        if text and len(text) > 3:
                            return text
                        break
                    
                    break
                
                return "Reasoning completed"
                
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "quota" in error_str.lower():
                    self.logger.warning(f"⚠️ Lite Key ...{api_key[-4:]} rate limited. Retrying...")
                    self._mark_key_as_failed(api_key)
                    continue
                
                self.logger.error(f"Lite model error: {e}")
                continue
        
        return "Reasoning loop failed"
    
    async def _call_gemini_final(self, original_messages: List[Dict[str, Any]], reasoning_result: str, user_id: str) -> str:
        """TIER 2: Flash model for final output (uses reasoning from tier 1)."""
        MAX_RETRIES = 5
        
        for attempt in range(MAX_RETRIES):
            api_key = self._get_best_api_key()
            if not api_key:
                return "API quota exceeded"
            
            try:
                genai.configure(api_key=api_key)
                
                current_time_str = datetime.now().strftime("%A, %d/%m/%Y %H:%M")
                time_context = f"SYSTEM ALERT: Current Date/Time is {current_time_str}.\n\n"
                
                # Modify prompt: skip thinking from tier 1, just focus on final output
                system_with_context = (
                    time_context + AZURIS_SYSTEM_PROMPT + 
                    "\n\n*** FINAL OUTPUT MODE ***\n"
                    "You received reasoning results from preliminary analysis. "
                    "Ignore any <THINKING> blocks or reasoning artifacts - just provide the clean, final answer with your personality."
                )
                
                generation_config = {
                    "temperature": 0.7,
                    "top_p": 0.9,
                    "top_k": 40,
                    "max_output_tokens": 2000,
                }
                
                model = genai.GenerativeModel(
                    model_name=self.config.MODEL_NAME,  # Flash (better quality)
                    system_instruction=system_with_context,
                    safety_settings=self.config.SAFETY_SETTINGS,
                    generation_config=generation_config
                )
                
                await self._throttle_api_request(api_key)
                
                # Create final messages: original + reasoning context
                final_messages = [msg.copy() for msg in original_messages]
                
                # Extract user input (BLOCK 1)
                user_input = ""
                if original_messages and original_messages[-1].get("role") == "user":
                    user_input = original_messages[-1].get("parts", [{}])[0].get("text", "")[:200]  # First 200 chars
                
                # Add reasoning as context in a user message
                if final_messages:
                    # Append reasoning context as new part (not concatenate string)
                    if final_messages[-1].get("role") == "user":
                        final_messages[-1]["parts"].append({"text": f"\n\n[REASONING CONTEXT:\n{reasoning_result}\n]"})
                    else:
                        final_messages.append({
                            "role": "user",
                            "parts": [{"text": f"[REASONING CONTEXT:\n{reasoning_result}\n]"}]
                        })
                
                self.logger.info(f"Final output for user {user_id} (Flash model)")
                
                response = await asyncio.to_thread(
                    model.generate_content, 
                    final_messages, 
                    stream=False
                )
                
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
                    text = re.sub(r'^ \[REASONING CONTEXT:.*?]', '', text, flags=re.MULTILINE | re.DOTALL).strip()
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
                if "429" in error_str or "quota" in error_str.lower():
                    self.logger.warning(f"⚠️ Flash Key ...{api_key[-4:]} rate limited. Retrying...")
                    self._mark_key_as_failed(api_key)
                    continue
                
                self.logger.error(f"Final model error: {e}")
                continue
        
        return "Final output failed"
    
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
            await self.db_repo.clear_all__data_db()
            
            await message.reply("⚠️ **ALL DATA CLEARED!** Database reset complete.", mention_author=False)
            self.logger.warning(f"Admin {user_id} cleared all database!")
        except Exception as e:
            self.logger.error(f"Error clearing all data: {e}")
            await message.reply("Error clearing data! 😞", mention_author=False)

