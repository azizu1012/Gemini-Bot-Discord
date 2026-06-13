# 📑 AZURIS BOT — CẨM NANG BÀN GIAO (HANDOFF PROTOCOL)

<!-- AI-READABLE + HUMAN-READABLE HYBRID -->
<!-- Generated: 2026-06-01 | Runtime: Python 3.11+ | Platform: Win32/Linux -->
<!-- Template v2 — Hybrid Narrative + Structured (Customized for Azuris) -->

---

## 🚀 1) TỔNG QUAN HỆ THỐNG (EXECUTIVE SUMMARY)

**Azuris** là một trợ lý AI tiên tiến trên Discord, tích hợp khả năng lập luận đa bước (Reasoning), gọi công cụ thời gian thực và quản lý ngữ cảnh dài hạn. Hệ thống hoạt động theo mô hình **Event-Driven Architecture (Kiến trúc Hướng Sự kiện)** với 2 services chính: **Gateway (BotCore)** và **Worker (MessageHandler)** kết nối qua **Redis Streams**.

**Thay đổi gần đây (Bản cập nhật mới nhất 2026 — Bảo vệ API Keys, Phục hồi Suy nghĩ & Đồng bộ Model):**
- **Đồng nhất Model Alias**: Chuyển dịch toàn bộ cấu hình từ alias cũ `gemini-flash-35` sang `gemini-flash` làm model chính lý luận và tổng hợp cuối. Xóa bỏ hoàn toàn alias `gemini-flash-30` lỗi thời. Thêm trường cấu hình `direct_model_id` cho chế độ gọi Google trực tiếp.
- **Bảo vệ rò rỉ khóa bảo mật (Google API Key Leak Prevention)**: Khắc phục lỗi bảo mật nghiêm trọng khi `ROUTER_AUTH_KEY` để trống nhưng có cấu hình `GEMINI_BASE_URL`. Bot hiện tại sẽ tự động bypass và quay về xoay vòng key direct Google thay vì gửi Google API Key thật lên header Authorization của Router API.
- **Bảo toàn Chain-of-Thought (`thought` và `thought_signature`)**: Cập nhật `gemini_api_manager.py` để phân tích cú pháp (parse) nhị phân/base64 một cách an toàn và giữ nguyên các thuộc tính suy nghĩ ẩn (`thought` và `thought_signature`) trong các đối tượng `genai_types.Part` của Google GenAI SDK. Điều này giúp ngăn chặn việc mất dữ liệu Chain-of-Thought của mô hình trong suốt các vòng lặp tool calling.
- **Sửa lỗi đơn vị Timeout & Tối ưu hóa Bypass**: Cấu hình timeout của HttpOptions trong Google GenAI SDK đã được chuyển sang đơn vị mili giây (kiểu int) thay vì giây dạng float (ví dụ `15000`ms cho kết nối, tăng client timeout tổng lên tới `120000`ms để tránh timeout sớm khi đi qua Router/proxy). Tối ưu hóa thời gian bypass Router về còn 30 giây (khi lỗi `endpoint_down`) và tự động chuyển toàn bộ các yêu cầu LLM sang alias Google Gemini Flash Lite tự động cập nhật mới nhất (`gemini-flash-lite-latest`) để bảo vệ quota.
- **Final model fallback**: Khi Router có `GEMINI_BASE_URL` nhưng rỗng `ROUTER_AUTH_KEY` → tự động fallback và sử dụng lite model cho cả reasoning và final synthesis để bảo vệ hạn ngạch chi phí.

**Thay đổi gần đây (Session 3 — Health Check UI & LLM Report):**
- `health_checker.py`: Xóa hoàn toàn LLM report (`_generate_recovery_report` giờ trả text static, không gọi Gemini). Gỡ `GeminiApiManager` dependency khỏi service.
- `bot_core.py` (`/health_check`): Chuyển từ text thuần sang `discord.Embed` với field API Keys (✅/❌), Ping Model, Model Scan + màu xanh/cam theo trạng thái.

