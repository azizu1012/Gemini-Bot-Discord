# Vận hành & Tham khảo Azuris

## Hạ tầng Docker (chuẩn)

`docker compose up -d --build` dựng đúng 3 service, thay thế binary portable cũ trong `src/.runtime/`:

| Service | Image | Vai trò | Data |
|---------|-------|---------|------|
| `bot` | build từ `Dockerfile` (py3.12-slim, non-root, 1 replica) | `python run_bot.py` | bind `./data`, `./uploaded_files`, `./logs`, `./assets/encrypted:ro` |
| `postgres` | `postgres:16` | Thay `src/.runtime/postgres` | bind `./data/postgres` + seed `./data/db_seed/azuris.sql` |
| `redis` | `redis:7-alpine` (`--save "" --appendonly no`) | Thay `src/.runtime/redis`, giữ semantic queue thuần | ephemeral |

Không publish port nào ra host: bot chỉ dial-out (Discord WS, LLM endpoint, search APIs); DB/Redis nói chuyện qua mạng nội bộ Compose. Cấu trúc `src/.runtime/` cũ xem [`deprecated.md`](deprecated.md):

```
.runtime/            # legacy, không dùng nữa
├── redis/            # Redis binaries & data
├── postgres/         # PostgreSQL engine & data cluster
├── config/           # postgresql.conf, pg_hba.conf
├── logs/             # stdout/stderr logs
├── run/              # PID files
└── downloads/        # Temp download cache
```

### Vòng đời (1 nút duy nhất: `run_bot.ps1` / `run_bot.sh`)
```powershell
.\run_bot.ps1              # build (nếu cần) + start toàn stack
.\run_bot.ps1 stop-bot     # chỉ tắt bot, giữ postgres/redis chạy
.\run_bot.ps1 stop-infra   # chỉ tắt infra, giữ container và data
.\run_bot.ps1 down         # tắt hết, giữ data
.\run_bot.ps1 logs         # log bot live
.\run_bot.ps1 ps           # trạng thái + RAM từng service
# đủ lệnh: up|down|stop-bot|stop-infra|rebuild|restart|logs [svc]|ps|seed|backup|update
```
Tương đương Docker thô: `docker compose up -d --build`, `docker compose stop bot`, `docker compose stop postgres redis`, `docker compose down`.
# reset toàn bộ: tắt stack, xóa nội dung data/postgres, up lại -> seed bung từ file

### Data & seed portable (đường dẫn tương đối — Windows/Linux đều chạy)
- Mọi mount đều là **relative** (`./data` gồm cả `./data/postgres` DB engine + `./data/db_seed` seed file, `./uploaded_files`, `./logs`): clone sang máy khác không sửa gì, seed tự bung full DB (endpoint config, history, notes) khi folder `data/postgres` còn trống — không bao giờ new-database.
- Refresh seed từ stack đang chạy:
```powershell
docker compose exec -T postgres pg_dump -U azuris -d azuris --no-owner --no-privileges --clean --if-exists -F p -f /tmp/seed.sql
docker cp azuris-postgres-1:/tmp/seed.sql data/db_seed/azuris.sql
```
- Backup DB đúng nghĩa: `docker compose exec postgres pg_dump -U azuris azuris > backup.sql`.

### Legacy local (ĐÃ GỠ — Session 21)
Runner trực tiếp cũ + toàn bộ `src/.runtime/` (~1GB) đã xóa. Docker là runtime duy nhất — xem [`deprecated.md`](deprecated.md).

### Logs (Docker)
- `docker compose logs -f bot` — log bot (ghi ra `./logs/bot.log` qua `BOT_LOG_PATH`)
- `docker compose logs postgres | redis` — log hạ tầng

