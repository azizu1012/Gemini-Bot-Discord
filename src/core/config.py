import os
from pathlib import Path
from dotenv import load_dotenv
import logging


def _load_runtime_env() -> None:
    current = Path(__file__).resolve()
    root_env_path = current.parents[3] / ".env"
    project_env_path = current.parents[2] / ".env"

    if project_env_path.exists():
        load_dotenv(dotenv_path=project_env_path)
    elif root_env_path.exists():
        load_dotenv(dotenv_path=root_env_path)
    else:
        load_dotenv()


class Config:
    """Singleton configuration manager for the bot."""
    
    def __init__(self):
        _load_runtime_env()
        
        # --- LOGGING SETUP ---
        self.logger = self._setup_logger()
        
        # --- DISCORD & BOT ---
        self.TOKEN = os.getenv('DISCORD_TOKEN')
        self.MODEL_NAME = os.getenv('MODEL_NAME', 'gemini-3-flash-preview')
        self.ADMIN_ID = os.getenv('ADMIN_ID', '')
        self.ADMIN_TOKEN = os.getenv('ADMIN_TOKEN', '')
        self.HABE_USER_ID = os.getenv('HABE_USER_ID', '')
        self.MIRA_USER_ID = os.getenv('MIRA_USER_ID', '')
        self.ADO_FAT_USER_ID = os.getenv('ADO_FAT_USER_ID', '')
        self.MUC_RIM_USER_ID = os.getenv('MUC_RIM_USER_ID', '')
        self.SUC_VIEN_USER_ID = os.getenv('SUC_VIEN_USER_ID', '')
        self.CHUI_USER_ID = os.getenv('CHUI_USER_ID', '')
        
        # --- GEMINI API KEYS (DYNAMIC LOAD) ---
        self.GEMINI_API_KEYS = []
        seen_keys = set()

        # Primary format: GEMINI_API_KEY_1..20
        for i in range(1, 21):
            key = (os.getenv(f'GEMINI_API_KEY_{i}') or '').strip()
            if key and key not in seen_keys:
                seen_keys.add(key)
                self.GEMINI_API_KEYS.append(key)

        # Compatibility format used by older runtime envs
        for name in [
            'GEMINI_API_KEY_PROD',
            'GEMINI_API_KEY_TEST',
            'GEMINI_API_KEY_BACKUP',
            'GEMINI_API_KEY_EXTRA1',
            'GEMINI_API_KEY_EXTRA2',
        ]:
            key = (os.getenv(name) or '').strip()
            if key and key not in seen_keys:
                seen_keys.add(key)
                self.GEMINI_API_KEYS.append(key)
        
        if not self.GEMINI_API_KEYS:
            self.logger.error("Không tìm thấy Gemini API keys! Bot sẽ không thể hoạt động.")
        else:
            self.logger.info(f"✅ Đã thiết lập {len(self.GEMINI_API_KEYS)} Gemini API keys cho Smart Rotation.")
        
        # --- SEARCH API KEYS ---
        self.SERPAPI_API_KEY = os.getenv('SERPAPI_API_KEY')
        self.TAVILY_API_KEY = os.getenv('TAVILY_API_KEY')
        self.EXA_API_KEY = os.getenv('EXA_API_KEY')
        
        # --- WEATHER API ---
        self.WEATHER_API_KEY = os.getenv('WEATHER_API_KEY')
        self.CITY = os.getenv('CITY')
        
        # --- FILE PATHS ---
        project_root = Path(__file__).resolve().parents[2]

        def _resolve_runtime_path(env_name: str, default_relative_path: str) -> str:
            raw_path = (os.getenv(env_name) or "").strip()
            target = Path(raw_path) if raw_path else (project_root / default_relative_path)
            if not target.is_absolute():
                target = project_root / target
            return str(target.resolve())

        self.DB_PATH = _resolve_runtime_path('DB_PATH', 'data/chat_history.db')
        self.DB_BACKUP_PATH = _resolve_runtime_path('DB_BACKUP_PATH', 'data/chat_history_backup.db')
        self.NOTE_PATH = _resolve_runtime_path('NOTE_PATH', 'data/notes.txt')
        self.MEMORY_PATH = _resolve_runtime_path('MEMORY_PATH', 'data/short_term_memory.json')
        self.WEATHER_CACHE_PATH = _resolve_runtime_path('WEATHER_CACHE_PATH', 'data/weather_cache.json')
        self.FILE_STORAGE_PATH = _resolve_runtime_path('FILE_STORAGE_PATH', 'uploaded_files')

        # --- VOICE ROOM OWNER LOCK ---
        self.VOICE_LOCK_BASE_DIR = os.path.join(os.path.dirname(__file__), '../../data/voice_lock')
        self.VOICE_WHITELIST_FILE = os.path.join(self.VOICE_LOCK_BASE_DIR, 'users.json')
        self.LOCKED_CHANNELS_FILE = os.path.join(self.VOICE_LOCK_BASE_DIR, 'locked_channels.json')
        self.ENFORCED_NAMES_FILE = os.path.join(self.VOICE_LOCK_BASE_DIR, 'enforced_names.json')
        self.VOICE_LOCK_LOG_FILE = os.path.join(self.VOICE_LOCK_BASE_DIR, 'voice_lock.log')
        
        # --- ANTI-SPAM ---
        self.SPAM_THRESHOLD = 3
        self.SPAM_WINDOW = 30
        
        # --- RATE & DM LIMITS ---
        self.DEFAULT_RATE_LIMIT = "10/60"
        self.PREMIUM_RATE_LIMIT = "20/60"
        self.DEFAULT_DM_LIMIT = 5
        self.PREMIUM_DM_LIMIT = 15
        self.ADMIN_USER_IDS = [self.ADMIN_ID] if self.ADMIN_ID else []
        
        # --- GEMINI SAFETY SETTINGS ---
        self.SAFETY_SETTINGS = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]
        
        # --- MIN FREE SPACE ---
        self.MIN_FREE_SPACE_MB = 100
    
    def _setup_logger(self):
        """Setup logging system."""
        logger = logging.getLogger('bot_gemini')
        logger.setLevel(logging.INFO)
        
        if logger.handlers:
            return logger
        
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
        
        file_handler = logging.FileHandler('bot.log', encoding='utf-8')
        file_handler.setFormatter(formatter)
        
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        
        logger.handlers = [file_handler, stream_handler]
        logger.propagate = False
        
        return logger


