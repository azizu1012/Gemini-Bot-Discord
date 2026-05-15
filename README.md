# Azuris Discord Bot

Azuris là Discord bot dùng luồng 2 tầng Gemini:

- Tier 1: reasoning + tool calling
- Tier 2: final response synthesis
- Có fallback khi model final không khả dụng

## Quick start

```bash
cd Azuris_refactor_code_base
pip install -r requirements.txt
python run_bot.py              # Bot only
python run_bot.py --server     # Bot + Flask server
```

## Current capabilities

- Tool calling qua Gemini với **6 tools**:
  - `web_search`
  - `get_weather`
  - `calculate`
  - `save_note`
  - `retrieve_notes`
  - `image_recognition`
- Search pipeline hiện tại:
  - Primary: DuckDuckGo streams
  - Fallback (khi cần và có API key): SerpAPI, Tavily, Exa
- Message history + notes persistence
- Premium DM access control
- Optional Flask endpoints: `/health`, `/stats`, `/api/message`, `/api/cache/clear`

## Bot usage

Mention bot trong channel:

```text
@Azuris câu hỏi của bạn
```

## Slash commands

Core/admin:

- `/reset-chat`
- `/premium`
- `/reset-all`
- `/message_to`

Voice room management:

- `/lock`
- `/unlock`
- `/move`
- `/move_all`
- `/set_room`
- `/add_privet`
- `/remove_privet`
- `/list_privet`

## Configuration

Xem `.env.example` để cấu hình đầy đủ.
Bắt buộc tối thiểu:

```env
DISCORD_TOKEN=...
GEMINI_API_KEY_1=...
```

## Source layout

`src/` gồm các package chính:

- `core`
- `database`
- `handlers`
- `instructions`
- `managers`
- `services`
- `tools`
- `voice`

---
Chi tiết kỹ thuật: xem `PROJECT_INFO.txt`.
