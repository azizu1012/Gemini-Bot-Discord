# 📋 TÓM TẮT SESSION — Azuris Bot + Router API

## 🗓️ Thông tin session
- **Ngày:** 10/06/2026
- **Nội dung:** Fix `/endpoint` auth key leak, fix model naming, đánh giá kiến trúc
- **Dự án 1:** `D:\AI_Projects\Discord-bot\Azuris_refactor_code_base` (Bot)
- **Dự án 2:** `D:\AI_Projects\router_api` (Router API Proxy)

---

## 1. VẤN ĐỀ PHÁT HIỆN & ĐÃ SỬA

### 1.1. Leak Google API Key lên Router (fixed)
- **File:** `src/core/gemini_api_manager.py:198-210`
- **Lỗi cũ:** Khi `ROUTER_AUTH_KEY` rỗng, `router_key = "" or api_key` → gửi Google API Key thật lên Router API
- **Fix:** Khi `ROUTER_AUTH_KEY` rỗng → quay về xoay vòng key qua Google trực tiếp, không đụng Router

### 1.2. Model ID sai (fixed)
- **File:** `src/core/api_config.py`
- **Alias** `gemini-flash-35` → đổi thành `gemini-flash`
- **model_id mặc định:**
  - `gemini-flash` → Router: `gemini-flash` | Google direct: (env var)
  - `gemini-flash-lite` → Router: `gemini-flash-lite` | Google direct: `gemini-flash-lite-lasted`
- Đã thêm field `direct_model_id` cho chế độ Google trực tiếp
- Đã xóa `gemini-flash-30` (outdated)

### 1.3. Final model fallback (fixed)
- **File:** `src/core/gemini_pipeline.py:738-742`
- Khi Router có `GEMINI_BASE_URL` nhưng `ROUTER_AUTH_KEY` rỗng → dùng lite model cho cả reasoning + final

### 1.4. Đổi tên model khắp nơi
- `src/core/api_router.py` — hardcoded `"gemini-flash-35"` → `"gemini-flash"`
- `src/handlers/message_handler.py` — hardcoded `"gemini-flash-35"` → `"gemini-flash"`

---

## 2. KIẾN TRÚC BOT (Azuris Discord Bot)

### 2.1. Tổng quan
- **Ngôn ngữ:** Python 3.10+
- **Tổng dòng:** ~10.700 (37 file)
- **Entry point:** `main.py` → `run_bot.py`
- **Database:** PostgreSQL (asyncpg pool, min=2 max=10)
- **Cache:** Redis (Streams + Pub/Sub) + RAM (cache_manager.py)
- **Zero-Docker:** PostgreSQL + Redis tự cài trong `.runtime/`

### 2.2. Luồng message

```
Discord → BotCore (Gateway) → Redis Stream 'discord-incoming' → MessageHandler (Worker)
    → GeminiPipeline (2-tier reasoning + final) → Redis Stream 'discord-outgoing'
    → BotCore → gửi về Discord
```

### 2.3. Pipeline Reasoning
- **2-tier:** Flash-Lite (reasoning, tool calling) → Flash (final synthesis)
- **Vòng lặp suy nghĩ:** Reasoning loop với tool calling (search, vision, notes, weather, role mgmt)
- **Token estimation:** Acquire quota trước khi gọi API
- **Continuation:** Tự động viết tiếp nếu output bị truncate
- **Fallback lite:** Khi flash-35 chết → fallback về lite model

### 2.4. Database (15 tables)
- messages, user_processing_states, user_notes, premium_users, moderator_users,
  admin_users, usage_logs, web_history, generated_images, rag_chunks,
  api_key_pool, api_key_rate_limits, custom_api_models, bot_model_config,
  custom_api_provider_config

### 2.5. Key rotation & Error handling
- 3 lớp retry: Pipeline retry → Key rotation → Circuit breaker
- Smart cooldown: 429=60s, 503=5s, Invalid Key=86400s, Endpoint Down=120s
- Circuit breaker: 5 failures/10s → open 30s
- In-memory key status: `{frozen_until, usage}`
- Global semaphore: `API_REQUEST_SEMAPHORE = 2`

### 2.6. Caching
- Chat history: RAM cache 50 msg/user, max 1000 users, TTL=300s
- Web search cache: TTL=3600s, max 1000 items, LRU eviction
- Image recognition cache: TTL=3600s
- Redis Pub/Sub invalidation events

### 2.7. Role system
- Admin (từ .env + DB), Moderator (DB), Premium (DB), Free (default)
- Free user: 50 msg/day, 5 DM/day
- Premium: Unlimited, 20/60 phút
- Admin/Mod: Unlimited + `/endpoint`, `/health_check`, `/reset-all`

### 2.8. Voice Room Management
- `/lock`, `/unlock`, `/set_room`, `/add_privet`, `/remove_privet`, `/move`, `/move_all`

---

## 3. KIẾN TRÚC ROUTER API

### 3.1. Tổng quan
- **Ngôn ngữ:** Python (FastAPI)
- **Tổng dòng:** ~10.500 (78 file)
- **Entry point:** `main.py` → uvicorn FastAPI app
- **Database:** SQLite (aiosqlite + sqlite3 sync)
- **Auth:** API key-based (Account Manager + accounts table)

### 3.2. Endpoints
- `POST /v1beta/models/{model}:generateContent` — Gemini native (non-stream)
- `POST /v1beta/models/{model}:streamGenerateContent` — Gemini native (stream)
- `POST /v1/chat/completions` — OpenAI compatible
- `POST /v1/messages` — Claude/Anthropic compatible
- `POST /v1/responses` — OpenAI Codex Responses
- Dashboard UI: `/`, `/dashboard/login`, admin API