# Global instance
_config = None

def get_config() -> Config:
    """Get or create the global config instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config


# Backward compatibility: expose as module-level attributes
config = get_config()
logger = config.logger
TOKEN = config.TOKEN
MODEL_NAME = config.MODEL_NAME
ADMIN_ID = config.ADMIN_ID
ADMIN_TOKEN = config.ADMIN_TOKEN
HABE_USER_ID = config.HABE_USER_ID
MIRA_USER_ID = config.MIRA_USER_ID
ADO_FAT_USER_ID = config.ADO_FAT_USER_ID
MUC_RIM_USER_ID = config.MUC_RIM_USER_ID
SUC_VIEN_USER_ID = config.SUC_VIEN_USER_ID
CHUI_USER_ID = config.CHUI_USER_ID
GEMINI_API_KEYS = config.GEMINI_API_KEYS
SAFETY_SETTINGS = config.SAFETY_SETTINGS
SPAM_THRESHOLD = config.SPAM_THRESHOLD
SPAM_WINDOW = config.SPAM_WINDOW
SERPAPI_API_KEY = config.SERPAPI_API_KEY
TAVILY_API_KEY = config.TAVILY_API_KEY
EXA_API_KEY = config.EXA_API_KEY
WEATHER_API_KEY = config.WEATHER_API_KEY
CITY = config.CITY
DB_PATH = config.DB_PATH
DB_BACKUP_PATH = config.DB_BACKUP_PATH
NOTE_PATH = config.NOTE_PATH
MEMORY_PATH = config.MEMORY_PATH
WEATHER_CACHE_PATH = config.WEATHER_CACHE_PATH
FILE_STORAGE_PATH = config.FILE_STORAGE_PATH
VOICE_LOCK_BASE_DIR = config.VOICE_LOCK_BASE_DIR
VOICE_WHITELIST_FILE = config.VOICE_WHITELIST_FILE
LOCKED_CHANNELS_FILE = config.LOCKED_CHANNELS_FILE
ENFORCED_NAMES_FILE = config.ENFORCED_NAMES_FILE
VOICE_LOCK_LOG_FILE = config.VOICE_LOCK_LOG_FILE
MIN_FREE_SPACE_MB = config.MIN_FREE_SPACE_MB
DEFAULT_RATE_LIMIT = config.DEFAULT_RATE_LIMIT
PREMIUM_RATE_LIMIT = config.PREMIUM_RATE_LIMIT
DEFAULT_DM_LIMIT = config.DEFAULT_DM_LIMIT
PREMIUM_DM_LIMIT = config.PREMIUM_DM_LIMIT
ADMIN_USER_IDS = config.ADMIN_USER_IDS
