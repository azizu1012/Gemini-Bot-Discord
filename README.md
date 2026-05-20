# Chad Gibiti Discord Bot

Chad Gibiti là Discord bot dùng pipeline Gemini 2 tầng (reasoning/tool loop + final synthesis), có memory dài hạn qua SQLite, shared knowledge có kiểm soát, và lớp ổn định runtime cho production (cache, retry budget, PM2 fresh mode).

## Quick start

```bash
pip install -r requirements.txt
python main.py
```

Hoặc chạy launcher:

```bash
python run_bot.py
python run_bot.py --server
python run_bot.py --preflight
```

Linux/Ubuntu launcher có hỗ trợ PM2:

```bash
./run_bot.sh --server
./run_bot.sh --pm2 --server
./run_bot.sh --pm2-fresh --server
./run_bot.sh --preflight-only
```

## Runtime hardening (cross-platform)
- Runtime folders/file sẽ tự tạo trước khi dùng (`data/`, `uploaded_files/`, `logs/`, quota state, voice lock files...).
- Startup banner luôn in:
  - Python executable
  - current working directory
  - project root
  - resolved runtime paths
- Preflight (`--preflight`) sẽ validate:
  - dependency versions quan trọng
  - writable DB/memory/upload/quota/log paths

## Deploy runbook chuẩn (Linux + PM2)

1. Clone đúng repo và cài venv:

```bash
git clone https://github.com/azizu1012/Gemini-Bot-Discord.git chat-bot
cd chat-bot
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

1. Cấu hình `.env` (tối thiểu `DISCORD_TOKEN`, `GEMINI_API_KEY_1...`).
   Nếu dùng tính năng `/donate`, thêm `DONATE_ENCRYPTION_KEY` (Fernet key) — xem `.env.example`.

1. Chạy preflight trước khi start:

```bash
python run_bot.py --preflight
```

1. Start bằng ecosystem có `cwd` cố định:

```bash
BOT_ENABLE_SERVER=1 pm2 start ecosystem.config.js --only chat-bot --update-env
# hoặc bot-only:
BOT_ENABLE_SERVER=0 pm2 start ecosystem.config.js --only chat-bot --update-env
pm2 save
```

1. Verify sau deploy:

```bash
pm2 logs chat-bot --lines 120
```

Checklist log cần thấy:
- Startup banner in đúng `Project root` và resolved paths.
- Không còn `unable to open database file`.
- Không còn `Fallback lite error: [Errno 2]`.

1. Nếu PM2 bị lỗi stale `pidusage`:

```bash
pm2 update
pm2 restart chat-bot
pm2 save
```

## Cấu hình tối thiểu

```env
DISCORD_TOKEN=...
GEMINI_API_KEY_1=...
```

Chi tiết biến môi trường: xem `.env.example`.

## Donate QR (mã hóa ảnh)

Ảnh QR donation được mã hóa Fernet tại `assets/encrypted/` (commit an toàn lên git).
Ảnh gốc nằm ở `Donet-qr/` (gitignored, không push).

- **Đổi ảnh QR**: thay file trong `Donet-qr/`, chạy `python scripts/encrypt_donate_qr.py`, commit lại `assets/encrypted/`.
- **Deploy server mới**: đảm bảo `.env` có `DONATE_ENCRYPTION_KEY` (cùng key đã dùng để encrypt).
- **Generate key mới**: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` — nhớ re-encrypt ảnh sau khi đổi key.

## Kiến trúc chính

- `main.py`: entrypoint mỏng, ủy quyền chạy cho `run_bot.py`
- `run_bot.py`: launcher chính, hỗ trợ mode bot-only hoặc bot + server
- `run_bot.sh`: launcher Linux/PM2 (`--pm2`, `--pm2-fresh`, `--server`)
- `src/handlers/message_handler.py`: routing, context building, intent detection
- `src/core/gemini_api_manager.py`: API key pool, throttle, client pool
- `src/core/gemini_pipeline.py`: reasoning loop, final synthesis, fallback
- `src/handlers/bot_core.py`: vòng đời bot, slash commands, admin interactions
- `src/services/file_index_service.py`: LLM-powered file indexing pipeline
- `src/tools/tools.py`: registry/dispatch tool calls cho model + search pipeline
- `src/database/repository.py`: SQLite repository, fresh schema bootstrap, auto-rebuild khi schema cũ/lỗi
- `src/managers/note_manager.py`: logic phân loại note, policy scope, promote global
- `src/core/prompt_loader.py`: LRU-cached prompt loading từ `src/instructions/`