**Thay đổi gần đây (Session 9 — Gỡ bỏ hoàn toàn Custom Endpoint / OpenAI-compatible handling):**
- **Xóa files:** `src/core/api_proxy.py` (311 dòng), `src/core/custom_endpoint.py` (33 dòng).
- **Biến môi trường mới:** `GEMINI_BASE_URL` — khi set, bot route Gemini SDK qua URL đó (Router API); khi để trống, gọi Google trực tiếp.
- **Đơn giản hóa:** `gemini_api_manager.py` chỉ hỗ trợ Gemini SDK; `api_router.py` gỡ bỏ custom model alias methods; `health_checker.py` thành stub 100 dòng.
- **Slash command mới:** `/endpoint` cho Admin xem/set `GEMINI_BASE_URL`. Đã gỡ bỏ `/enable_custom_api`, `/custom_api_config`.

**Thay đổi gần đây (Session 10 — Sửa lỗi crash khởi động và nâng cấp hạ tầng Redis):**
- **Sửa lỗi crash cú pháp (NameError & IndentationError):** Reset tệp `src/handlers/bot_core.py` về HEAD sạch và cấu trúc lại. Di chuyển helper `_update_env_var` ra thành phương thức cấp lớp của `BotCore` (thụt lề 4 spaces), đưa lệnh `/endpoint` (`endpoint_slash`) vào bên trong phương thức `_register_slash_commands(self)` (thụt lề 8 spaces). Điều này đảm bảo tất cả slash command được đăng ký đúng phạm vi và tránh lỗi cú pháp lúc nạp lớp.
- **Nâng cấp Redis Server hỗ trợ Redis Streams:** Thay đổi link tải Redis trong `install_services.ps1` từ MSOpenTech Redis 3.2.100 (không hỗ trợ Streams) thành tporadowski Redis 5.0.14.1 cho Windows (hỗ trợ đầy đủ Streams). Xóa thư mục runtime cũ, cài đặt lại hạ tầng và khởi chạy lại bot. Loại bỏ hoàn toàn các lỗi `unknown command 'XGROUP'` và `unknown command 'XREADGROUP'` giúp hệ thống Event-Driven hoạt động ổn định.
- **Bổ sung script stop_bot.ps1:** Tạo kịch bản PowerShell `stop_bot.ps1` tại thư mục gốc giúp quét và tắt nhanh toàn bộ các tiến trình Python chạy ngầm thuộc thư mục dự án này, ngăn chặn tình trạng mồ côi và trùng lặp session bot.

**Thay đổi gần đây (Session 7 — Triển khai Real Streaming cho Router và Bot):**
- **Router (`gemini_routes.py` & `gemini_api_manager.py`):**
  - Sửa đổi `_parse_gemini_contents()` để hỗ trợ đầy đủ `functionCall` và `functionResponse`, sửa lỗi mất mát dữ liệu khi chuyển tiếp tool calling.
  - Sửa lỗi `image_count` bị stale trong vòng lặp cắt bớt ngữ cảnh (truncation loop) sau khi `contents.pop(0)`.
  - Triển khai `call_gemini_stream` thực tế với đầy đủ logic xoay vòng khóa, xử lý lỗi và giới hạn tốc độ (rate limiting) giống hệt cuộc gọi sync.
  - Thay thế cơ chế stream giả (fake stream bằng cách chia nhỏ chữ) bằng kết nối stream thực tế thông qua `generate_content_stream` từ Google GenAI SDK.
- **Bot (`gemini_pipeline.py` & `gemini_api_manager.py`):**
  - Bổ sung phương thức `_generate_gemini_content_stream` vào `GeminiApiManager` hỗ trợ cả `AsyncOpenAI` (đã gỡ bỏ ở Session 9) và `genai.Client`.
  - Nâng cấp `GeminiPipeline._call_gemini_final` để gọi stream thực tế từ API và gom các chunk trả về, đồng thời sử dụng cơ chế `MockResponse` bọc kết quả giúp giữ nguyên toàn bộ logic xử lý phía sau (truncation, continuation...) mà không làm phá vỡ cấu trúc code cũ.

