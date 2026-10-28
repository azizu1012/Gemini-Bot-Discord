# Kiến trúc Hệ thống Azuris

## Tổng quan

**Azuris** là trợ lý AI trên Discord với kiến trúc hướng sự kiện phân tán (Event-Driven), sử dụng **PostgreSQL**, **Redis Streams**, và pipeline lập luận đa bước **Google Gemini**.

### Tính năng chính
- Contextual Chat: Hội thoại theo ngữ cảnh, lưu lịch sử ngắn & dài hạn
- Real-time Tool-calling: Web search, thời tiết, ghi chú, nhận diện ảnh
- Multi-user Isolation: Cô lập dữ liệu cá nhân tuyệt đối
- Containerized Runtime: Docker Compose — 1 bot + PostgreSQL 16 + Redis 7, data ngoài image
- Hybrid Role System: 4 nhóm quyền Admin, Moderator, Premium, Free

## Sơ đồ kiến trúc

```
┌──────────────┐     ┌──────────────────┐     ┌──────────────────────┐
│  Discord     │     │  API Gateway     │     │  Redis Streams       │
│  Client      │◄──►│  (bot_core.py)    │◄───►│  (Local Runtime)     │
│  (WS/REST)   │     │  - on_message    │     │  - discord-incoming  │
└──────────────┘     │  - slash cmds    │     │  - discord-outgoing  │
                     │  - typing loop   │     │  - search-subtasks   │
                     └──────────────────┘     └──────────┬───────────┘
                                                          │
                                                          ▼
                     ┌─────────────────────────────────────────────┐
                     │  Worker Node (message_handler.py)           │
                     │  - RAM KV Cache (CacheManager)              │
                     │  - File/Image Parser                        │
                     │  - GeminiPipeline (Reasoning → Synthesis)   │
                     │  - Tool Execution (Search, Notes, Weather)  │
                     │  - DB & Cache Updates                       │
                     └─────────────────────────────────────────────┘
```

### Service chính

| Service | File | Vai trò |
|---------|------|---------|
| API Gateway | `src/handlers/discord/bot_core.py` | Kết nối Discord WS, nhận sự kiện, push Redis |
| Commands | `src/handlers/discord/commands.py` | Định nghĩa slash commands |
| UI Helpers | `src/handlers/discord/ui.py` | UI components, embeds |
| Worker | `src/handlers/message_handler.py` | Xử lý tin nhắn nền, gọi pipeline |
| Pipeline | `src/core/gemini_pipeline.py` | Reasoning loop, synthesis |
| LLM Adapter | `src/core/llm/{base,genai_client,openai_client,gateway,resolver}.py` | 2 SDK (genai/openai), 3 model slot, fallback cùng provider |
| Repository | `src/database/repository.py` | 17 bảng PostgreSQL, asyncpg |

### Cổng dịch vụ (nội bộ mạng Compose — không publish ra host)

| Dịch vụ | Cổng nội bộ | Ghi chú |
|---------|-------------|---------|
| PostgreSQL | 5432 | Service `postgres`; bind `./data/postgres` + seed `data/db_seed/azuris.sql` |
| Redis | 6379 | Service `redis`, ephemeral (`--save "" --appendonly no`) |
| Router API (tùy chọn, ngoài repo) | 58100 | Bot dial-out tới; từ container `127.0.0.1` là chính nó |

Port 55432/6379 trên host chỉ còn ý nghĩa với legacy local runtime (`src/.runtime`, xem `docs/deprecated.md`). Bot không listen port nào.

## Cấu trúc thư mục

