import os
from dotenv import load_dotenv
import logging
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# --- TẢI BIẾN MÔI TRƯỜNG ---
load_dotenv()

# --- LOGGING ---
logger = logging.getLogger('bot_gemini')
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')

file_handler = logging.FileHandler('bot.log', encoding='utf-8')
file_handler.setFormatter(formatter)

stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)

logger.handlers = [file_handler, stream_handler]
logger.propagate = False

# --- DISCORD & BOT ---
TOKEN = os.getenv('DISCORD_TOKEN')
MODEL_NAME = os.getenv('MODEL_NAME')
if not MODEL_NAME:
    logger.warning("MODEL_NAME environment variable not set. Using default 'gemini-pro'.")
    MODEL_NAME = 'gemini-pro'
ADMIN_ID = os.getenv('ADMIN_ID', '')
HABE_USER_ID = os.getenv('HABE_USER_ID', '')
MIRA_USER_ID = os.getenv('MIRA_USER_ID', '')
ADO_FAT_USER_ID = os.getenv('ADO_FAT_USER_ID', '')
MUC_RIM_USER_ID = os.getenv('MUC_RIM_USER_ID', '')
SUC_VIEN_USER_ID = os.getenv('SUC_VIEN_USER_ID', '')
CHUI_USER_ID = os.getenv('CHUI_USER_ID', '')

# --- GEMINI API KEYS ---
GEMINI_API_KEY_PROD = os.getenv('GEMINI_API_KEY_PROD')
GEMINI_API_KEY_TEST = os.getenv('GEMINI_API_KEY_TEST')
GEMINI_API_KEY_BACKUP = os.getenv('GEMINI_API_KEY_BACKUP')
GEMINI_API_KEY_EXTRA1 = os.getenv('GEMINI_API_KEY_EXTRA1')
GEMINI_API_KEY_EXTRA2 = os.getenv('GEMINI_API_KEY_EXTRA2')

GEMINI_API_KEYS = [key for key in [
    GEMINI_API_KEY_PROD,
    GEMINI_API_KEY_TEST,
    GEMINI_API_KEY_BACKUP,
    GEMINI_API_KEY_EXTRA1,
    GEMINI_API_KEY_EXTRA2
] if key]

if not GEMINI_API_KEYS:
    logger.error("Không tìm thấy Gemini API keys! Bot sẽ không thể hoạt động.")
else:
    logger.info(f"Đã thiết lập {len(GEMINI_API_KEYS)} Gemini API keys cho Failover.")

# --- SEARCH API KEYS ---
SERPAPI_API_KEY = os.getenv('SERPAPI_API_KEY')
TAVILY_API_KEY = os.getenv('TAVILY_API_KEY')
EXA_API_KEY = os.getenv('EXA_API_KEY')
GOOGLE_CSE_ID = os.getenv('GOOGLE_CSE_ID')
GOOGLE_CSE_API_KEY = os.getenv('GOOGLE_CSE_API_KEY')
GOOGLE_CSE_ID_1 = os.getenv("GOOGLE_CSE_ID_1")
GOOGLE_CSE_API_KEY_1 = os.getenv("GOOGLE_CSE_API_KEY_1")
GOOGLE_CSE_ID_2 = os.getenv("GOOGLE_CSE_ID_2")
GOOGLE_CSE_API_KEY_2 = os.getenv("GOOGLE_CSE_API_KEY_2")
# --- HUGGING FACE API KEY ---
HF_TOKEN = os.getenv('HF_TOKEN')

# --- WEATHER API ---
WEATHER_API_KEY = os.getenv('WEATHER_API_KEY')
CITY = os.getenv('CITY')

# --- FILE PATHS ---
DB_PATH = os.path.join(os.path.dirname(__file__), 'chat_history.db')
DB_BACKUP_PATH = os.path.join(os.path.dirname(__file__), 'chat_history_backup.db')
NOTE_PATH = os.path.join(os.path.dirname(__file__), 'notes.txt')
MEMORY_PATH = os.path.join(os.path.dirname(__file__), 'short_term_memory.json')
WEATHER_CACHE_PATH = os.path.join(os.path.dirname(__file__), 'weather_cache.json')

# --- HỆ THỐNG FILE HYBRID MỚI ---
FILE_STORAGE_PATH = os.path.join(os.path.dirname(__file__), 'uploaded_files')
MIN_FREE_SPACE_MB = 100  # Ngưỡng dung lượng trống (MB)


# --- ANTI-SPAM ---
SPAM_THRESHOLD = 3
SPAM_WINDOW = 30

# --- GEMINI SAFETY SETTINGS ---
SAFETY_SETTINGS = [
    {"category": HarmCategory.HARM_CATEGORY_HARASSMENT, "threshold": HarmBlockThreshold.BLOCK_NONE},
    {"category": HarmCategory.HARM_CATEGORY_HATE_SPEECH, "threshold": HarmBlockThreshold.BLOCK_NONE},
    {"category": HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, "threshold": HarmBlockThreshold.BLOCK_NONE},
    {"category": HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, "threshold": HarmBlockThreshold.BLOCK_NONE},
]