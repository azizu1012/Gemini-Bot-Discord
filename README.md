# Gemini Discord Bot - Advanced Modular Edition

<p align="center">
  <a href="https://github.com/azizu1012/Gemini-Bot-Discord/blob/main/LICENSE">
    <img alt="License" src="https://img.shields.io/github/license/azizu1012/Gemini-Bot-Discord?style=flat-square"/>
  </a>
  <a href="https://discord.com/oauth2/authorize?client_id=1418949883859308594&permissions=8&integration_type=0&scope=bot">
    <img alt="Discord Bot" src="https://img.shields.io/badge/Discord-Add%20Bot-5865F2?style=flat-square&logo=discord&logoColor=white"/>
  </a>
  <a href="https://www.python.org/">
    <img alt="Python" src="https://img.shields.io/badge/Python-3.11%2B-blue?style=flat-square&logo=python"/>
  </a>
  <a href="https://render.com/">
    <img alt="Render" src="https://img.shields.io/badge/Render-Web%20Service%20(Free)-46E3B7?style=flat-square&logo=render&logoColor=white"/>
  </a>
</p>

## Introduction

**Gemini Discord Bot** is a high-performance, modular AI assistant built with `discord.py` and powered by **Google's Gemini Pro**. It's designed to be an autonomous and intelligent agent, capable of performing complex tasks through dynamic tool use.

This bot goes beyond simple chat by integrating a sophisticated, multi-layered search system, long-term memory, file analysis, image recognition, and more. The architecture is optimized for easy maintenance and has been engineered for stable, 24/7 deployment on **Render's Free Web Service Tier** using an integrated Flask server, eliminating the need for paid background workers.

---

## Key Features

| Feature | Description |
| :--- | :--- |
| 🤖 **Core AI** | Powered by **Google Gemini** with a failover system supporting up to **5 API keys** for maximum reliability. Features a fun, e-girl persona. |
| 🛠️ **Autonomous Tool Use** | Dynamically decides when to use tools like web search, calculator, or memory functions based on the conversation. |
| 🌐 **Multi-API Search** | - **Parallel Search**: Queries 3 separate Google Custom Search Engines simultaneously.<br>- **Automatic Fallback**: If CSE fails, it round-robins between **SerpAPI**, **Tavily**, and **Exa.ai**.<br>- **Topic-Aware**: Categorizes queries (e.g., Gaming, Tech, Finance) to generate smarter search terms.<br>- **6-Hour Cache**: Caches search results to reduce API calls. |
| 🧠 **Long-Term Memory** | - **Automatic Noting**: Intelligently identifies and saves important user information (preferences, facts, file summaries) to a persistent **SQLite** database.<br>- **Contextual Retrieval**: Fetches relevant memories when the user asks about past information. |
| 📄 **File & Image Analysis** | - **File Parsing**: Reads and understands content from uploaded files (`.txt`, `.py`, `.md`, etc.) and saves summaries to memory.<br>- **Image Recognition**: Uses a Hugging Face vision model to perform OCR, object detection, and answer questions about images. |
| 💬 **Interaction** | Responds to DMs (premium users only), replies, and mentions. Splits long responses into multiple messages. |
| 🔐 **Admin & Premium** | - **Admin Commands**: `/reset-all`, `/message_to` for privileged users.<br>- **Premium System**: Manages premium users in a `premium_users.json` file to grant DM access. |
| ⚙️ **System & Deployment** | - **SQLite Database**: Stores chat history and user notes.<br>- **Automatic Maintenance**: Backs up and cleans the database on startup.<br>- **Render-Optimized**: Integrated Flask server ensures 24/7 uptime on Render's free tier. |
| 🛡️ **Safe & Secure** | Includes an anti-spam/rate-limiting system and sanitizes user input to prevent prompt injection. |

---

## Tech Stack

- **Language**: Python 3.11+
- **Discord Library**: `discord.py`
- **AI Model**: Google Gemini Pro
- **Database**: SQLite
- **Web Framework**: Flask (for keep-alive)
- **Core Tools**: SymPy (Math), `requests`, `aiohttp`
- **Search APIs**: Google CSE, SerpAPI, Tavily, Exa.ai
- **Other APIs**: WeatherAPI, Hugging Face (for Vision)

---

## API Keys & Setup

To run the bot, you need the following:
- **Discord Bot Token**
- **Google Gemini API Key(s)** (at least 1, up to 5 are supported for failover)
- **At least one Search API key** from the following (all are recommended):
  - Google Custom Search Engine (up to 3 supported)
  - SerpAPI
  - Tavily
  - Exa.ai
