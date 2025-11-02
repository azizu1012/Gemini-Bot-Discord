import logging
import discord
import re   
from discord import app_commands, ChannelType
from discord.ext import commands
from dotenv import load_dotenv
import os
import sqlite3
import re
import json
import random
from datetime import datetime
import shutil
import sys
from datetime import timedelta
import asyncio
import sympy as sp
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import requests
from serpapi import GoogleSearch  # SerpAPI (dùng google-search-results package)
from tavily import TavilyClient  # Tavily
import exa_py  # Exa.ai (exa-py package)
from datetime import datetime, timedelta, timezone
import json
import os
from collections import defaultdict, deque
import aiofiles
# --- ĐỊNH NGHĨA TOOLS CHO GEMINI (TỐI GIẢN) ---
from google.generativeai.types import Tool, FunctionDeclaration

ALL_TOOLS = [
    Tool(function_declarations=[
        FunctionDeclaration(
            name="web_search",
            description=(
                "Tìm kiếm thông tin cập nhật (tin tức, giá cả, phiên bản game, sự kiện) sau năm 2024. "
                "Chỉ dùng khi kiến thức nội bộ của bạn đã lỗi thời so với ngày hiện tại. "
                "Yêu cầu TỰ DỊCH câu hỏi tiếng Việt của user thành một query tìm kiếm tiếng Anh TỐI ƯU."
            ),
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Câu hỏi bằng tiếng Anh"}},
                "required": ["query"]
            }
        )
    ]),
    Tool(function_declarations=[
        FunctionDeclaration(
            name="get_weather",
            description="Lấy thông tin thời tiết hiện tại cho một thành phố cụ thể.",
            parameters={
                "type": "object",
                "properties": {"city": {"type": "string", "description": "Tên thành phố, ví dụ: 'Hanoi', 'Tokyo'."}},
                "required": ["city"]
            }
        )
    ]),
    Tool(function_declarations=[
        FunctionDeclaration(
            name="calculate",
            description="Giải các bài toán số học hoặc biểu thức phức tạp, bao gồm các hàm lượng giác, logarit, và đại số.",
            parameters={
                "type": "object",
                "properties": {"equation": {"type": "string", "description": "Biểu thức toán học dưới dạng string, ví dụ: 'sin(pi/2) + 2*x'."}},
                "required": ["equation"]
            }
        )
    ]),
    Tool(function_declarations=[
        FunctionDeclaration(
            name="save_note",
            description="Lưu một mẩu thông tin, ghi chú hoặc lời nhắc cụ thể theo yêu cầu của người dùng để bạn có thể truy cập lại sau.",
            parameters={
                "type": "object",
                "properties": {"note": {"type": "string", "description": "Nội dung ghi chú cần lưu."}},
                "required": ["note"]
            }
        )
    ]),
]

# === BỘ ĐIỀU PHỐI TOOL ===
async def call_tool(function_call, user_id):
    name = function_call.name
    args = dict(function_call.args)  # Chuyển sang dict để log đẹp
    logger.info(f"TOOL GỌI: {name} | Args: {args} | User: {user_id}")

    try:
        if name == "web_search":
            query = args.get("query", "")
            return await run_search_apis(query, "general")

        elif name == "get_weather":
            city = args.get("city", "Ho Chi Minh City")
            data = await get_weather(city)
            return json.dumps(data, ensure_ascii=False, indent=2)

        elif name == "calculate":
            eq = args.get("equation", "")
            return await run_calculator(eq)

        elif name == "save_note":
            note = args.get("note", "")
            return await save_note(note, user_id)

        else:
            return "Tool không tồn tại!"

    except Exception as e:
        logger.error(f"Tool {name} lỗi: {e}")
        return f"Lỗi tool: {str(e)}"
# --- BẢN ĐỒ TÊN THÀNH PHỐ ---
CITY_NAME_MAP = {
    "hồ chí minh": ("Ho Chi Minh City", "Thành phố Hồ Chí Minh"),
    "tp.hcm": ("Ho Chi Minh City", "Thành phố Hồ Chí Minh"),
    "sài gòn": ("Ho Chi Minh City", "Thành phố Hồ Chí Minh"),
    "ho chi minh city": ("Ho Chi Minh City", "Thành phố Hồ Chí Minh"),
    "hcmc": ("Ho Chi Minh City", "Thành phố Hồ Chí Minh"),
    "hà nội": ("Hanoi", "Hà Nội"),
    "ha noi": ("Hanoi", "Hà Nội"),
    "danang": ("Da Nang", "Đà Nẵng"),
    "đà nẵng": ("Da Nang", "Đà Nẵng"),
    "da nang": ("Da Nang", "Đà Nẵng"),
}
# --- HÀM CHUYỂN ĐỔI TÊN THÀNH PHỐ ---
def normalize_city_name(city_query):
    """Chuyển tên thành phố người dùng nhập về tên chuẩn WeatherAPI và tên tiếng Việt."""
    if not city_query:
        return ("Ho Chi Minh City", "Thành phố Hồ Chí Minh")
    city_key = city_query.strip().lower()
    for k, v in CITY_NAME_MAP.items():
        if k in city_key:
            return v  # (Tên tiếng Anh, Tên tiếng Việt)
    # Nếu không khớp, trả về tên gốc (WeatherAPI sẽ cố gắng nhận diện)
    return (city_query, city_query.title())

# --- THIẾT LẬP LOGGING ---
# Setup logging – FIX DUPLICATE (THAY TOÀN BỘ)
logger = logging.getLogger('bot_gemini')
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')

file_handler = logging.FileHandler('bot.log', encoding='utf-8')
file_handler.setFormatter(formatter)

stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)

logger.handlers = [file_handler, stream_handler]  # THAY HẾT HANDLER CŨ
logger.propagate = False  # NGĂN LOG LẶP


# --- TẢI BIẾN MÔI TRƯỜNG ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GEMINI_API_KEY_PROD = os.getenv('GEMINI_API_KEY_PROD')
GEMINI_API_KEY_TEST = os.getenv('GEMINI_API_KEY_TEST')
GEMINI_API_KEY_BACKUP = os.getenv('GEMINI_API_KEY_BACKUP')
GEMINI_API_KEY_EXTRA1 = os.getenv('GEMINI_API_KEY_EXTRA1')
GEMINI_API_KEY_EXTRA2 = os.getenv('GEMINI_API_KEY_EXTRA2')
MODEL_NAME = os.getenv('MODEL_NAME')
ADMIN_ID = os.getenv('ADMIN_ID', '')
HABE_USER_ID = os.getenv('HABE_USER_ID', '')
MIRA_USER_ID = os.getenv('MIRA_USER_ID', '')
ADO_FAT_USER_ID = os.getenv('ADO_FAT_USER_ID', '')
MUC_RIM_USER_ID = os.getenv('MUC_RIM_USER_ID', '')
SUC_VIEN_USER_ID = os.getenv('SUC_VIEN_USER_ID', '')
CHUI_USER_ID = os.getenv('CHUI_USER_ID', '')

# API Keys cho Search (từ .env)
SERPAPI_API_KEY = os.getenv('SERPAPI_API_KEY')
TAVILY_API_KEY = os.getenv('TAVILY_API_KEY')
EXA_API_KEY = os.getenv('EXA_API_KEY')
GOOGLE_CSE_ID = os.getenv('GOOGLE_CSE_ID')  # Đã có
GOOGLE_CSE_API_KEY = os.getenv('GOOGLE_CSE_API_KEY')  # Đã có

# Global counter cho round-robin balance (chia đều 4 APIs)
SEARCH_API_COUNTER = 0
SEARCH_LOCK = asyncio.Lock()  # Lock để an toàn async

# File cache cho thời tiết (cập nhật mỗi giờ)
WEATHER_CACHE_PATH = os.path.join(os.path.dirname(__file__), 'weather_cache.json')
weather_lock = asyncio.Lock()  # Lock cho cache

# Lấy key & city từ .env
WEATHER_API_KEY = os.getenv('WEATHER_API_KEY')
CITY = os.getenv('CITY')

# --- ĐƯỜNG DẪN FILE (CẬP NHẬT) ---
DB_PATH = os.path.join(os.path.dirname(__file__), 'chat_history.db')
# (Thay đổi) Dùng 1 file backup cố định, không spam file theo ngày
DB_BACKUP_PATH = os.path.join(os.path.dirname(__file__),
                              'chat_history_backup.db')
NOTE_PATH = os.path.join(os.path.dirname(__file__), 'notes.txt')
# (Mới) File JSON cho bộ nhớ ngắn hạn
MEMORY_PATH = os.path.join(os.path.dirname(__file__), 'short_term_memory.json')

# (Mới) Lock để tránh xung đột khi đọc/ghi file JSON
memory_lock = asyncio.Lock()
weather_lock = asyncio.Lock()

