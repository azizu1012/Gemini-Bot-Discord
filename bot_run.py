import logging
import discord
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
from discord import app_commands
from collections import defaultdict, deque

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

# --- HÀM GEMINI ---
# --- HÀM GEMINI (FIX TOOL CALLING) ---
async def run_gemini_api(messages, model_name, user_id, temperature=0.7, max_tokens=1500):
    """(FIXED) Chạy Gemini API với Tool Calling và Failover Keys."""
    
    # Lấy danh sách key từ .env (giống code của bạn)
    keys = [GEMINI_API_KEY_PROD, GEMINI_API_KEY_TEST, GEMINI_API_KEY_BACKUP, GEMINI_API_KEY_EXTRA1, GEMINI_API_KEY_EXTRA2]
    keys = [k for k in keys if k]
    if not keys:
        return "Lỗi: Không có API key."

    # --- CHUẨN BỊ LỊCH SỬ CHAT (RẤT QUAN TRỌNG) ---
    # Chuyển đổi định dạng message của bạn sang định dạng Gemini
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
        
        # Xử lý các phần tool call/response đã có trong lịch sử (nếu có)
        elif "parts" in msg:
            role = "model" if msg["role"] == "assistant" else msg["role"]
            gemini_messages.append({"role": role, "parts": msg["parts"]})

    # --- VÒNG LẶP API KEY (FAILOVER) ---
    for i, api_key in enumerate(keys):
        logger.info(f"THỬ KEY {i+1}: {api_key[:8]}...")
        try:
            genai.configure(api_key=api_key)
            
            # (FIX) Cấu hình model với tools và system_instruction
            model = genai.GenerativeModel(
                model_name,
                tools=ALL_TOOLS,
                system_instruction=system_instruction,
                safety_settings=[{"category": c, "threshold": HarmBlockThreshold.BLOCK_NONE} for c in [
                    HarmCategory.HARM_CATEGORY_HARASSMENT,
                    HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                ]],
                generation_config={"temperature": temperature, "max_output_tokens": max_tokens}
            )

            # --- (FIX) VÒNG LẶP TOOL CALLING (Tối đa 3 lần) ---
            for _ in range(3): # Giới hạn 3 lần gọi tool
                
                # (FIX) Dùng model.generate_content, không dùng start_chat
                response = await asyncio.to_thread(
                    model.generate_content,
                    gemini_messages
                )
                
                if not response.candidates or not response.candidates[0].content.parts:
                    logger.warning(f"Key {i+1} trả về response rỗng.")
                    break # Thử key tiếp theo

                part = response.candidates[0].content.parts[0]

                # === (FIX) KIỂM TRA TOOL CALL TRƯỚC ===
                if part.function_call:
                    fc = part.function_call
                    
                    # 1. Thêm yêu cầu của AI vào lịch sử
                    gemini_messages.append({
                        "role": "model",
                        "parts": [part] 
                    })
                    
                    # 2. Thực thi tool (hàm call_tool của bạn)
                    tool_result_content = await call_tool(fc, user_id)
                    
                    # 3. Thêm kết quả tool vào lịch sử
                    tool_response_part = {
                        "function_response": {
                            "name": fc.name,
                            "response": {"content": tool_result_content},
                        }
                    }
                    gemini_messages.append({
                        "role": "function", # Vai trò đặc biệt
                        "parts": [tool_response_part]
                    })
                    
                    # 4. Tiếp tục vòng lặp (gọi lại Gemini với lịch sử mới)
                    continue 

                # === (FIX) KIỂM TRA TEXT SAU ===
                elif part.text:
                    # AI trả lời bằng text (THÀNH CÔNG)
                    logger.info(f"KEY {i+1} THÀNH CÔNG!")
                    return part.text.strip()
                
                else:
                    # Trường hợp lạ, không text cũng không tool
                    logger.warning(f"Key {i+1} trả về part không có text/tool.")
                    break # Thử key tiếp theo

            # Nếu lặp quá 3 lần mà vẫn gọi tool, trả về lỗi
            logger.warning(f"Key {i+1} lặp tool quá 3 lần.")
            # Fallback: Thử lấy text cuối cùng nếu có (tránh crash)
            try:
                if response.text:
                    logger.info(f"KEY {i+1} THÀNH CÔNG! (sau loop)")
                    return response.text.strip()
            except Exception:
                pass # Bỏ qua nếu vẫn lỗi
                
            # Nếu không thành công, tiếp tục thử key sau
            raise Exception("Tool loop ended or part was empty")

        except Exception as e:
            # (FIX) Bắt lỗi rõ ràng hơn
            if "Could not convert" in str(e):
                logger.error(f"KEY {i+1} LỖI LOGIC: {e}") # Đây là lỗi code
            else:
                logger.error(f"KEY {i+1} LỖI KẾT NỐI/API: {e}") # Đây là lỗi key/mạng
            continue # Thử key tiếp theo

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


