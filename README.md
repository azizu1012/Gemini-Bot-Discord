# Azuris Discord Bot

Azuris là Discord bot dùng pipeline Gemini 2 tầng (reasoning/tool loop + final synthesis), có memory dài hạn qua SQLite, shared knowledge có kiểm soát, và lớp ổn định runtime cho production (cache, retry budget, PM2 fresh mode).

## Quick start

```bash
cd Azuris_refactor_code_base
pip install -r requirements.txt
python main.py
```

Hoặc chạy launcher:

```bash
python run_bot.py
python run_bot.py --server
```

Linux/Ubuntu launcher có hỗ trợ PM2:

```bash
./run_bot.sh --server
./run_bot.sh --pm2 --server
./run_bot.sh --pm2-fresh --server
```

## Cấu hình tối thiểu

```env
DISCORD_TOKEN=...
GEMINI_API_KEY_1=...
```

Chi tiết biến môi trường: xem `.env.example`.

## Kiến trúc chính

- `main.py`: entrypoint mỏng, ủy quyền chạy cho `run_bot.py`
- `run_bot.py`: launcher chính, hỗ trợ mode bot-only hoặc bot + server
- `run_bot.sh`: launcher Linux/PM2 (`--pm2`, `--pm2-fresh`, `--server`)
- `src/handlers/message_handler.py`: orchestration pipeline xử lý mỗi message
- `src/handlers/bot_core.py`: vòng đời bot, slash commands, admin interactions
- `src/tools/tools.py`: registry/dispatch tool calls cho model + search pipeline
- `src/database/repository.py`: SQLite repository, fresh schema bootstrap, auto-rebuild khi schema cũ/lỗi
- `src/managers/note_manager.py`: logic phân loại note, policy scope, promote global

## Pipeline phản hồi

1. Nhận message từ DM hoặc mention.
2. Lấy context gần nhất từ DB.
3. Chạy reasoning loop, gọi tool khi cần.
4. Chạy final synthesis để tạo câu trả lời sạch.
5. Log user/assistant messages về DB.

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
- Gói context gửi agent ngoài: `AGENT_HANDOFF_PROJECT_CONTEXT.md`
