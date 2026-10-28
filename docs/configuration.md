# Cấu hình & Cơ sở dữ liệu Azuris

## Biến môi trường

File `.env` duy nhất, đọc bởi `src/core/config.py`.

### Hạ tầng cốt lõi

| Biến | Mặc định | Mô tả |
|------|----------|-------|
| `DATABASE_URL` | `postgresql://...` | URL kết nối PostgreSQL — legacy local (cổng 55432). Trong Docker bị `environment` của Compose override sang `postgres:5432` |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | URL kết nối Redis — trong Docker bị override sang `redis://redis:6379/0` |
| `AZURIS_DB_USER` / `AZURIS_DB_PASSWORD` / `AZURIS_DB_NAME` | `azuris` / *(bắt buộc)* / `azuris` | Credential Postgres cho Docker (user/pass/db). Mật khẩu chỉ dùng ký tự URL-safe `[A-Za-z0-9_-]` vì được nhúng vào `DATABASE_URL` |
| `DISCORD_TOKEN` | — | Token bot Discord |
| `LOCAL_RUNTIME_ROOT` | `src/.runtime` | Đường dẫn runtime cục bộ |
| `AZURIS_POSTGRES_START_MODE` | `direct` | Chế độ khởi động PostgreSQL (direct/auto/pg_ctl) |
| `DONATE_ENCRYPTION_KEY` | — | Khóa mã hóa Fernet cho QR donate + API key endpoint |

### LLM Endpoint & Model

| Biến | Mặc định | Mô tả |
|------|----------|-------|
| `GEMINI_TIMEOUT_MS` | `60000` | Timeout gọi LLM (ms) — dùng cho cả 2 SDK |

> Endpoint (URL, API key, SDK active, 3 model slot) lưu trong PostgreSQL và cấu hình qua `/endpoint` trong Discord — xem [`endpoint_and_models.md`](endpoint_and_models.md). Không còn `GEMINI_API_KEY_*`, `GEMINI_BASE_URL`, `ROUTER_AUTH_KEY`, `*_MODEL_ALIAS`.

### Search & Weather

| Biến | Mô tả |
|------|-------|
| `SERPAPI_API_KEY` | SerpAPI key |
| `TAVILY_API_KEY` | Tavily key |
| `EXA_API_KEY` | Exa AI key |
| `WEATHER_API_KEY` | OpenWeatherMap key |
| `CITY` | Thành phố mặc định tra cứu thời tiết |
| `SEARCH_PARALLEL_STREAMS` | Số luồng search song song (1–2, mặc định 1). Biến cũ `GOOGLE_SEARCH_STREAMS` vẫn được đọc |
| `SEARCH_FALLBACK_PROVIDER_LIMIT` | Số provider fallback tối đa khi search fail (mặc định 2) |

### Rate Limit & Anti-Spam

| Biến | Mặc định | Mô tả |
|------|----------|-------|
| `SPAM_THRESHOLD` | `3` | Số tin nhắn spam tối đa trong window |
| `SPAM_WINDOW` | `30` | Cửa sổ thời gian (giây) |
| `DEFAULT_RATE_LIMIT` | `10/60` | 10 messages / 60s |
| `PREMIUM_RATE_LIMIT` | `20/60` | 20 messages / 60s |
| `DEFAULT_DM_LIMIT` | `5` | DM tối đa/ngày (free user) |
| `PREMIUM_DM_LIMIT` | `15` | DM tối đa/ngày (premium) |

### Phân quyền tĩnh

| Biến | Mô tả |
|------|-------|
| `ADMIN_IDS` | Danh sách Admin tĩnh (cách nhau bằng dấu phẩy) |
| `ADMIN_ID` | Tương thích ngược |
| `MODERATOR_IDS` | Danh sách Moderator tĩnh ban đầu |

### Pipeline Tuning

| Biến | Mặc định | Giới hạn |
|------|----------|----------|
| `REASONING_MAX_API_RETRIES` | 3 | 1-6 |
| `REASONING_MAX_LOOPS` | 3 | 1-6 |
| `FINAL_MAX_API_RETRIES` | 3 | 1-6 |
| `FALLBACK_MAX_API_RETRIES` | 2 | 1-5 |
| `FINAL_MAX_OUTPUT_TOKENS` | 8192 | 512-65536 |
| `FINAL_CONTINUATION_MAX_CALLS` | 5 | 1-8 |
| `MAX_SEARCH_CALLS_PER_TURN` | 5 | 1-20 |
| `MIN_FREE_SPACE_MB` | 100 | Ngưỡng dọn file upload cũ |

### NLP gate (hằng số code trong `src/core/nlp_gate.py`, không env)

