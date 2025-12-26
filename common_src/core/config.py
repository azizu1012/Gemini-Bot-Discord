import os
from dotenv import load_dotenv
import logging
from pathlib import Path
from google.generativeai.types import HarmCategory, HarmBlockThreshold


class Config:
    """Singleton configuration manager for the bot."""
    
    def __init__(self):
        # Load .env from current working directory (instance folder)
        env_path = Path.cwd() / '.env'
        load_dotenv(dotenv_path=env_path, verbose=True)
        
        # --- LOGGING SETUP ---
        self.logger = self._setup_logger()
        
        # --- DISCORD & BOT ---
        self.TOKEN = os.getenv('DISCORD_TOKEN')
        self.MODEL_NAME = os.getenv('MODEL_NAME')
        self.ADMIN_ID = os.getenv('ADMIN_ID', '')
        self.HABE_USER_ID = os.getenv('HABE_USER_ID', '')
        self.MIRA_USER_ID = os.getenv('MIRA_USER_ID', '')
        self.ADO_FAT_USER_ID = os.getenv('ADO_FAT_USER_ID', '')
        self.MUC_RIM_USER_ID = os.getenv('MUC_RIM_USER_ID', '')
        self.SUC_VIEN_USER_ID = os.getenv('SUC_VIEN_USER_ID', '')
        self.CHUI_USER_ID = os.getenv('CHUI_USER_ID', '')
        
        # --- GEMINI API KEYS (DYNAMIC LOAD 1-15+) ---
        self.GEMINI_API_KEYS = []
        # Tự động load từ GEMINI_API_KEY_1 đến GEMINI_API_KEY_20
        for i in range(1, 21): 
            key = os.getenv(f'GEMINI_API_KEY_{i}')
            if key:
                self.GEMINI_API_KEYS.append(key)
        
        if not self.GEMINI_API_KEYS:
            self.logger.error("Không tìm thấy Gemini API keys! Bot sẽ không thể hoạt động.")
        else:
            self.logger.info(f"✅ Đã thiết lập {len(self.GEMINI_API_KEYS)} Gemini API keys cho Smart Rotation.")
        
        # --- SEARCH API KEYS ---
        self.SERPAPI_API_KEY = os.getenv('SERPAPI_API_KEY')
        self.TAVILY_API_KEY = os.getenv('TAVILY_API_KEY')
        self.EXA_API_KEY = os.getenv('EXA_API_KEY')
        self.GOOGLE_CSE_ID = os.getenv('GOOGLE_CSE_ID')
        self.GOOGLE_CSE_API_KEY = os.getenv('GOOGLE_CSE_API_KEY')
        self.GOOGLE_CSE_ID_1 = os.getenv("GOOGLE_CSE_ID_1")
        self.GOOGLE_CSE_API_KEY_1 = os.getenv("GOOGLE_CSE_API_KEY_1")
        self.GOOGLE_CSE_ID_2 = os.getenv("GOOGLE_CSE_ID_2")
        self.GOOGLE_CSE_API_KEY_2 = os.getenv("GOOGLE_CSE_API_KEY_2")
        
        # --- HUGGING FACE API KEY ---
        self.HF_TOKEN = os.getenv('HF_TOKEN')
        
        # --- WEATHER API ---
        self.WEATHER_API_KEY = os.getenv('WEATHER_API_KEY')
        self.CITY = os.getenv('CITY')
        
        # --- FILE PATHS (relative to instance working directory) ---
        instance_data_dir = Path.cwd() / 'data'
        instance_data_dir.mkdir(exist_ok=True)
        
        self.DB_PATH = str(instance_data_dir / 'chat_history.db')
        self.DB_BACKUP_PATH = str(instance_data_dir / 'chat_history_backup.db')
        self.NOTE_PATH = str(instance_data_dir / 'notes.txt')
        self.MEMORY_PATH = str(instance_data_dir / 'short_term_memory.json')
        self.WEATHER_CACHE_PATH = str(instance_data_dir / 'weather_cache.json')
        self.FILE_STORAGE_PATH = str(Path.cwd() / 'uploaded_files')
        
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
            {"category": HarmCategory.HARM_CATEGORY_HARASSMENT, "threshold": HarmBlockThreshold.BLOCK_NONE},
            {"category": HarmCategory.HARM_CATEGORY_HATE_SPEECH, "threshold": HarmBlockThreshold.BLOCK_NONE},
            {"category": HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, "threshold": HarmBlockThreshold.BLOCK_NONE},
            {"category": HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, "threshold": HarmBlockThreshold.BLOCK_NONE},
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
GOOGLE_CSE_ID = config.GOOGLE_CSE_ID
GOOGLE_CSE_API_KEY = config.GOOGLE_CSE_API_KEY
GOOGLE_CSE_ID_1 = config.GOOGLE_CSE_ID_1
GOOGLE_CSE_API_KEY_1 = config.GOOGLE_CSE_API_KEY_1
GOOGLE_CSE_ID_2 = config.GOOGLE_CSE_ID_2
GOOGLE_CSE_API_KEY_2 = config.GOOGLE_CSE_API_KEY_2
HF_TOKEN = config.HF_TOKEN
WEATHER_API_KEY = config.WEATHER_API_KEY
CITY = config.CITY
DB_PATH = config.DB_PATH
DB_BACKUP_PATH = config.DB_BACKUP_PATH
NOTE_PATH = config.NOTE_PATH
MEMORY_PATH = config.MEMORY_PATH
WEATHER_CACHE_PATH = config.WEATHER_CACHE_PATH
FILE_STORAGE_PATH = config.FILE_STORAGE_PATH
MIN_FREE_SPACE_MB = config.MIN_FREE_SPACE_MB
DEFAULT_RATE_LIMIT = config.DEFAULT_RATE_LIMIT
PREMIUM_RATE_LIMIT = config.PREMIUM_RATE_LIMIT
DEFAULT_DM_LIMIT = config.DEFAULT_DM_LIMIT
PREMIUM_DM_LIMIT = config.PREMIUM_DM_LIMIT
ADMIN_USER_IDS = config.ADMIN_USER_IDS
