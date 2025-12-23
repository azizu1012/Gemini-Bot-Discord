# 🤖 AZURIS DISCORD BOT - Refactored OOP Architecture

A production-ready Discord bot powered by Google Gemini 2.5-Flash with intelligent tools, advanced search capabilities, and user memory management.

**Status:** ✅ **PRODUCTION READY** | **4500+ Lines of Code** | **25+ Classes** | **100% Logic Preserved**

---

## 🚀 Quick Start (2 Minutes)

### Ubuntu/Linux Server (Recommended)
```bash
cd Azuris_refactor_code_base
chmod +x run_bot.sh
./run_bot.sh
```

With web server for monitoring:
```bash
./run_bot.sh --server
```

### Windows (Legacy)
```batch
cd Azuris_refactor_code_base
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python run_bot.py
```

### Mac/Linux Manual Setup
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your keys
python3 run_bot.py
```

---

## 📋 Configuration

1. **Get API Keys:**
   - Discord Bot Token: https://discord.com/developers
   - Gemini API Keys (×5): https://ai.google.dev/
   - Google CSE IDs (×3): https://programmablesearchengine.google.com/
   - Search Fallbacks: SerpAPI, Tavily, Exa
   - Weather: weatherapi.com
   - Images: Hugging Face token

2. **Setup:**
   ```bash
   cp .env.example .env
   # Edit .env with your actual keys
   python run_bot.py
   ```

3. **For Docker/Production:**
   - See PROJECT_INFO.txt for deployment options

---

## ✨ Key Features

| Feature | Details |
|---------|---------|
| **AI Model** | Gemini 2.5-Flash with extended thinking (5000 tokens) |
| **Web Search** | 3 Google CSE + SerpAPI/Tavily/Exa fallback (6h cache) |
| **Image Recognition** | Hugging Face Qwen model with 1h caching |
| **Tools** | 8 integrated tools (search, weather, math, notes, images, Drive) |
| **Memory** | Auto-save user notes + retrievable long-term memory |
| **Files** | Parse .txt and .pdf attachments (20MB limit) |
| **Rate Limiting** | 1 msg/5 min per user (configurable per premium tier) |
| **Premium Users** | Admin-controlled access to DM mode |
| **API Rotation** | 5 Gemini keys for automatic failover |
| **Data Persistence** | SQLite database + JSON memory |
| **Monitoring** | Web server with /health and /stats endpoints |

---

## 🎮 Commands

### User Commands
- **`/reset-chat`** - Clear your chat history (requires confirmation)

### Admin Commands
- **`/premium @user check`** - Check if user has premium
- **`/premium @user add`** - Grant premium access
- **`/premium @user remove`** - Revoke premium access
- **`/reset-all`** - Clear ALL database (requires "YES RESET" confirmation)
- **`/message_to @user "text"`** - Send DM to user
- **`/message_to #channel "text"`** - Send message to channel

### Usage
```
@Azuris What's the weather in London?
@Azuris Search for latest anime news
@Azuris Calculate 2^10 + 50
```

---

## 🏗️ Architecture

Clean separation of 8 architectural layers with proper OOP design:

```
Layer 1: CORE (Config + Logging + System Prompt)
   ├─ src/core/config.py
   ├─ src/core/logger.py
   └─ src/core/system_prompt.py

Layer 2: DATABASE (SQLite Persistence)
   └─ src/database/repository.py

Layer 3: SERVICES (Memory + File Parsing)
   ├─ src/services/memory_service.py
   └─ src/services/file_parser.py

Layer 4: MANAGERS (Cache, Cleanup, Premium, Notes)
   ├─ src/managers/cache_manager.py
   ├─ src/managers/cleanup_manager.py
   ├─ src/managers/premium_manager.py
   └─ src/managers/note_manager.py

Layer 5: TOOLS (Gemini Integration)
   └─ src/tools/tools.py (1700+ lines)

Layer 6: HANDLERS (Discord Integration)
   ├─ src/handlers/bot_core.py
   ├─ src/handlers/message_handler.py
   └─ src/handlers/bot_server.py

Layer 7: ENTRY POINTS
   ├─ main.py
   ├─ run_bot.py
   └─ run_bot.bat

Layer 8: CONFIGURATION & DATA
   ├─ .env (populated from .env.example)
   ├─ requirements.txt (27 packages)
   └─ data/ (persistent storage)
│   ├── premium_manager.py   # Premium users
│   └── note_manager.py      # User notes
│
├── tools/             # Gemini tools
│   └── tools.py       # 8 tools (search, weather, calc, etc.)
│
└── handlers/          # Discord integration
    ├── bot_core.py    # Bot init & commands
    ├── message_handler.py   # Message processing
    └── bot_server.py  # Flask web server

main.py               # Entry point
run_bot.py           # Bot runner with options
```

## 🎮 Commands

### User Commands
- **`/reset-chat`** - Clear your chat history (requires confirmation)
- **`/premium`** - Check premium status (info command)

### Admin Commands (must have `ADMIN_USER_IDS` set)
- **`/premium add @user`** - Add premium user
- **`/premium remove @user`** - Remove premium user
- **`/premium check @user`** - Check premium status
- **`/reset-all`** - Clear all database (requires "YES RESET" confirmation)
- **`/message_to @user "message"`** - Send DM to user
- **`/message_to #channel "message"`** - Send channel message

### Interaction Methods
1. **Mentions** - `@bot your question` in any channel
2. **DMs** - Direct message (premium users only)