| Hằng số | Giá trị | Ý nghĩa |
|---------|---------|---------|
| `EASY_THRESHOLD` | 0.50 | Ngưỡng cosine EASY/COMPLEX |
| `MAX_WORDS_EASY` | 12 | Dài hơn → auto COMPLEX (ngôn ngữ có khoảng trắng) |
| `MAX_CHARS_EASY_NORM` | 60 | Dài hơn → auto COMPLEX (chữ Hán/Nhật/Thái không khoảng trắng) |
| `EASY_LEN_SLACK_CHARS` | 12 | Text dài hơn mẫu khớp nhất quá slack này → COMPLEX (chào + câu hỏi) |
| `MAX_CHARS_EASY` | 300 | Guard trước khi gọi gate từ `message_handler` |
| `EASY_MAX_OUTPUT_TOKENS` | 1024 | Trong `EASY_GENERATION_CONFIG` (temp 0.7, không tool) |
| `EASY_TIMEOUT_SECONDS` | 60 | Timeout đường tắt → fail-open full pipeline |

## Cơ sở dữ liệu

PostgreSQL 16, database `azuris` (trong Docker: service `postgres`, cổng nội bộ 5432; legacy local: cổng 55432).

### 17 bảng

#### Đang hoạt động

**messages** — Lịch sử hội thoại
| Cột | Kiểu | Mô tả |
|-----|------|-------|
| message_id | TEXT PK | ID Discord |
| user_id | TEXT NOT NULL | ID người dùng |
| role | TEXT NOT NULL | `user` / `model` |
| content | TEXT NOT NULL | Nội dung |
| timestamp | TIMESTAMPTZ | DEFAULT CURRENT_TIMESTAMP |

**user_processing_states** — Chống spam
| Cột | Kiểu | Mô tả |
|-----|------|-------|
| user_id | TEXT PK | ID người dùng |
| is_busy | BOOLEAN | Đang xử lý? |
| current_stage | TEXT | Giai đoạn ('searching', 'thinking') |
| last_updated | TIMESTAMPTZ | |

**user_notes** — Trí nhớ dài hạn
| Cột | Kiểu | Mô tả |
|-----|------|-------|
| note_id | TEXT PK | UUID |
| user_id | TEXT NOT NULL | |
| content | TEXT NOT NULL | Nội dung ghi chú |
| metadata | JSONB | {filename, source, hash, ...} |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |
| scope | TEXT | `user` / `global` |
| importance | INTEGER | 0 mặc định |
| is_active | INTEGER | 1 mặc định |
| note_type | TEXT | `personal_preference` mặc định |
| fact_hash | TEXT | Chống ghi trùng |

**llm_endpoints** — Endpoint LLM theo SDK
| Cột | Kiểu | Mô tả |
|-----|------|-------|
| sdk | TEXT PK | `genai` / `openai` |
| base_url | TEXT NOT NULL | URL endpoint |
| api_key_encrypted | TEXT NOT NULL | Key đã mã hóa (Fernet hoặc `plain:`) |
| is_active | BOOLEAN | SDK đang active (tối đa 1 dòng true) |
| updated_by | TEXT | Admin cập nhật |
| updated_at | TIMESTAMPTZ | |
| last_check_ok | BOOLEAN | Kết quả test gần nhất |
| last_check_error | TEXT | Lỗi gần nhất |
| last_checked_at | TIMESTAMPTZ | |

**llm_model_slots** — 3 model slot theo SDK
| Cột | Kiểu | Mô tả |
|-----|------|-------|
| sdk | TEXT PK | `genai` / `openai` |
| slot | TEXT PK | `reasoning` / `final` / `fallback` (slot `vision` đã bỏ — DB CHECK chỉ còn 3) |
| model_id | TEXT | NULL = dùng default rule |
| updated_by | TEXT | |
| updated_at | TIMESTAMPTZ | |

**premium_users** / **moderator_users** / **admin_users**
| Cột | Kiểu |
|-----|------|
| user_id | TEXT PK |
| added_at | TIMESTAMPTZ |

**usage_logs** — Cost tracking
| Cột | Kiểu |
|-----|------|
| id | BIGSERIAL PK |
| user_id | TEXT, action_type TEXT, model_name TEXT |
| tokens_used | INTEGER |
| metadata | TEXT, timestamp TIMESTAMPTZ |

**web_history** — Search audit
| Cột | Kiểu |
|-----|------|
| id | BIGSERIAL PK |
| user_id | TEXT, query TEXT, results TEXT, timestamp TIMESTAMPTZ |

**generated_images** — Image generation log
| Cột | Kiểu |
|-----|------|
| id | BIGSERIAL PK |
| user_id | TEXT, prompt TEXT, image_url TEXT, timestamp TIMESTAMPTZ |

**rag_chunks** — Document chunks
| Cột | Kiểu | Mô tả |
|-----|------|-------|
| chunk_id | TEXT PK | document_id prefix + chunk index |
| document_id | TEXT NOT NULL | |
| content | TEXT NOT NULL | Nội dung chunk |
| chunk_summary | TEXT NOT NULL | Tóm tắt |
| keywords | TEXT[] | Từ khóa |
| metadata | TEXT, created_at TIMESTAMPTZ | |

