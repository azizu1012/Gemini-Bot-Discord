import json
import os
import asyncio
from core.config import MEMORY_PATH, logger
from typing import Dict, Any, List


class MemoryService:
    """Service for managing JSON-based short-term memory."""
    
    def __init__(self, memory_path: str = MEMORY_PATH):
        self.memory_path = memory_path
        self.memory_lock = asyncio.Lock()
        self.logger = logger
    
    def init_json_memory(self) -> None:
        """Initialize JSON memory file if it doesn't exist."""
        if not os.path.exists(self.memory_path):
            try:
                with open(self.memory_path, 'w', encoding='utf-8') as f:
                    json.dump({}, f)
                self.logger.info(f"Created new short term memory file: {self.memory_path}")
            except Exception as e:
                self.logger.error(f"Failed to create memory file: {e}")
    
    async def load_json_memory(self) -> Dict[str, Any]:
        """Load memory from JSON file (thread-safe with lock)."""
        async with self.memory_lock:
            if not os.path.exists(self.memory_path):
                self.init_json_memory()
                return {}
            try:
                with open(self.memory_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                self.logger.error("Failed to decode memory JSON, resetting file.")
                self.init_json_memory()
                return {}
            except Exception as e:
                self.logger.error(f"Failed to load memory file: {e}")
                return {}
    
    async def save_json_memory(self, data: Dict[str, Any]) -> None:
        """Save memory to JSON file (thread-safe with lock)."""
        async with self.memory_lock:
            try:
                with open(self.memory_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                self.logger.error(f"Failed to save memory file: {e}")
    
    async def log_message_memory(self, user_id: str, role: str, content: str) -> None:
        """Log a message to JSON memory (keeps last 10 messages per user)."""
        try:
            memory = await self.load_json_memory()
            if user_id not in memory:
                memory[user_id] = []
            
            memory[user_id].append({"role": role, "content": content})
            memory[user_id] = memory[user_id][-10:]
            
            await self.save_json_memory(memory)
        except Exception as e:
            self.logger.error(f"Failed to update JSON memory for {user_id}: {e}")
    
    async def get_user_history_async(self, user_id: str) -> List[Dict[str, str]]:
        """Get user's message history from JSON memory."""
        memory = await self.load_json_memory()
        return memory.get(user_id, [])
    
    async def clear_user_data_memory(self, user_id: str) -> bool:
        """Clear a specific user's data from memory."""
        try:
            memory = await self.load_json_memory()
            if user_id in memory:
                del memory[user_id]
                await self.save_json_memory(memory)
                self.logger.info(f"User {user_id} history cleared from JSON memory")
            return True
        except Exception as e:
            self.logger.error(f"Failed to clear JSON memory for {user_id}: {e}")
            return False
    
    async def clear_all_data_memory(self) -> bool:
        """Clear all data from memory."""
        try:
            await self.save_json_memory({})
            self.logger.info("ADMIN: Reset JSON memory file.")
            return True
        except Exception as e:
            self.logger.error(f"ADMIN: Failed to reset JSON memory: {e}")
            return False
