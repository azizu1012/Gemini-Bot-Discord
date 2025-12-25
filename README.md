# ✨ FUGUE - The Ethereal Soul Companion

**Vong Quy Nhân (忘歸人)** | Tingyun Reborn | Xianzhou Wisdom | 2-Tier Model System

✅ **PRODUCTION READY** | 4500+ lines | 25+ classes | 0% logic loss

---

## 🚀 Quick Start (2 Minutes)

### Ubuntu/Linux Server (Recommended)
```bash
cd Fuge_refactor_code_base
chmod +x run_bot.sh
./run_bot.sh
```

With web server for monitoring:
```bash
./run_bot.sh --server
```

### Windows
```batch
cd Fuge_refactor_code_base
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python run_bot.py
```

---

## ✨ Key Features

### 🧠 2-Tier Model System
- **Tier 1 (Lite)**: Internal reasoning + tool calling (gemini-2.5-flash-lite)
- **Tier 2 (Flash)**: Personality-rich response (gemini-2.5-flash)
- **Fallback**: If Flash fails (429), Lite takes over with elegance
- **3-Block Context**: User input + reasoning + tool results → harmonious synthesis

### 🔍 Advanced Search
- **3 Google CSE in Parallel**: Simultaneous queries for comprehensive insight
- **Smart Classification**: 30+ topic categories for precise discovery
- **Fallback Chain**: CSE → SerpAPI → Tavily → Exa
- **6-Hour Cache**: Timeless wisdom at hand

### 🎨 Tools & Integration
- **8 Tools**: Search, weather, calculator, notes, images, Drive
- **Image Recognition**: Hugging Face Qwen2.5-VL (perceives visual essence)
- **File Parsing**: Extract wisdom from .txt, .pdf (up to 20MB)
- **User Notes**: Remember and cherish personal insights

### 💾 Data & Persistence
- **SQLite**: Conversations preserved, 30-day natural cycle
- **JSON Memory**: Last 10 messages per user (inner chamber)
- **Auto-Backup**: On awakening
- **User Isolation**: Each spirit's private sanctuary

### 🛡️ Safety & Control
- **API Rotation**: 5 Gemini keys (graceful fallback on strain)
- **Rate Limiting**: 1 msg/5 min per user (respect the rhythm)
- **Premium System**: Admin-curated access
- **Confirmation Prompts**: Wisdom before action

### 🎯 Personality
**FUGUE = Tingyun Reimagined**
- Elegant, metaphor-based responses
- Poetic wisdom (Honkai Star Rail aesthetic)
- Graceful synthesis of knowledge
- Xianzhou elegance in every word

---
