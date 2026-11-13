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

### Hành vi vận hành (Redis worker — sau fix commit gần đây)

- **Single-worker Redis instance-lock**: `run_bot.py` giành khoá Redis NX EX (key `azuris:worker:instance-lock`, TTL 3600s) khi khởi động. Nếu instance khác đang giữ khoá, bot log lỗi rõ ràng và thoát với status code 1. Fail-open khi Redis không khả dụng (cảnh báo và tiếp tục) để hỗ trợ dev local. Khoá được giải phóng khi shutdown.
- **Periodic pending reclaim**: `message_handler` chạy reclaim định kỳ các message Redis pending (crash/chưa ACK) mỗi `RECLAIM_PENDING_INTERVAL_SECONDS` (mặc định 60s) bên cạnh reclaim lúc khởi động — giảm cửa sổ mất message sau khi worker crash.
- **ACK semantics**: một message chỉ được ACK sau khi publish reply thành công (hoặc sau khi publish fallback busy-reply thành công). Nếu cả hai thất bại, message được để lại un-ACKed cho reclaim thay vì bị drop im lặng (at-least-once).
- **Search subtask group id ổn định** (`azuris_search_results`): restart không tích luỹ consumer group mồ côi; subtask worker ACK sau khi publish kết quả.
- **Egress**: hàng đợi reply outgoing bị giới hạn (100), drop item cũ nhất khi overflow; vòng lặp sender sống sót qua lỗi từng payload.

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

