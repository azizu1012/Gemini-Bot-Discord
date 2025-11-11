# File khởi động chính cho bot.
# File này sẽ chạy server Flask trong một luồng nền để giữ cho bot hoạt động trên Render,
# sau đó khởi động bot Discord.

import threading
import os
from flask import Flask
from bot_core import bot
from config import TOKEN, logger

# --- FLASK KEEP-ALIVE SERVER ---
keep_alive_app = Flask(__name__)


@keep_alive_app.route('/', methods=['GET', 'POST'])
def webhook() -> str:
    return "Bot alive! No sleep pls~ 😴"

def run_keep_alive():
    """
    Chạy Flask server để đáp ứng health checks từ Render.
    """
    port = int(os.environ.get('PORT', 8080))
    # Chạy server trên host 0.0.0.0 để có thể truy cập từ bên ngoài container
    keep_alive_app.run(host='0.0.0.0', port=port, debug=False)

# --- MAIN EXECUTION ---
def main():
    """
    Hàm chính để khởi chạy bot và server keep-alive.
    """

    # Khởi chạy server keep-alive trong một luồng riêng
    logger.info("Khởi tạo server keep-alive...")
    keep_alive_thread = threading.Thread(target=run_keep_alive, daemon=True)
    keep_alive_thread.start()

    logger.info("Máy chủ Bot đang khởi động...")

    # Chạy bot
    if TOKEN:
        try:
            bot.run(TOKEN)
        except Exception as e:
            logger.error(f"Lỗi nghiêm trọng khi chạy bot: {e}")
    else:
        logger.error("BIẾN MÔI TRƯỜNG DISCORD_TOKEN CHƯA ĐƯỢC CÀI ĐẶT.")

if __name__ == "__main__":

    main()