### CI/CD (GitHub Actions → GHCR)
- `ci.yml`: compile + pytest (Postgres/Redis service containers) trên `main` và PR.
- `secret_scan.yml`: chặn credential mới trong diff; liệt kê finding cũ.
- `docker.yml`: validate Compose → build image → Trivy scan (fail khi có CRITICAL/HIGH sửa được) → push `ghcr.io/<owner>/<repo>` (`:latest` cho main, `:<short-sha>`, `:vX.Y.Z` cho tag). PR build + scan, không push. Cache layer bằng GHA.
- CD = pull-based, không SSH: trên máy deploy đặt `BOT_IMAGE=ghcr.io/<owner>/<repo>:<tag>` vào `.env` rồi `docker compose pull && docker compose up -d`. Không cần Docker Hub.
- Muốn merge an toàn: bật branch protection yêu cầu 3 check (CI, Secret Scan, Docker) pass.

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
/endpoint config      # chọn SDK → URL/key → 3 slot model
/endpoint view
/endpoint switch      # đổi SDK active thủ công
/endpoint models      # fetch lại danh sách model
/endpoint test        # ping + latency + kiểm tra slot
```

Chi tiết: [`endpoint_and_models.md`](endpoint_and_models.md).

## Gemini Pipeline & Reasoning

### Kiến trúc Pipeline

```
GeminiPipeline.execute()  [COMPLEX — sau NLP gate]
    ├── 1. Reasoning Loop (gemini-flash-lite, temp 0.35, max 2600 tokens)
    │   System prompt + chat history + tools
    │   Model → functionCall hoặc text
    │   Nếu functionCall → execute tool 1 round → defer về synthesis
    │   Max REASONING_MAX_LOOPS (mặc định 3)
    └── 2. Final Synthesis (gemini-flash, streaming)
        Reasoning transcript → tổng hợp câu trả lời
        Stream real từ Google GenAI SDK
        Gom chunks → MockResponse
        Continuation nếu finish_reason = MAX_TOKENS