### 3.3. Auth flow
```
Request → _resolve_gemini_auth() (X-Goog-Api-Key > Authorization > query)
    → _check_auth() → account_manager.find_by_key(token)
        → SQLite accounts table → account info (rpm, tpm, rpd, tier)
```

### 3.4. Key resolution (cốt lõi)
- **Thuật toán:** Sort candidates by `(active_requests, -priority, failures)`
  → chọn top 50% → random choice → atomic reserve
- **4 chiều quota:** RPM + TPM + RPD + per-model frozen
- **Adaptive cooldown:** `8 * (3^(failures-1))` max 600s
- **RPD hết:** Cooldown đến nửa đêm hôm sau
- **Model pool:** `gemini-flash` pool [gemini-3.5-flash, gemini-3.0-flash, gemini-2.5-flash]
  swap_failures=5, auto swap khi hết quota per-model
- **Circuit breaker:** 10 failures/30s → open 60s

### 3.5. Các tính năng chính
- Usage logging + cost tracking (SQLite, batch flush 5s, 30-day retention)
- Token estimation + truncation (emergency limit 200k tokens)
- Web search: Hybrid DuckDuckGo + Google Grounding
- Rate limiter per account (RPM/TPM/RPD)
- `.env` hot reload (watch 3s)
- Adaptive cooldown với penalty cộng dồn

---

## 4. CÁCH 2 DỰ ÁN KẾT NỐI

```
Bot config.GEMINI_BASE_URL = http://127.0.0.1:58100  ───→ Router API
Bot config.ROUTER_AUTH_KEY = "xxx"                   ───→ Xác thực qua Account Manager

Bot: genai.Client(
    api_key=ROUTER_AUTH_KEY,
    http_options={base_url=GEMINI_BASE_URL, headers={"Authorization": "Bearer ROUTER_AUTH_KEY"}}
)
                                                      Router: _resolve_gemini_auth()
                                                             → _check_auth()
                                                             → router.reserve_key()
                                                             → call Gemini SDK → Google
                                                             → log_usage() → SQLite
```

---

## 5. ĐÁNH GIÁ 12 GÓC NHÌN

| # | Góc nhìn | Điểm | Ghi chú |
|---|----------|------|---------|
| 1 | Kiến trúc & Design Pattern | 9/10 | Event-driven, singleton, zero-docker |
| 2 | Khả năng Scale | 8/10 | Redis Streams scale ngang, nút thắt chính là API key |
| 3 | Độ tin cậy & Error Handling | 9/10 | 3 lớp retry, circuit breaker, adaptive cooldown |
| 4 | Hiệu năng | 7/10 | Semaphore=2 hơi thấp, parallel download tốt |
| 5 | Bảo mật | 9/10 | 3-tier role, secrets.compare_digest, ko leak key |
| 6 | Bảo trì | 7/10 | bot_core.py 1907 dòng monolithic, chưa tách file |
| 7 | Database Design | 8/10 | 15 tables, GIN index JSONB, migration tự động |
| 8 | Cache & Memory | 7/10 | 3 lớp cache, nhưng gemini_clients dict ko eviction |
| 9 | Giám sát & Observability | 5/10 | Không metrics, không tracing, không alerting |
| 10 | Triển khai & DevOps | 7/10 | Zero-Docker, PM2, .env hot reload, không CI/CD |
| 11 | Chất lượng Code | 7/10 | Nhiều comment, thiếu unit tests, try/except tràn lan |
| 12 | Khả năng mở rộng | 9/10 | Plugin tools, Redis Streams mở, multi-provider ready |
| | **TRUNG BÌNH** | **7.7/10** | |

---

## 6. ĐIỂM UNIQUE CỦA 2 DỰ ÁN

### Router API — Điều không ai làm
- Proxy chuyên để **cày free tier** — track 4 chiều quota (RPM + TPM + RPD + per-model)
- Adaptive cooldown `8 * (3^(failures-1))` — không thằng opensource nào có
- Model pool swap khi hết quota per-model
- RPD tracking + cooldown đến nửa đêm
- Tất cả opensource proxy khác design cho paid key, budget chỉ là `$50/day → block`

### Bot — Điều khác biệt
- **Event-Driven** với Gateway + Worker riêng qua Redis Streams (không ai làm kiểu này cho Discord bot)
- **2-tier pipeline** reasoning → final (thay vì 1 call đơn giản)
- **Zero-Docker** runtime (PostgreSQL + Redis tự cài)
- **Hybrid lock** Redis + Local RAM chống spam
- Token estimation + quota gate trước khi gọi API
- **Tiếng Việt** toàn bộ prompt + response

### Vấn đề còn tồn tại
- bot_core.py 1907 dòng → cần tách file
- Không monitoring/metrics → mù khi crash
- Không unit tests → sợ sửa
- Semaphore=2 → bottleneck nhẹ
- `MODEL_NAME` legacy trong config.py chết

---

## 7. NHỮNG GÌ ĐÃ BÀN LUẬN THÊM

- Scale: Hệ thống chịu được 200-500 users sau tune, nhưng thực tế chỉ có 5 users + free key → không cần scale
- Proxy không giảm cost, chỉ giảm rủi ro (failover, không lệ thuộc 1 provider)
- Không opensource proxy nào có budget control thật sự như Router của chủ dự án
- Dashboard UI của Router thuần JS/CSS, hạn chế về mặt thẩm mỹ nhưng đủ dùng
- Nếu dùng paid key thì mấy proxy opensource như CCX (Go) ngon hơn về performance, nhưng không có cơ chế bảo vệ budget