```
Azuris_refactor_code_base/
├── main.py                       # Entrypoint → ủy quyền run_bot.py
├── run_bot.py                    # Trình khởi chạy chính
├── run_bot.ps1 / run_bot.sh      # Script launcher (Win/Linux)
├── stop_infra.ps1 / stop_infra.sh# Tắt hạ tầng an toàn
├── install_services.ps1 / .sh    # Bootstrap Redis + PostgreSQL
├── ecosystem.config.js           # Cấu hình PM2 (Linux)
├── .env                          # Biến môi trường
├── requirements.txt              # Dependencies Python
├── README.md                     # Hướng dẫn khởi chạy nhanh
├── CLAUDE.md                     # Agent SOP & Hard Rules
│
├── src/
│   ├── core/                     # Lớp nhân & điều phối API
│   │   ├── llm/                  # Adapter LLM (endpoint-only)
│   │   │   ├── base.py           # LLMError, classify_error, protocol
│   │   │   ├── genai_client.py   # Adapter Google GenAI native
│   │   │   ├── openai_client.py  # Adapter LLM tương thích OpenAI
│   │   │   ├── gateway.py        # Façade generate/vision/list_models + fallback
│   │   │   └── resolver.py       # Đọc endpoint/slot từ PostgreSQL, giải mã key
│   │   ├── config.py             # Đọc .env, export biến, setup logger
│   │   ├── gemini_pipeline.py    # Reasoning loop + Final Synthesis
│   │   ├── logger.py             # Format log hệ thống
│   │   ├── preflight.py          # Kiểm tra môi trường trước khởi chạy
│   │   └── prompt_loader.py      # Tải prompt từ instructions/ (LRU)
│   │
│   ├── database/
│   │   ├── mixins/               # Domain mixins (schema, state, roles, audit, chat, notes, endpoints)
│   │   └── repository.py         # asyncpg composite repository, 17 bảng, connection pool
│   │
│   ├── handlers/
│   │   ├── discord/
│   │   │   ├── bot_core.py       # Gateway: WS Discord, typing, stream I/O
│   │   │   ├── commands.py       # Khai báo slash commands
│   │   │   └── ui.py             # UI helpers, embeds
│   │   └── message_handler.py    # Worker: xử lý tin nhắn từ Redis
│   │
│   ├── instructions/             # OOP Prompt Subsystem
│   │   ├── manager.py            # PromptManager (OOP singleton: load, cache, hot-reload)
│   │   ├── models.py             # Domain models (PromptTemplate, RetrievalPrompts, RoleContracts)
│   │   ├── builders.py           # Builders & formatters (IdentityPromptBuilder, FallbackPromptFormatter)
│   │   ├── prompts.py            # Facade constants & functions tương thích ngược
│   │   ├── system_prompt.py / lite_sys_prompt.py / fallback_sys_prompt.py # Re-export facades
│   │   └── templates/            # Thư mục chứa toàn bộ file template (.txt)
│   │       ├── azuris_system_prompt.txt
│   │       ├── fallback_system_prompt.txt
│   │       ├── lite_reasoning_prompt.txt
│   │       ├── identity_capability_prompt.txt
│   │       ├── retrieval_prompts.txt
│   │       ├── role_contract.txt
│   │       ├── file_index_reasoning_prompt.txt
│   │       └── file_index_validation_prompt.txt
│   │
│   ├── managers/
│   │   ├── cache_manager.py      # Singleton KV Cache RAM (TTL+LRU)
│   │   ├── cleanup_manager.py    # Dọn file upload cũ
│   │   ├── note_manager.py       # User notes + auto-summary LLM Lite
│   │   └── premium_manager.py    # Quản lý trạng thái Premium
│   │
│   ├── services/
│   │   ├── file_index_service.py # Chunking & indexing tài liệu
│   │   ├── file_parser.py        # Parse file đính kèm (txt, pdf, code...)
│   │   ├── health_checker.py     # Monitoring stub (~100 dòng)
│   │   ├── redis_service.py      # Service Redis
│   │   ├── search_subtask_client.py # Client search subtask Redis
│   │   └── search_subtask_worker.py # Worker search subtask
│   │
│   ├── tools/
│   │   ├── tools.py              # Function Calling definitions
│   │   ├── search/               # Search subsystem (OOP composite engine & mixins)
│   │   │   ├── engine.py         # SearchEngine composite coordinator
│   │   │   ├── reranker.py       # SearchReranker (consensus boost, authority ranking)
│   │   │   ├── query_planner.py  # QueryPlanner (temporal transformations, multi-intent)
│   │   │   ├── url_safety.py     # SSRF security shield (private IPs, loopback, cloud metadata)
│   │   │   ├── mixins/           # data, text, evidence, ranking mixins
│   │   │   ├── languages/        # vi, en, ja, korea, chinese, spanish catalogs
│   │   │   └── providers/        # duckduckgo, serpapi, tavily, exa, fetcher
│   │   ├── weather_service.py    # OpenWeatherMap
│   │   ├── calculator_service.py # Calculator
│   │   ├── helpers.py            # Helper utilities
│   │   └── constants.py          # Constants
│   │
│   └── voice/
│       ├── models.py             # Domain models (LockRecord, LockOutcome, PurgeReport, RoleMovePlan)
│       ├── store.py              # LockStore, WhitelistStore + LockStoreProtocol, WhitelistStoreProtocol
│       ├── lock_service.py       # RoomLockService (lock, unlock, enforce)
│       ├── tools_service.py      # RoomToolsService (move, move_all, set_room)
│       ├── purge.py              # VoicePurgeService (OOP dọn tin nhắn/reaction ngoài allowlist)
│       ├── role_hierarchy.py     # RoleHierarchyService (OOP tính toán & lập plan role rank)
│       ├── ui.py                 # RolePickerView, RolePositionView (UI components)
│       └── voice_lock.py         # VoiceLockManager facade tương thích ngược
│
├── assets/encrypted/             # QR donate mã hóa Fernet
├── data/                         # Dữ liệu runtime (gitignored)
├── uploaded_files/               # File tải lên tạm (gitignored)
├── logs/                         # Logs (gitignored)
├── docs/                         # Tài liệu kỹ thuật
└── tests/                        # Unit test suite (pytest-compatible)
```

