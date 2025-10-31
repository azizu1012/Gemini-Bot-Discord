# Discord AI Assistant

<p align="center">
  <a href="https://github.com/azizu1012/Gemini-Bot-Discord/blob/main/LICENSE">
    <img alt="License" src="https://img.shields.io/github/license/azizu1012/Gemini-Bot-Discord?style=flat-square"/>
  </a>
  <a href="https://discord.com/api/oauth2/authorize?client_id=YOUR_BOT_ID&permissions=274878258176&scope=bot%20applications.commands">
    <img alt="Discord Bot" src="https://img.shields.io/badge/Discord-Add%20Bot-5865F2?style=flat-square&logo=discord&logoColor=white"/>
  </a>
  <a href="https://www.python.org/">
    <img alt="Python" src="https://img.shields.io/badge/Python-3.13%2B-blue?style=flat-square&logo=python"/>
  </a>
  <a href="https://render.com/">
    <img alt="Render" src="https://img.shields.io/badge/Render-Web%20Service%20(Free)-46E3B7?style=flat-square&logo=render&logoColor=white"/>
  </a>
</p>

---

## Giới thiệu

**Discord AI Assistant** là một bot Discord hiệu suất cao, được phát triển bằng `discord.py` và tích hợp **Google Gemini AI** để xử lý hội thoại tự nhiên, tìm kiếm thông tin thời gian thực và hỗ trợ tính toán toán học.

Bot được thiết kế để hoạt động **ổn định 24/7 trên Render Free Tier** bằng **Web Service** với **Flask tích hợp** (không cần file `keep_alive.py` riêng), đảm bảo uptime cao và không bị restart loop.

---

## Tính năng chính

| Tính năng | Mô tả |
|---------|-------|
| **AI hội thoại thông minh** | Sử dụng Gemini AI với cơ chế failover 5 API key |
| **Tìm kiếm thời gian thực** | Tích hợp **Google CSE**, **SerpAPI**, **Tavily**, **Exa.ai** (round-robin + cache) |
| **Giải toán học** | Hỗ trợ biểu thức, phương trình, đạo hàm, tích phân qua **SymPy** |
| **Quản lý lịch sử chat** | Lưu trữ theo user trong SQLite + bộ nhớ ngắn hạn (JSON) |
| **Tương tác đa kênh** | Phản hồi khi mention, reply hoặc DM |
| **Lệnh quản trị** | Slash commands: `/reset-chat`, `/dm`, `/history`, `!resetall` (admin) |
| **Chống spam** | Rate limit + anti-spam nâng cao |
| **Tự động backup DB** | Sao lưu tự động khi khởi động |

---

## Yêu cầu hệ thống

- Python 3.13+
- Discord Bot Token
- Google Gemini API Key(s)
- API Key cho ít nhất một trong các dịch vụ tìm kiếm (khuyến nghị dùng cả 4)

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

MODEL_NAME=gemini-2.0-flash-exp

ADMIN_ID=your_admin_user_id

# Search APIs (tối thiểu 1, khuyến nghị dùng hết)
SERPAPI_API_KEY=your_serpapi_key
TAVILY_API_KEY=your_tavily_key
EXA_API_KEY=your_exa_key
GOOGLE_CSE_ID=your_cse_id
GOOGLE_CSE_API_KEY=your_cse_key

# Optional
WEATHER_API_KEY=your_weather_key
```

Chạy bot:

```bash
python bot_run.py
```

---

## Triển khai trên Render (Web Service – Free Tier)

> **Không dùng Background Worker (cần paid)**  
> **Dùng Web Service + Flask tích hợp trong `bot_run.py`** để giữ alive và tránh restart loop.

### 1. Tạo dịch vụ

1. Truy cập [Render Dashboard](https://dashboard.render.com)
2. **New** → **Web Service**
3. Kết nối repository: `azizu1012/Gemini-Bot-Discord`

### 2. Cấu hình

| Trường | Giá trị |
|-------|--------|
| **Name** | `discord-ai-assistant` |
| **Branch** | `main` |
| **Runtime** | `Python 3` |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `python bot_run.py` |
| **Health Check Path** | `/` |

### 3. Biến môi trường

Thêm toàn bộ biến từ file `.env` vào phần **Environment** trên Render.

> **Lưu ý**:  
> - **Không cần `keep_alive.py`** – Flask đã tích hợp trong `bot_run.py`  
> - **Không cần `PORT`** – Render tự động cung cấp  
> - **Flask bind `0.0.0.0` + `PORT` env** → Render health check ổn định

---

## Cấu trúc dự án

```
/
├── bot_run.py              # Logic chính + Flask tích hợp
├── requirements.txt        # Dependencies
├── chat_history.db         # SQLite DB (tạo tự động)
├── chat_history_backup.db  # Backup DB
├── short_term_memory.json  # Bộ nhớ ngắn hạn
├── bot.log                 # Log hoạt động
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
| `/dm` | Gửi tin nhắn riêng (admin) | Admin |
| `/history` | Xem lịch sử chat (admin) | Admin |

---

## Bảo mật

- **Không commit `.env`** lên repository công khai.
- Tất cả API key được quản lý qua **Environment Variables** trên Render.
- Flask chỉ trả về `"Bot alive!"` tại `/` – an toàn cho health check.

---

## Giữ Bot Luôn Sống (Free Tier)

Render Free **sleep sau 15 phút không hoạt động**.

### Giải pháp (miễn phí):

**Dùng [UptimeRobot](https://uptimerobot.com)**:
1. Tạo monitor → **HTTP(s)**
2. URL: `https://your-service.onrender.com/`
3. Interval: **5 phút**
→ Bot được ping → **không sleep**

---

## Giấy phép

Dự án được cấp phép theo **[MIT License](LICENSE)**.

---

## Liên hệ & Hỗ trợ

- **Repository**: [github.com/azizu1012/Gemini-Bot-Discord](https://github.com/azizu1012/Gemini-Bot-Discord)
- **Issues**: Báo lỗi hoặc đề xuất tính năng tại [GitHub Issues](https://github.com/azizu1012/Gemini-Bot-Discord/issues)

---

> **Đã kiểm thử và triển khai thành công trên Render Free Tier**  
> **Không cần Background Worker, không cần UptimeRobot nếu có người chat thường xuyên**  
> **Flask tích hợp → ổn định, không loop, không lỗi**
```