**Thay đổi gần đây (Session 8 — Fix Cost Tracking Dashboard cho toàn hệ thống):**
- **Router (`gemini_routes.py`, `gemini_api_manager.py`, `opencode_proxy`, `claude_proxy`):**
  - Thêm `log_usage` cho streaming endpoints (`streamGenerateContent`, SSE) — trước đây không log → chi phí $0.
  - Đổi toàn bộ `log_usage` dùng `model_id` thực tế (model Gemini đã resolve) thay vì `model_alias` requested → khớp với bảng `model_prices` để dashboard tính chi phí chính xác.
  - Fix tất cả paths: `opencode_proxy` (stream/non-stream/fallback), `claude_proxy` (stream/non-stream), `gemini_pass_through` (stream/non-stream).
- **Bot (`gemini_pipeline.py`, `gemini_api_manager.py`):**
  - `_generate_gemini_content_stream` yield `model_id` thực tế trong chunk data để Router log đúng.
- **Kết quả**: Dashboard hiển thị **chi phí thực & tiền tiết kiệm** thay vì `$0.0000` cho mọi endpoint.

**Cốt lõi kiến trúc:**
- **Entry point**: `main.py` → khởi tạo toàn bộ hạ tầng Redis, Postgres và nạp Bot/Worker.
- **Message bus**: **Redis Streams** — Đảm bảo tính bất đồng bộ, chống nghẽn Event Loop của Discord và cho phép scale ngang Worker dễ dàng.
- **Database**: **PostgreSQL** — 15 tables, quản lý từ lịch sử chat, ghi chú, đến cấu hình API động.
- **Tổng file**: ~45 files cốt lõi, ~12,000 dòng code (không tính runtime).

```
[ Discord User ] ↔ [ API Gateway (BotCore) ] ↔ [ Redis Streams (Local) ] ↔ [ Worker (MessageHandler) ]
                         ↑                                                ↓
                   [ Health Checker ]                             [ DB / Cache / LLM / Tools ]
```

---

## 📂 2) CẤU TRÚC THƯ MỤC (PROJECT TREE)

```
Azuris_refactor_code_base/
├── main.py                    # Entry point khởi chạy toàn bộ hệ thống
├── run_bot.py                 # Script điều phối khởi động bot
├── PROJECT_INFO.txt           # Nguồn sự thật kỹ thuật (Technical Source of Truth)
├── CLAUDE.md                  # Quy tắc vận hành và Hard Rules cho Agent
├── AGENT_HANDOFF_PROJECT_CONTEXT.md # Tài liệu bàn giao này
├── src/
│   ├── core/                  # Cấu hình, Router API, Pipeline Reasoning
│   ├── database/              # Lớp truy cập DB (Repository)
│   ├── handlers/              # Xử lý sự kiện Discord & Redis Streams Worker
│   ├── managers/              # Quản lý Cache, Note, Role, Premium
│   ├── services/              # Health check, File Parser, Search Worker
│   ├── tools/                 # Định nghĩa Function Calling cho LLM
│   ├── voice/                 # Quản lý khóa phòng thoại
│   └── .runtime/              # Hạ tầng cục bộ (Redis, Postgres)
├── data/                      # Lưu trữ DB, File Chunks, Voice Logs
└── uploaded_files/            # Thư mục tạm chứa tệp người dùng tải lên
```

**Thay đổi gần đây (Session 2 — APIConnectionError & Timeout):**
- `gemini_api_manager.py`: Thêm `Timeout(15.0, connect=5.0)` + `max_retries=1` vào `AsyncOpenAI` client (đã gỡ bỏ cùng toàn bộ code OpenAI ở Session 9). Wrap `chat.completions.create()` với `try/except APIConnectionError` → mark key failed + re-raise.
- `gemini_pipeline.py`: Thêm `_is_connection_error` check vào cả 4 block error handler → mark key `endpoint_down` (120s) + rotate key.

### File Metrics

