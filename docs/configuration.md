# Cấu hình & Cơ sở dữ liệu Azuris

## Biến môi trường

File `.env` duy nhất, đọc bởi `src/core/config.py`.

### Hạ tầng cốt lõi

| Biến | Mặc định | Mô tả |
|------|----------|-------|
| `DATABASE_URL` | `postgresql://...` | URL kết nối PostgreSQL (cổng 55432) |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | URL kết nối Redis |
| `DISCORD_TOKEN` | — | Token bot Discord |
| `LOCAL_RUNTIME_ROOT` | `src/.runtime` | Đường dẫn runtime cục bộ |
| `AZURIS_POSTGRES_START_MODE` | `direct` | Chế độ khởi động PostgreSQL (direct/auto/pg_ctl) |
| `DONATE_ENCRYPTION_KEY` | — | Khóa mã hóa Fernet cho QR donate |

### Gemini & Model

| Biến | Mặc định | Mô tả |
|------|----------|-------|
| `GEMINI_API_KEYS` | — | Danh sách key (GEMINI_API_KEY_1, 2...) |
| `GEMINI_BASE_URL` | (rỗng) | Router API URL. Rỗng = gọi Google trực tiếp |
| `REASONING_MODEL_ALIAS` | `gemini-flash` | Alias cho reasoning loop |
| `FINAL_MODEL_ALIAS` | `gemini-flash` | Alias cho final synthesis |
| `FALLBACK_MODEL_ALIAS` | `gemini-flash-lite` | Alias cho fallback |

### Search & Weather

| Biến | Mô tả |
|------|-------|
| `SERPAPI_API_KEY` | SerpAPI key |
| `TAVILY_API_KEY` | Tavily key |
| `EXA_API_KEY` | Exa AI key |
| `WEATHER_API_KEY` | OpenWeatherMap key |
| `CITY` | Thành phố mặc định tra cứu thời tiết |

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

### Circuit Breaker

| Biến | Mặc định |
|------|----------|
| `GEMINI_CIRCUIT_ENABLED` | True |
| `GEMINI_CIRCUIT_FAILURE_THRESHOLD` | 5 |
| `GEMINI_CIRCUIT_WINDOW_SECONDS` | 10 |
| `GEMINI_CIRCUIT_OPEN_SECONDS` | 30 |

## Cơ sở dữ liệu

PostgreSQL 16, cổng 55432, database `azuris`.

### 15 bảng

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
5. API Key Leak Prevention: Khi ROUTER_AUTH_KEY trống → fallback Google direct
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

### API Key Leak Prevention
Khi `ROUTER_AUTH_KEY` trống + `GEMINI_BASE_URL` có giá trị → tự động bypass, gọi Google direct, dùng `gemini-flash-lite-latest`.

### Router Bypass
`router_bypass_until` timestamp, khi ConnectError → bypass 30s, `base_url = ""`, map sang Lite model. Hết 30s tự thử lại Router.

### SDK Crash (TypeError)
Router trả lỗi không có `code` → SDK crash `'<=' not supported` → bắt TypeError, coi như connection error → key rotation.

### Timeout Unit Fix
GenAI SDK yêu cầu ms (int): connection 15000ms, client 120000ms.
