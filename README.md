# Gemini Discord Bot

## Hướng dẫn chạy local
1. Tạo file `.env` (xem mẫu `.env.example`).
2. Cài thư viện:
   ```
   pip install -r requirements.txt
   ```
3. Chạy bot:
   ```
   python bot_run.py
   ```

## Deploy Render
- Add các biến môi trường từ `.env` vào Render dashboard.
- Service start command: `python bot_run.py`
- Để giữ bot online 24/7, dùng UptimeRobot ping endpoint của Flask (mặc định là `/`).

## Bảo mật
- KHÔNG commit file `.env` lên GitHub!