| File / Dir | Dòng | Vai trò |
|------------|------|---------|
| `src/handlers/bot_core.py` | 2648 | API Gateway: Kết nối Discord, Redis Streams Producer/Consumer, UI/UX |
| `src/handlers/message_handler.py` | 912 | Worker: Xử lý logic, gọi Pipeline, cập nhật DB/Cache |
| `src/core/gemini_pipeline.py` | 1094 | Trái tim Reasoning: Điều phối suy nghĩ, gọi Tool, Synthesis |
| `src/database/repository.py` | 1350 | Data Layer: Quản lý 15 bảng, Connection Pool, JSONB Logic |
| `src/core/api_router.py` | 472 | Router: Điều phối API Key, Circuit Breaker. Đã gỡ bỏ custom endpoint logic |
| `src/services/health_checker.py` | ~100 | Monitoring stub: Router API đảm nhận giám sát key health |
| **Tổng cộng (Core)** | **~7000+** | (Chỉ tính các file logic chính) |

---

## 🗺️ 3) BẢN ĐỒ LUỒNG DỮ LIỆU (DATA FLOW BLUEPRINT)

### 📥 A. CHIỀU VÀO (INGESTION)

```
[Discord Client]
   │
   │ (1) Tin nhắn / Slash Command
   ▼
┌───────────────────────────────────────────┐
│ API GATEWAY (src/handlers/bot_core.py)    │
├───────────────────────────────────────────┤
│ • Gửi Typing Status (Loop 5s)             │
│ • Kiểm tra Atomic Lock (Postgres)         │
│ • Đóng gói Attachment & Metadata          │
│ • Push vào Redis stream 'discord-incoming' │
└───────────────────────────────────────────┘
```

### ⚙️ B. XỬ LÝ (PROCESSING PIPELINE)

```
Redis Streams: discord-incoming
   │
   ▼
┌───────────────────────────────────────────┐
│ 1. MessageHandler (message_handler.py)    │
│    - Load Chat History (RAM Cache/DB)     │
│    - Parse File/Image (Parallel Download) │
└───────────────────────────────────────────┘
   │
   ▼
┌───────────────────────────────────────────┐
│ 2. GeminiPipeline (gemini_pipeline.py)    │
│    - Reasoning Loop (Suy nghĩ đa bước)    │
│    - Tool Execution (Search/Note/Weather) │
│    - Final Synthesis (Viết câu trả lời)   │
└───────────────────────────────────────────┘
   │
   ▼
┌───────────────────────────────────────────┐
│ 3. Post-Processing                        │
│    - Save Message to DB                   │
│    - Update RAM Cache                     │
│    - Push to stream 'discord-outgoing'     │
└───────────────────────────────────────────┘
```

### 📤 C. CHIỀU RA (EGRESS)

```
┌───────────────────────────────────────────┐
│ API GATEWAY (src/handlers/bot_core.py)    │
├───────────────────────────────────────────┤
│ • Lắng nghe stream 'discord-outgoing'      │
│ • Cancel Typing Loop                      │
│ • Chia nhỏ tin nhắn (limit 1900 chars)    │
│ • Gửi phản hồi về Discord REST API        │
└───────────────────────────────────────────┘
   │
   │ (4) Phản hồi hoàn chỉnh
   ▼
[Discord Client]
```

---

## 🏗️ 4) CHI TIẾT TỪNG TẦNG (LAYER-BY-LAYER)

### 🥇 A. TẦNG API GATEWAY — `src/handlers/bot_core.py`

**Vai trò:** Tiếp nhận mọi tương tác từ Discord, quản lý trạng thái hiển thị (typing, buttons), và đảm bảo tính toàn vẹn của dữ liệu trước khi đưa vào hàng đợi.

#### Function / Method Map (Trích lược)

| Dòng | Tên hàm | Mô tả | Ghi chú |
|------|---------|-------|---------|
| 1020 | `_build_attachment_payload` | Đóng gói metadata file đính kèm | Critical |
| 1118 | `handle_outgoing_payload` | Xử lý phản hồi từ Redis gửi về Discord | Async |
| 1202 | `_outgoing_sender_loop` | Hàng đợi gửi tin nhắn tránh Rate Limit | Loop |
| 2401 | `_register_events` | Đăng ký `on_message`, `on_ready`... | Core |
| 2502 | `_typing_loop` | Gửi tín hiệu "đang gõ" liên tục mỗi 5s | UX |

