# 🔥 AZURIS - Tech-Bro Discord Bot

**Chad Gibiti** | Gemini 2.5 (2-Tier) | Smart Tools | Production Ready

## Quick Start

```bash
cd Azuris_refactor_code_base
pip install -r requirements.txt
python run_bot.py              # Bot only
python run_bot.py --server     # + Web server
```

## Features

- **2-Tier Model**: Lite (reasoning) + Flash (personality)
- **Smart Tools**: Search, weather, calculator, notes, images
- **Auto Fallback**: Lite takes over if Flash fails
- **Fast Search**: 3 Google CSE in parallel, 6-hour cache
- **Safe**: API rotation, rate limiting, auto-backup
- **Premium**: DM access for admin-approved users

## Usage

```
@Azuris your question
```

**Commands:**
```
/reset-chat              - Clear history
/premium @user add       - Grant access (admin)
/premium @user remove    - Revoke access (admin)
```

## Configuration

See `.env.example` for all settings. Required:
```env
DISCORD_TOKEN=your_token
GEMINI_API_KEY_1=your_key
```

---

📖 **Details?** See `PROJECT_INFO.txt`
