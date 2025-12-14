# File khởi động chính cho bot.
# File này sẽ chạy server Flask trong một luồng nền để giữ cho bot hoạt động trên Render,
# sau đó khởi động bot Discord.

import threading
import os
import psutil
import time
from datetime import timedelta
from flask import Flask, render_template_string, jsonify
from bot_core import bot
from config import TOKEN, logger

# --- FLASK KEEP-ALIVE SERVER ---
keep_alive_app = Flask(__name__)

# Store the bot's start time
start_time = time.time()

# HTML template for the dashboard with auto-refreshing stats
DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bot Status</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #1e1e1e; color: #d4d4d4; margin: 0; padding: 20px; }
        .container { max-width: 900px; margin: auto; background: #2d2d2d; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.5); }
        h1, h2 { color: #569cd6; border-bottom: 2px solid #444; padding-bottom: 10px; }
        .status-ok { color: #4ec9b0; font-size: 1.2em; font-weight: bold; }
        .metric { margin-bottom: 15px; font-size: 1.1em; }
        .metric-label { font-weight: bold; color: #9cdcfe; }
        #file-list { display: flex; flex-wrap: wrap; gap: 10px; list-style-type: none; padding: 0; }
        .file-item { background: #3c3c3c; padding: 10px; border-radius: 4px; border-left: 3px solid #569cd6; flex-basis: calc(33.333% - 20px); box-sizing: border-box; word-break: break-all; }
        .folder { border-left-color: #f0a869; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Bot Status</h1>
        
        <h2>System Metrics</h2>
        <div class="metric">
            <span class="metric-label">Server Uptime:</span> <span id="uptime">{{ uptime }}</span>
        </div>
        <div class="metric">
            <span class="metric-label">CPU Usage:</span> <span id="cpu">{{ cpu_percent }}</span>%
        </div>
        <div class="metric">
            <span class="metric-label">RAM Usage:</span> <span id="ram_percent">{{ ram_percent }}</span>% (<span id="ram_usage">{{ ram_used }} / {{ ram_total }} GB</span>)
        </div>
        
        <h2>Project Files & Folders</h2>
        <ul id="file-list">
            {% for item in file_system %}
                <li class="file-item {{ 'folder' if item.is_dir else '' }}">{{ item.name }}</li>
            {% endfor %}
        </ul>
    </div>

    <script>
        function updateStats() {
            fetch('/stats')
                .then(response => response.json())
                .then(data => {
                    document.getElementById('uptime').textContent = data.uptime;
                    document.getElementById('cpu').textContent = data.cpu_percent;
                    document.getElementById('ram_percent').textContent = data.ram_percent;
                    document.getElementById('ram_usage').textContent = `${data.ram_used} / ${data.ram_total} GB`;

                    const fileList = document.getElementById('file-list');
                    fileList.innerHTML = ''; // Clear existing list
                    data.file_system.forEach(item => {
                        const li = document.createElement('li');
                        li.className = 'file-item ' + (item.is_dir ? 'folder' : '');
                        li.textContent = item.name;
                        fileList.appendChild(li);
                    });
                })
                .catch(error => console.error('Error fetching stats:', error));
        }

        // Update stats on page load and then every 30 seconds
        document.addEventListener('DOMContentLoaded', () => {
            updateStats(); // Initial update
            setInterval(updateStats, 30000); // Update every 30 seconds
        });
    </script>
</body>
</html>
"""

def get_system_stats():
    """Helper function to gather all system stats."""
    # Uptime
    uptime_seconds = time.time() - start_time
    uptime_str = str(timedelta(seconds=int(uptime_seconds)))

    # CPU and RAM
    cpu_percent = psutil.cpu_percent()
    ram = psutil.virtual_memory()
    ram_percent = ram.percent
    ram_total_gb = round(ram.total / (1024**3), 2)
    ram_used_gb = round(ram.used / (1024**3), 2)

    # Files and Folders
    project_path = '.'
    items = os.listdir(project_path)
    file_system_info = []
    for item in sorted(items, key=lambda s: s.lower()):
        is_dir = os.path.isdir(os.path.join(project_path, item))
        file_system_info.append({"name": item, "is_dir": is_dir})
        
    return {
        "uptime": uptime_str,
        "cpu_percent": cpu_percent,
        "ram_percent": ram_percent,
        "ram_total": ram_total_gb,
        "ram_used": ram_used_gb,
        "file_system": file_system_info
    }

@keep_alive_app.route('/')
def dashboard():
    """
    Renders the main dashboard page with initial data.
    The page will then auto-update via JavaScript.
    """
    stats = get_system_stats()
    return render_template_string(DASHBOARD_TEMPLATE, **stats)

@keep_alive_app.route('/stats')
def stats_api():
    """
    API endpoint to provide system stats as JSON for the frontend.
    """
    return jsonify(get_system_stats())

@keep_alive_app.route('/status')
def status():
    """
    Endpoint for Uptime Robot to ping, returns simple JSON.
    """
    uptime_seconds = time.time() - start_time
    return jsonify({"status": "alive", "uptime": str(timedelta(seconds=int(uptime_seconds)))})


def run_keep_alive():
    """
    Chạy Flask server để đáp ứng health checks từ Render.
    """
    port = int(os.environ.get('PORT', 8080))
    # Chạy server trên host 0.0.0.0 để có thể truy cập từ bên ngoài container
    # Tắt reloader để tránh chạy main 2 lần
    keep_alive_app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

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