# 🤖 Tingyun Discord Bot

Bot Discord thông minh được xây dựng với **Google Gemini AI**, hỗ trợ đa API key với hệ thống **Proactive Rate Limiting** để tránh lỗi 429. Bot được thiết kế với **Design Patterns** (Singleton, Repository, Builder) và cấu trúc code sạch, dễ bảo trì.

Bot được thiết kế để hoạt động **ổn định 24/7** với hệ thống quản lý API keys thông minh, tự động chuyển đổi keys khi gặp rate limit.

---

## 📋 Mục Lục

- [Giới Thiệu](#giới-thiệu)
- [Tính Năng Chính](#tính-năng-chính)
- [Yêu Cầu Hệ Thống](#yêu-cầu-hệ-thống)
- [Cài Đặt](#cài-đặt)
- [Cấu Hình](#cấu-hình)
- [Cấu Trúc Dự Án](#cấu-trúc-dự-án)
- [Luồng Xử Lý](#luồng-xử-lý)
- [Chạy Bot](#chạy-bot)
- [Triển Khai Trên Render](#triển-khai-trên-render)
- [Lệnh Slash](#lệnh-slash)
- [Troubleshooting](#troubleshooting)

---

## 🎯 Giới Thiệu

**Tingyun Discord Bot** là một bot Discord AI hiệu suất cao, được phát triển bằng `discord.py` và tích hợp **Google Gemini AI** để xử lý hội thoại tự nhiên, tìm kiếm thông tin thời gian thực và hỗ trợ tính toán toán học.

Bot được thiết kế với:
- **Design Patterns**: Singleton (Config, Logger), Repository (Database), Builder (Prompt)
- **Proactive Rate Limiting**: Tự động quản lý API keys, tránh lỗi 429
- **Multi-API Key Support**: Hỗ trợ tối đa 20+ API keys với health check song song
- **Clean Architecture**: Code được tổ chức rõ ràng, dễ bảo trì và mở rộng

---

## ✨ Tính Năng Chính

| Tính Năng | Mô Tả |
|-----------|-------|
| **AI Hội Thoại Thông Minh** | Sử dụng Gemini AI với cơ chế Proactive Rate Limiting, hỗ trợ nhiều API keys và tool calling tự động |
| **Tìm Kiếm Thời Gian Thực** | Tích hợp **Google CSE**, **SerpAPI**, **Tavily**, **Exa.ai** (round-robin + cache). AI tự quyết định search nếu kiến thức out-date |
| **Giải Toán Học** | Hỗ trợ biểu thức, phương trình, đạo hàm, tích phân qua **SymPy** (tool calling tự động) |
| **Quản Lý Lịch Sử Chat** | Lưu trữ theo user trong SQLite + bộ nhớ ngắn hạn (JSON) |
| **Xử Lý File** | Hỗ trợ upload và parse file (PDF, DOCX, TXT, etc.) |
| **Tương Tác Đa Kênh** | Phản hồi khi mention, reply hoặc DM |
| **Premium System** | Quản lý premium users với rate limit riêng |
| **Lệnh Quản Trị** | Slash commands: `/reset-chat`, `/premium` (admin) |
| **Chống Spam** | Rate limit + anti-spam nâng cao |
| **Tự Động Backup DB** | Sao lưu tự động khi khởi động |
| **Proxy Support** | Hỗ trợ proxy để tránh rate limit khi dùng shared IP |
| **Thời Tiết & Ghi Chú** | Tool calling cho thời tiết và lưu note |

---

## 🖥️ Yêu Cầu Hệ Thống

- **Python**: 3.8 trở lên (khuyến nghị 3.10+)
- **Discord Bot Token**: Tạo bot tại [Discord Developer Portal](https://discord.com/developers/applications)
- **Google Gemini API Key(s)**: Lấy tại [Google AI Studio](https://makersuite.google.com/app/apikey)
  - **Khuyến nghị**: Ít nhất 5-10 keys để tránh rate limit
  - Bot hỗ trợ tối đa 20+ keys
- **API Keys khác** (tùy chọn):
  - SerpAPI (tìm kiếm Google)
  - Tavily (tìm kiếm web AI-powered)
  - Exa (tìm kiếm semantic)
  - Google Custom Search Engine
  - Hugging Face (AI models)
  - Weather API

---

## 📦 Cài Đặt

### 1. Clone Repository

```bash
git clone <repository-url>
cd Tingyun
```

### 2. Cài Đặt Dependencies

```bash
pip install -r requirements.txt
```

### 3. Tạo File Cấu Hình

Sao chép file example và điền thông tin:

```bash
# Windows
copy .env.example .env
copy config.ini.example config.ini

# Linux/Mac
cp .env.example .env
cp config.ini.example config.ini
```

### 4. Điền Thông Tin Cấu Hình

Mở file `.env` và `config.ini`, điền các thông tin cần thiết (xem phần [Cấu Hình](#cấu-hình)).

**Lưu ý:** 
- File `.env.example` và `config.ini.example` là template mẫu, KHÔNG chứa thông tin thật
- Bạn cần copy thành `.env` và `config.ini` rồi điền thông tin thực tế vào
- File `.env` và `config.ini` đã được thêm vào `.gitignore`, sẽ không bị commit lên Git

---

## ⚙️ Cấu Hình

### File `.env` và `.env.example`

File `.env` chứa tất cả các API keys và thông tin nhạy cảm. **KHÔNG BAO GIỜ** commit file này lên GitHub!

File `.env.example` là template mẫu với tất cả các biến môi trường cần thiết:

**Các biến bắt buộc:**
- `DISCORD_TOKEN`: Token của Discord bot
- `GEMINI_API_KEY_*`: Ít nhất 1 Gemini API key (khuyến nghị nhiều keys để tránh rate limit)

**Các biến tùy chọn:**
- `MODEL_NAME`: Tên model Gemini (mặc định: `gemini-pro`)
- `ADMIN_ID`: Discord User ID của admin
- `GEMINI_API_KEY_PROD`, `GEMINI_API_KEY_TEST`, `GEMINI_API_KEY_BACKUP`: Keys từ bot cũ
- `GEMINI_API_KEY_EXTRA1` đến `GEMINI_API_KEY_EXTRA10`: Keys bổ sung
- `GEMINI_API_KEY_1` đến `GEMINI_API_KEY_9`: Keys từ translator (main pool)
- `GEMINI_API_KEY_Tomtat` đến `GEMINI_API_KEY_Tomtat_5`: Keys cho tác vụ tóm tắt
- `SERPAPI_API_KEY`, `TAVILY_API_KEY`, `EXA_API_KEY`: Search API keys
- `GOOGLE_CSE_ID`, `GOOGLE_CSE_API_KEY`: Google Custom Search Engine
- `HF_TOKEN`: Hugging Face token
- `WEATHER_API_KEY`, `CITY`: Weather API
- `PROXY`: Proxy configuration (format: host:port:username:password)

Xem file `.env.example` trong repository để biết cách điền chi tiết với comments đầy đủ.

**Các biến bắt buộc:**
- `DISCORD_TOKEN`: Token của Discord bot
- `GEMINI_API_KEY_*`: Ít nhất 1 Gemini API key (khuyến nghị nhiều keys để tránh rate limit)

**Các biến tùy chọn:**
- `MODEL_NAME`: Tên model Gemini (mặc định: `gemini-pro`)
- `ADMIN_ID`: Discord User ID của admin
- Các API keys khác cho tính năng tìm kiếm, weather, etc.

**Ví dụ `.env`:**
```env
DISCORD_TOKEN=your_discord_bot_token_here
MODEL_NAME=gemini-pro
ADMIN_ID=your_admin_user_id

# Gemini API Keys (khuyến nghị nhiều keys)
GEMINI_API_KEY_1=AIzaSy...
GEMINI_API_KEY_2=AIzaSy...
GEMINI_API_KEY_3=AIzaSy...
# ... thêm nhiều keys hơn

# Search APIs (tùy chọn)
SERPAPI_API_KEY=your_serpapi_key
TAVILY_API_KEY=your_tavily_key
EXA_API_KEY=your_exa_key
GOOGLE_CSE_ID=your_cse_id
GOOGLE_CSE_API_KEY=your_cse_key
```

### File `config.ini` và `config.ini.example`

File `config.ini` chứa cấu hình proxy và các settings khác.

File `config.ini.example` là template mẫu với cấu hình proxy:

**Cấu hình Proxy:**
```ini
[PROXY]
# Bật/tắt proxy: true hoặc false
enabled = false

# Proxy host (không bao gồm http:// hoặc https://)
host = proxy.example.com

# Proxy port (số nguyên)
port = 8080

# Proxy username (nếu proxy yêu cầu authentication)
username = your_proxy_username

# Proxy password (nếu proxy yêu cầu authentication)
password = your_proxy_password
```

Xem file `config.ini.example` trong repository để biết chi tiết với comments đầy đủ.

**Lưu ý:**
- Bot sẽ ưu tiên đọc proxy từ `config.ini` trước
- Nếu `config.ini` không có hoặc `enabled = false`, bot sẽ đọc từ `.env`
- Nếu cả hai đều không có, bot sẽ không dùng proxy
- File `config.ini` đã được thêm vào `.gitignore`, sẽ không bị commit lên Git

---

## 📁 Cấu Trúc Dự Án

```
Tingyun/
├── main.py                 # Entry point chính
├── requirements.txt        # Python dependencies
├── .env                   # Environment variables (KHÔNG commit)
├── config.ini             # Proxy config (KHÔNG commit)
├── .gitignore             # Git ignore rules
│
├── src/                   # Source code chính
│   ├── core/              # Core modules
│   │   ├── config.py      # Config Singleton (quản lý tất cả settings)
│   │   └── logger.py      # Logger Singleton (logging tập trung)
│   │
│   ├── database/          # Database layer
│   │   ├── repository.py  # Repository Pattern (tất cả DB operations)
│   │   └── *.db          # SQLite database files
│   │
│   ├── handlers/          # Event handlers
│   │   ├── bot_core.py    # Discord bot core (events, commands)
│   │   └── message_handler.py  # Xử lý messages từ users
│   │
│   ├── services/          # Business logic services
│   │   ├── api_key_manager.py      # Proactive Rate Limiting System
│   │   ├── key_health_checker.py   # Health check API keys
│   │   ├── memory_service.py       # Quản lý memory (short-term)
│   │   ├── prompt_builder.py       # Builder Pattern cho prompts
│   │   └── file_parser.py          # Parse files (PDF, DOCX, etc.)
│   │
│   ├── managers/          # Resource managers
│   │   ├── premium_manager.py     # Quản lý premium users
│   │   ├── note_manager.py        # Quản lý notes/files
│   │   ├── cleanup_manager.py    # Dọn dẹp files cũ
│   │   └── cache_manager.py       # Cache management
│   │
│   ├── tools/             # AI Tools (function calling)
│   │   └── tools.py       # Search, calculator, weather, etc.
│   │
│   └── instructions/      # AI Instructions
│       └── prompt.txt     # System prompt chính cho AI
│
├── data/                  # Data files
│   └── short_term_memory.json  # Short-term memory storage
│
└── uploaded_files/        # Files uploaded by users
```

### Design Patterns Được Sử Dụng

1. **Singleton Pattern**: 
   - `Config` class (`src/core/config.py`) - Đảm bảo chỉ có 1 instance config
   - `Logger` class (`src/core/logger.py`) - Centralized logging

2. **Repository Pattern**: 
   - `db_repository` (`src/database/repository.py`) - Tách biệt database logic khỏi business logic

3. **Builder Pattern**: 
   - `PromptBuilder` (`src/services/prompt_builder.py`) - Xây dựng prompts động

---

## 🔄 Luồng Xử Lý

### 1. Khởi Động Bot (`main.py` → `bot_core.py`)

```
main.py
  └─> Import bot từ src.handlers.bot_core
      └─> Bot khởi tạo với intents
          └─> on_ready() event:
              ├─> Sync slash commands
              ├─> Initialize database (db_repository.initialize())
              ├─> Initialize JSON memory (init_json_memory())
              ├─> Initialize API Key Manager (initialize_api_key_manager())
              │   └─> Health check tất cả API keys song song
              ├─> Cleanup old messages (db_repository.cleanup())
              ├─> Cleanup old files (cleanup_local_files())
              └─> Backup database (db_repository.backup())
```

### 2. Xử Lý Message (`bot_core.py` → `message_handler.py`)

```
User gửi message
  └─> on_message() event
      └─> handle_message()
          ├─> Kiểm tra spam/rate limit
          ├─> Parse attachment (nếu có file)
          │   └─> file_parser.parse_attachment()
          │       └─> Lưu vào database (note_manager)
          ├─> Load user history từ database
          ├─> Load short-term memory từ JSON
          ├─> Build system prompt
          │   └─> prompt_builder.build()
          │       ├─> Load base prompt từ instructions/prompt.txt
          │       ├─> Thêm time info
          │       ├─> Thêm memory context
          │       └─> Thêm image instructions (nếu có)
          └─> Gọi Gemini API
              └─> run_gemini_api()
                  ├─> Lấy API key từ api_key_manager
                  │   └─> get_next_api_key()
                  │       ├─> Check rate limit (proactive)
                  │       ├─> Chọn key nhanh nhất
                  │       └─> Health check nếu cần
                  ├─> Gọi API với throttling
                  │   └─> make_throttled_api_call()
                  ├─> Xử lý tool calling (nếu AI cần)
                  │   └─> call_tool() → tools.py
                  └─> Trả về response
                      └─> Lưu vào database & memory
```

### 3. Proactive Rate Limiting System

```
API Key Manager (api_key_manager.py)
  ├─> Track request history cho mỗi key
  │   └─> key_request_history[key] = [timestamp1, timestamp2, ...]
  │
  ├─> Check rate limit trước khi dùng
  │   └─> check_key_rate_limit()
  │       ├─> Đếm requests trong 30 phút gần nhất
  │       ├─> Nếu < 20 requests → OK
  │       └─> Nếu >= 20 requests → Cooldown
  │
  ├─> Chọn key tốt nhất
  │   └─> get_next_api_key()
  │       ├─> Lọc keys available (không trong cooldown)
  │       ├─> Health check song song (nếu cần)
  │       └─> Chọn key nhanh nhất
  │
  └─> Xử lý lỗi 429
      └─> handle_429_error()
          └─> Đưa key vào delayed pool (cooldown 30 phút)
```

### 4. System Prompt Flow

```
instructions/prompt.txt (Base prompt)
  └─> prompt_builder.load_base_prompt()
      └─> prompt_builder.add_time_info()
      └─> prompt_builder.add_memory_context()
      └─> prompt_builder.add_image_instructions()
      └─> prompt_builder.build()
          └─> Final system instruction cho Gemini
```

**Nội dung prompt.txt bao gồm:**
- Luật cơ bản của bot
- Cách phân tích câu hỏi (LUẬT 4.5)
- Cách sử dụng tools
- Cách trả lời thông minh, không lạc đề
- Thinking process (THINKING block)

---

## 🚀 Chạy Bot

### Chạy Cục Bộ

```bash
python main.py
```

### Chạy với Python Module

```bash
python -m src.handlers.bot_core
```

### Chạy trên Server (Production)

Sử dụng `screen` hoặc `tmux` để chạy bot trong background:

```bash
# Với screen
screen -S tingyun-bot
python main.py
# Nhấn Ctrl+A, sau đó D để detach

# Với tmux
tmux new -s tingyun-bot
python main.py
# Nhấn Ctrl+B, sau đó D để detach
```

Hoặc sử dụng systemd service (Linux):

```ini
# /etc/systemd/system/tingyun-bot.service
[Unit]
Description=Tingyun Discord Bot
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/Tingyun
ExecStart=/usr/bin/python3 main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable tingyun-bot
sudo systemctl start tingyun-bot
```

---

## 🌐 Triển Khai Trên Render (Web Service – Free Tier)

> **Không dùng Background Worker (cần paid)**  
> **Dùng Web Service + Flask tích hợp** để giữ alive và tránh restart loop.

### 1. Tạo Dịch Vụ

1. Truy cập [Render Dashboard](https://dashboard.render.com/)
2. **New** → **Web Service**
3. Kết nối repository: `<your-repo>`

### 2. Cấu Hình

| Trường | Giá Trị |
|--------|---------|
| **Name** | tingyun-discord-bot |
| **Branch** | main |
| **Runtime** | Python 3 |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `python main.py` |
| **Health Check Path** | `/` (nếu có Flask server) |

### 3. Biến Môi Trường

Thêm toàn bộ biến từ file `.env` vào phần **Environment** trên Render.

> **Lưu ý**:
> - **Không cần `keep_alive.py`** – Flask có thể tích hợp trong bot nếu cần
> - **Không cần `PORT`** – Render tự động cung cấp
> - **Proxy**: Nếu dùng Render Free Tier với shared IP, nên bật proxy trong `config.ini`

### 4. Giữ Bot Luôn Sống (Free Tier)

Render Free **sleep sau 15 phút không hoạt động**.

**Giải pháp (miễn phí):**

**Dùng UptimeRobot**:
1. Tạo monitor → **HTTP(s)**
2. URL: `https://your-service.onrender.com/`
3. Interval: **5 phút** → Bot được ping → **không sleep**

---

## 📝 Lệnh Slash (Discord)

| Lệnh | Mô Tả | Quyền |
|------|-------|-------|
| `/reset-chat` | Xóa lịch sử chat của người dùng | Mọi người |
| `/premium` | Kiểm tra hoặc quản lý trạng thái Premium của người dùng | Admin |
| `/reset-all` | Xóa toàn bộ DB và Memory (nguy hiểm!) | Admin |
| `/message_to` | Gửi tin nhắn tới user hoặc kênh | Admin |

### Chi Tiết Lệnh

#### `/reset-chat`
- Xóa toàn bộ lịch sử chat của user trong database và memory
- Yêu cầu xác nhận: Reply **yes** hoặc **y** trong 60 giây

#### `/premium`
- **Action**: `check` (kiểm tra), `add` (thêm), `remove` (xóa)
- **User**: User cần kiểm tra/thêm/xóa Premium
- Chỉ Admin mới có quyền sử dụng

#### `/reset-all`
- ⚠️ **NGUY HIỂM**: Xóa toàn bộ database và memory của tất cả users
- Yêu cầu xác nhận: Reply **YES RESET** trong 60 giây
- Chỉ Admin mới có quyền sử dụng

#### `/message_to`
- Gửi tin nhắn tới user hoặc kênh cụ thể
- **User**: User nhận tin nhắn (chọn hoặc nhập ID)
- **Message**: Nội dung tin nhắn
- **Channel**: Kênh để gửi tin nhắn (tùy chọn, mặc định là DM)
- Chỉ Admin mới có quyền sử dụng

---

## 🔧 Troubleshooting

### Bot không khởi động

1. **Kiểm tra DISCORD_TOKEN**: Đảm bảo token hợp lệ trong `.env`
2. **Kiểm tra Python version**: `python --version` (cần >= 3.8)
3. **Kiểm tra dependencies**: `pip install -r requirements.txt`
4. **Kiểm tra logs**: Xem file `bot.log` hoặc console output

### Lỗi 429 (Rate Limit)

Bot đã có hệ thống Proactive Rate Limiting, nhưng nếu vẫn gặp lỗi:

1. **Thêm nhiều API keys hơn**: Thêm vào `.env` với format `GEMINI_API_KEY_1`, `GEMINI_API_KEY_2`, etc.
2. **Kiểm tra proxy**: Đảm bảo proxy hoạt động (nếu dùng shared IP như Render Free Tier)
3. **Giảm số lượng requests**: Tăng `MIN_REQUEST_INTERVAL` trong `api_key_manager.py`
4. **Kiểm tra health check**: Xem log khi khởi động để biết keys nào active

### Bot không trả lời

1. **Kiểm tra API keys**: Đảm bảo có ít nhất 1 key hợp lệ
2. **Kiểm tra logs**: Xem lỗi cụ thể trong `bot.log`
3. **Kiểm tra permissions**: Bot cần quyền đọc/gửi messages
4. **Kiểm tra mention**: Bot chỉ trả lời khi được mention hoặc trong DM

### Database lỗi

1. **Kiểm tra quyền ghi file**: Đảm bảo bot có quyền ghi vào `src/database/`
2. **Kiểm tra disk space**: Đảm bảo còn đủ dung lượng
3. **Backup database**: Chạy `db_repository.backup()` để backup

### Proxy không hoạt động

1. **Kiểm tra config.ini**: Đảm bảo thông tin proxy đúng
2. **Test proxy**: Thử kết nối proxy bằng curl hoặc Python
3. **Tắt proxy tạm thời**: Set `enabled = false` trong `config.ini`

---

## 📝 Notes

- **File `.env` và `config.ini` KHÔNG BAO GIỜ được commit lên Git**
- Bot tự động backup database mỗi khi khởi động
- Bot tự động cleanup messages và files cũ
- API keys được health check song song khi khởi động
- Rate limiting được xử lý proactive (trước khi gửi request)
- Bot hỗ trợ tối đa 20+ API keys với tự động load balancing

---

## 📄 License

Dự án được cấp phép theo **MIT License**. Xem file `LICENSE` để biết thêm chi tiết.

---

## 🤝 Contributing

1. Fork repository
2. Tạo feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to branch (`git push origin feature/AmazingFeature`)
5. Mở Pull Request

---

## 📧 Support

Nếu gặp vấn đề, vui lòng mở Issue trên GitHub hoặc liên hệ admin.

---

> **Đã kiểm thử và triển khai thành công với Proactive Rate Limiting System**  
> **Hỗ trợ 20+ API keys với health check song song**  
> **Code được tổ chức với Design Patterns, dễ bảo trì và mở rộng**
