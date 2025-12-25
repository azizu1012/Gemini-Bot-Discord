# 🔥 AZURIS - The Ultimate Tech-Bro Discord Bot

**Chad Gibiti Reborn** | High-Tier AI | Advanced Tool Integration | 2-Tier Model System

✅ **PRODUCTION READY** | 4500+ lines | 25+ classes | 0% logic loss

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

### Windows
```batch
cd Azuris_refactor_code_base
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python run_bot.py
```

---

## ✨ Key Features

### 🧠 2-Tier Model System
- **Tier 1 (Lite)**: Fast reasoning + tool calling (gemini-2.5-flash-lite)
- **Tier 2 (Flash)**: Personality-driven response (gemini-2.5-flash)
- **Fallback**: If Flash fails (429), Lite takes over with personality
- **3-Block Context**: User input + reasoning + tool results → optimal processing

### 🔍 Advanced Search
- **3 Google CSE in Parallel**: Simultaneous queries for speed
- **Smart Classification**: 30+ topic categories for relevance
- **Fallback Chain**: CSE → SerpAPI → Tavily → Exa
- **6-Hour Cache**: Instant repeated queries

### 🎨 Tools & Integration
- **8 Tools**: Search, weather, calculator, notes, images, Drive, code execution
- **Image Recognition**: Hugging Face Qwen2.5-VL (analyzes images)
- **File Parsing**: Extract text from .txt, .pdf (up to 20MB)
- **User Notes**: Save & retrieve personal notes

### 💾 Data & Persistence
- **SQLite**: Messages + notes with 30-day auto-cleanup
- **JSON Memory**: Last 10 messages per user (instant access)
- **Auto-Backup**: On startup
- **User Isolation**: Per-user history + notes

### 🛡️ Safety & Control
- **API Rotation**: 5 Gemini keys (automatic failover on 429)
- **Rate Limiting**: 1 msg/5 min per user (prevents spam)
- **Premium System**: Admin-controlled DM access
- **Confirmation Prompts**: Destructive actions require verification

### 🎯 Personality
**AZURIS = Chad Gibiti Reborn**
- Direct, witty, zero cringe responses
- Tech-focused expertise (gaming, code, AI, science)
- Bro-tier humor without the fluff
- Synthesizes complex info into actionable insights

---

## ⚙️ Configuration

**Required Variables:**
```env
DISCORD_TOKEN=your_token_here
GEMINI_API_KEY_1...5=your_keys
GOOGLE_CSE_ID_1...3=your_cse_ids
GOOGLE_CSE_API_KEY_1...3=your_api_keys
ADMIN_USER_IDS=123456789,987654321
```

See `.env.example` for complete list with all 30+ variables.

---

## 🎮 How to Use

### In Public Channels
```
@Azuris your question
```
Examples:
- `@Azuris What's the latest GPU benchmark?`
- `@Azuris Explain quantum computing in gaming terms`
- `@Azuris What's the weather in Tokyo?`

### Direct Messages (Premium Users Only)
Just send a message to the bot DM.

### Commands
```
/reset-chat              - Clear your history
/premium @user check     - Check premium status (admin)
/premium @user add       - Grant premium (admin)
/premium @user remove    - Revoke premium (admin)
```

---

## 📊 Monitoring

**Health Check:**
```bash
curl http://localhost:5000/health
```

**Bot Stats:**
```bash
curl http://localhost:5000/stats
```

---

## ✨ What Makes AZURIS Different

✅ **2-Tier Model**: Lite (reasoning) + Flash (personality) = best of both  
✅ **Fallback System**: Never fails - lite takes over if flash dies  
✅ **3-Block Context**: Structured reasoning + results for better output  
✅ **Smart Search**: 30 categories, parallel queries, auto-retry  
✅ **No Cringe**: Direct, witty, zero BS responses  
✅ **Production Ready**: 4500+ lines, 25+ classes, battle-tested  

---

**Status**: ✅ Production Ready | **Version**: 1.0.0-refactored | **Date**: December 2025  

📖 **Need technical details?** Read **PROJECT_INFO.txt** for deep documentation.