```

Đường tắt EASY (trước pipeline — `src/core/nlp_gate.py`, ~1ms, offline):
chào hỏi/xã giao, không attachment, không RAG context → 1 call lite
(model slot `reasoning`, sandwich rút gọn, không tool), fail-open về full
pipeline khi gate COMPLEX hoặc EASY lỗi/timeout (60s).

### Model Slots (3 slot — slot `vision` đã bỏ ở PR #27, resolve về `final`)

| Slot | Vai trò | Default khi bỏ trống |
|------|---------|----------------------|
| `reasoning` | Reasoning loop + tools | `final` |
| `final` | Tổng hợp câu trả lời | Model đầu tiên trong danh sách |
| `fallback` | Retry khi model chính lỗi | `reasoning` → `final` |

### Fallback
- Lỗi model chính → retry cùng model theo `*_MAX_API_RETRIES` → thử `fallback` đúng 1 lần.
- Fallback luôn cùng provider/SDK active; muốn đổi provider → `/endpoint switch` thủ công.
- Chain-of-Thought được bảo toàn (thought, thought_signature trong `genai_types.Part`).

## Slash Commands

### Admin
| Lệnh | Mô tả |
|------|-------|
| `/endpoint` | Cấu hình endpoint: config / view / switch / models / test |
| `/health_check` | Endpoint active + latency + 3 model slot + PostgreSQL |
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
| `/health_check` | Endpoint active + latency + 3 model slot + PostgreSQL |
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
- 3 model slot + fallback 1 lần cùng provider; key mã hóa Fernet
  (lúc ship là 4 slot; slot `vision` bỏ ở PR #27, resolve về `final`)
- Test mới trong `tests/`; CI + security scan ở Phase 2, tách god-file ở Phase 3

### Session 18 — NLP gate + google-genai 2.33.0 + đánh giá ADK
- **Đường tắt EASY**: `src/core/nlp_gate.py` (pure stdlib, ~1ms, offline — bỏ dấu/teencode + char 3-gram cosine, ngưỡng 0.50, precision 1.00 trên golden set `tests/test_nlp_gate.py`). Chào hỏi/xã giao → 1 call lite + sandwich rút gọn, không tool; fail-open COMPLEX.
- **Wire vào `message_handler.process_message`**: `_call_easy_with_deadline` (timeout 60s), phân loại trên raw text trước intent cues, loại trừ attachment/RAG context.
- **Upgrade google-genai**: `2.8.0` → `2.33.0` (`requirements.txt`); batch test xanh (llm base/genai/openai/gateway, nlp_gate, layering, handler timeout+concurrency — 16 passed).
- **Đánh giá Google ADK 2.13.0 rồi KHÔNG chọn**: spike đối đầu (`LlmAgent`+`Runner`+`FunctionTool` vs pipeline thật, chung sandwich final thật) cho transcript tương đương nhưng không thêm capability; 1-model multi-pass lộ lỗi trả lời nhầm meta-prompt; debug xuyên abstraction đắt; framework còn xoay. Chi tiết: `docs/architecture.md` (§Quyết định kiến trúc).

### Session 19 — Docker hóa + DB seed portable + dọn script infra cũ
- **Chuẩn runtime mới**: `Dockerfile` (py3.12-slim, non-root UID 1000, không bake secret) + `docker-compose.yml` (bot 1 replica + `postgres:16` + `redis:7-alpine` ephemeral, không publish port) + `.dockerignore` (chặn `.env`, `.venv/`, `src/.runtime/`).
- **DB ngoài image**: seed `data/db_seed/azuris.sql` qua `/docker-entrypoint-initdb.d`; data live trong bind `./data/postgres` (subfolder của `/data`, tách riêng khỏi file app của bot). Verify: 208 messages / 2 endpoints / 6 slots / 1 note khớp DB cũ. Lệnh 1-phát: `run_bot.ps1` / `run_bot.sh` (`up|down|stop-bot|stop-infra|rebuild|restart|logs|ps|seed|backup|update` — tách dừng bot/infra như cơ chế cũ).
- **Giới hạn RAM** (Docker Desktop cap 4GB): postgres 768m, redis 256m (+`tmpfs /data` chặn volume mồ côi), bot 1g.

### Session 20 — Trivy gate xanh (bài học về false positive)
- Trivy fail 26 HIGH thật → nâng dependency (`aiohttp` 3.14.4, `cryptography` 50.0.0, `pypdf` 6.21.2, `urllib3` 2.8.0, `msgpack` 1.2.3, `setuptools` 84.2.1, `wheel` 0.46.2, `jaraco.context` 6.1.0).
- 7 HIGH còn lại KHÔNG phải package cũ: 2 từ dist-info vendored trong `setuptools/_vendor` (jaraco 5.3.0, wheel 0.45.1 — `setuptools` 84.2.1 vendor bản đã vá nên tự hết), 5 từ `pip/_vendor/bom.cdx.json` (SBOM của deps vendored trong pip, chỉ dùng lúc build) → `skip-files` file SBOM này, dist-info thật vẫn quét.
- Bài học: đừng tin ngay "cache cũ" — moi log `pip install` trong CI ra đối chiếu mới thấy root cause thật (vendored/SBOM). Build CI để `no-cache` cho tính đúng đắn tuyệt đối.
- **Compose override URL**: `DATABASE_URL`/`REDIS_URL` trong `environment` thắng `.env` (trỏ sang service nội bộ); `BOT_LOG_PATH=/app/logs/bot.log` tránh ghi writable layer; healthcheck bot = `run_bot.py --preflight`.
- **Dọn code**: xóa `install_services.*`, `stop_infra.*`, `stop_bot.ps1`, `ecosystem.config.js`; `run_bot.ps1/.sh` giữ lại cho dev local (đường thiếu runtime/pm2 giờ báo lỗi trỏ sang Docker); `.env.example` thêm `AZURIS_DB_USER/PASSWORD/NAME`.
- **Verify**: 3 service healthy, bot `is online and ready!`, slash sync đủ 26.
