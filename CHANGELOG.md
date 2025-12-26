# Changelog - Unified Discord Bot

## v1.0.0 - Unified Bot Consolidation (Dec 26, 2025)

### ✨ New Features
- **Unified Codebase**: Consolidated Azuris & Fuge into single `common_src` with per-instance personalities
- **Dynamic Personality Loading**: Each instance loads personality from `instructions.py` dynamically
- **2-Tier Gemini Model System**:
  - Tier 1: gemini-2.5-flash-lite (reasoning + tools)
  - Tier 2: gemini-2.5-flash (final output with personality)
- **Smart Message Chunking**: Intelligent text splitting (newlines → spaces → hard split)
- **Chain Reply System**: Bot messages chain-reply for better readability
- **@Mention Safety Filter**: Automatically disables @everyone/@here/@mentions in output

### 🔧 Technical Improvements
- Removed hardcoded personalities (replaced with Python modules)
- Removed Flask dependency (use PM2 for process management)
- Instance-specific .env loading (each bot loads from its own folder)
- Fixed DB path handling (per-instance databases)
- Simplified lite prompt to avoid unnecessary searches
- Softened personality tone for better user experience

### 📁 Architecture
```
Muti-bot-syns/
├── common_src/           # Shared logic for ALL instances
│   ├── core/            # Config, prompts, logging
│   ├── handlers/        # Bot core & message processing
│   ├── database/        # SQLite repository
│   ├── managers/        # Cache, cleanup, notes, premium
│   ├── services/        # Memory, file parsing
│   └── tools/           # Gemini tools (search, calc, weather, etc)
├── instances/
│   ├── azuris/          # Chad Gibiti instance
│   │   ├── .env         # Instance-specific config
│   │   ├── run.py       # Entry point
│   │   ├── data/        # Instance-specific DB + memory
│   │   └── instructions/
│   │       └── instructions.py  # Personality definition
│   └── fuge/            # Tingyun Reborn instance
│       └── [same structure]
└── .gitignore           # Excludes data/, .env, logs
```

### 🚀 Deployment
```bash
# Start Azuris
pm2 start instances/azuris/run.py --name azuris

# Start Fuge
pm2 start instances/fuge/run.py --name fuge

# Manage
pm2 logs
pm2 stop azuris
pm2 restart azuris
```

### 🔒 Safety Features
- @mention filtering (prevents @everyone/@here pings)
- Rate limiting (15 req/30min warning)
- Exponential backoff for API failures
- Database backup system
- Spam detection
- Permission checks (admin-only commands)

### 📝 Known Limitations
- Knowledge cutoff: 2024 (searches for recent info if needed)
- 2000 char limit per Discord message (smart chunking handles this)
- 15 Gemini API keys rotation (exponential backoff on 429)

### 🔄 Migration Notes
- Old standalone folders (Azuris_refactor_code_base, Fuge_refactor_code_base) remain for reference
- All new development should use Muti-bot-syns/
- Instance data stored locally (not in git)