## Luồng xử lý tin nhắn

### Chiều vào (Ingestion)
```
[Discord User] → on_message
    → bot_core.py (Gateway)
        → Kiểm tra spam (Hybrid Lock: Redis NX EX 20 / Local RAM Lock TTL 20s)
        → User processing state (Postgres atomic)
        → Khởi tạo typing loop (5s interval)
        → Đóng gói payload JSON (user_id, channel_id, content, attachments, bot_name)
        → Push vào Redis Stream: discord-incoming
```

### Xử lý (Processing)
```
Redis Stream: discord-incoming
    → message_handler.py (Worker)
        → Load chat history (CacheManager RAM / PostgreSQL fallback)
        → Parse file/ảnh đính kèm (asyncio.gather + Semaphore 3)
        → Build identity instruction (thay bot_name động)
        → NLP gate (~1ms, offline — `src/core/nlp_gate.py`)
            ├── EASY (chào hỏi/xã giao, không attachment/RAG): đường tắt
            │   1 call lite + sandwich rút gọn (không reasoning, không tool)
            └── COMPLEX (mọi thứ còn lại): GeminiPipeline.execute()
                ├── Reasoning Loop (max REASONING_MAX_LOOPS)
                │   → Gọi Gemini (gemini-flash-lite)
                │   → Phân tích function_call → thực thi tool → defer synthesis
                └── Final Synthesis (gemini-flash, stream real)
                    → Gom chunks, continuation nếu MAX_TOKENS
        → Lưu message vào DB + update RAM cache
        → Push vào Redis Stream: discord-outgoing
```

### Chiều ra (Egress)
```
Redis Stream: discord-outgoing
    → bot_core.py (Gateway)
        → Cancel typing loop
        → Chia nhỏ message (limit 1900 ký tự)
        → _outgoing_sender_loop (queue tuần tự tránh rate limit)
        → Gửi lên Discord REST API
```

## Chi tiết Module

### API Gateway — `src/handlers/discord/bot_core.py`
- `_build_attachment_payload`: Đóng gói metadata file đính kèm (id, url, proxy_url, filename, size, content_type, source, source_message_id)
- `handle_outgoing_payload`: Xử lý phản hồi từ Redis gửi về Discord
- `_outgoing_sender_loop`: Queue gửi tin tuần tự tránh rate limit
- `_typing_loop`: Gửi typing status mỗi 5s
- `_register_events`: Đăng ký on_message, on_ready
- `_update_env_var`: Cập nhật biến .env runtime

### Worker — `src/handlers/message_handler.py`
- `_download_file_with_sem`: Tải ảnh song song Semaphore(3)
- `_build_identity_instruction`: Thay tên bot động vào prompt
- `process_message`: Entry point xử lý tin nhắn từ Redis
- `_call_easy_with_deadline`: Đường tắt EASY (NLP gate → 1 call lite, fail-open về pipeline)
- `_process_imagine_command`: Xử lý /imagine

### NLP Gate — `src/core/nlp_gate.py`
- Pure stdlib, không AI model, không gọi mạng: chuẩn hóa tiếng Việt (bỏ dấu, teencode theo ranh giới từ) + char 3-gram cosine so với ~110 câu chào mẫu (16 ngôn ngữ: Việt, Anh, Nhật, Hàn, Trung, Tây Ban Nha, Pháp, Đức, Bồ Đào Nha, Nga, Thái, Indonesia, Hindi, Ý, Ả Rập, Thổ Nhĩ Kỳ)
- `classify()` → `EASY`/`COMPLEX`: ngưỡng cosine 0.50 + text dài hơn mẫu khớp nhất không quá 12 ký tự (chào + câu hỏi → COMPLEX); mơ hồ → COMPLEX
- `classify()` → `EASY`/`COMPLEX` (ngưỡng 0.50, precision 1.00 trên golden set `tests/test_nlp_gate.py`); mơ hồ → COMPLEX
- `build_easy_system_instruction()`: sandwich rút gọn (identity + persona + user block, slot reasoning để trống với marker, tools = `(No tools were called)`)