**api_key_pool** — Key management
| Cột | Kiểu |
|-----|------|
| key_id | BIGSERIAL PK |
| api_key | TEXT UNIQUE |
| provider | TEXT (default 'gemini') |
| is_active | BOOLEAN, cooldown_until TIMESTAMPTZ, created_at TIMESTAMPTZ |

**api_key_rate_limits** — Per-key rate limits
| Cột | Kiểu |
|-----|------|
| key_id | BIGINT PK → api_key_pool(key_id) |
| requests_used | INTEGER, last_reset TIMESTAMPTZ |

#### Legacy (không dùng)
- `custom_api_models`, `custom_api_provider_config`, `bot_model_config`

### Indexes

| Tên | Bảng | Cột | Loại |
|-----|------|-----|------|
| `idx_messages_user_time` | messages | (user_id, timestamp DESC) INCLUDE (role) | BTREE |
| `idx_user_notes_user_scope_active` | user_notes | (user_id, scope, is_active) | BTREE |
| `idx_user_notes_fact_hash` | user_notes | fact_hash | BTREE |
| `idx_user_notes_metadata_gin` | user_notes | metadata | GIN (JSONB) |
| `idx_rag_chunks_keywords` | rag_chunks | keywords | GIN (array) |
| `idx_rag_chunks_summary_trgm` | rag_chunks | chunk_summary | GIN (trgm) |

### Quy tắc JSONB
- Luôn dùng `metadata->>'key' = $val` để tận dụng GIN Index
- Cấm `metadata::text ILIKE $1` — vô hiệu hóa GIN
- Cấm vòng lặp Python lọc JSON — đẩy xuống PostgreSQL
- Dùng toán tử trigram `%` (không phải `%%`) cho `chunk_summary`

## Phân quyền & Bảo mật

### 4 Role Tiers

| Vai trò | Xác thực | Quyền | Giới hạn |
|---------|----------|-------|----------|
| Admin | .env (tĩnh) + admin_users (động) | Toàn quyền | Không |
| Moderator | .env (tĩnh) + moderator_users (động) | health_check, endpoint (xem) | Không reset-all, moderator, premium add |
| Premium | premium_users (động) | Chat unlimited, imagine | Không quyền quản trị |
| Free User | Mặc định | 50 messages/ngày | Không imagine |

### Cơ chế bảo vệ
1. Admin tĩnh bất khả xâm phạm: ID trong .env không thể bị demote bởi DB hay LLM
2. Tool Isolation: `manage_user_role` bị ẩn khỏi non-Admin
3. SQL Injection: 100% parameterized query ($1, $2...) qua asyncpg
4. Atomic User Lock: PostgreSQL `UPDATE ... WHERE is_busy = false`
5. API Key Protection: Mã hóa Fernet at-rest trong PostgreSQL; che key trên UI
6. Rate Limit: Spam threshold + DM limit + role-based rate limit

## Cache & Tối ưu hiệu năng

### RAM KV Cache (`cache_manager.py`)

| Thuộc tính | Giá trị |
|------------|---------|
| Pattern | Singleton |
| Storage | dict trong RAM Worker |
| Max users | 1,000 (LRU eviction) |
| TTL | 300 giây |
| Messages/user | 12 tin nhắn gần nhất |

Luồng: `get_chat_history()` → Cache Hit (0ms) / Cache Miss → PostgreSQL → `set_chat_history()` → sau LLM → `add_chat_message()` append.

Invalidation: `/reset-chat` → Redis Pub/Sub → Worker xóa RAM cache.

### Performance features
- Parallel Image Download: `asyncio.gather` + Semaphore(3), RAM-Only, cấm lưu bytes vào DB
- Lightweight Reranking: Consensus Boost, Freshness Boost, Domain Duplication Penalty
- Smart Incremental Retry: lần 1: 3s, lần 2: 5s (worst-case 14s → 8s)
- Dynamic Timeout: `max(SEARCH_SUBTASK_TIMEOUT_SEC, num_intents * 8)`
- Discord Table Render Safety: cấm bảng Markdown thô, dùng list thụt lề hoặc text table trong code block

## Anti-Brick & Security

### API Key At Rest
- Key endpoint mã hóa Fernet bằng `DONATE_ENCRYPTION_KEY` trước khi ghi PostgreSQL.
- Thiếu key → lưu `plain:<key>` (chỉ dùng khi phát triển); `/endpoint view` chỉ hiện 4 ký tự cuối.

### Unconfigured Gate
- Không kiểm tra endpoint lúc khởi động; khi chưa cấu hình, chat trả ephemeral "Bot chưa được cấu hình, hãy liên hệ admin."

### Timeout Unit Fix
GenAI SDK yêu cầu ms (int): connection 15000ms, client 120000ms.
