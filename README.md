
---

# Discord AI Assistant  
![License](https://img.shields.io/github/license/azizu1012/Gemini-Bot-Discord?style=flat-square)  
[![Discord - Add Bot](https://img.shields.io/badge/Discord-Add%20Bot-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.com/oauth2/authorize?client_id=1418949883859308594&permissions=8&integration_type=0&scope=bot)  
![Python](https://img.shields.io/badge/Python-3.13%2B-blue?style=flat-square&logo=python)  
![Render](https://img.shields.io/badge/Render-Web%20Service%20(Free)-46E3B7?style=flat-square&logo=render&logoColor=white)

## Giới thiệu  
**Discord AI Assistant** là một bot Discord hiệu suất cao, được phát triển bằng `discord.py` và tích hợp **Google Gemini AI** để xử lý hội thoại tự nhiên, tìm kiếm thông tin thời gian thực, hỗ trợ tính toán toán học, tra cứu thời tiết, lưu ghi chú và nhiều tính năng hữu ích khác.

Bot được thiết kế để hoạt động ổn định 24/7 trên **Render Free Tier** bằng Web Service với **Flask tích hợp sẵn trong `bot_run.py`**, không cần file `keep_alive.py` riêng biệt — đảm bảo uptime cao và tránh vòng lặp khởi động lại.

---

## Tính năng chính  

| Tính năng | Mô tả |
|----------|-------|
| **AI hội thoại thông minh** | Sử dụng Google Gemini với cơ chế **failover 5 API key** và **tool calling tự động** |
| **Tìm kiếm thời gian thực** | Tích hợp **Google CSE**, **SerpAPI**, **Tavily**, **Exa.ai** (round-robin + cache 6h). AI **tự động gọi search** khi kiến thức đã cũ (sau 2024) |
| **Giải toán học** | Hỗ trợ biểu thức, phương trình, đạo hàm, tích phân qua **SymPy** (tool calling tự động) |
| **Thời tiết & Ghi chú** | Tool `get_weather` và `save_note` để tra cứu thời tiết theo thành phố hoặc lưu ghi chú cá nhân |
| **Quản lý lịch sử chat** | Lưu theo user trong **SQLite** (`chat_history.db`) + **bộ nhớ ngắn hạn JSON** (`short_term_memory.json`) |
| **Tương tác đa kênh** | Phản hồi khi **mention**, **reply**, hoặc **DM** |
| **Lệnh quản trị** | Slash commands: `/reset-chat`, `/reset-all`, `/dm` (chỉ admin) |
| **Chống spam** | Rate limit + anti-spam nâng cao (giới hạn 3 tin/30 giây) |
| **Tự động backup DB** | Sao lưu DB khi khởi động và dọn dẹp tin nhắn cũ (>30 ngày) |
| **Keep-alive tích hợp** | Flask webhook tại `/` giúp Render health check ổn định |

---

## Yêu cầu hệ thống  

- Python **3.13+**
- Discord Bot Token
- **Google Gemini API Key(s)** (tối đa 5 key hỗ trợ failover)
- **Ít nhất 1 API key** từ các dịch vụ tìm kiếm sau (khuyến nghị dùng đủ 4):
  - SerpAPI
  - Tavily
  - Exa.ai
  - Google Custom Search Engine (CSE)
- (Tùy chọn) WeatherAPI Key

---

## Cài đặt cục bộ  

```bash
git clone https://github.com/azizu1012/Gemini-Bot-Discord.git
cd Gemini-Bot-Discord
pip install -r requirements.txt
```

Tạo file `.env` tại thư mục gốc:

```env
DISCORD_TOKEN=your_bot_token
GEMINI_API_KEY_PROD=your_primary_key
GEMINI_API_KEY_TEST=key_2
GEMINI_API_KEY_BACKUP=key_3
GEMINI_API_KEY_EXTRA1=key_4
GEMINI_API_KEY_EXTRA2=key_5

MODEL_NAME=gemini-2.5-flash

ADMIN_ID=your_admin_user_id

# Search APIs (tối thiểu 1, khuyến nghị dùng hết)
SERPAPI_API_KEY=your_serpapi_key
TAVILY_API_KEY=your_tavily_key
EXA_API_KEY=your_exa_key
GOOGLE_CSE_ID=your_cse_id
GOOGLE_CSE_API_KEY=your_cse_key

# Optional
WEATHER_API_KEY=your_weather_key
CITY=Ho Chi Minh City
```

Chạy bot:

```bash
python bot_run.py
```

---

## Triển khai trên Render (Web Service – Free Tier)

> ⚠️ **Không dùng Background Worker** (yêu cầu paid plan). Dùng **Web Service** + Flask tích hợp trong `bot_run.py`.

### 1. Tạo dịch vụ  
- Truy cập [Render Dashboard](https://dashboard.render.com)  
- **New → Web Service**  
- Kết nối repository: `azizu1012/Gemini-Bot-Discord`  

### 2. Cấu hình  

| Trường | Giá trị |
|--------|--------|
| **Name** | `discord-ai-assistant` |
| **Branch** | `main` |
| **Runtime** | `Python 3` |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `python bot_run.py` |
| **Health Check Path** | `/` |

### 3. Biến môi trường  
Thêm toàn bộ biến từ `.env` vào phần **Environment Variables** trên Render.

> ✅ **Lưu ý**:  
> - Không cần `keep_alive.py` — Flask đã tích hợp trong `bot_run.py`  
> - Không cần khai báo `PORT` — Render tự cung cấp  
> - Flask bind `0.0.0.0` + `PORT` từ env → health check ổn định  

---

## Cấu trúc dự án  

```
/
├── bot_run.py              # Logic chính + Flask keep-alive tích hợp
├── requirements.txt        # Dependencies
├── chat_history.db         # SQLite DB (tạo tự động)
├── chat_history_backup.db  # Backup DB (ghi đè mỗi lần chạy)
├── short_term_memory.json  # Bộ nhớ ngắn hạn cho AI (10 tin/user)
├── notes.txt               # File lưu ghi chú người dùng
├── bot.log                 # Log hoạt động (console + file)
└── README.md
```

---

## Dependencies (`requirements.txt`)

```txt
discord.py
python-dotenv
sympy
google-generativeai
requests
flask
google-search-results
tavily-python
exa-py
```

---

## Lệnh Slash (Discord)

| Lệnh | Mô tả | Quyền |
|------|------|------|
| `/reset-chat` | Xóa lịch sử chat của người dùng | Mọi người |
| `/reset-all` | Xóa toàn bộ DB + memory (xác nhận 2 bước) | Chỉ admin |
| `/dm` | Gửi tin nhắn riêng tới user cụ thể | Chỉ admin |

> Ngoài ra, admin có thể dùng lệnh text `!resetall` trong DM với bot để kích hoạt reset toàn bộ.

---

## Bảo mật  

- **Không commit `.env`** lên repository công khai.  
- Tất cả API key được quản lý qua **Environment Variables**.  
- Flask chỉ trả về `"Bot alive! No sleep pls~ 😴"` tại `/` — an toàn cho health check.  

---

## Giữ Bot Luôn Sống (Free Tier)

Render Free Tier sẽ **sleep sau 15 phút không hoạt động**.

### Giải pháp miễn phí:
Dùng [UptimeRobot](https://uptimerobot.com):  
- Tạo monitor → **HTTP(s)**  
- URL: `https://your-service.onrender.com/`  
- Interval: **5 phút**  
→ Bot được ping liên tục → **không bị sleep**

---

## Giấy phép  
Dự án được cấp phép theo [MIT License](LICENSE).

---

## Liên hệ & Hỗ trợ  

- **Repository**: [github.com/azizu1012/Gemini-Bot-Discord](https://github.com/azizu1012/Gemini-Bot-Discord)  
- **Mời bot**: [Nhấn vào đây để thêm bot vào server của bạn](https://discord.com/oauth2/authorize?client_id=1418949883859308594&permissions=8&integration_type=0&scope=bot)  
- **Báo lỗi / Đề xuất**: [GitHub Issues](https://github.com/azizu1012/Gemini-Bot-Discord/issues)

> ✅ Đã kiểm thử và triển khai thành công trên **Render Free Tier**  
> ✅ Không cần Background Worker, không cần UptimeRobot nếu có người chat thường xuyên  
> ✅ Flask tích hợp → ổn định, không loop, không lỗi

---