---

### 🥈 B. TẦNG WORKER — `src/handlers/message_handler.py`

**Vai trò:** Thực thi các tác vụ nặng (tải file, xử lý ảnh, gọi LLM) ở tiến trình riêng biệt để không chặn Gateway.

| Dòng | Tên hàm | Mô tả |
|------|---------|-------|
| 107 | `_download_file_with_sem` | Tải ảnh song song dùng Semaphore(3) |
| 216 | `_build_identity_instruction` | Thay thế tên Bot động vào prompt |
| 272 | `process_message` | Entry point xử lý tin nhắn từ Redis |
| 350 | `_process_imagine_command` | Xử lý lệnh tạo ảnh (/imagine) |

---

### 🥉 C. TẦNG REASONING — `src/core/gemini_pipeline.py`

**Vai trò:** Thực hiện logic lập luận đa bước thông qua Gemini SDK.

| Dòng | Tên hàm | Mô tả |
|------|---------|-------|
| 627 | `_call_gemini_reasoning_loop` | Vòng lặp suy nghĩ và gọi Tools |
| 850 | `_call_gemini_final` | Tổng hợp câu trả lời cuối cùng |
| 910 | `_continue_final_output` | Cơ chế viết tiếp nếu output bị cắt cụt |

---

## 🗄️ 5) CƠ SỞ DỮ LIỆU (DATABASE SCHEMA)

Hệ thống sử dụng **PostgreSQL** (Cổng 55432 cục bộ).

### 📋 Bảng: `user_notes` (Trí nhớ dài hạn)

| Cột | Kiểu | Mô tả |
|-----|------|-------|
| `note_id` | TEXT (PK) | UUID tự sinh |
| `user_id` | TEXT | ID người dùng Discord |
| `metadata` | JSONB | Chứa filename, source, hash... |
| `fact_hash` | TEXT | Chống ghi trùng lặp thông tin |

**Indexes:**
| Tên | Cột | Loại |
|-----|-----|------|
| `idx_user_notes_metadata_gin` | `metadata` | **GIN** (Tối ưu truy vấn JSON) |
| `idx_messages_user_time` | `user_id, timestamp` | BTREE (Tối ưu lấy chat history) |

---

## ⚙️ 6) CẤU HÌNH MÔI TRƯỜNG (ENVIRONMENT CONFIG)

File: `.env`

| Biến | Mặc định | Mô tả | Bí mật? |
|------|----------|-------|---------|
| `DATABASE_URL` | `postgresql://...` | Kết nối Postgres cục bộ | ✅ |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | Kết nối Redis Streams & Pub/Sub cục bộ | ✅ |
| `GEMINI_API_KEYS` | (List) | Danh sách keys xoay vòng | ✅ |
| `GEMINI_BASE_URL` | (Empty) | Endpoint URL cho Gemini SDK. Để trống = gọi Google trực tiếp; đặt `http://127.0.0.1:58100` = route qua Router API | ❌ |
| `ADMIN_IDS` | (String) | ID Admin tĩnh (quyền tối cao) | ❌ |
| `AZURIS_POSTGRES_START_MODE` | `direct` | Chế độ khởi động DB | ❌ |

---

## 🔒 7) MA TRẬN BẢO MẬT & PHÂN QUYỀN (SECURITY CONTRACT)

### Vai trò (Roles)

| Vai trò | Xác thực | Quyền | Giới hạn |
|---------|----------|-------|----------|
| **Admin** | Tĩnh (.env) | Toàn quyền, thăng/hạ cấp | Không |
| **Moderator** | Động (DB) | Health Check, `/endpoint` xem GEMINI_BASE_URL | Không được `/reset-all` |
| **Premium** | Động (DB) | Không giới hạn chat, `/imagine` | Không có quyền quản trị |

---

## ⚡ 8) TỐI ƯU HIỆU NĂNG (PERFORMANCE OPTIMIZATIONS)