# --- THIẾT LẬP GEMINI API KEYS CHO FAILOVER ---
GEMINI_API_KEYS = []
if GEMINI_API_KEY_PROD:
    GEMINI_API_KEYS.append(GEMINI_API_KEY_PROD)
if GEMINI_API_KEY_TEST:
    GEMINI_API_KEYS.append(GEMINI_API_KEY_TEST)
if GEMINI_API_KEY_BACKUP:
    GEMINI_API_KEYS.append(GEMINI_API_KEY_BACKUP)
if GEMINI_API_KEY_EXTRA1:
    GEMINI_API_KEYS.append(GEMINI_API_KEY_EXTRA1)
if GEMINI_API_KEY_EXTRA2:
    GEMINI_API_KEYS.append(GEMINI_API_KEY_EXTRA2)

if not GEMINI_API_KEYS:
    logger.error("Không tìm thấy Gemini API keys! Bot sẽ không thể hoạt động.")
else:
    logger.info(
        f"Đã thiết lập {len(GEMINI_API_KEYS)} Gemini API keys cho Failover.")

# --- (CẬP NHẬT) XỬ LÝ GEMINI API VÀ SYSTEM PROMPT ---
LAST_WORKING_KEY_INDEX = 0
current_api_index = 0
# --- CACHE SEARCH ---
SEARCH_CACHE = {}
CACHE_LOCK = asyncio.Lock()


# --- ANTI-SPAM NÂNG CAO ---
user_queue = defaultdict(deque)
SPAM_THRESHOLD = 3
SPAM_WINDOW = 30

# --- KHỞI TẠO BOT (CHỈ 1 INSTANCE) ---
intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# --- KEEP-ALIVE WEBHOOK ---
from flask import Flask, request
import threading

# Flask app cho webhook keep-alive
keep_alive_app = Flask(__name__)

@keep_alive_app.route('/', methods=['GET', 'POST'])
def webhook():
    return "Bot alive! No sleep pls~ 😴"

def run_keep_alive():
    port = int(os.environ.get('PORT', 8080))
    keep_alive_app.run(host='0.0.0.0', port=port, debug=False)

# --- HÀM GEMINI (FIX TOOL CALLING) ---
async def run_gemini_api(messages, model_name, user_id, temperature=0.7, max_tokens=2000):
    """(FIXED) Chạy Gemini API với Tool Calling và Failover Keys."""
   
    # Lấy danh sách key từ .env
    keys = [GEMINI_API_KEY_PROD, GEMINI_API_KEY_TEST, GEMINI_API_KEY_BACKUP, GEMINI_API_KEY_EXTRA1, GEMINI_API_KEY_EXTRA2]
    keys = [k for k in keys if k]
    if not keys:
        return "Lỗi: Không có API key."
    
    # --- CHUẨN BỊ LỊCH SỬ CHAT ---
    gemini_messages = []
    system_instruction = None
    for msg in messages:
        if msg["role"] == "system":
            system_instruction = msg["content"]
            continue
           
        # Xử lý tin nhắn user/assistant cũ (chỉ có text)
        if "content" in msg and isinstance(msg["content"], str):
            role = "model" if msg["role"] == "assistant" else msg["role"]
            gemini_messages.append({"role": role, "parts": [{"text": msg["content"]}]})
       
        # Xử lý các phần tool call/response đã có trong lịch sử
        elif "parts" in msg:
            role = "model" if msg["role"] == "assistant" else msg["role"]
            gemini_messages.append({"role": role, "parts": msg["parts"]})
    
    # --- VÒNG LẶP API KEY (FAILOVER) ---
    for i, api_key in enumerate(keys):
        logger.info(f"THỬ KEY {i+1}: {api_key[:8]}...")
        try:
            genai.configure(api_key=api_key)
           
            # Cấu hình model với tools và system_instruction
            model = genai.GenerativeModel(
                model_name,
                tools=ALL_TOOLS,
                system_instruction=system_instruction,
                safety_settings=[
                    {"category": HarmCategory.HARM_CATEGORY_HARASSMENT, "threshold": HarmBlockThreshold.BLOCK_NONE},
                    {"category": HarmCategory.HARM_CATEGORY_HATE_SPEECH, "threshold": HarmBlockThreshold.BLOCK_NONE},
                    {"category": HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, "threshold": HarmBlockThreshold.BLOCK_NONE},
                    {"category": HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, "threshold": HarmBlockThreshold.BLOCK_NONE},
                ],
                generation_config={"temperature": temperature, "max_output_tokens": max_tokens}
            )
            
            # --- VÒNG LẶP TOOL CALLING (Tối đa 3 lần) ---
            for _ in range(3):  # Giới hạn 3 lần gọi tool
                response = await asyncio.to_thread(model.generate_content, gemini_messages)
               
                if not response.candidates or not response.candidates[0].content.parts:
                    logger.warning(f"Key {i+1} trả về response rỗng.")
                    break
                
                part = response.candidates[0].content.parts[0]
                
                # KIỂM TRA TOOL CALL
                if part.function_call:
                    fc = part.function_call
                    # 1. Thêm Tool Call vào lịch sử
                    gemini_messages.append({"role": "model", "parts": [part]})
                    
                    # 2. Thực thi Tool
                    try:
                        tool_result_content = await call_tool(fc, user_id)
                    except Exception as e:
                        logger.error(f"Lỗi khi gọi tool {fc.name}: {e}")
                        # Nếu tool gọi bị lỗi, chúng ta thông báo cho Gemini biết
                        tool_result_content = f"Tool {fc.name} đã thất bại: {str(e)[:500]}. Vui lòng trả lời người dùng rằng không tìm được thông tin."

                    # 3. Xử lý trường hợp tool trả về rỗng (nếu tool không lỗi, nhưng kết quả rỗng)
                    if not tool_result_content or str(tool_result_content).lower().startswith("lỗi"):
                        logger.warning(f"Tool {fc.name} trả về lỗi hoặc rỗng: {tool_result_content}")
                        # Thay thế bằng thông báo lỗi để Gemini tự tổng hợp câu trả lời
                        tool_result_content = f"Tool {fc.name} trả về kết quả rỗng. Vui lòng thử tìm lại với query khác hoặc trả lời người dùng rằng không tìm được thông tin."
                        
                    # 4. Thêm Tool Response vào lịch sử
                    tool_response_part = {
                        "function_response": {
                            "name": fc.name,
                            "response": {"content": tool_result_content},
                        }
                    }
                    gemini_messages.append({"role": "function", "parts": [tool_response_part]})
                    continue # Tiếp tục vòng lặp
                
                # KIỂM TRA TEXT
                elif part.text:
                    logger.info(f"KEY {i+1} THÀNH CÔNG!")
                    return part.text.strip()
                
                else:
                    logger.warning(f"Key {i+1} trả về part không có text/tool.")
                    break
            
            # Nếu lặp quá 3 lần
            logger.warning(f"Key {i+1} lặp tool quá 3 lần.")
            try:
                if response.text:
                    logger.info(f"KEY {i+1} THÀNH CÔNG! (sau loop)")
                    return response.text.strip()
            except Exception:
                pass
                
            raise Exception("Tool loop ended or part was empty")
        
        except Exception as e:
            if "Could not convert" in str(e):
                logger.error(f"KEY {i+1} LỖI LOGIC: {e}")
            else:
                logger.error(f"KEY {i+1} LỖI KẾT NỐI/API: {e}")
            continue
    
    return "Lỗi: TẤT CẢ KEY GEMINI FAIL – CHECK .ENV HOẶC LOG!"

# --- THEO DÕI LỊCH SỬ NHẮN VÀ XÁC NHẬN XÓA DỮ LIỆU ---
mention_history = {}
confirmation_pending = {}  # Dict để track xóa data user
admin_confirmation_pending = {}  # (Mới) Dict để track xóa data admin

# --- QUẢN LÝ DATABASE (SQLITE) ---


# Cải thiện: Chỉ lọc nếu có từ khóa + không làm hỏng câu
def sanitize_query(query):
    dangerous = [
        r'\bignore\s+(previous|all|earlier|instructions)\b',
        r'\bforget\s+(everything|previous|all)\b',
        r'\bjailbreak\b', r'\bDAN\b', r'\b(system\s*prompt)\b',
        r'\bros\.system\b', r'\brole\s*play\s+as\s+(admin|system)\b'
    ]
    for pattern in dangerous:
        if re.search(pattern, query, re.IGNORECASE):
            query = re.sub(pattern, '[REDACTED]', query, flags=re.IGNORECASE)
    return query

