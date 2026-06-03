# 📑 AZURIS BOT — CẨM NANG BÀN GIAO (HANDOFF PROTOCOL)

<!-- AI-READABLE + HUMAN-READABLE HYBRID -->
<!-- Generated: 2026-06-01 | Runtime: Python 3.11+ | Platform: Win32/Linux -->
<!-- Template v2 — Hybrid Narrative + Structured (Customized for Azuris) -->

---

## 🚀 1) TỔNG QUAN HỆ THỐNG (EXECUTIVE SUMMARY)

**Azuris** là một trợ lý AI tiên tiến trên Discord, tích hợp khả năng lập luận đa bước (Reasoning), gọi công cụ thời gian thực và quản lý ngữ cảnh dài hạn. Hệ thống hoạt động theo mô hình **Event-Driven Architecture (Kiến trúc Hướng Sự kiện)** với 2 services chính: **Gateway (BotCore)** và **Worker (MessageHandler)** kết nối qua **Apache Kafka**.

**Thay đổi gần đây (Session 3 — Health Check UI & LLM Report):**
- `health_checker.py`: Xóa hoàn toàn LLM report (`_generate_recovery_report` giờ trả text static, không gọi Gemini). Gỡ `GeminiApiManager` dependency khỏi service.
- `bot_core.py` (`/health_check`): Chuyển từ text thuần sang `discord.Embed` với field API Keys (✅/❌), Ping Model, Model Scan + màu xanh/cam theo trạng thái.

**Thay đổi gần đây (Session 4 — Script Review PS1/SH):**
- Review toàn bộ 6 script (`run_bot.ps1`, `install_services.ps1`, `stop_infra.ps1` + 3 `.sh` tương ứng).
- **Kết luận:** Không có lỗi critical. Các fix Kafka Windows (log4j, .deleted cleanup, `log.cleaner.enable=false`) đã hoạt động ổn. Linux scripts không cần các workaround đó.
- Minor: `credentials.env` thiếu permission hardening trên Windows. `install_services.sh` dùng `|| true` nhiều có thể che lỗi thật sau này.

**Cốt lõi kiến trúc:**
- **Entry point**: `main.py` → khởi tạo toàn bộ hạ tầng Kafka, Postgres và nạp Bot/Worker.
- **Message bus**: **Apache Kafka** — Đảm bảo tính bất đồng bộ, chống nghẽn Event Loop của Discord và cho phép scale ngang Worker dễ dàng.
- **Database**: **PostgreSQL** — 15 tables, quản lý từ lịch sử chat, ghi chú, đến cấu hình API động.
- **Tổng file**: ~45 files cốt lõi, ~12,000 dòng code (không tính runtime).

```
[ Discord User ] ↔ [ API Gateway (BotCore) ] ↔ [ Kafka (Local) ] ↔ [ Worker (MessageHandler) ]
                         ↑                                           ↓
                  [ Health Checker ]                        [ DB / Cache / LLM / Tools ]
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
│   ├── handlers/              # Xử lý sự kiện Discord & Kafka Worker
│   ├── managers/              # Quản lý Cache, Note, Role, Premium
│   ├── services/              # Health check, File Parser, Search Worker
│   ├── tools/                 # Định nghĩa Function Calling cho LLM
│   ├── voice/                 # Quản lý khóa phòng thoại
│   └── .runtime/              # Hạ tầng cục bộ (Java, Kafka, Postgres)
├── data/                      # Lưu trữ DB, File Chunks, Voice Logs
└── uploaded_files/            # Thư mục tạm chứa tệp người dùng tải lên
```

**Thay đổi gần đây (Session 2 — APIConnectionError & Timeout):**
- `gemini_api_manager.py`: Thêm `Timeout(15.0, connect=5.0)` + `max_retries=1` vào `AsyncOpenAI` client. Wrap `chat.completions.create()` với `try/except APIConnectionError` → mark key failed + re-raise.
- `gemini_pipeline.py`: Thêm `_is_connection_error` check vào cả 4 block error handler → mark key `endpoint_down` (120s) + rotate key.