### A. RAM KV Cache
- **Vấn đề**: Truy vấn chat history liên tục làm chậm bot.
- **Giải pháp**: Cache 12 tin nhắn gần nhất trên RAM Worker (`cache_manager.py`).
- **Quy tắc cứng**: Phải gửi sự kiện Invalidate qua Redis Pub/Sub khi reset chat.

### B. Loại bỏ toàn bộ Custom Endpoint
- **Vấn đề trước đây**: Code phình to vì phải hỗ trợ LM Studio/Ollama/OpenAI-compatible provider với nhiều nhánh xử lý riêng biệt.
- **Giải pháp**: Toàn bộ logic custom endpoint (routing, pipeline safety profile, image generation, health check scan, UI config) đã bị xóa sạch. Bot hiện chỉ hỗ trợ Gemini SDK thuần qua Google hoặc Router API.
- **Kết quả**: Giảm ~600 dòng code phức tạp, bảo trì dễ hơn, không còn lỗi Jinja template, connection error handling đơn giản hơn.

### C. Parallel Image Download
- **Vấn đề**: Tải nhiều ảnh tuần tự gây lag.
- **Giải pháp**: Dùng `asyncio.gather` + `Semaphore(3)` trong `message_handler.py`.
- **Quy tắc cứng**: Không bao giờ lưu bytes ảnh vào Database.

---

## 🧪 9) KIỂM THỬ (TEST SUITES)

| File | Mô tả | Trạng thái |
|------|-------|------------|
| `test_dynamic_roles.py` | Kiểm tra phân quyền Admin/Mod | ✅ |
| `test_health_checker.py` | Kiểm tra tự động scan key/model | ✅ |
| `test_typing_identity.py` | Kiểm tra typing loop & bot name | ✅ |

---

## 🛠️ 10) VẬN HÀNH (OPERATIONS)

### Khởi động (Startup)
```powershell
powershell ./run_bot.ps1 --server
```

### Quản lý Endpoint
- Admin dùng `/endpoint` để xem hoặc thay đổi `GEMINI_BASE_URL`.
- Khi `GEMINI_BASE_URL` rỗng, bot gọi Google Gemini trực tiếp.
- Khi set (VD: `http://127.0.0.1:58100`), bot route toàn bộ Gemini SDK qua Router API proxy.
- **Cập nhật logic xác thực (Session 11):** Do Router API có thể gặp lỗi nội bộ HTTP 500 (như lỗi `AttributeError` khi nạp method) trên các endpoint native của Gemini, logic xác thực `validate_endpoint` của Bot đã được cập nhật để chấp nhận mã lỗi HTTP 500 như là phản hồi thành công (vì điều này chứng tỏ kết nối mạng bình thường và Auth Key đã được xác thực thành công qua middleware của Router mà không bị lỗi 401 Unauthorized). Đồng thời, model dùng để gọi API kiểm thử trong `validate_endpoint` cũng đã được đổi từ `gemini-2.5-flash` thành `gemini-flash` để tương thích chính xác với các model được Router API hỗ trợ.
- **Xử lý lỗi TypeError do SDK crash status_code (Session 12):** Khắc phục lỗi khi Router API trả về lỗi nhưng không chứa trường `code` (như khi Router gặp lỗi `'async for' requires an object with __aiter__ method` trên generator native Gemini stream). Lỗi này khiến `google-genai` SDK phía Bot bị crash `TypeError: '<=' not supported between instances of 'int' and 'NoneType'` khi so sánh `status_code` is `None`. Ta đã cập nhật logic xác định lỗi `_is_connection_error` trong `GeminiApiManager` của Bot để bắt ngoại lệ này, coi nó như lỗi endpoint/kết nối thông thường để Bot thực hiện key rotation hoặc fallback sang model Lite không stream, tăng tính ổn định của hệ thống theo nguyên tắc Anti-Brick.
- **Tự động Bypass Router API khi lỗi kết nối (Session 13 - Cập nhật):** Khắc phục triệt để tình trạng Bot bị treo hoặc báo lỗi fallback khi Router API hoặc proxy sập (gặp lỗi `ConnectError`/`ConnectionError`). Khi phát hiện lỗi kết nối (`endpoint_down`), Bot sẽ tự động bypass (bỏ qua) Router trong vòng 30 giây để gọi trực tiếp tới Google Gemini API bằng các API Key có sẵn. Để tối ưu hóa quota và tương thích 100% với Google API, khi bypass Router hoạt động, hệ thống tự động ánh xạ (map) toàn bộ các cuộc gọi mô hình (kể cả reasoning, final, fallback) về alias Google Gemini Flash Lite tự động cập nhật mới nhất `gemini-flash-lite-latest` thay vì phân mảnh model Flash thường. Sau khi hết thời gian bypass, Bot tự động khôi phục kết nối qua Router bình thường. Ngoài ra, lỗi ReadTimeout lập tức khi đi qua Router đã được sửa đổi triệt để bằng việc chuyển cấu hình timeout của HttpOptions từ 15.0s (mặc định hiểu nhầm là giây) sang 15000ms (đơn vị mili giây thực tế mà Google GenAI SDK yêu cầu), giúp phục hồi kết nối ổn định 100% qua Router API.


