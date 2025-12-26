# Unified Discord Bot - Azuris & Fuge

A consolidated Discord bot with **2-tier Gemini model system** combining reasoning (lite) + personality-driven responses (flash), with shared core logic for multiple bot instances.

## 🎯 Features

### Architecture
- **Unified Codebase**: Single `common_src/` with shared handlers, database, services, tools
- **Per-Instance Personalities**: Each bot instance loads its own personality from Python module
- **2-Tier Model System**:
  - **Tier 1 (Lite)**: gemini-2.5-flash-lite for reasoning, tool planning, and execution
  - **Tier 2 (Flash)**: gemini-2.5-flash for final output with personality
- **No Flask Dependency**: Simple async bot with PM2 process management

### Safety & Features
- ✅ **@Mention Filter**: Automatically disables @everyone/@here/@mentions in bot output
- ✅ **Smart Message Chunking**: Splits long responses (Discord 2000 char limit)
- ✅ **Chain Reply System**: Bot messages reply to each other for readability
- ✅ **Rate Limiting**: 15 Gemini API keys with smart rotation
- ✅ **Database**: SQLite with per-instance storage
- ✅ **Long-term Memory**: User notes system
- ✅ **6 Integrated Tools**: web_search, calculate, get_weather, image_recognition, save_note, retrieve_notes

## 🚀 Quick Start

### Prerequisites
```bash
pip install -r requirements.txt
```

### Environment Setup

**Azuris Instance** (`instances/azuris/.env`):
```env
DISCORD_TOKEN=your_azuris_token
GEMINI_API_KEY_1=key1
GEMINI_API_KEY_2=key2
# ... up to GEMINI_API_KEY_15
MODEL_NAME=gemini-2.5-flash
```

**Fuge Instance** (`instances/fuge/.env`):
```env
DISCORD_TOKEN=your_fuge_token
GEMINI_API_KEY_1=key1
# ... same Gemini keys (can be same or different)
```

### Run Bots

**Development** (terminal):
```bash
# Azuris
cd instances/azuris
python run.py

# Fuge (different terminal)
cd instances/fuge
python run.py
```

**Production** (PM2):
```bash
pm2 start instances/azuris/run.py --name azuris
pm2 start instances/fuge/run.py --name fuge

# Monitor
pm2 logs

# Stop
pm2 stop azuris fuge

# Restart
pm2 restart azuris fuge

# Delete
pm2 delete azuris fuge
```

## 📁 Structure

```
Muti-bot-syns/
├── common_src/                    # Shared logic
│   ├── core/
│   │   ├── config.py             # .env loader, API keys
│   │   ├── system_prompt.py       # Dynamic personality loader
│   │   ├── lite_sys_prompt.py     # Tier 1 (reasoning-only) prompt
│   │   └── logger.py
│   ├── handlers/
│   │   ├── bot_core.py          # Discord.py bot setup
│   │   ├── message_handler.py   # 2-tier Gemini orchestration + @mention filter
│   │   └── bot_server.py
│   ├── database/
│   │   └── repository.py        # SQLite operations
│   ├── managers/
│   │   ├── cache_manager.py
│   │   ├── cleanup_manager.py
│   │   ├── note_manager.py      # Long-term memory
│   │   └── premium_manager.py
│   ├── services/
│   │   ├── memory_service.py
│   │   └── file_parser.py
│   └── tools/
│       └── tools.py             # Web search, calculate, weather, etc.
├── instances/
│   ├── azuris/
│   │   ├── .env                 # Instance-specific config
│   │   ├── run.py               # Entry point
│   │   ├── data/                # Instance-specific DB & memory
│   │   └── instructions/
│   │       └── instructions.py  # PERSONALITY_PROMPT for Chad Gibiti
│   └── fuge/
│       └── [same structure]     # PERSONALITY_PROMPT for Tingyun Reborn
├── requirements.txt
├── .gitignore                   # Excludes .env, data/, logs
└── CHANGELOG.md
```

## 🔧 How It Works

### Message Flow
```
User Message
    ↓
[Tier 1: Lite Model] → Reasoning + Tool Planning
    ↓
[Tools Execution] → web_search, calculate, get_weather, etc.
    ↓
[Tier 2: Flash Model] → Final Output with Personality
    ↓
[@Mention Filter] → Disable @everyone/@here/@mentions
    ↓
[Smart Chunking] → Split if > 1900 chars
    ↓
[Chain Reply] → Send with Discord reply threading
    ↓
User Sees Response
```

### Personality Loading
```python
# instances/azuris/instructions/instructions.py
PERSONALITY_PROMPT = r"""
You are Chad Gibiti - a sharp tech-bro...
[personality definition]
"""

# common_src/core/system_prompt.py
def get_system_prompt():
    # Dynamically loads PERSONALITY_PROMPT from instance folder
    # Falls back to default if not found
```

### @Mention Filter
```python
# Automatically applied in message_handler.py
@everyone → @everyone (disabled)
@here     → @here (disabled)
<@12345>  → <@​12345> (disabled with zero-width space)
```

## 🔑 API Keys

The bot rotates through **15 Gemini API keys** with exponential backoff:
- First failure: 2 second delay
- Second failure: 4 second delay
- Up to: 10 second delay between keys

Supports both:
- Individual keys per instance (recommended)
- Shared keys across instances

## 🛡️ Safety Features

1. **Rate Limiting**: Warns after 15 requests/30 minutes
2. **@Mention Prevention**: No accidental @everyone/@here pings
3. **Permission Checks**: Admin-only commands
4. **Spam Detection**: 3 messages/30 sec threshold
5. **Database Backups**: Auto-backup on startup
6. **Error Recovery**: Fallback to lite model if flash fails

## 📊 Customization

### Change Personality
Edit `instances/{bot_name}/instructions/instructions.py` and update `PERSONALITY_PROMPT`.

### Adjust Model Tiers
- Tier 1: Change `gemini-2.5-flash-lite` in message_handler.py
- Tier 2: Change `gemini-2.5-flash` in message_handler.py

### Modify Tools
Edit `common_src/tools/tools.py` to add/remove capabilities.

## 🐛 Troubleshooting

**Bot not responding**: Check `.env` file exists in instance folder
**API key errors**: Verify GEMINI_API_KEY_1 through KEY_15 in .env
**Permission denied**: Ensure bot has Send Messages + Embed Links permissions
**@Mention filter not working**: Check message_handler.py `_sanitize_mentions()` function

## 📝 Development Notes

- All Python files checked for syntax (✅ all valid)
- Instance data excluded from git (.gitignore)
- No framework dependencies (direct discord.py + google.generativeai)
- Async/await throughout for performance

## 📄 License

See LICENSE.txt if present in the repository.

## 🤝 Contributing

When modifying shared logic (`common_src/`), test on both instances.
Instance-specific changes go in respective `instructions/` folders.

---

**Last Updated**: Dec 26, 2025  
**Instances**: Azuris (Chad Gibiti), Fuge (Tingyun Reborn)  
**Model**: Gemini 2.5 (Flash + Lite)