### Gemini Pipeline — `src/core/gemini_pipeline.py`
- `_call_gemini_reasoning_loop`: Vòng lặp suy nghĩ + gọi tools
- `_call_gemini_final`: Tổng hợp câu trả lời cuối (stream real)
- `_continue_final_output`: Viết tiếp nếu output bị cắt (MAX_TOKENS)

### LLM Adapter — `src/core/llm/`
- `resolver.py`: đọc endpoint + 3 model slot từ PostgreSQL, giải mã key (Fernet), cache in-memory + `invalidate()`
- `genai_client.py`: adapter Google GenAI native (`generate_content`, tools, vision)
- `openai_client.py`: adapter LLM tương thích OpenAI (`/v1/chat/completions`, tools, vision; không grounding)
- `gateway.py`: façade duy nhất cho pipeline — `generate`, `generate_text`, `generate_vision`, `list_models_for`, retry + 1 fallback cùng provider
- `base.py`: `LLMError`, `LLMNotConfiguredError`, `classify_error`

### Tools — `src/tools/tools.py`
- `web_search`: SerpAPI, Tavily, Exa, DuckDuckGo (multi-intent, parallel gather, lightweight reranking, smart incremental retry)
- `get_weather`: OpenWeatherMap
- `calculate`: Máy tính
- `save_note` / `retrieve_notes` / `delete_note`: Ghi chú cá nhân
- `image_recognition`: Gemini Flash
- `manage_user_role`: Quản lý role (chỉ visible cho Admin)

### Model AI
- Reasoning: `gemini-flash-lite` (slot `reasoning`, temp 0.35, 1 round tool rồi defer synthesis)
- Final Synthesis: `gemini-flash` (slot `final`, sandwich 3-block, stream real)
- Fallback: `gemini-flash-lite` (slot `fallback`, thử đúng 1 lần cùng provider)
- Vision: resolve về `final` (slot `vision` đã bỏ ở PR #27)
- Đường tắt EASY: model slot `reasoning` (lite), sandwich rút gọn, không tool
- Image Generation: Gemini Imagen 3
- SDK: Google GenAI SDK `google-genai==2.33.0` (+ adapter OpenAI-compatible `/v1/chat/completions`)

## Quyết định kiến trúc: vì sao chưa dùng Google ADK (2026-10-28)

Đã spike đối đầu ADK 2.13.0 (`LlmAgent` + `Runner` + `FunctionTool`) với pipeline hiện tại trên model/router thật, cùng sandwich final thật cho cả hai. Kết quả: transcript tương đương byte-for-byte về hình thức (`("Reasoning completed", "[calculate] {...}")`), final cùng đúng.

Không migrate vì:
1. **Port = dịch tên, không thêm capability.** Mọi rule domain (evidence threshold, partial/strict-uncertainty, continuation MAX_TOKENS, thought signature, identity build động, retry giữ state theo loại lỗi, text-fallback parse `<tool_code>`) ADK không có — phải viết lại thành callback/node, code không biến mất mà chỉ chuyển chỗ.
2. **Debug xuyên abstraction đắt.** Lỗi thật (router 429/throttle) bị chôn dưới 10 tầng `DynamicNodeFailError` → tenacity → `aiohttp`; loop tự viết thì lỗi ở đâu hiện ở đó.
3. **Framework còn xoay.** Dòng 2.x release dồn dập (deprecate `Sequential/LoopAgent`, đổi default model, GenAI SDK v2) — theo ADK nghĩa là theo nhịp breaking change của Google trong khi code hiện tại đứng yên vẫn chạy.
4. **Rủi ro đã đo, lợi ích chưa thấy.** Biến thể 1-model multi-pass của ADK còn lộ lỗi cấu trúc (pass cuối trả lời nhầm meta-prompt thay vì câu user); 2-tier hiện tại neo đáp án tốt hơn.

Giữ pipeline hiện tại; đầu tư vào đường tắt EASY (NLP gate) thay vì thay core loop. Chi tiết so sánh xem `docs/operations.md` (Session 18) và `tests/test_nlp_gate.py`.