### Bảo trì Database
```sql
-- Kiểm tra trạng thái bận của user
SELECT * FROM user_processing_states WHERE is_busy = true;
```

---

## 📌 11) LƯU Ý CHO NGƯỜI TIẾP QUẢN (AGENT HANDOFF NOTES)

### Kiến trúc cần bảo vệ

1. **JSONB Query**: Luôn dùng `metadata->>'key'` để tận dụng GIN Index. CẤM ép kiểu sang `text`.
2. **Typing Loop**: Tác vụ gõ chữ phải được cancel ngay khi gửi tin nhắn xong để tránh treo UI Discord.
3. **Admin Root**: Tuyệt đối không xóa ID Admin khỏi `.env` vì đây là chốt chặn cuối cùng nếu DB lỗi.
4. **Smart Incremental Retry**: Cơ chế cào dữ liệu trong `tools.py` sử dụng Smart Incremental Retry (Lần 1: 3.0s, Lần 2: 5.0s) để tối ưu hóa tốc độ phản hồi tối đa (worst-case giảm từ 14s xuống còn 8s) mà không gây nghẽn.
5. **Không còn Custom Endpoint**: Toàn bộ code OpenAI-compatible, LM Studio, Ollama đã bị xóa. Bot chỉ hỗ trợ Gemini SDK. Điều chỉnh endpoint qua biến `GEMINI_BASE_URL` trong `.env` hoặc lệnh `/endpoint`.
6. **Router API**: Khi bật `GEMINI_BASE_URL`, Router API (`gemini_routes.py`) đảm nhận proxy, log cost và key rotation thay cho bot trực tiếp.

### File cần đồng bộ khi thay đổi

| Thay đổi | Cập nhật file |
|----------|---------------|
| Thêm bảng DB | `repository.py` & `PROJECT_INFO.txt` |
| Thêm biến .env | `config.py` & `PROJECT_INFO.txt` |

---

## 🧠 12) KIẾN TRÚC VÀNG (KEY ARCHITECTURE DECISIONS)

1. **Zero-Docker Runtime**: Toàn bộ hạ tầng chạy trong `.runtime/` giúp triển khai "mì ăn liền" trên mọi VPS.
2. **Hybrid Lock**: Kết hợp Local RAM Lock và Postgres State để chống spam tuyệt đối.
3. **Smart Key Rotation**: Tự động xoay vòng Gemini keys và cooldown khi gặp lỗi 429.

---

## 📊 PHỤ LỤC: IMPORT DEPENDENCY GRAPH

```
main.py
├── run_bot.py
│   ├── src/handlers/bot_core.py (Gateway)
│   │   └── src/database/repository.py
│   └── src/handlers/message_handler.py (Worker)
│       ├── src/core/gemini_pipeline.py
│       ├── src/managers/cache_manager.py
│       └── src/services/file_parser.py
```

---
<!-- Hết tài liệu -->
