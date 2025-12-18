"""
Main Entry Point - Chạy bot Discord
"""
import sys
import os

# Thêm src vào path để import được
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.handlers.bot_core import bot
from src.core.config import config
from src.core.logger import logger

def main():
    """Hàm chính để chạy bot"""
    if not config.DISCORD_TOKEN:
        logger.error("DISCORD_TOKEN chưa được cấu hình trong .env!")
        sys.exit(1)
    
    try:
        logger.info("Đang khởi động bot...")
        bot.run(config.DISCORD_TOKEN)
    except KeyboardInterrupt:
        logger.info("Bot đã dừng bởi người dùng")
    except Exception as e:
        logger.error(f"Lỗi khi chạy bot: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