**Thay đổi gần đây (Session 1 — Kafka Windows fix):**
- `run_bot.ps1` + `install_services.ps1`: Dọn `.deleted` file trước start Kafka, inject `log.cleaner.enable=false`, retention settings.
- `src/.runtime/config/kafka/log4j.properties`: File-only appenders, bỏ ConsoleAppender để tránh PowerShell pipe deadlock.

### File Metrics

| File / Dir | Dòng | Vai trò |
|------------|------|---------|
| `src/handlers/bot_core.py` | 2648 | API Gateway: Kết nối Discord, Kafka Producer/Consumer, UI/UX |
| `src/handlers/message_handler.py` | 912 | Worker: Xử lý logic, gọi Pipeline, cập nhật DB/Cache |
| `src/core/gemini_pipeline.py` | 1094 | Trái tim Reasoning: Điều phối suy nghĩ, gọi Tool, Synthesis |
| `src/database/repository.py` | 1350 | Data Layer: Quản lý 15 bảng, Connection Pool, JSONB Logic |
| `src/core/api_router.py` | 472 | Router: Điều phối API Key, Circuit Breaker, Custom Endpoint |
| `src/services/health_checker.py` | 532 | Monitoring: Kiểm tra sức khỏe key, báo cáo khôi phục |
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
│ • Push vào Kafka topic 'discord-incoming' │
└───────────────────────────────────────────┘
```

### ⚙️ B. XỬ LÝ (PROCESSING PIPELINE)

```
Kafka: discord-incoming
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
│    - Push to topic 'discord-outgoing'     │
└───────────────────────────────────────────┘
```

### 📤 C. CHIỀU RA (EGRESS)

```
┌───────────────────────────────────────────┐
│ API GATEWAY (src/handlers/bot_core.py)    │
├───────────────────────────────────────────┤
│ • Lắng nghe topic 'discord-outgoing'      │
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
| 1118 | `handle_outgoing_payload` | Xử lý phản hồi từ Kafka gửi về Discord | Async |
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
| 272 | `process_message` | Entry point xử lý tin nhắn từ Kafka |
| 350 | `_process_imagine_command` | Xử lý lệnh tạo ảnh (/imagine) |

---

### 🥉 C. TẦNG REASONING — `src/core/gemini_pipeline.py`

**Vai trò:** Thực hiện logic lập luận đa bước thông qua Gemini hoặc Custom Models.

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
| `GEMINI_API_KEYS` | (List) | Danh sách keys xoay vòng | ✅ |
| `ADMIN_IDS` | (String) | ID Admin tĩnh (quyền tối cao) | ❌ |
| `AZURIS_POSTGRES_START_MODE` | `direct` | Chế độ khởi động DB | ❌ |

---

## 🔒 7) MA TRẬN BẢO MẬT & PHÂN QUYỀN (SECURITY CONTRACT)

### Vai trò (Roles)

| Vai trò | Xác thực | Quyền | Giới hạn |
|---------|----------|-------|----------|
| **Admin** | Tĩnh (.env) | Toàn quyền, thăng/hạ cấp | Không |
| **Moderator** | Động (DB) | Config API, Health Check | Không được `/reset-all` |
| **Premium** | Động (DB) | Không giới hạn chat, `/imagine` | Không có quyền quản trị |

---

## ⚡ 8) TỐI ƯU HIỆU NĂNG (PERFORMANCE OPTIMIZATIONS)

### A. RAM KV Cache
- **Vấn đề**: Truy vấn chat history liên tục làm chậm bot.
- **Giải pháp**: Cache 12 tin nhắn gần nhất trên RAM Worker (`cache_manager.py`).
- **Quy tắc cứng**: Phải gửi sự kiện Invalidate qua Kafka khi reset chat.

### B. Parallel Image Download
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