## Pipeline phản hồi

1. Nhận message từ DM hoặc mention.
2. Lấy context gần nhất từ DB.
3. Nếu có file đính kèm: chạy file indexing pipeline (chunk → LLM index → validation).
4. Chạy reasoning loop, gọi tool khi cần.
5. Chạy final synthesis để tạo câu trả lời sạch.
6. Log user/assistant messages về DB.

## Prompt configuration

Tất cả prompt templates nằm trong `src/instructions/`. Chỉnh sửa nội dung prompt bằng cách edit file `.txt` tương ứng — không cần sửa code Python.

Các file prompt chính:

- `azuris_system_prompt.txt` — system prompt chính (Chad Gibiti identity)
- `identity_capability_prompt.txt` — template identity + role contract + tool capabilities
- `lite_reasoning_prompt.txt` — prompt cho tier-1 reasoning model
- `fallback_system_prompt.txt` — prompt cho fallback synthesis
- `three_block_context_prompt.txt` — template 3-block context
- `file_index_reasoning_prompt.txt` — prompt cho file indexing reasoning
- `file_index_validation_prompt.txt` — prompt cho file index validation

Model alias có thể override qua env:

- `REASONING_MODEL_ALIAS` — model cho reasoning loop (default: flash-lite)
- `FINAL_MODEL_ALIAS` — model cho final synthesis (default: flash)
- `FALLBACK_MODEL_ALIAS` — model cho fallback (default: same as reasoning)

## Search & cache runtime (production)

`web_search` hiện có các lớp ổn định chính:

- Canonical cache key cho query tương đương nghĩa (không chỉ match theo raw text).
- Cache TTL theo ngữ cảnh:
  - query thường (`SEARCH_GENERAL_CACHE_TTL_SEC`)
  - query nhạy thời gian (`SEARCH_TIME_SENSITIVE_CACHE_TTL_SEC`)
- Inflight dedup: nhiều request trùng key sẽ join cùng 1 task thay vì gọi provider lặp.
- Failed-query cooldown (`SEARCH_FAILED_QUERY_COOLDOWN_SEC`) để tránh spam provider khi nguồn ngoài lỗi.
- Deep-read có retry ngắn, lọc boilerplate, và empty-evidence cache để giảm fetch lặp.

## Memory model hiện tại

Hệ thống theo hướng **DB-first + hybrid scope**:

- Mặc định note là `scope=user` (riêng từng user).
- Tri thức không cá nhân có thể vào `candidate_global`.
- Chỉ promote thành `scope=global` khi đủ ngưỡng xác nhận từ nhiều user khác nhau.
- Có chặn nội dung note mang tính lạm dụng (harassment/impersonation/dox-like markers).

## Tool inventory

Hiện có 6 tools:

- `web_search`
- `get_weather`
- `calculate`
- `save_note`
- `retrieve_notes`
- `image_recognition`

## Slash commands đáng chú ý

Core/admin:

- `/reset-chat`
- `/premium`
- `/reset-all`
- `/message_to`
- `/global-notes`
- `/global-note-demote`
- `/donate` — hiện QR ủng hộ (Ko-fi / PayPal), ảnh mã hóa Fernet, tự xóa sau 2 phút

Voice room:

- `/lock`
- `/unlock`
- `/move`
- `/move_all`
- `/set_room`
- `/add_privet`
- `/remove_privet`
- `/list_privet`

## Admin moderation cho global memory

`/global-notes` và `/global-note-demote` có flow dropdown + pagination để review/demote trực quan.

## Tài liệu kỹ thuật

- Tổng quan kỹ thuật: `PROJECT_INFO.txt`
- Cấu trúc project: `Project_structure.txt`

## Custom API Health Checker
Tính năng tự động kiểm tra sức khoẻ (health check) của OpenAI Custom Endpoint chạy ngầm. Tính năng này:
1. Nằm trong thư mục `src/services/health_checker.py`.
2. Có thể được trigger thủ công bằng slash command `/health_check` dành cho Admin.
3. Khi keys chết (die), tự động sử dụng LLM để tóm tắt và gửi report cho Admin theo mốc timestamp.