- **(Optional) WeatherAPI Key** for the weather tool.
- **(Optional) Hugging Face Token** for the image recognition tool.

---

## Local Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/azizu1012/Gemini-Bot-Discord.git
    cd Gemini-Bot-Discord/gemini discord bot/clone
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Create the `.env` file:**
    In the `clone` directory, create a file named `.env` and fill it with your API keys.

    ```env
    # --- REQUIRED ---
    DISCORD_TOKEN=your_discord_bot_token
    ADMIN_ID=your_discord_user_id
    MODEL_NAME=gemini-pro # Or any other supported Gemini model

    # --- GEMINI KEYS (at least 1 required) ---
    GEMINI_API_KEY_PROD=your_main_gemini_key
    GEMINI_API_KEY_TEST=your_second_key
    GEMINI_API_KEY_BACKUP=your_third_key
    GEMINI_API_KEY_EXTRA1=your_fourth_key
    GEMINI_API_KEY_EXTRA2=your_fifth_key

    # --- SEARCH KEYS (at least 1 required) ---
    # Google CSE (Engine 1)
    GOOGLE_CSE_ID=your_google_cse_id_1
    GOOGLE_CSE_API_KEY=your_google_api_key_1
    # Google CSE (Engine 2)
    GOOGLE_CSE_ID_1=your_google_cse_id_2
    GOOGLE_CSE_API_KEY_1=your_google_api_key_2
    # Google CSE (Engine 3)
    GOOGLE_CSE_ID_2=your_google_cse_id_3
    GOOGLE_CSE_API_KEY_2=your_google_api_key_3
    # Fallback APIs
    SERPAPI_API_KEY=your_serpapi_key
    TAVILY_API_KEY=your_tavily_key
    EXA_API_KEY=your_exa_key

    # --- OPTIONAL ---
    WEATHER_API_KEY=your_weatherapi_key
    HF_TOKEN=your_huggingface_read_token
    ```

4.  **Run the bot:**
    ```bash
    python run_bot_sever.py
    ```

---

## Deploying on Render (Free)

This bot is designed to run on Render's free **Web Service** tier, which is more stable than a Background Worker.

1.  **Create a New Web Service:**
    - Go to your [Render Dashboard](https://dashboard.render.com) and click **New → Web Service**.
    - Connect your GitHub account and select the forked repository.

2.  **Configure the Service:**
    - **Name**: A name for your service (e.g., `gemini-discord-bot`).
    - **Branch**: `main`.
    - **Root Directory**: `gemini discord bot/clone` (Important: Set this correctly).
    - **Runtime**: `Python 3`.
    - **Build Command**: `pip install -r requirements.txt`.
    - **Start Command**: `python run_bot_sever.py`.
    - **Health Check Path**: `/` (This will ping the integrated Flask server).

3.  **Add Environment Variables:**
    - Go to the **Environment** tab.
    - Add all the variables from your `.env` file one by one.

4.  **Deploy:**
    - Click **Create Web Service**. Render will build and deploy your bot. The integrated Flask server will respond to health checks, keeping the bot online 24/7.

---

## Slash Commands

| Command | Description | Permissions |
| :--- | :--- | :--- |
| `/reset-chat` | Clears your personal chat history with the bot. | Everyone |
| `/premium` | Checks premium status or adds a premium user. | Admin Only |
| `/reset-all` | **Deletes all data** from the database (requires confirmation). | Admin Only |
| `/message_to` | Sends a DM or channel message to a specified user. | Admin Only |

---

## Project Structure

```
clone/
├── bot_core.py             # Core bot logic, Discord events, slash commands
├── message_handler.py      # Handles incoming messages and delegates tasks
├── tools.py                # Defines and executes all external tools (search, weather, etc.)
├── config.py               # Loads and manages all environment variables and constants
├── database.py             # Handles all SQLite database operations
├── memory.py               # Manages short-term (JSON) memory for chat context
├── note_manager.py         # Service layer for saving/retrieving long-term notes
├── file_parser.py          # Utility to parse content from uploaded files
├── premium_manager.py      # Manages the premium user list
├── server.py               # Integrated Flask web server for keep-alive
├── run_bot_sever.py        # Main entry point to start the bot and server
├── .env                    # Local environment variables (ignored by Git)
└── requirements.txt        # Python dependencies
```

---

## License

This project is licensed under the [MIT License](LICENSE).
