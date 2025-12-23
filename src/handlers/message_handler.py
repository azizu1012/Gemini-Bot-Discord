import discord
import asyncio
import google.generativeai as genai
from datetime import datetime, timedelta
from collections import defaultdict, deque
from typing import Any, Optional, Dict, List
import json

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
    
    def __init__(self, bot_core, config: Config):
        self.bot_core = bot_core
        self.config = config
        self.logger = logger
        self.db_repo = DatabaseRepository()
        self.memory_service = MemoryService()
        self.cache_mgr = CacheManager()
        self.note_mgr = NoteManager(self.db_repo)
        self.file_parser = FileParserService(CleanupManager())
        self.tools_mgr = ToolsManager()
        self.premium_mgr = PremiumManager()
        
        # Rate limiting
        self.user_queue: Dict[str, deque] = defaultdict(deque)
        self.MAX_QUEUE_SIZE = 1
        self.RATE_LIMIT_WINDOW = 300
        
        # API key rotation
        self.api_key_index = 0
    
    async def handle_message(self, message: discord.Message, bot: discord.ext.commands.Bot):
        """Main message handler."""
        try:
            # Skip bot messages and system messages
            if message.author == bot.user or message.author.bot:
                return
            
            user_id = str(message.author.id)
            
            # Check rate limiting
            now = datetime.now()
            self.user_queue[user_id].append(now)
            
            # Remove old timestamps
            while self.user_queue[user_id] and self.user_queue[user_id][0] < now - timedelta(seconds=self.RATE_LIMIT_WINDOW):
                self.user_queue[user_id].popleft()
            
            if len(self.user_queue[user_id]) > self.MAX_QUEUE_SIZE:
                self.logger.warning(f"User {user_id} rate limited (queue: {len(self.user_queue[user_id])})")
                return
            
            # Check for DM
            if isinstance(message.channel, discord.DMChannel):
                await self._handle_dm(message)
            else:
                # Check for mention
                if bot.user in message.mentions:
                    await self._handle_mention(message)
            
            # Check for confirmation pending
            if user_id in self.bot_core.confirmation_pending and self.bot_core.confirmation_pending[user_id]['awaiting']:
                if message.content.lower() in ['yes', 'y']:
                    await self._clear_user_history(message, user_id)
                self.bot_core.confirmation_pending[user_id]['awaiting'] = False
                return
            
            # Check for admin confirmation
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
        
        # Check if user allowed
        premium = self.premium_mgr.is_premium_user(user_id)
        if not premium and user_id != self.config.ADMIN_USER_IDS[0]:
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
            # Extract content
            content = message.content
            if message.mentions:
                for mention in message.mentions:
                    content = content.replace(f"<@{mention.id}>", "").replace(f"<@!{mention.id}>", "")
            content = content.strip()
            
            if not content and not message.attachments:
                await message.reply("Please provide a message or file! 😐", mention_author=False)
                return
            
            # Handle attachments
            attachment_data = ""
            if message.attachments:
                for attachment in message.attachments:
                    try:
                        parsed = await self.file_parser.parse_attachment(attachment)
                        if "error" in parsed:
                            await message.reply(f"File error: {parsed.get('error')}", mention_author=False)
                            return
                        attachment_data += f"\n[File: {parsed['filename']}]\n{parsed['content']}\n"
                    except Exception as e:
                        self.logger.error(f"Error parsing attachment: {e}")
                        await message.reply(f"Error parsing file! 😞", mention_author=False)
                        return
            
            # Get user history
            history = await self.memory_service.get_user_history_async(user_id)
            db_history = await self.db_repo.get_user_history_from_db(user_id, limit=10)
            
            # Build messages for Gemini
            messages = []
            for msg in history:
                messages.append({
                    "role": msg["role"],
                    "parts": [{"text": msg["content"]}]
                })
            
            # Add current message
            user_message = content + attachment_data
            messages.append({
                "role": "user",
                "parts": [{"text": user_message}]
            })
            
            # Show typing indicator
            async with message.channel.typing():
                # Call Gemini API
                response_text = await self._call_gemini_api(messages, user_id)
            
            # Log to memory and DB
            await self.memory_service.log_message_memory(user_id, "user", user_message)
            await self.memory_service.log_message_memory(user_id, "assistant", response_text)
            
            await self.db_repo.log_message_db(user_id, "user", user_message)
            await self.db_repo.log_message_db(user_id, "assistant", response_text)
            
            # Send response
            if len(response_text) > 2000:
                for i in range(0, len(response_text), 1900):
                    chunk = response_text[i:i+1900]
                    await message.reply(chunk, mention_author=False)
            else:
                await message.reply(response_text, mention_author=False)
        
        except Exception as e:
            self.logger.error(f"Error processing message: {e}")
            await message.reply(f"Error! 😞 Details: {str(e)[:100]}", mention_author=False)
    
    async def _call_gemini_api(self, messages: List[Dict[str, Any]], user_id: str) -> str:
        """Call Gemini API with tool support and thinking."""
        max_iterations = 5
        iteration = 0
        
        try:
            # Rotate API key
            api_key = self.config.GEMINI_API_KEYS[self.api_key_index % len(self.config.GEMINI_API_KEYS)]
            self.api_key_index += 1
            genai.configure(api_key=api_key)
            
            # System instruction (comprehensive prompt with rules and personality)
            system_instruction = AZURIS_SYSTEM_PROMPT
            
            # Get tools
            tools = self.tools_mgr.get_all_tools()
            
            # Build generation config with thinking
            generation_config = {
                "temperature": 1.0,
                "top_p": 0.95,
                "top_k": 40,
                "max_output_tokens": 8000,
                "thinking": {
                    "type": "ENABLED",
                    "budget_tokens": 5000
                }
            }
            
            # Initialize model
            model = genai.GenerativeModel(
                model_name=self.config.MODEL_NAME,
                system_instruction=system_instruction,
                tools=tools,
                safety_settings=self.config.SAFETY_SETTINGS,
                generation_config=generation_config
            )
            
            # Tool loop
            while iteration < max_iterations:
                iteration += 1
                self.logger.info(f"Gemini iteration {iteration} for user {user_id}")
                
                # Send request
                response = await asyncio.to_thread(
                    model.generate_content,
                    messages,
                    stream=False
                )
                
                # Extract thinking if available
                thinking_text = ""
                if hasattr(response, 'thinking') and response.thinking:
                    thinking_text = response.thinking
                    self.logger.debug(f"Thinking: {thinking_text[:200]}...")
                
                # Check for function call
                if response.candidates[0].content.parts:
                    part = response.candidates[0].content.parts[0]
                    
                    if hasattr(part, 'function_call'):
                        # Tool call
                        function_call = part.function_call
                        tool_name = function_call.name
                        tool_args = {arg: function_call.args[arg] for arg in function_call.args}
                        
                        self.logger.info(f"Tool call: {tool_name} with args {tool_args}")
                        
                        # Execute tool
                        tool_result = await self.tools_mgr.call_tool(function_call, user_id)
                        
                        # Add to messages
                        messages.append({
                            "role": "model",
                            "parts": [part]
                        })
                        messages.append({
                            "role": "user",
                            "parts": [{
                                "function_response": {
                                    "name": tool_name,
                                    "response": {"result": str(tool_result)}
                                }
                            }]
                        })
                        
                        continue
                    else:
                        # Text response
                        text_response = part.text
                        
                        # Clean thinking tags if present
                        if "<|thinking|>" in text_response:
                            text_response = text_response.split("<|thinking|>")[0]
                        
                        return text_response.strip()
                else:
                    return "No response from model"
            
            return "Max iterations reached without final response"
        
        except Exception as e:
            self.logger.error(f"Error calling Gemini API: {e}")
            return f"API Error: {str(e)[:100]}"
    
    async def _clear_user_history(self, message: discord.Message, user_id: str):
        """Clear user chat history."""
        try:
            await self.memory_service.clear_user_data_memory(user_id)
            await self.db_repo.clear_user_data_db(user_id)
            await message.reply("✅ Your chat history cleared! Ready for a fresh start!", mention_author=False)
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