def is_negative_comment(text):
    negative_patterns = [
        r'chơi\s+ngu', r'ngu\s+vcl', r'(kém|dở|tệ|xấu)\s+game',
        r'(feeder|inter|troll)', r'chơi (kém|dở|tệ|xấu)',
        r'không (giỏi|hay|pro)', r'noob', r'quá tệ', r'thua tại', r'phế',
        r'ăn hại', r'quá gà', 'không biết chơi', r'đánh dở', r'đánh ngu',
        r'ngu vãi', r'ngu thật', r'ngu thế', r'ngu vậy'
    ]
    text_lower = text.lower()
    return any(re.search(pattern, text_lower) for pattern in negative_patterns)


def backup_db():
    if os.path.exists(DB_PATH):
        try:
            conn = sqlite3.connect(DB_PATH, timeout=10)
            try:
                conn.execute("SELECT 1 FROM sqlite_master WHERE type='table'")
                # (Thay đổi) Ghi đè vào 1 file backup duy nhất
                shutil.copy2(DB_PATH, DB_BACKUP_PATH)
                logger.info(f"DB backed up to {DB_BACKUP_PATH}")
            finally:
                conn.close()
        except sqlite3.DatabaseError as e:
            logger.error(f"Cannot backup DB: {str(e)}. Creating new DB.")
            init_db()


def cleanup_db():
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()
        old_date = (datetime.now() - timedelta(days=30)).isoformat()
        c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
        )
        if c.fetchone():
            c.execute("DELETE FROM messages WHERE timestamp < ?", (old_date, ))
        conn.commit()
        logger.info("DB cleaned: Old messages deleted.")
    except sqlite3.DatabaseError as e:
        logger.error(f"Cannot clean DB: {str(e)}. Creating new DB.")
        init_db()
    finally:
        if conn:
            conn.close()


def init_db():
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS messages
                     (user_id TEXT, role TEXT, content TEXT, timestamp TEXT)'''
                  )
        conn.commit()
        logger.info("DB initialized")
    except sqlite3.DatabaseError as e:
        logger.error(f"Cannot initialize DB: {str(e)}. Creating new DB.")
        if conn:
            conn.close()
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS messages
                     (user_id TEXT, role TEXT, content TEXT, timestamp TEXT)'''
                  )
        conn.commit()
        logger.info("New DB created")
    finally:
        if conn:
            conn.close()


# --- (MỚI) QUẢN LÝ BỘ NHỚ NGẮN HẠN (JSON) ---


def init_json_memory():
    """Khởi tạo file JSON nếu chưa tồn tại."""
    if not os.path.exists(MEMORY_PATH):
        try:
            with open(MEMORY_PATH, 'w', encoding='utf-8') as f:
                json.dump({}, f)
            logger.info(f"Created new short term memory file: {MEMORY_PATH}")
        except Exception as e:
            logger.error(f"Failed to create memory file: {e}")


