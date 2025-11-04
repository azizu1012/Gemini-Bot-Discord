
from config import logger
from database import log_message_db
from memory import log_message_memory

async def log_message(user_id, role, content):
    await log_message_db(user_id, role, content)
    await log_message_memory(user_id, role, content)
    if role == "user":
        logger.info(f"User {user_id} sent a message")
    elif role == "assistant" and "DM reply" in content:
        logger.info(f"Bot sent DM to user mentioned in message")