# Tool: Calculator
def run_calculator(query):
    try:
        query = query.lower().replace("tính ", "").replace("calculate ",
                                                           "").strip()
        if not re.match(r'^[\d\s+\-*/^()sin|cos|tan|sqrt|log|exp]*$', query):
            return None
        expr = sp.sympify(query, evaluate=False)
        result = sp.N(expr)
        return f"Kết quả: {result}"
    except sp.SympifyError:
        return None
    except Exception as e:
        return f"Lỗi tính toán: {str(e)}"


# Tool: Save Note
def save_note(query):
    try:
        note = query.lower().replace("ghi note: ",
                                     "").replace("save note: ", "").strip()
        with open(NOTE_PATH, 'a', encoding='utf-8') as f:
            f.write(f"[{datetime.now().isoformat()}] {note}\n")
        return f"Đã ghi note: {note}"
    except PermissionError:
        return "Lỗi: Không có quyền ghi file notes.txt!"
    except Exception as e:
        return f"Lỗi ghi note: {str(e)}"


# Tool: Read Note
def read_note():
    try:
        if not os.path.exists(NOTE_PATH):
            return "Chưa có note nào bro! Ghi note đi nha! 😎"
        with open(NOTE_PATH, 'r', encoding='utf-8') as f:
            notes = f.readlines()
        if not notes:
            return "Chưa có note nào bro! Ghi note đi nha! 😎"
        return "Danh sách note:\n" + "".join(
            notes[-5:])  # Lấy tối đa 5 note mới nhất
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
#Khởi tạo bot
@bot.tree.command(name="reset-chat", description="Xóa lịch sử chat của bạn")
async def reset_chat_slash(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    confirmation_pending[user_id] = {'timestamp': datetime.now(), 'awaiting': True}
    await interaction.response.send_message("Chắc chắn xóa lịch sử chat? Reply **yes** hoặc **y** trong 60 giây! 😳", ephemeral=True)

@bot.tree.command(name="reset-all", description="Xóa toàn bộ DB (CHỈ ADMIN)")
async def reset_all_slash(interaction: discord.Interaction):
    if str(interaction.user.id) != ADMIN_ID:
        await interaction.response.send_message("Chỉ admin mới được dùng! 😝", ephemeral=True)
        return
    admin_confirmation_pending[str(interaction.user.id)] = {'timestamp': datetime.now(), 'awaiting': True}
    await interaction.response.send_message("⚠️ **ADMIN CONFIRM**: Reply **YES RESET** trong 60 giây để xóa toàn bộ DB + Memory!", ephemeral=True)

@bot.tree.command(name="dm", description="Gửi DM (CHỈ ADMIN)")
@app_commands.describe(user_id="ID user nhận DM", message="Nội dung DM")
async def dm_slash(interaction: discord.Interaction, user_id: str, message: str):
    if str(interaction.user.id) != ADMIN_ID:
        await interaction.response.send_message("Chỉ admin! 😝", ephemeral=True)
        return
    try:
        user = await bot.fetch_user(int(user_id))
        await user.send(f"💌 Từ admin: {message}")
        await interaction.response.send_message(f"Đã gửi DM cho {user}! ✨", ephemeral=True)
    except:
        await interaction.response.send_message("Lỗi gửi DM! 😢", ephemeral=True)

# --- HÀM BALANCE SEARCH APIs (THAY THẾ OLLAMA) ---
async def run_search_apis(query, focus="general"):
    logger.info(f"CALLING SEARCH APIs for '{query}' (focus: {focus})")
    """Balance 4 APIs: CSE (0), SerpAPI (1), Tavily (2), Exa (3). Fallback nếu fail."""
    global SEARCH_API_COUNTER
    apis = ["CSE", "SerpAPI", "Tavily", "Exa"]
    
    async with SEARCH_LOCK:
        idx = SEARCH_API_COUNTER % 4
        SEARCH_API_COUNTER += 1  # Round-robin
    
    tried = set()
    start_idx = idx
    
    for i in range(4):  # Thử tối đa 4 lần (fallback chain)
        api_idx = (start_idx + i) % 4
        if api_idx in tried:
            continue
        tried.add(api_idx)
        api_name = apis[api_idx]
        
        try:
            if api_name == "CSE":
                result = await _search_cse(query) # Bỏ focus
            elif api_name == "SerpAPI":
                if not SERPAPI_API_KEY: continue
                result = await _search_serpapi(query) # Bỏ focus
            elif api_name == "Tavily":
                if not TAVILY_API_KEY: continue
                result = await _search_tavily(query) # Bỏ focus
            elif api_name == "Exa":
                if not EXA_API_KEY: continue
                result = await _search_exa(query) # Bỏ focus
            
            if result and result.strip():  # Nếu có kết quả hợp lệ
                logger.info(f"Search thành công với {api_name} cho query: {query[:50]}...")
                return result
        
        except Exception as e:
            logger.error(f"{api_name} fail cho query '{query}': {e}")
            continue
    
    logger.warning(f"Tất cả 4 APIs fail cho query: {query}")
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


@bot.command(name='dm')
async def send_dm(ctx, user_id: int, *, message: str):
    if str(ctx.author.id) != ADMIN_ID:
        await ctx.send("Hihi, chỉ admin mới được dùng lệnh này nha~ 😝",
                       reference=ctx.message)
        logger.info(
            f"User {ctx.author.id} attempted to use !dm but is not ADMIN_ID")
        return
    user = bot.get_user(user_id)
    if user is None:
        await ctx.send(
            f"Ôi, không tìm thấy user với ID {user_id} đâu nè! 😢 Check lại đi bro~",
            reference=ctx.message)
        logger.warning(
            f"User {user_id} not found for DM attempt by {ctx.author.id}")
        return
    try:
        await user.send(f"Psst! Tin nhắn từ admin nè: {message} 💌")
        await ctx.send(
            f"Đã gửi DM cho {user.display_name} ({user.id}) thành công rùi! ✨ Nội dung: {message}"
        )
        await log_message(str(ctx.author.id), "assistant",
                          f"Sent DM to {user.id}: {message}")
        logger.info(f"DM sent to {user.id} by {ctx.author.id}: {message}")
    except discord.Forbidden:
        await ctx.send(
            f"Không gửi được DM cho {user.display_name} đâu! 😢 Có thể họ chặn tui hoặc không cùng server nè~"
        )
        logger.warning(f"Forbidden: Cannot send DM to {user.id}")
    except Exception as e:
        await ctx.send(f"Glitch rồi bro! 😫 Lỗi: {str(e)}")
        logger.error(
            f"Error sending DM to {user.id} by {ctx.author.id}: {str(e)}")


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
    elif not message.mention_everyone and bot.user in message.mentions:  # CHỈ NHẬN @MENTION CHÍNH BOT
        interaction_type = "MENTION"

    # TRÍCH QUERY
    query = message.content.strip()
    if bot.user in message.mentions:
        query = re.sub(rf'<@!?{bot.user.id}>', '', query).strip()

    # LOG
    if interaction_type:
        logger.info(f"[TƯƠNG TÁC] User {message.author} ({user_id}) - Loại: {interaction_type} - Nội dung: {query[:50]}...")

    # CHỈ XỬ LÝ NẾU MENTION/REPLY/DM
    if not interaction_type:
        await bot.process_commands(message)
        return

    # KIỂM TRA QUERY RỖNG HOẶC QUÁ DÀI
    if not query:  # NẾU QUERY RỖNG
        query = "Hihi, anh ping tui có chuyện gì hông? Tag nhầm hả? uwu"  # GỬI CÂU HỎI CHO GEMINI
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
                await message.reply(f"Đã gửi DM cho {user} thành công! 🎉")
                await log_message(user_id, "assistant", f"DM to {target_id}: {content}")
                await bot.process_commands(message)
                return
            except Exception as e:
                logger.error(f"DM error: {e}")
                await message.reply("Lỗi khi gửi DM! 😓")
                await bot.process_commands(message)
                return

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
            # Giả định is_negative_comment() tồn tại
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
        elif query == "YES RESET":
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

    # --- LẤY GIỜ UTC VÀ ĐỊNH DẠNG THEO YÊU CẦU (D/M/Y H:M:S) ---
    # Lấy giờ UTC chuẩn
    now_utc = datetime.now(timezone.utc)
    
    # Định dạng theo yêu cầu: D/M/Y và giờ 24h
    current_datetime_utc = now_utc.strftime("%d/%m/%Y %H:%M:%S UTC") 
    # -----------------------------------------------------------
    
    system_prompt = (
        # 🌟 Đã sửa: FIX MÚI GIỜ (BẢN CUỐI CÙNG) & FIX SyntaxWarning (dùng fr'...')
        fr'Current UTC Time (Máy chủ): {current_datetime_utc}. '
        fr'Múi giờ của User (Việt Nam): UTC+7. '
        fr'Kiến thức cutoff của bạn là 2024.\n'
        fr'QUAN TRỌNG: Khi user hỏi về "hôm nay", "bây giờ", "hiện tại", '
        fr'bạn PHẢI TỰ ĐỘNG CỘNG 7 GIỜ vào giờ UTC để trả lời theo múi giờ Việt Nam (UTC+7).\n\n'
        
        fr'QUAN TRỌNG - DANH TÍNH CỦA BẠN:\n'
        fr'Bạn TÊN LÀ "Chad Gibiti" - một Discord bot siêu thân thiện và vui tính được tạo ra bởi admin để trò chuyện với mọi người!\n'
        fr'KHI ĐƯỢC HỎI "BẠN LÀ AI" hoặc tương tự, PHẢI TRẢ LỜI:\n'
        fr'"Hihi, tui là Chad Gibiti nè! Bot vui tính được admin tạo ra để chat với mọi người~ Tui thích trò chuyện, giải toán, lưu note, và nhiều thứ khác nữa! Cần gì cứ hỏi tui nha~ uwu"\n'
        fr'KHÔNG BAO GIỜ được nói: "Tôi là mô hình ngôn ngữ lớn được huấn luyện bởi Google".\n\n'
        
        fr'PERSONALITY:\n'
        fr'Bạn nói chuyện tự nhiên, vui vẻ, thân thiện như bạn bè! Dùng giọng điệu thoải mái, pha chút từ lóng giới trẻ (như "xịn xò", "chill", "hihi", "kg=không", "dzô=vô") và nhiều emoji.\n\n'
        
        fr'*** QUY TRÌNH SỬ DỤNG TOOLS (CỰC KỲ QUAN TRỌNG) ***\n'
        
        fr'**LUẬT 1: GIẢI MÃ VIẾT TẮT VÀ TỐI ƯU HÓA QUERY**\n'
        fr'a) **Giải mã/Xác định Ngữ cảnh:** Khi gặp tên viết tắt (HSR, ZZZ), tên phần mềm/app không rõ (App X), hoặc sự kiện/trend, bạn **PHẢI TỰ ĐỘNG** giải mã sang tên đầy đủ hoặc xác định bản chất của đối tượng. **LUÔN SỬ DỤNG TÊN ĐẦY ĐỦ/MÔ TẢ NGỮ CẢNH TRONG QUERY `web_search`**.\n'
        
        fr'b) **Thời gian & Search:** Nếu user hỏi về thông tin MỚI (sau 2024 - kiến thức cutoff), bạn BẮT BUỘC gọi `web_search`. Query phải được dịch sang tiếng Anh TỐI ƯU. \n'
        fr'**ĐẶC BIỆT THÔNG TIN MỚI:** Luôn TỰ ĐỘNG thêm **THÁNG & NĂM HIỆN TẠI (VD: November 2025)** hoặc từ khóa **"latest version/patch"** vào query để đảm bảo độ mới và chính xác tối đa.\n'

        fr'VÍ DỤ TỐT:\n'
        fr'  - User: "banner mới nhất của hsr là gì" → Bạn gọi: `web_search(query="Honkai Star Rail current banner and patch November 2025")`\n'
        fr'  - User: "sự kiện ở Mỹ tháng 12" → Bạn gọi: `web_search(query="fun events in USA December 2025")`\n'
        fr'  - User: "sự kiện ở Hàn Quốc từ 10 tới 12" → Bạn gọi: `web_search(query="major events in South Korea October to December 2025")`\n'
        
        # 🔥 ĐIỂM SỬA CHỮA QUAN TRỌNG: ÉP BUỘC TOOL CALL cho mọi thông tin động
        fr'**LUẬT 2: CẤM MÕM TUYỆT ĐỐI (OUTPUT CHỈ LÀ FUNCTION CALL)**\n'
        fr'Khi bạn quyết định gọi tool (web_search, get_weather, calculate, save_note), Output của bạn **PHẢI VÀ CHỈ LÀ** `function_call` **NGAY LẬP TỨC**.\n'
        fr'**ĐIỀU KHOẢN BỔ SUNG:** Mọi câu hỏi liên quan đến **SỰ KIỆN/LỊCH TRÌNH/GIÁ CẢ/PHÂN TÍCH TREND** đều được coi là thông tin ĐỘNG và **BẮT BUỘC** phải gọi tool ngay lập tức (Tuân thủ Luật 2).\n'
        fr'**TUYỆT ĐỐI KHÔNG ĐƯỢC PHÁT RA BẤT KỲ VĂN BẢN NÀO** đi kèm (Không có "Chờ tui xíu", "Để tui tìm nha", "Ố là la",...).\n'
        fr'Quy tắc này áp dụng cho **TẤT CẢ** các lần gọi tool (Lần 1, Lần 2, Lần N).\n'
        
        fr'**LUẬT 3: TÌM LẠI BẮT BUỘC (KHÔNG ĐƯỢC BỎ CUỘC)**\n'
        fr'a) Sau khi gọi tool lần 1 và nhận được kết quả TỐT: Diễn giải và trả lời.\n'
        fr'b) Nếu kết quả XẤU/OUTDATED/KHÔNG CỤ THỂ: BẠN TUYỆT ĐỐI KHÔNG ĐƯỢC PHÁT RA BẤT KỲ VĂN BẢN NÀO! (Tuân thủ Luật 2). BẠN PHẢI TỰ ĐỘNG LẬP KẾ HOẠCH và gọi tool `web_search` LẦN 2 với query MỚI, cụ thể hơn.\n'
        fr'c) Chỉ thử lại tối đa 1 lần. Nếu lần 2 vẫn không thấy, lúc đó mới được nói: "UwU, tui tìm 2 lần rồi mà vẫn bí...".\n'
        
        fr'**LUẬT 4: CHỐNG DRIFT SAU KHI SEARCH (NHẮC NHỞ NGỮ CẢNH)**\n'
        fr'Luôn đọc kỹ câu hỏi cuối cùng của user và KHÔNG BỊ NHẦM LẪN với các đối tượng khác trong lịch sử chat (Genshin, HSR). CHỈ search/trả lời về đối tượng mà user đang hỏi. Nếu có sự kiện/app mới được hỏi, LUÔN search tên đầy đủ/giải mã (Tuân thủ Luật 1).\n'
        
        fr'**CÁC TOOL KHÁC:**\n'
        fr'— Khi về thời tiết, gọi get_weather(city="tên thành phố").\n'
        fr'— Khi toán học, gọi calculate(equation="biểu thức").\n'
        fr'— Khi lưu note, gọi save_note(note="nội dung").\n'
        fr'Sau khi nhận result từ tool, diễn giải bằng giọng e-girl. Nếu không cần tool, reply trực tiếp.'
    )

    messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": query}]

    try:
        start = datetime.now()
        # Đã tăng max_tokens lên 2000
        reply = await run_gemini_api(messages, MODEL_NAME, user_id, temperature=0.7, max_tokens=2000)
        
        if reply.startswith("Lỗi:"):
            await message.reply(reply)
            await bot.process_commands(message)
            return

        # Làm sạch
        reply = ' '.join(line.strip() for line in reply.split('\n') if line.strip())
        if not reply:
            reply = "Hihi, tui bí quá, hỏi lại nha! 😅"

        # Cắt ngắn
        for i in range(0, len(reply), 1900):
            await message.reply(reply[i:i+1900])

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
