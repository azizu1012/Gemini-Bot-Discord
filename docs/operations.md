# Vận hành & Tham khảo Azuris

## Hạ tầng cục bộ (Zero-Docker)

Toàn bộ hạ tầng chạy trong `src/.runtime/`:

```
.runtime/
├── redis/            # Redis binaries & data
├── postgres/         # PostgreSQL engine & data cluster
├── config/           # postgresql.conf, pg_hba.conf
├── logs/             # stdout/stderr logs
├── run/              # PID files
└── downloads/        # Temp download cache
```

### Vòng đời
1. **Bootstrap**: `install_services.ps1` / `.sh` → tải Redis (tporadowski 5.0.14.1), PostgreSQL 16, init cluster
2. **Khởi chạy**: `run_bot.ps1 --server` → dọn tiến trình cũ → Redis → PostgreSQL
3. **Tắt**: `stop_infra.ps1` → graceful stop → force kill nếu timeout
4. **Tắt bot**: `stop_bot.ps1` → quét `.venv` Python processes

### Khởi động lần đầu

```powershell
# Windows
pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File .\install_services.ps1
# Sau đó điền .env
powershell .\run_bot.ps1 --preflight-only
powershell .\run_bot.ps1 --server
```

```bash
# Linux
chmod +x install_services.sh run_bot.sh stop_infra.sh
./install_services.sh
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./run_bot.sh --preflight-only
./run_bot.sh --pm2 --server
```

### Dừng
```powershell
# Windows
powershell .\stop_infra.ps1    # Tắt Redis + PostgreSQL
powershell .\stop_bot.ps1      # Tắt tiến trình Python
```
```bash
# Linux
./stop_infra.sh
pm2 stop azuris-bot
```

### Logs
- File chính: `bot.log` (RotatingFileHandler)
- Runtime logs: `src/.runtime/logs/`
- PM2 (Linux): `pm2 logs azuris-bot --lines 100`

### Chi tiết lỗi & chẩn đoán
Xem [`docs/incidents.md`](incidents.md) để biết các sự cố đã gặp (CPU 100%, re-read vô hạn, RESP3), nguyên nhân và cách khắc phục.

### Bảo trì DB
```sql
-- Kiểm tra user đang xử lý
SELECT * FROM user_processing_states WHERE is_busy = true;
-- Xóa lock treo
UPDATE user_processing_states SET is_busy = false, current_stage = ''
WHERE is_busy = true AND last_updated < NOW() - INTERVAL '5 minutes';
```

### Cập nhật endpoint

```powershell
# Discord (ADMIN)
/endpoint config      # chọn SDK → URL/key → 4 slot model
/endpoint view
/endpoint switch      # đổi SDK active thủ công
/endpoint models      # fetch lại danh sách model
/endpoint test        # ping + latency + kiểm tra slot
```

Chi tiết: [`endpoint_and_models.md`](endpoint_and_models.md).

## Gemini Pipeline & Reasoning

### Kiến trúc Pipeline

```
GeminiPipeline.execute()
    ├── 1. Reasoning Loop (gemini-flash)
    │   System prompt + chat history + tools
    │   Model → functionCall hoặc text
    │   Nếu functionCall → execute tool → append result → loop
    │   Max REASONING_MAX_LOOPS (mặc định 3)
    └── 2. Final Synthesis (gemini-flash, streaming)
        Reasoning transcript → tổng hợp câu trả lời
        Stream real từ Google GenAI SDK
        Gom chunks → MockResponse
        Continuation nếu finish_reason = MAX_TOKENS
```

### Model Slots

| Slot | Vai trò | Default khi bỏ trống |
|------|---------|----------------------|
| `reasoning` | Reasoning loop + tools | `final` |
| `final` | Tổng hợp câu trả lời | Model đầu tiên trong danh sách |
| `fallback` | Retry khi model chính lỗi | `reasoning` → `final` |
| `vision` | Phân tích ảnh | `final` |

### Fallback
- Lỗi model chính → retry cùng model theo `*_MAX_API_RETRIES` → thử `fallback` đúng 1 lần.
- Fallback luôn cùng provider/SDK active; muốn đổi provider → `/endpoint switch` thủ công.
- Chain-of-Thought được bảo toàn (thought, thought_signature trong `genai_types.Part`).

## Slash Commands

### Admin
| Lệnh | Mô tả |
|------|-------|
| `/endpoint` | Cấu hình endpoint: config / view / switch / models / test |
| `/health_check` | Endpoint active + latency + 4 model slot + PostgreSQL |
| `/moderator` | Thăng/hạ Moderator động |
| `/premium` | Thêm/xóa Premium |
| `/rolerank` | Kéo thứ tự role trong server bằng menu tương tác |
| `/change bd` | Đổi biệt danh thành viên trong server |
| `/reset-all` | Reset DB + xóa cache |
| `/global-notes` | Xem ghi chú global |
| `/message_to` | Gửi DM / tin nhắn cross-server |
| `/donate` | Hiển thị QR donate (tự xóa sau 2 phút) |

### Moderator
| Lệnh | Mô tả |
|------|-------|
| `/health_check` | Endpoint active + latency + 4 model slot + PostgreSQL |
| `/global-notes` | Xem ghi chú global |
| `/message_to` | Nhắn nội bộ guild |
| `/imagine` | Tạo ảnh (giới hạn) |

