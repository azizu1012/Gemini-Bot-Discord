import json
import os
import asyncio
import tempfile
from src.core.config import MEMORY_PATH, logger
from typing import Dict, Any, List


class MemoryService:
    """Service for managing JSON-based short-term memory."""

    def __init__(self, memory_path: str = MEMORY_PATH):
        self.memory_path = memory_path
        self.memory_lock = asyncio.Lock()
        self.logger = logger

    def _ensure_parent_dir(self) -> None:
        parent = os.path.dirname(self.memory_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    def _read_json_sync(self) -> Dict[str, Any]:
        with open(self.memory_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _atomic_write_json_sync(self, data: Dict[str, Any]) -> None:
        self._ensure_parent_dir()
        parent = os.path.dirname(self.memory_path) or "."
        fd, temp_path = tempfile.mkstemp(prefix="memory_", suffix=".tmp", dir=parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(temp_path, self.memory_path)
        except Exception:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass
            raise

    def init_json_memory(self) -> None:
        """Initialize JSON memory file if it doesn't exist."""
        if os.path.exists(self.memory_path):
            return
        try:
            self._atomic_write_json_sync({})
            self.logger.info(f"Created new short term memory file: {self.memory_path}")
        except Exception as e:
            self.logger.error(f"Failed to create memory file: {e}")

    async def load_json_memory(self) -> Dict[str, Any]:
        """Load memory from JSON file (thread-safe with lock)."""
        async with self.memory_lock:
            if not os.path.exists(self.memory_path):
                await asyncio.to_thread(self._atomic_write_json_sync, {})
                return {}
            try:
                return await asyncio.to_thread(self._read_json_sync)
            except json.JSONDecodeError:
                self.logger.error("Failed to decode memory JSON, resetting file.")
                await asyncio.to_thread(self._atomic_write_json_sync, {})
                return {}
            except Exception as e:
                self.logger.error(f"Failed to load memory file: {e}")
                return {}

    async def save_json_memory(self, data: Dict[str, Any]) -> None:
        """Save memory to JSON file (thread-safe with lock)."""
        async with self.memory_lock:
            try:
                await asyncio.to_thread(self._atomic_write_json_sync, data)
            except Exception as e:
                self.logger.error(f"Failed to save memory file: {e}")

    async def log_message_memory(self, user_id: str, role: str, content: str) -> None:
        """Log a message to JSON memory (keeps last 10 messages per user)."""
        try:
            async with self.memory_lock:
                if not os.path.exists(self.memory_path):
                    memory: Dict[str, Any] = {}
                else:
                    try:
                        memory = await asyncio.to_thread(self._read_json_sync)
                    except json.JSONDecodeError:
                        self.logger.error("Failed to decode memory JSON, resetting file.")
                        memory = {}
                    except Exception as e:
                        self.logger.error(f"Failed to load memory file: {e}")
                        memory = {}

                if user_id not in memory:
                    memory[user_id] = []

                memory[user_id].append({"role": role, "content": content})
                memory[user_id] = memory[user_id][-10:]

                await asyncio.to_thread(self._atomic_write_json_sync, memory)
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
