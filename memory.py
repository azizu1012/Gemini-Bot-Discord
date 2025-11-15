
import json
import os
import asyncio
from config import MEMORY_PATH, logger
from typing import Dict, Any

memory_lock = asyncio.Lock()

def init_json_memory() -> None:
    """Khởi tạo file JSON nếu chưa tồn tại."""
    if not os.path.exists(MEMORY_PATH):
        try:
            with open(MEMORY_PATH, 'w', encoding='utf-8') as f:
                json.dump({}, f)
            logger.info(f"Created new short term memory file: {MEMORY_PATH}")
        except Exception as e:
            logger.error(f"Failed to create memory file: {e}")

async def load_json_memory() -> Dict[str, Any]:
    """Tải bộ nhớ từ file JSON (an toàn với Lock)."""
    async with memory_lock:
        if not os.path.exists(MEMORY_PATH):
            init_json_memory()
            return {}
        try:
            with open(MEMORY_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.error("Failed to decode memory JSON, resetting file.")
            init_json_memory()
            return {}
        except Exception as e:
            logger.error(f"Failed to load memory file: {e}")
            return {}

async def save_json_memory(data: Dict[str, Any]) -> None:
    """Lưu bộ nhớ vào file JSON (an toàn với Lock)."""
    async with memory_lock:
        try:
            with open(MEMORY_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save memory file: {e}")

async def log_message_memory(user_id: str, role: str, content: str) -> None:
    try:
        memory = await load_json_memory()
        if user_id not in memory:
            memory[user_id] = []

        memory[user_id].append({"role": role, "content": content})
        memory[user_id] = memory[user_id][-10:]

        await save_json_memory(memory)
    except Exception as e:
        logger.error(f"Failed to update JSON memory for {user_id}: {e}")

async def get_user_history_async(user_id: str) -> list:
    memory = await load_json_memory()
    return memory.get(user_id, [])

async def clear_user_data_memory(user_id: str) -> bool:
    try:
        memory = await load_json_memory()
        if user_id in memory:
            del memory[user_id]
            await save_json_memory(memory)
            logger.info(f"User {user_id} history cleared from JSON memory")
            return True
        else:
            return True
    except Exception as e:
        logger.error(f"Failed to clear JSON memory for {user_id}: {e}")
        return False

async def clear_all_data_memory() -> bool:
    try:
        await save_json_memory({})
        logger.info("ADMIN: Reset JSON memory file.")
        return True
    except Exception as e:
        logger.error(f"ADMIN: Failed to reset JSON memory: {e}")
        return False