## 🔧 Configuration

### Environment Variables
```env
# Discord
DISCORD_TOKEN=your_bot_token

# Gemini API (rotate 5 keys)
GEMINI_API_KEY_1=key1
GEMINI_API_KEY_2=key2
GEMINI_API_KEY_3=key3
GEMINI_API_KEY_4=key4
GEMINI_API_KEY_5=key5

# Search APIs
GOOGLE_CSE_ID_1=cse1
GOOGLE_CSE_ID_2=cse2
GOOGLE_CSE_ID_3=cse3
GOOGLE_API_KEY=key
SERP_API_KEY=key
TAVILY_API_KEY=key
EXA_API_KEY=key

# Other
WEATHER_API_KEY=key
HF_TOKEN=huggingface_token
ADMIN_USER_IDS=12345,67890

# Files
FILE_STORAGE_PATH=uploaded_files/
DB_PATH=data/bot_database.db
MEMORY_PATH=data/short_term_memory.json
```

## 📊 Web Server API

When running with `--server`:

```bash
GET /health              # Check bot status
GET /stats              # Bot statistics
POST /api/message       # Send message (webhook)
POST /api/cache/clear   # Clear cache (admin token)
```

Example:
```bash
curl http://localhost:5000/health
# {"status": "online", "bot_ready": true, ...}
```

## 🔄 API Key Rotation

Automatically rotates through 5 Gemini API keys:
- Key 1 → Key 2 → Key 3 → Key 4 → Key 5 → Key 1

If a key hits rate limit, seamlessly continues with next key.

## 💾 Data Storage

### SQLite Database
- **messages table**: Stores all conversations
- **user_notes table**: Persistent user notes
- **Auto-cleanup**: Deletes messages > 30 days
- **Backups**: Automatic backup on startup

### JSON Memory
- Fast access (in-memory cache)
- Last 10 messages per user
- Resets on bot restart

## 🚀 Performance Features

- **Parallel Searches**: 3 CSE APIs run simultaneously
- **Smart Caching**: 6h searches, 1h images
- **API Rotation**: 5-key pool prevents rate limits
- **Async/Await**: Non-blocking message processing
- **Rate Limiting**: Per-user cooldown system
- **Disk Management**: Auto-cleanup when low on space

---

## 📦 Installation & Deployment

### Quick Start (Ubuntu/Linux/Mac)
```bash
# Make script executable
chmod +x run_bot.sh

# Run with auto setup
./run_bot.sh

# Or with web server
./run_bot.sh --server
```

The script automatically:
- Checks Python 3.9+ 
- Creates/uses virtual environment
- Installs dependencies
- Validates .env file
- Starts the bot

### Production Deployment (Ubuntu/Linux)

**Option 1: PM2 (Recommended)**
```bash
npm install -g pm2
pm2 start "bash run_bot.sh" --name azuris --interpreter bash
pm2 startup
pm2 save
pm2 logs azuris        # View logs
```

**Option 2: Systemd Service (Standard)**
```bash
# Create /etc/systemd/system/azuris.service
[Unit]
Description=Azuris Discord Bot
After=network.target

[Service]
Type=simple
User=botuser
WorkingDirectory=/path/to/bot
ExecStart=/path/to/bot/run_bot.sh
Restart=on-failure

[Install]
WantedBy=multi-user.target

# Enable and start
sudo systemctl enable azuris
sudo systemctl start azuris
sudo journalctl -u azuris -f
```

**Option 3: Docker**
```dockerfile
FROM python:3.9-slim
WORKDIR /app
COPY . .
RUN chmod +x run_bot.sh
CMD ["./run_bot.sh"]
```

---

## 📈 Monitoring

### Logs
- Console output with timestamps
- Error tracking for debugging
- API call details (rotating keys)

### Web Server Stats
```
GET /stats
{
  "bot_name": "Azuris",
  "latency": 0.05,
  "guilds": 5,
  "users": 1234
}
```

## ⚙️ Development

### Running Tests
```bash
# Test bot initialization
python -c "from src.handlers.bot_core import BotCore; print('✓ BotCore loads')"

# Test database
python -c "from src.database.repository import DatabaseRepository; print('✓ DB loads')"

# Test all imports
python -c "from src.core.config import get_config; config = get_config(); print(f'✓ Config: {config.MODEL_NAME}')"
```

### Code Structure
- Classes use dependency injection
- Services have single responsibility
- Managers encapsulate features
- Handlers bridge Discord ↔ Services

## 🐛 Troubleshooting

### Bot doesn't respond
- Check token in .env
- Verify `intents.message_content = True`
- Check Discord server permissions

### "Missing environment variable"
- Copy all keys to .env
- Check for typos in variable names
- Use `.env.example` as template

### Rate limit errors
- Verify API keys are correct
- Check quota on each service
- Bot uses 5 Gemini keys (automatic rotation)

### File parsing errors
- Check file size < 20 MB
- Verify disk space > 100 MB free
- Supported formats: .txt, .pdf

## 📄 License

Based on @clone codebase. Refactored with OOP patterns and clean architecture.

## 🤝 Contributing

Modifications should:
1. Preserve existing logic
2. Follow class-based structure
3. Use dependency injection
4. Add type hints where possible
5. Log important operations

## 📞 Support

For issues, check:
1. `.env` configuration
2. Console logs for errors
3. Discord permissions
4. API quotas (search, Gemini, etc.)

---

**Version**: 1.0.0-refactored  
**Status**: Production Ready