### Voice & Room (Owner / Allowlist)
| Lệnh | Mô tả |
|------|-------|
| `/lock` / `/unlock` | Khóa/mở phòng voice hiện tại, kick người ngoài và dọn tin nhắn |
| `/locklist` | Xem danh sách các phòng voice đang khóa |
| `/allow` / `/allowremove` | Thêm hoặc xóa người khỏi allowlist (alias: `/add_privet`, `/remove_privet`) |
| `/allowlist` | Xem danh sách người trong allowlist (alias: `/list_privet`) |
| `/move` / `/move_all` | Di chuyển 1 thành viên hoặc cả nhóm allowlist sang phòng khác |
| `/set_room` | Đổi tên/status phòng (khóa tên nếu phòng đang bị lock) |

### Tất cả users
| Lệnh | Mô tả |
|------|-------|
| `/ping` | Kiểm tra độ trễ |
| `/reset-chat` | Xóa lịch sử trò chuyện |

## Kiểm thử

### Test files
| File | Mô tả |
|------|-------|
| `tests/test_*.py` | Bộ unit test (pytest-compatible) |

### Chạy test
```powershell
Get-ChildItem tests\test_*.py | ForEach-Object { python $_.FullName }
```
Pytest chính thức bật ở Phase 2 (CI). `tests/` không bị gitignore.

### Kết quả đã xác minh
1. Dynamic Roles: Pass 100%
2. Health Checker: Pass 100%
3. RAM KV Cache: Pass 100% (0ms hit, TTL 300s, LRU, Redis Pub/Sub invalidation)
4. Security Audit: Pass 100% (SQL Injection, Race Condition 5 luồng)
5. Multimodal Image: Pass 100% (song song, RAM-Only)
6. Smoke Test: Preflight + Run bot → Discord Gateway connected
7. Endpoint-only refactor (Phase 1): 13 file test PASS — xem PR.

## Lịch sử thay đổi

### Session 2 — APIConnectionError & Timeout
Thêm `_is_connection_error` handler, mark key `endpoint_down` (120s) + rotate.

### Session 3 — Health Check UI
Health checker xóa LLM report, `/health_check` dùng Embed ✅/❌.

### Session 7 — Real Streaming
Final synthesis gọi stream real, MockResponse wrapper.

### Session 8 — Cost Tracking
Log usage cho streaming, dùng model_id thực tế.

### Session 9 — Gỡ bỏ Custom Endpoint
Xóa `api_proxy.py`, `custom_endpoint.py`. `GEMINI_BASE_URL` mới. Chỉ hỗ trợ Gemini SDK.

### Session 10 — Fix crash + Redis upgrade
Fix NameError/IndentationError bot_core.py. Redis 3.2.100 → 5.0.14.1 (Streams).

### Session 11 — Validate endpoint 500
Chấp nhận HTTP 500 thành công. Model test đổi `gemini-2.5-flash` → `gemini-flash`.

### Session 12 — SDK crash TypeError
Bắt TypeError `'<=' not supported`, coi như connection error.

### Session 13 — Router Bypass + Timeout
Bypass Router 30s khi ConnectError. Timeout 15000ms (int).

### Session 14 — Redis Streams ACK fix + LSP cleanup
- **Redis ACK bug fix**: Xoá `xack()` khỏi `__anext__()` → ACK chỉ sau khi `_publish_outgoing` thành công
- **PEL reclaim**: Thêm `reclaim_pending()` (XCLAIM) + đọc pending trước new (`'0'` → `'>'`)
- **Gateway ACK**: BotCore ACK `discord-outgoing` chỉ sau khi Discord API trả về thành công
- **0 LSP errors**: Fix 48 type errors (import stubs, Optional guards, type narrowing, discord.py stub mismatches)

### Session 15 — Xoá DummyAttachment, refactor FileParserService
- **Xoá `DummyAttachment`**: Class mock giả lập `discord.Attachment` bị xoá hoàn toàn
- **`FileParserService` không còn phụ thuộc `discord`**: `_download_attachment`, `parse_attachment`, `prepare_file_for_indexing` nhận `url: str`, `filename: str`, `size: int` trực tiếp thay vì `discord.Attachment`
- **Xoá `import discord` khỏi `file_parser.py`**: Module thuần utility, không biết gì về Discord model
- **Caller sửa native**: `message_handler.py` gọi `prepare_file_for_indexing(url, filename, size=...)` trực tiếp, không qua DummyAttachment wrapper

### Session 16 — Router 500 isolation + google-genai 2.8.0
- **Xoá `router_bypass_until`**: Loại bỏ hybrid fallback router→Google direct khỏi `gemini_api_manager.py`
- **Xoá 500→endpoint_down handlers**: 3 handler trong `gemini_pipeline.py` removed — không còn fallback router→direct khi 500
- **Fix config.py log**: Hiển thị "Router mode" / "Direct mode" thay vì "Smart Rotation" gây hiểu nhầm
- **Upgrade google-genai**: `1.52.0` → `2.8.0` (khớp version router, internal tenacity retry mạnh hơn)
- **Clean test scripts**: Xoá 14 test script tạm thời khỏi project root
- **Router fix**: `handle_error` trong router không còn raise RuntimeError cho `bad_request`/`project_denied` — freeze key + thử key tiếp theo, không ngắt retry loop

### Session 17 — Endpoint-only refactor
- Gỡ key rotation: `gemini_api_manager.py`, `api_router.py`, `api_config.py`, `gemini_rate_limiter.py`
- Thêm `src/core/llm/` (2 SDK: genai/openai), bảng `llm_endpoints` + `llm_model_slots`
- Nhóm lệnh `/endpoint` + `/health_check` mới; gate "chưa cấu hình"
- 4 model slot + fallback 1 lần cùng provider; key mã hóa Fernet
- Test mới trong `tests/`; CI + security scan ở Phase 2, tách god-file ở Phase 3