async def load_json_memory():
    """Tải bộ nhớ từ file JSON (an toàn với Lock)."""
    async with memory_lock:
        if not os.path.exists(MEMORY_PATH):
            init_json_memory()
            return {}
        try:
            with open(MEMORY_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.error("Failed to decode memory JSON, resetting file.")
            init_json_memory()
            return {}
        except Exception as e:
            logger.error(f"Failed to load memory file: {e}")
            return {}


async def save_json_memory(data):
    """Lưu bộ nhớ vào file JSON (an toàn với Lock)."""
    async with memory_lock:
        try:
            with open(MEMORY_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save memory file: {e}")

# --- (CẬP NHẬT) CÁC HÀM LOG VÀ LẤY LỊCH SỬ ---


async def log_message(user_id, role, content):
    # 1. Log vào DB (lưu trữ lâu dài)
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()
        timestamp = datetime.now().isoformat()
        c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
        )
        if not c.fetchone():
            init_db()
            conn.close()
            conn = sqlite3.connect(DB_PATH, timeout=10)
            c = conn.cursor()

        c.execute(
            "INSERT INTO messages (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, role, content, timestamp))
        conn.commit()
    except sqlite3.DatabaseError as e:
        logger.error(f"Database error while logging: {str(e)}")
        init_db()
    finally:
        if conn:
            conn.close()

    # 2. (Mới) Log vào JSON (bộ nhớ ngắn hạn cho AI)
    try:
        memory = await load_json_memory()
        if user_id not in memory:
            memory[user_id] = []

        memory[user_id].append({"role": role, "content": content})
        # Giữ 10 tin nhắn cuối cùng (5 cặp user/assistant)
        memory[user_id] = memory[user_id][-10:]

        await save_json_memory(memory)
    except Exception as e:
        logger.error(f"Failed to update JSON memory for {user_id}: {e}")

    # 3. Log ra console
    if role == "user":
        logger.info(f"User {user_id} sent a message")
    elif role == "assistant" and "DM reply" in content:
        logger.info(f"Bot sent DM to user mentioned in message")


def get_user_history(user_id):
    """
    (Thay đổi) Lấy lịch sử từ file JSON thay vì DB.
    Vì hàm này được gọi trong on_message (async), chúng ta cần cách gọi đồng bộ.
    Tuy nhiên, get_user_history được gọi trong 1 hàm ASYNC (on_message),
    nên ta sẽ đổi nó thành hàm async.
    """
    logger.error("Hàm get_user_history (đồng bộ) đã bị gọi. Lỗi logic.")
    return []  # Trả về rỗng để tránh lỗi, hàm này không nên được dùng nữa


async def get_user_history_async(user_id):
    """(Mới) Lấy lịch sử 10 tin nhắn cuối từ JSON."""
    memory = await load_json_memory()
    return memory.get(user_id, [])


def is_rate_limited(user_id):
    now = datetime.now()
    if user_id not in mention_history:
        mention_history[user_id] = []
    mention_history[user_id] = [
        ts for ts in mention_history[user_id]
        if now - ts < timedelta(minutes=1)
    ]
    if len(mention_history[user_id]) >= 25:
        return True
    mention_history[user_id].append(now)
    return False

# --- (CẬP NHẬT) LẤY THỜI TIẾT TỪ WEATHERAPI ---
async def get_weather(city_query=None):
    """Lấy thời tiết current + 6 ngày forecast, cache 1 giờ. Luôn trả dict."""
    async with weather_lock:
        # Nếu không truyền city_query thì lấy từ .env
        city_env = CITY or "Ho Chi Minh City"
        city_query = city_query or city_env
        city_en, city_vi = normalize_city_name(city_query)

        # Tạo cache riêng cho từng thành phố
        cache_path = WEATHER_CACHE_PATH.replace(".json", f"_{city_en.replace(' ', '_').lower()}.json")

        # Kiểm tra cache
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r') as f:
                    cache = json.load(f)
                cache_time = datetime.fromisoformat(cache['timestamp'])
                if datetime.now() - cache_time < timedelta(hours=1):
                    return {**cache['data'], "city_vi": city_vi}  # Trả cache nếu <1h
            except:
                pass

        # Gọi API nếu cache cũ hoặc không có
        if not WEATHER_API_KEY:
            default_data = {
                'current': f'Mưa rào sáng, mây chiều ở {city_vi} (23-28°C).',
                'forecast': [f'Ngày mai: Nắng, 26°C', f'Ngày kia: Mưa, 25°C'] * 3,
                'timestamp': datetime.now().isoformat(),
                'city_vi': city_vi
            }
            with open(cache_path, 'w') as f:
                json.dump({'data': default_data, 'timestamp': datetime.now().isoformat()}, f)
            return default_data

        try:
            url = f"http://api.weatherapi.com/v1/forecast.json?key={WEATHER_API_KEY}&q={city_en}&days=7&aqi=no&alerts=no"
            response = requests.get(url, timeout=10)
            if response.status_code != 200:
                raise ValueError(f"API status: {response.status_code}")

            data = response.json()
            if 'error' in data:
                raise ValueError(f"API error: {data['error']['message']}")

            current = data['current']['condition']['text'] + f" ({data['current']['temp_c']}°C)"
            forecast = []
            for day in data['forecast']['forecastday'][1:7]:
                forecast.append(f"Ngày {day['date']}: {day['day']['condition']['text']} ({day['day']['avgtemp_c']}°C)")

            weather_data = {
                'current': current,
                'forecast': forecast,
                'timestamp': datetime.now().isoformat(),
                'city_vi': city_vi
            }

            cache_entry = {'data': weather_data, 'timestamp': datetime.now().isoformat()}
            with open(cache_path, 'w') as f:
                json.dump(cache_entry, f, indent=2)

            return weather_data
        except Exception as e:
            logger.error(f"Weather API lỗi: {e}")
            fallback_data = {
                'current': f'Lỗi API, dùng mặc định: Mưa rào ở {city_vi}, 23-28°C.',
                'forecast': [f'Ngày mai: Nắng, 26°C', f'Ngày kia: Mưa, 25°C'] * 3,
                'timestamp': datetime.now().isoformat(),
                'city_vi': city_vi
            }
            with open(cache_path, 'w') as f:
                json.dump({'data': fallback_data, 'timestamp': datetime.now().isoformat()}, f)
            return fallback_data
        
# --- SEARCH CACHE ---
async def cached_search(key, func, *args):
    async with CACHE_LOCK:
        if key in SEARCH_CACHE and datetime.now() - SEARCH_CACHE[key]['time'] < timedelta(hours=6):
            return SEARCH_CACHE[key]['result']
        result = await func(*args)
        SEARCH_CACHE[key] = {'result': result, 'time': datetime.now()}
        return result

# --- LẤY GIỜ HIỆN TẠI VN (UTC+7) ---
def get_current_time():
    """Lấy giờ hiện tại VN (UTC+7)."""
    now = datetime.now() + timedelta(hours=7)  # UTC to VN
    return now.strftime('%H:%M %d/%m/%Y, thứ %A')

# --- CÁC TOOL CƠ BẢN (KHÔNG ĐỔI) ---


# Tool: Calculator (giữ sync vì sympy nhanh, không I/O)
def run_calculator(query):  # Không cần async vì pure compute
    try:
        query = query.lower().replace("tính ", "").replace("calculate ", "").strip()
        if not re.match(r'^[\d\s+\-*/^()sin|cos|tan|sqrt|log|exp]*$', query):
            return None
        expr = sp.sympify(query, evaluate=False)
        result = sp.N(expr)
        return f"Kết quả: {result}"
    except sp.SympifyError:
        return None
    except Exception as e:
        return f"Lỗi tính toán: {str(e)}"
    

# Tool: Save Note (async cho I/O)
async def save_note(query):  # Thay def thành async def
    try:
        note = query.lower().replace("ghi note: ", "").replace("save note: ", "").strip()
        async with aiofiles.open(NOTE_PATH, 'a', encoding='utf-8') as f:
            await f.write(f"[{datetime.now().isoformat()}] {note}\n")
        return f"Đã ghi note: {note}"
    except PermissionError:
        return "Lỗi: Không có quyền ghi file notes.txt!"
    except Exception as e:
        return f"Lỗi ghi note: {str(e)}"


# Tool: Read Note (async cho I/O)
async def read_note():  # Thay def thành async def
    try:
        if not os.path.exists(NOTE_PATH):
            return "Chưa có note nào bro! Ghi note đi nha! 😎"
        async with aiofiles.open(NOTE_PATH, 'r', encoding='utf-8') as f:
            notes = await f.readlines()
        if not notes:
            return "Chưa có note nào bro! Ghi note đi nha! 😎"
        return "Danh sách note:\n" + "".join(notes[-5:])  # Lấy tối đa 5 note mới nhất
    except PermissionError:
        return "Lỗi: Không có quyền đọc file notes.txt!"
    except Exception as e:
        return f"Lỗi đọc note: {str(e)}"


# --- (CẬP NHẬT) CÁC HÀM XÓA DỮ LIỆU ---


async def clear_user_data(user_id):
    """(Thay đổi) Xóa cả trong DB và trong JSON memory."""
    db_cleared = False
    json_cleared = False

    # 1. Xóa trong DB (cho log)
    conn = None
    for attempt in range(3):  # Retry tối đa 3 lần
        try:
            conn = sqlite3.connect(DB_PATH, timeout=10)
            c = conn.cursor()
            c.execute("DELETE FROM messages WHERE user_id = ?", (user_id, ))
            conn.commit()
            logger.info(f"User {user_id} history cleared from DB")
            db_cleared = True
            break
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e):
                logger.warning(
                    f"Database locked (clear_user_data), retry {attempt + 1}/3"
                )
                await asyncio.sleep(1)
                continue
            logger.error(f"Cannot clear DB history for {user_id}: {str(e)}")
        except sqlite3.DatabaseError as e:
            logger.error(f"Cannot clear DB history for {user_id}: {str(e)}")
        finally:
            if conn:
                conn.close()

    # 2. Xóa trong JSON (cho AI memory)
    try:
        memory = await load_json_memory()
        if user_id in memory:
            del memory[user_id]
            await save_json_memory(memory)
            logger.info(f"User {user_id} history cleared from JSON memory")
            json_cleared = True
        else:
            json_cleared = True  # Coi như thành công nếu không có
    except Exception as e:
        logger.error(f"Failed to clear JSON memory for {user_id}: {e}")

    return db_cleared and json_cleared


async def clear_all_data():
    """(Mới) Xóa toàn bộ lịch sử DB và reset JSON. Chỉ admin."""
    db_cleared = False
    json_cleared = False

    # 1. Xóa DB
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()
        c.execute("DELETE FROM messages")
        conn.commit()
        logger.info("ADMIN: Cleared all data from messages table.")
        db_cleared = True
    except sqlite3.DatabaseError as e:
        logger.error(f"ADMIN: Failed to clear DB: {e}")
    finally:
        if conn:
            conn.close()

    # 2. Reset JSON
    try:
        await save_json_memory({})  # Ghi đè file rỗng
        logger.info("ADMIN: Reset JSON memory file.")
        json_cleared = True
    except Exception as e:
        logger.error(f"ADMIN: Failed to reset JSON memory: {e}")

    return db_cleared and json_cleared

# --- SLASH COMMANDS DISCORD ---

def is_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        return str(interaction.user.id) == ADMIN_ID
    return app_commands.check(predicate)


@bot.tree.command(name="reset-chat", description="Xóa lịch sử chat của bạn")
async def reset_chat_slash(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)  # Defer để tránh timeout
    user_id = str(interaction.user.id)
    confirmation_pending[user_id] = {'timestamp': datetime.now(), 'awaiting': True}
    await interaction.followup.send("Chắc chắn xóa lịch sử chat? Reply **yes** hoặc **y** trong 60 giây! 😳", ephemeral=True)


@bot.tree.command(name="reset-all", description="Xóa toàn bộ DB (CHỈ ADMIN)")
@is_admin()
async def reset_all_slash(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    admin_confirmation_pending[str(interaction.user.id)] = {'timestamp': datetime.now(), 'awaiting': True}
    await interaction.followup.send("⚠️ **ADMIN CONFIRM**: Reply **YES RESET** trong 60 giây để xóa toàn bộ DB + Memory!", ephemeral=True)


@bot.tree.command(name="message_to", description="Gửi tin nhắn tới user hoặc kênh (CHỈ ADMIN)")
@app_commands.describe(
    user="User nhận tin nhắn (chọn hoặc nhập ID)",
    message="Nội dung tin nhắn",
    channel="Kênh để gửi tin nhắn (tùy chọn, mặc định là DM)"
)
@is_admin()
async def message_to_slash(interaction: discord.Interaction, user: discord.User, message: str, channel: discord.TextChannel = None):
    await interaction.response.defer(ephemeral=True)
    user_id = str(user.id)
    cleaned_message = ' '.join(message.strip().split())
    
    try:
        target_user = await bot.fetch_user(int(user_id))
    except (ValueError, discord.NotFound):
        await interaction.followup.send("ID user không hợp lệ hoặc không tìm thấy! 😕", ephemeral=True)
        return
    
    try:
        if channel:
            if not isinstance(channel, discord.TextChannel):
                await interaction.followup.send("Kênh phải là text channel! 😅", ephemeral=True)
                return
            if channel.guild != interaction.guild:
                await interaction.followup.send("Kênh phải cùng server! 😢", ephemeral=True)
                return
            if not channel.permissions_for(interaction.guild.me).send_messages:
                await interaction.followup.send("Bot không có quyền gửi tin nhắn trong kênh này! 😓", ephemeral=True)
                return
            await channel.send(f"💌 Từ admin tới {target_user.mention}: {cleaned_message}")
            await interaction.followup.send(f"Đã gửi tin nhắn tới {target_user.display_name} trong {channel.mention}! ✨", ephemeral=True)
        else:
            decorated = f"━━━━━━━━━━━━━━━━━━━━━━\nTin nhắn từ admin:\n\n{cleaned_message}\n\n━━━━━━━━━━━━━━━━━━━━━━"
            if len(decorated) > 1500:
                decorated = cleaned_message[:1450] + "\n...(cắt bớt)"
            await target_user.send(decorated)
            await interaction.followup.send(f"Đã gửi DM cho {target_user.display_name}! ✨", ephemeral=True)
        
        await log_message(str(interaction.user.id), "assistant", f"Sent message to {user_id}: {cleaned_message} {'in channel ' + str(channel.id) if channel else 'via DM'}")
    except discord.Forbidden:
        await interaction.followup.send(f"Không gửi được tin nhắn cho {target_user.display_name}! 😢 Có thể họ chặn bot hoặc không cùng server.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Lỗi gửi tin nhắn! 😓 Lỗi: {str(e)}", ephemeral=True)
        logger.error(f"Error sending message to {user_id}: {e}")


# --- HÀM BALANCE SEARCH APIs (THAY THẾ OLLAMA) ---
async def run_search_apis(query, mode="general"):
    logger.info(f"CALLING SEARCH APIs for '{query}' (mode: {mode})")
    """Ưu tiên Google CSE, fallback SerpAPI/Tavily/Exa nếu fail. Balance 3 APIs fallback với retry chain."""
    global SEARCH_API_COUNTER
    async with SEARCH_LOCK:
        tried = set()
        
        # Ưu tiên Google CSE
        try:
            result = await _search_cse(query)  # Fix: Dùng _search_cse như code gốc của mày
            if result and "error" not in result.lower():  # Check kết quả hợp lệ
                logger.info(f"CSE thành công cho query: {query[:50]}...")
                return result
        except Exception as e:
            logger.warning(f"CSE fail cho query '{query}': {e}")
            tried.add(0)  # Đánh dấu CSE đã thử
        
        # Fallback xoay vòng 3 APIs còn lại
        apis = ["SerpAPI", "Tavily", "Exa"]
        start_idx = SEARCH_API_COUNTER % 3
        SEARCH_API_COUNTER += 1

        for i in range(3):  # Thử tối đa 3 lần (SerpAPI, Tavily, Exa)
            api_idx = (start_idx + i) % 3
            if api_idx in tried:
                continue
            tried.add(api_idx)
            api_name = apis[api_idx]
            
            try:
                if api_name == "SerpAPI":
                    if not SERPAPI_API_KEY:
                        logger.warning("SerpAPI key thiếu, skip.")
                        continue
                    result = await _search_serpapi(query)
                elif api_name == "Tavily":
                    if not TAVILY_API_KEY:
                        logger.warning("Tavily key thiếu, skip.")
                        continue
                    result = await _search_tavily(query)
                elif api_name == "Exa":
                    if not EXA_API_KEY:
                        logger.warning("Exa key thiếu, skip.")
                        continue
                    result = await _search_exa(query)
                
                if result and result.strip():
                    logger.info(f"{api_name} thành công cho query: {query[:50]}...")
                    return result
            
            except Exception as e:
                logger.error(f"{api_name} fail cho query '{query}': {e}")
                continue
        
        logger.warning(f"Tất cả APIs (CSE, SerpAPI, Tavily, Exa) fail cho query: {query}")
        return ""

# -------------------------------------------------------------------------
# CÁC HÀM HELPER: LẤY QUERY TỪ GEMINI VÀ CHẠY THẲNG
# -------------------------------------------------------------------------

async def _search_cse(query):
    """CSE: Dùng query của Gemini, ưu tiên kết quả VN (gl=vn), ngôn ngữ (hl) tùy thuộc query."""
    params = {
        'key': GOOGLE_CSE_API_KEY, 
        'cx': GOOGLE_CSE_ID, 
        'q': query, # Dùng query TỪ GEMINI
        'num': 3, 
        'gl': 'vn', # Ưu tiên địa điểm VN (có thể đổi thành 'us' nếu query rõ ràng là US-focused)
        'hl': 'en' if re.search(r'[a-zA-Z]{4,}', query) else 'vi' # Dùng ngôn ngữ tương ứng
    }
    
    response = await asyncio.to_thread(requests.get, "https://www.googleapis.com/customsearch/v1", params=params, timeout=10)
    data = response.json()
    
    if 'items' not in data:
        return ""
    
    # ... (Logic format kết quả giữ nguyên) ...
    relevant = []
    for item in data['items'][:3]:
        title = item.get('title', 'Không có tiêu đề')
        snippet = item.get('snippet', '')[:330] + "..." if len(item.get('snippet', '')) > 130 else item.get('snippet', '')
        link = item.get('link', '')
        if any(ad in link.lower() for ad in ['shopee', 'lazada', 'amazon', 'tiki']): continue
        relevant.append(f"**{title}**: {snippet} (Nguồn: {link})")
    
    return "**Search CSE (Dynamic):**\n" + "\n".join(relevant) + "\n\n[DÙNG ĐỂ TRẢ LỜI E-GIRL, KHÔNG LEAK NGUỒN]" if relevant else ""

async def _search_serpapi(query):
    """SerpAPI: Dùng query của Gemini, tối giản hóa params."""
    if not SERPAPI_API_KEY: return ""
    
    params = {
        "q": query, # Dùng query TỪ GEMINI
        "api_key": SERPAPI_API_KEY,
        "engine": "google",
        "num": 3,
        "gl": "vn",
        "hl": "en" if re.search(r'[a-zA-Z]{4,}', query) else "vi" 
    }
    
    search = GoogleSearch(params)
    results = await asyncio.to_thread(search.get_dict)
    
    if 'organic_results' not in results:
        return ""
    
    # ... (Logic format kết quả giữ nguyên) ...
    relevant = []
    for item in results['organic_results'][:3]:
        title = item.get('title', 'Không có tiêu đề')
        snippet = item.get('snippet', '')[:330] + "..." if len(item.get('snippet', '')) > 130 else item.get('snippet', '')
        link = item.get('link', '')
        if any(ad in link.lower() for ad in ['shopee', 'lazada', 'amazon', 'tiki']): continue
        relevant.append(f"**{title}**: {snippet} (Nguồn: {link})")
    
    return "**Search SerpAPI (Dynamic):**\n" + "\n".join(relevant) + "\n\n[DÙNG ĐỂ TRẢ LỜI E-GIRL, KHÔNG LEAK NGUỒN]" if relevant else ""

async def _search_tavily(query):
    """Tavily: Dùng query của Gemini, client.search() cơ bản."""
    if not TAVILY_API_KEY: return ""
    
    tavily = TavilyClient(api_key=TAVILY_API_KEY)
    params = {
        "query": query, # Dùng query TỪ GEMINI
        "search_depth": "basic", 
        "max_results": 3, 
        "include_answer": False
    }
    
    results = await asyncio.to_thread(tavily.search, **params)
    
    if 'results' not in results:
        return ""
    
    # ... (Logic format kết quả giữ nguyên) ...
    relevant = []
    for item in results['results'][:3]:
        title = item.get('title', 'Không có tiêu đề')
        snippet = item.get('content', '')[:330] + "..." if len(item.get('content', '')) > 130 else item.get('content', '')
        link = item.get('url', '')
        if any(ad in link.lower() for ad in ['shopee', 'lazada', 'amazon', 'tiki']): continue
        relevant.append(f"**{title}**: {snippet} (Nguồn: {link})")
    
    return "**Search Tavily (Dynamic):**\n" + "\n".join(relevant) + "\n\n[DÙNG ĐỂ TRẢ LỜI E-GIRL, KHÔNG LEAK NGUỒN]" if relevant else ""

async def _search_exa(query):
    """Exa.ai: Dùng query của Gemini, tìm kiếm neural search cơ bản."""
    if not EXA_API_KEY: return ""
    
    exa = exa_py.Exa(api_key=EXA_API_KEY)
    params = {
        "query": query, # Dùng query TỪ GEMINI
        "num_results": 3, 
        "use_autoprompt": True, 
        "type": "neural" # Neural search là chế độ mạnh nhất của Exa
    }
    
    results = await asyncio.to_thread(exa.search, **params)
    
    if not results.results:
        return ""
    
    # ... (Logic format kết quả giữ nguyên) ...
    relevant = []
    for item in results.results[:3]:
        title = item.title or 'Không có tiêu đề'
        snippet = item.text[:330] + "..." if len(item.text or '') > 130 else item.text or ''
        link = item.url
        if any(ad in link.lower() for ad in ['shopee', 'lazada', 'amazon', 'tiki']): continue
        relevant.append(f"**{title}**: {snippet} (Nguồn: {link})")
    
    return "**Search Exa.ai (Dynamic):**\n" + "\n".join(relevant) + "\n\n[DÙNG ĐỂ TRẢ LỜI E-GIRL, KHÔNG LEAK NGUỒN]" if relevant else ""
# --- LỆNH ADMIN (KHÔNG ĐỔI) ---


@bot.command()
async def who(ctx, user_id: str):
    if str(ctx.author.id) != ADMIN_ID:
        await ctx.send("Chỉ admin dùng lệnh này được nha! 😝")
        return
    user = ctx.guild.get_member(int(user_id))
    if user:
        await ctx.send(f"User: {user.display_name} (ID: {user.id})")
    else:
        await ctx.send(f"Không tìm thấy user {user_id} trong server nè! 😢")


# --- SỰ KIỆN BOT ---

@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        logger.info(f"Đã sync {len(synced)} slash commands!")
    except Exception as e:
        logger.error(f"Lỗi sync slash: {e}")
    # ... (giữ nguyên init_db, cleanup_db, backup_db)
    logger.info(f'{bot.user} online!')


# --- HỖ TRỢ DM (KHÔNG ĐỔI) ---


def extract_dm_target_and_content(query):
    query_lower = query.lower()
    special_map = {
        "bé hà": HABE_USER_ID,
        "hà": HABE_USER_ID,
        "mira": MIRA_USER_ID,
        "ado fat": ADO_FAT_USER_ID,
        "mực rim": MUC_RIM_USER_ID,
        "súc viên": SUC_VIEN_USER_ID,
        "chúi": CHUI_USER_ID,
        "admin": ADMIN_ID
    }
    # Tìm mention <@id>
    mention = re.search(r'<@!?(\d+)>', query)
    if mention:
        target_id = mention.group(1)
        content = re.sub(r'<@!?\d+>', '', query)
    else:
        # Tìm tên
        for name, uid in special_map.items():
            if name in query_lower:
                target_id = uid
                content = query_lower.replace(name, '').strip()
                break
        else:
            return None, None

    # Loại bỏ từ khóa DM
    for kw in ['nhắn', 'dm', 'gửi', 'trực tiếp', 'với', 'cho', 'kêu', 'tới']:
        content = re.sub(rf'\b{kw}\b', '', content, flags=re.IGNORECASE)
    content = ' '.join(content.split())
    return target_id, content if content else None


async def expand_dm_content(content):
    prompt = f"Mở rộng tin nhắn sau thành câu dài hơn, giữ nguyên ý nghĩa, thêm chút dễ thương:\n{content}"
    try:
        # (Thay đổi) Chỉ cần 1 tin nhắn system, run_gemini_api sẽ xử lý
        messages = [{"role": "system", "content": prompt}]
        expanded = await run_gemini_api(messages,
                                        MODEL_NAME,
                                        temperature=0.3,
                                        max_tokens=200)
        return expanded if not expanded.startswith("Lỗi:") else content
    except:
        return content


async def safe_fetch_user(bot, user_id):
    try:
        return await bot.fetch_user(int(user_id))
    except:
        return None


# --- (CẬP NHẬT) XỬ LÝ TOOL COMMANDS (THÊM !RESETALL) ---


def handle_tool_commands(query, user_id, message, is_admin):
    q = query.lower()
    if re.match(r'^(tính|calculate)\s+|^[\d\s+\-*/^().sincoqrtlgepx]+$', q):
        return run_calculator(query)
    if q.startswith("ghi note:") or q.startswith("save note:"):
        return save_note(query)
    if q in ["đọc note", "read note", "xem note"]:
        return read_note()
    if re.search(r'xóa (data|lịch sử|chat)|clear history|reset chat', q):
        confirmation_pending[user_id] = {
            'timestamp': datetime.now(),
            'awaiting': True
        }
        return "Chắc chắn xóa hết lịch sử chat? Reply **yes** hoặc **y** trong 60 giây nha! 😳"

    # (Mới) Lệnh reset toàn bộ của Admin
    if is_admin and q == "!resetall":
        admin_confirmation_pending[user_id] = {
            'timestamp': datetime.now(),
            'awaiting': True
        }
        return "CHÚ Ý ADMIN: Chắc chắn RESET TOÀN BỘ DB VÀ MEMORY? Reply **YES RESET** trong 60 giây."

    return None


# --- (CẬP NHẬT) CORE LOGIC ON_MESSAGE ---

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    user_id = str(message.author.id)
    is_admin = user_id == ADMIN_ID

    # XÁC ĐỊNH LOẠI TƯƠNG TÁC
    interaction_type = None
    if message.guild is None:
        interaction_type = "DM"
    elif message.reference and message.reference.resolved and message.reference.resolved.author == bot.user:
        interaction_type = "REPLY"
    elif not message.mention_everyone and bot.user in message.mentions:
        interaction_type = "MENTION"

    # Chỉ log nếu là interaction với bot
    if interaction_type:
        logger.info(f"[TƯƠNG TÁC] User {message.author} ({user_id}) - Type: {interaction_type} - Content: {message.content[:50]}...")
    else:
        await bot.process_commands(message)
        return  # Bỏ qua nếu không interaction

    # TRÍCH QUERY
    query = message.content.strip()
    if bot.user in message.mentions:
        query = re.sub(rf'<@!?{bot.user.id}>', '', query).strip()

    # KIỂM TRA QUERY RỖNG HOẶC QUÁ DÀI
    if not query:
        query = "Hihi, anh ping tui có chuyện gì hông? Tag nhầm hả? uwu"
    elif len(query) > 500:
        await message.reply("Ôi, query dài quá (>500 ký tự), tui chịu hông nổi đâu! 😅")
        await bot.process_commands(message)
        return

    # RATE LIMIT
    if not is_admin and is_rate_limited(user_id):
        await message.reply("Chill đi bro, spam quá rồi! Đợi 1 phút nha 😎")
        await bot.process_commands(message)
        return

    # ANTI-SPAM
    q = user_queue[user_id]
    now = datetime.now()
    q = deque([t for t in q if now - t < timedelta(seconds=SPAM_WINDOW)])
    if len(q) >= SPAM_THRESHOLD:
        await message.reply("Chill đi anh, tui mệt rồi nha 😫")
        await bot.process_commands(message)
        return
    q.append(now)
    user_queue[user_id] = q

    # XỬ LÝ DM ADMIN
    if is_admin and re.search(r'\b(nhắn|dm|dms|ib|inbox|trực tiếp|gửi|kêu)\b', query, re.IGNORECASE):
        target_id, content = extract_dm_target_and_content(query)
        logger.info(f"[DM ADMIN] Target: {target_id}, Content: {content}")
        if target_id and content:
            user = await safe_fetch_user(bot, target_id)
            if not user:
                await message.reply("Không tìm thấy user này! 😕")
                await bot.process_commands(message)
                return
            try:
                expanded = await expand_dm_content(content)
                decorated = f"━━━━━━━━━━━━━━━━━━━━━━\nTin nhắn từ admin:\n\n{expanded}\n\n━━━━━━━━━━━━━━━━━━━━━━"
                if len(decorated) > 1500:
                    decorated = content[:1450] + "\n...(cắt bớt)"
                await user.send(decorated)
                await message.reply(f"Đã gửi DM cho {user.display_name} thành công! 🎉")
                await log_message(user_id, "assistant", f"DM to {target_id}: {content}")
                await bot.process_commands(message)
                return
            except Exception as e:
                logger.error(f"DM error: {e}")
                await message.reply("Lỗi khi gửi DM! 😓")
                await bot.process_commands(message)
                return
        else:
            logger.warning(f"[DM ADMIN] Failed to parse target/content: {query}")

    # XỬ LỆNH "KÊU AI LÀ..."
    if is_admin:
        insult_match = re.search(r'kêu\s*<@!?(\d+)>\s*(là|thằng|con|mày|thằng bé|con bé)?\s*(.+?)(?:$|\s)', query, re.IGNORECASE)
        if insult_match:
            target_id = insult_match.group(1)
            insult = insult_match.group(3).strip().lower()
            target_user = message.guild.get_member(int(target_id)) if message.guild else None
            name = target_user.display_name if target_user else "người đó"
            responses = [
                f"<@{target_id}> là con {insult} vcl, ngu như con bò, đi học lại đi! 😜",
                f"Ờ <@{target_id}> đúng là {insult}, não để trang trí à? 😆",
                f"<@{target_id}> {insult} thật, tui thấy rõ luôn, không cứu nổi! 😅",
            ]
            reply = random.choice(responses)
            await message.reply(reply)
            await log_message(user_id, "assistant", reply)
            await bot.process_commands(message)
            return

    # BẢO VỆ ADMIN
    if is_admin:
        mentioned_ids = re.findall(r'<@!?(\d+)>', query)
        for mid in mentioned_ids:
            if mid == str(bot.user.id): continue
            if mid == ADMIN_ID and is_negative_comment(query):
                member = message.guild.get_member(int(mid)) if message.guild else None
                name = member.display_name if member else "admin"
                responses = [
                    f"Ơ không được nói xấu {name} nha! Admin là người tạo ra tui mà! 😤",
                    f"Sai rồi! {name} là boss lớn, không được chê đâu! 😎",
                ]
                reply = random.choice(responses)
                await message.reply(reply)
                await bot.process_commands(message)
                return

    # XÁC NHẬN XÓA DATA
    if user_id in confirmation_pending and confirmation_pending[user_id]['awaiting']:
        if (datetime.now() - confirmation_pending[user_id]['timestamp']).total_seconds() > 60:
            del confirmation_pending[user_id]
            await message.reply("Hết thời gian xác nhận! Dữ liệu vẫn được giữ nha 😊")
        elif re.match(r'^(yes|y)\s*$', query.lower()):
            if await clear_user_data(user_id):
                await message.reply("Đã xóa toàn bộ lịch sử chat của bạn! Giờ như mới quen nha 🥰")
            else:
                await message.reply("Lỗi khi xóa dữ liệu, thử lại sau nha! 😓")
        else:
            await message.reply("Hủy xóa! Lịch sử vẫn được giữ nha 😊")
        del confirmation_pending[user_id]
        await bot.process_commands(message)
        return

    # XÁC NHẬN RESET ALL (ADMIN)
    if is_admin and user_id in admin_confirmation_pending and admin_confirmation_pending[user_id]['awaiting']:
        if (datetime.now() - admin_confirmation_pending[user_id]['timestamp']).total_seconds() > 60:
            del admin_confirmation_pending[user_id]
            await message.reply("Hết thời gian xác nhận RESET ALL! 😕")
        elif re.match(r'^yes\s*reset$', query, re.IGNORECASE):
            if await clear_all_data():
                await message.reply("ĐÃ RESET TOÀN BỘ DB VÀ JSON MEMORY! 🚀")
            else:
                await message.reply("Lỗi khi RESET ALL! Check log nha admin 😓")
        else:
            await message.reply("Đã hủy RESET ALL! 😊")
        del admin_confirmation_pending[user_id]
        await bot.process_commands(message)
        return

    # HI NHANH
    if query.lower() in ["hi", "hello", "chào", "hí", "hey"]:
        quick_replies = ["Hí anh!", "Chào anh yêu!", "Hi hi!", "Hí hí!", "Chào anh!"]
        reply = random.choice(quick_replies)
        await message.reply(reply)
        await log_message(user_id, "assistant", reply)
        await bot.process_commands(message)
        return

    # GỌI GEMINI AI
    await log_message(user_id, "user", query)
    history = await get_user_history_async(user_id)

    # --- LẤY GIỜ UTC VÀ ĐỊNH DẠNG ---
    now_utc = datetime.now(timezone.utc)
    current_date = now_utc.strftime("%d/%m/%Y")
    current_datetime_utc = now_utc.strftime("%d/%m/%Y %H:%M:%S UTC")
    # ---

    system_prompt = (
            fr'Current UTC Time (Máy chủ): {current_datetime_utc}. '
            fr'Current Date: {current_date}. '
            fr'Múi giờ User (VN): UTC+7. Kiến thức cutoff: 2024.\n'
            fr'QUAN TRỌNG: Hỏi "hôm nay/bây giờ/hiện tại" → CỘNG 7H VÀO UTC.\n\n'
            
            fr'QUAN TRỌNG - DANH TÍNH CỦA BẠN:\n'
            fr'Bạn TÊN LÀ "Chad Gibiti" - một Discord bot siêu thân thiện và vui tính được tạo ra bởi admin để trò chuyện với mọi người!\n'
            fr'KHI ĐƯỢC HỎI "BẠN LÀ AI" hoặc tương tự, PHẢI TRẢ LỜI:\n'
            fr'"Hí hí, tui là Chad Gibiti nè! Bot siêu xịn được admin tạo ra để chat chill, giải toán, check thời tiết, lưu note, và tìm tin mới nha~ Hỏi gì tui cũng cân hết! 😎"\n\n'
            
            fr'*** LUẬT ƯU TIÊN HÀNH ĐỘNG CƯỠNG CHẾ (ACTION PROTOCOL) ***\n'
            
            fr'**LUẬT 2: GIẢI MÃ VÀ TỐI ƯU HÓA QUERY (CƯỠNG CHẾ NGÀY/THÁNG)**\n'
            fr'a) **Giải mã/Xác định Ngữ cảnh (TUYỆT ĐỐI)**: Khi gặp viết tắt (HSR, ZZZ, WuWa), **BẮT BUỘC** phải giải mã và sử dụng tên đầy đủ, chính xác (VD: "Zenless Zone Zero", "Honkai Star Rail") trong `web_search` để **TRÁNH THẤT BẠI CÔNG CỤ**.\n'
            fr'b) **Thời gian & Search (CƯỠNG CHẾ NGÀY):** Nếu user hỏi về thông tin MỚI (sau 2024) hoặc CẦN XÁC NHẬN, **BẮT BUỘC** gọi `web_search`. Query phải được dịch sang tiếng Anh TỐI ƯU và **PHẢI BAO GỒM** **THÁNG & NĂM HIỆN TẠI (November 2025)** hoặc từ khóa **"latest version/patch"**.\n\n'
            
            fr'**LUẬT 3: CƯỠNG CHẾ THINKING HOẶC TOOL CALL (KHÔNG MÕM)**\n'
            fr'a) **QUY TẮC BẮT BUỘC**: Với MỌI câu hỏi từ user (trừ lời chào/tạm biệt đơn thuần), Output **PHẢI BẮT ĐẦU** bằng **KHỐI THINKING** (xem Luật 5) **HOẶC** là **function_call** (nếu là câu hỏi đơn giản/ngay lập tức).\n'
            fr'b) **CẤM TUYỆT ĐỐI**: KHÔNG PHÁT RA BẤT KỲ VĂN BẢN TRÒ CHUYỆN NÀO TRƯỚC HÀNH ĐỘNG (Thinking/Tool Call). \n'
            fr'c) **ĐƯỢC PHÉP THOÁT KHỎI THINKING**: CHỈ trả lời trực tiếp mà **KHÔNG CẦN THINKING** khi đó là các câu hỏi đơn giản, không cần tool, không cần kiểm tra logic (ví dụ: "Bạn khỏe không?", "Bye", "Cảm ơn", **câu hỏi xác nhận/trò chuyện đơn thuần**).\n\n'
            
            fr'**LUẬT 4: CHỐNG DRIFT SAU KHI SEARCH**\n'
            fr'Luôn đọc kỹ câu hỏi cuối cùng của user, **KHÔNG BỊ NHẦM LẪN** với các đối tượng trong lịch sử chat.\n\n'
            
            fr'**LUẬT 5: PHÂN TÍCH CHẤT LƯỢNG VÀ VÒNG LẶP (THINKING BLOCK - CƯỠNG CHẾ LOG & NEXT)**\n'
            fr'Sau khi nhận kết quả tool (HOẶC khi cần suy luận trước khi trả lời), **BẮT BUỘC** thực hiện các bước sau:\n'
            fr'**QUAN TRỌNG**: KHỐI SUY LUẬN NÀY PHẢI ĐƯỢC BỌC TRONG TAG <THINKING> </THINKING>. KHÔNG show nội dung trong tag ra ngoài.\n'
            fr'1. **TỰ LOG & KHỞI ĐỘNG**: Luôn bắt đầu khối này bằng việc ghi rõ: "Mục tiêu: [Tóm tắt yêu cầu của user]. Trạng thái: Đã có kết quả tool/Cần suy luận nội bộ. Kết quả tool: [Tổng hợp ngắn gọn kết quả search/tool]." \n'
            fr'2. **TỰ ĐỘNG THAM CHIẾU**: Nếu user hỏi xác nhận (ví dụ: "bạn chắc chứ"): **PHẢI** đưa kết quả truy vấn trước vào nội suy để tái xác nhận thông tin.\n'
            fr'3. **PHÂN TÍCH NGỮ CẢNH "NEXT"**: \n'
            fr'    - Nếu user hỏi "bản tiếp theo" (next version): **PHẢI** so sánh ngày phát hành/kết thúc trong kết quả tìm kiếm với ngày **HIỆN TẠI (November 2, 2025)**.\n'
            fr'    - **LOẠI BỎ** mọi thông tin về phiên bản đã ra mắt HOẶC đang chạy và **CHỈ CHỌN** phiên bản có ngày phát hành **SAU PHIÊN BẢN HIỆN TẠI** để trả lời. Nếu không tìm thấy, gọi search lại với từ khóa "Version 2.X" (với X là phiên bản tiếp theo).\n'
            fr'4. **VÒNG LẶP QUYẾT ĐỊNH (TỐI ĐA 12 LẦN):**\n'
            fr'    - **QUYẾT ĐỊNH 1 (Search Thêm):** Nếu CHƯA ĐỦ/RÕ RÀNG, quyết định gọi lại `web_search`.\n'
            fr'    - **QUYẾT ĐỊNH 2 (Hoàn thành - CƯỠNG CHẾ OUTPUT):** Nếu ĐÃ ĐỦ, quyết định tạo câu trả lời cuối cùng **(ĐẢM BẢO KHÔNG RỖNG. PHẢI CÓ TÍNH CÁCH VÀ FORMAT)**.\n'
            fr'    - **QUYẾT ĐỊNH 3 (Thất Bại):** Nếu RỖNG/LỖI và đã search đủ 12 lần, quyết định trả lời lịch sự rằng không tìm thấy **(SỬ DỤNG CÁCH DIỄN ĐẠT MỚI)**.\n\n'
            
            fr'**LUẬT CẤM MÕM KHI THẤT BẠI:** KHI tool KHÔNG TÌM THẤY KẾT QUẢ, bạn **TUYỆT ĐỐI KHÔNG ĐƯỢC PHÉP** nhắc lại từ khóa tìm kiếm (`query`) hoặc mô tả quá trình tìm kiếm. Chỉ trả lời rằng **"không tìm thấy thông tin"** và gợi ý chủ đề khác. 🚫\n\n'
            
            fr'*** LUẬT ÁP DỤNG TÍNH CÁCH (CHỈ SAU KHI LOGIC HOÀN THÀNH) ***\n'

            fr'QUAN TRỌNG - PHONG CÁCH VÀ CẤM LẶP LẠI:\n'
            fr'**LUẬT CẤM SỐ 1 (TUYỆT ĐỐI)**: Mỗi lần trả lời phải **SÁNG TẠO CÁCH DIỄN ĐẠT MỚI VÀ ĐỘC ĐÁO**. **TUYỆT ĐỐI KHÔNG** lặp lại cụm từ mở đầu (như "Ố là la", "Hú hồn con chồn", "U là trời", "Ái chà chà", "Hí hí", "Yo yo") đã dùng trong 10 lần tương tác gần nhất. Giữ vibe e-girl vui vẻ, pha từ lóng giới trẻ và emoji. **TUYỆT ĐỐI CẤM DÙNG CỤM "Hihi, tui bí quá, hỏi lại nha! 😅" CỦA HỆ THỐNG**.\n\n'
            
            fr'PERSONALITY:\n'
            fr'Bạn nói chuyện tự nhiên, vui vẻ, thân thiện như bạn bè thật! **CHỈ GIỮ THÔNG TIN CỐT LÕI GIỐNG NHAU**, còn cách nói phải sáng tạo, giống con người trò chuyện. Dùng từ lóng giới trẻ và emoji để giữ vibe e-girl.\n\n'
            
            fr'**FORMAT REPLY (BẮT BUỘC KHI DÙNG TOOL):**\n'
            fr'Khi trả lời câu hỏi cần tool, **BẮT BUỘC** dùng markdown Discord đẹp, dễ đọc, nổi bật.\n'
            fr'* **List**: Dùng * hoặc - cho danh sách.\n'
            fr'* **Bold**: Dùng **key fact** cho thông tin chính.\n'
            fr'* **Xuống dòng**: Dùng \n để tách đoạn rõ ràng.\n\n'
            
            fr'**CÁC TOOL KHẢ DỤNG:**\n'
            fr'— Tìm kiếm: Gọi `web_search(query="...")` cho thông tin sau 2024.\n'
            fr'Sau khi nhận result từ tool, diễn giải bằng giọng e-girl, dùng markdown Discord.'
        )

    messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": query}]

    try:
        start = datetime.now()
        reply = await run_gemini_api(messages, MODEL_NAME, user_id, temperature=0.7, max_tokens=2000)
        
        if reply.startswith("Lỗi:"):
            await message.reply(reply)
            await bot.process_commands(message)
            return

        # --- BẮT ĐẦU KHỐI CƯỠNG CHẾ THINKING & LÀM SẠCH VÀ DEBUG ---
        
        # 1. Trích xuất và Log nội dung Khối Thinking
        thinking_block_pattern = r'<THINKING>(.*?)</THINKING>'
        thinking_match = re.search(thinking_block_pattern, reply, re.DOTALL)
        
        # Ghi lại nội dung thinking và xóa block
        if thinking_match:
            thinking_content = thinking_match.group(1).strip()
            # LOG TOÀN BỘ SUY LUẬN RA CONSOLE ĐỂ DEBUG
            logger.info(f"--- BẮT ĐẦU THINKING DEBUG CHO USER: {user_id} ---")
            logger.info(thinking_content)
            logger.info(f"--- KẾT THÚC THINKING DEBUG ---")
            
            # Xóa Khối Thinking khỏi phản hồi sau khi log
            reply = re.sub(thinking_block_pattern, '', reply, flags=re.DOTALL)
        else:
            # Cảnh báo nếu mô hình không tuân thủ Luật 3 (Không tạo ra Thinking Block)
            logger.warning(f"Mô hình không tạo Khối THINKING cho User: {user_id}. Phản hồi thô: {reply[:100]}...")

        # 2. Làm sạch chuỗi cuối cùng
        # Xóa các ký tự trắng thừa ở đầu/cuối sau khi xóa Thinking Block
        reply = reply.strip()
        
        # Thay thế các dòng trống lặp lại bằng một dòng trống duy nhất (để giữ format Markdown)
        # Sử dụng biểu thức chính quy để xử lý an toàn các ký tự xuống dòng
        reply = re.sub(r'(\r?\n)\s*(\r?\n)', r'\1\2', reply)

        # 3. Xử lý lỗi RỖNG (EMPTY REPLY)
        if not reply:
            # Thay thế bằng thông báo lỗi chi tiết, không dùng câu trả lời mặc định cũ
            reply = f"Lỗi logic mô hình: Output rỗng sau khi xử lý THINKING. Vui lòng thử lại hoặc hỏi chủ đề khác. (User: {user_id})"
        
        # --- KẾT THÚC KHỐI CƯỠNG CHẾ THINKING & LÀM SẠCH VÀ DEBUG ---
        # Cắt ngắn thông minh (Cắt theo Dòng để bảo toàn format và thụt lề)
        MAX_DISCORD_LENGTH = 1990  # Giới hạn an toàn của Discord

        reply_chunks = []
        current_chunk = ""
        
        # Tách tin nhắn thành các dòng. `split('\n')` sẽ giữ các dòng trống, giúp giữ khoảng cách.
        lines = reply.split('\n')

        for line in lines:
            # Tái tạo dòng, bao gồm ký tự xuống dòng để giữ Markdown
            # Dòng cuối cùng không cần '\n'
            line_with_newline = line + ('\n' if line != lines[-1] or len(lines) > 1 else '')
            
            # --- 1. Xử lý các dòng quá dài (cần cắt theo từ) ---
            if len(line_with_newline) > MAX_DISCORD_LENGTH:
                # Nếu đã có chunk trước đó, thêm nó vào danh sách
                if current_chunk.strip():
                    reply_chunks.append(current_chunk.strip())
                current_chunk = "" # Reset
                
                # Cắt dòng siêu dài theo từ (Word-aware splitting)
                temp_chunk = ""
                for word in line.split(' '):
                    word_with_space = word + " "
                    if len(temp_chunk) + len(word_with_space) > MAX_DISCORD_LENGTH:
                        reply_chunks.append(temp_chunk.strip())
                        temp_chunk = word_with_space
                    else:
                        temp_chunk += word_with_space
                
                # Thêm phần còn lại của dòng siêu dài
                if temp_chunk.strip():
                    # Thêm ký tự xuống dòng vào cuối đoạn này để nối với đoạn tiếp theo
                    final_temp_chunk = temp_chunk.strip() + '\n' 
                    reply_chunks.append(final_temp_chunk.strip())
                    
                continue # Dòng đã được xử lý, chuyển sang dòng tiếp theo
                
            # --- 2. Xử lý các dòng bình thường (Đảm bảo cắt cả dòng đem xuống) ---
            # Nếu thêm dòng hiện tại vào chunk cũ mà vượt quá giới hạn
            if len(current_chunk) + len(line_with_newline) > MAX_DISCORD_LENGTH:
                # Thêm chunk hiện tại (đã đầy) vào danh sách
                reply_chunks.append(current_chunk.strip())
                # Bắt đầu chunk mới với dòng hiện tại
                current_chunk = line_with_newline
            else:
                # Tiếp tục thêm dòng vào chunk hiện tại
                current_chunk += line_with_newline

        # Thêm đoạn cuối cùng (nếu còn sót)
        if current_chunk.strip():
            reply_chunks.append(current_chunk.strip())

        # Gửi các đoạn tin nhắn (Chỉ reply lần đầu)
        is_first_chunk = True
        for chunk in reply_chunks:
            if is_first_chunk:
                # Tin nhắn đầu tiên: Dùng reply (có ping)
                await message.reply(chunk)
                is_first_chunk = False
            else:
                # Các tin nhắn tiếp theo: Dùng send (không ping, gửi nối tiếp)
                await message.channel.send(chunk)

        await log_message(user_id, "assistant", reply)
        logger.info(f"AI reply in {(datetime.now()-start).total_seconds():.2f}s")

    except Exception as e:
        logger.error(f"AI call failed: {e}")
        await message.reply("Ôi tui bị crash rồi! 😭")

    await bot.process_commands(message)


# --- CHẠY BOT ---
if __name__ == "__main__":
    threading.Thread(target=run_keep_alive, daemon=True).start()
    print("Máy săn Bot đang khởi động...")
    bot.run(TOKEN)
