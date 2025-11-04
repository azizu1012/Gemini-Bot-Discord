
import threading
from bot_core import bot
from server import run_keep_alive
from config import TOKEN, logger

if __name__ == "__main__":
    threading.Thread(target=run_keep_alive, daemon=True).start()
    logger.info("Máy săn Bot đang khởi động...")
    bot.run(TOKEN)