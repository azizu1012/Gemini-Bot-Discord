"""
Configuration Manager - Singleton Pattern
Quản lý tất cả cấu hình của bot một cách tập trung
"""
import os
import configparser
from dotenv import load_dotenv
from typing import List, Dict, Optional
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# Load environment variables
load_dotenv()


class Config:
    """
    Singleton Pattern cho Configuration
    Đảm bảo chỉ có một instance duy nhất của config trong toàn bộ ứng dụng
    """
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if Config._initialized:
            return
        
        # Discord & Bot Configuration
        self.DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
        self.MODEL_NAME = os.getenv('MODEL_NAME', 'gemini-pro')
        self.ADMIN_ID = os.getenv('ADMIN_ID', '')
        
        # Special User IDs
        self.HABE_USER_ID = os.getenv('HABE_USER_ID', '')
        self.MIRA_USER_ID = os.getenv('MIRA_USER_ID', '')
        self.ADO_FAT_USER_ID = os.getenv('ADO_FAT_USER_ID', '')
        self.MUC_RIM_USER_ID = os.getenv('MUC_RIM_USER_ID', '')
        self.SUC_VIEN_USER_ID = os.getenv('SUC_VIEN_USER_ID', '')
        self.CHUI_USER_ID = os.getenv('CHUI_USER_ID', '')
        
        # Gemini API Keys
        self._load_gemini_api_keys()
        
        # Search API Keys
        self.SERPAPI_API_KEY = os.getenv('SERPAPI_API_KEY')
        self.TAVILY_API_KEY = os.getenv('TAVILY_API_KEY')
        self.EXA_API_KEY = os.getenv('EXA_API_KEY')
        self.GOOGLE_CSE_ID = os.getenv('GOOGLE_CSE_ID')
        self.GOOGLE_CSE_API_KEY = os.getenv('GOOGLE_CSE_API_KEY')
        self.GOOGLE_CSE_ID_1 = os.getenv("GOOGLE_CSE_ID_1")
        self.GOOGLE_CSE_API_KEY_1 = os.getenv("GOOGLE_CSE_API_KEY_1")
        self.GOOGLE_CSE_ID_2 = os.getenv("GOOGLE_CSE_ID_2")
        self.GOOGLE_CSE_API_KEY_2 = os.getenv("GOOGLE_CSE_API_KEY_2")
        
        # Hugging Face API Key
        self.HF_TOKEN = os.getenv('HF_TOKEN')
        
        # Weather API
        self.WEATHER_API_KEY = os.getenv('WEATHER_API_KEY')
        self.CITY = os.getenv('CITY')
        
        # Proxy Configuration
        self._load_proxy_config()
        
        # File Paths
        self._setup_paths()
        
        # Rate Limiting & Anti-Spam
        self.SPAM_THRESHOLD = 3
        self.SPAM_WINDOW = 30
        self.DEFAULT_RATE_LIMIT = "10/60"  # 10 requests per 60 seconds
        self.PREMIUM_RATE_LIMIT = "20/60"  # 20 requests per 60 seconds
        self.DEFAULT_DM_LIMIT = 5  # 5 DMs per day
        self.PREMIUM_DM_LIMIT = 15  # 15 DMs per day
        self.ADMIN_USER_IDS = [self.ADMIN_ID] if self.ADMIN_ID else []
        
        # Gemini Safety Settings
        self.SAFETY_SETTINGS = [
            {"category": HarmCategory.HARM_CATEGORY_HARASSMENT, "threshold": HarmBlockThreshold.BLOCK_NONE},
            {"category": HarmCategory.HARM_CATEGORY_HATE_SPEECH, "threshold": HarmBlockThreshold.BLOCK_NONE},
            {"category": HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, "threshold": HarmBlockThreshold.BLOCK_NONE},
            {"category": HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, "threshold": HarmBlockThreshold.BLOCK_NONE},
        ]
        
        Config._initialized = True

    def _load_gemini_api_keys(self) -> None:
        """Load và validate Gemini API keys - Từ cả bot và file dịch truyện"""
        # Keys từ bot cũ
        bot_keys = [
            os.getenv('GEMINI_API_KEY_PROD'),
            os.getenv('GEMINI_API_KEY_TEST'),
            os.getenv('GEMINI_API_KEY_BACKUP'),
            os.getenv('GEMINI_API_KEY_EXTRA1'),
            os.getenv('GEMINI_API_KEY_EXTRA2'),
            os.getenv('GEMINI_API_KEY_EXTRA3'),
            os.getenv('GEMINI_API_KEY_EXTRA4'),
            os.getenv('GEMINI_API_KEY_EXTRA5'),
            os.getenv('GEMINI_API_KEY_EXTRA6'),
            os.getenv('GEMINI_API_KEY_EXTRA7'),
            os.getenv('GEMINI_API_KEY_EXTRA8'),
            os.getenv('GEMINI_API_KEY_EXTRA9'),
            os.getenv('GEMINI_API_KEY_EXTRA10'),
        ]
        
        # Keys từ file dịch truyện (main pool)
        translator_main_keys = [
            os.getenv('GEMINI_API_KEY_1'),
            os.getenv('GEMINI_API_KEY_2'),
            os.getenv('GEMINI_API_KEY_3'),
            os.getenv('GEMINI_API_KEY_4'),
            os.getenv('GEMINI_API_KEY_5'),
            os.getenv('GEMINI_API_KEY_6'),
            os.getenv('GEMINI_API_KEY_7'),
            os.getenv('GEMINI_API_KEY_8'),
            os.getenv('GEMINI_API_KEY_9'),
        ]
        
        # Keys từ file dịch truyện (summary pool - dùng chung)
        translator_summary_keys = [
            os.getenv('GEMINI_API_KEY_Tomtat'),
            os.getenv('GEMINI_API_KEY_Tomtat_2'),
            os.getenv('GEMINI_API_KEY_Tomtat_3'),
            os.getenv('GEMINI_API_KEY_Tomtat_4'),
            os.getenv('GEMINI_API_KEY_Tomtat_5'),
        ]
        
        # Gộp tất cả keys lại (loại bỏ None và trùng lặp)
        all_keys = bot_keys + translator_main_keys + translator_summary_keys
        unique_keys = []
        seen = set()
        for key in all_keys:
            if key and key.strip() and key not in seen:
                unique_keys.append(key)
                seen.add(key)
        
        self.GEMINI_API_KEYS = unique_keys
        
        if not self.GEMINI_API_KEYS:
            print("WARNING: Khong tim thay Gemini API keys! Bot se khong the hoat dong.")
        else:
            print(f"INFO: Da thiet lap {len(self.GEMINI_API_KEYS)} Gemini API keys.")
            print(f"     - Bot keys: {len([k for k in bot_keys if k])}")
            print(f"     - Translator main: {len([k for k in translator_main_keys if k])}")
            print(f"     - Translator summary: {len([k for k in translator_summary_keys if k])}")

    def _load_proxy_config(self) -> None:
        """Load proxy configuration từ config.ini hoặc .env"""
        # base_dir là root của project (2 levels up từ src/core/config.py)
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        config_ini_path = os.path.join(base_dir, 'config.ini')
        
        # Đọc từ config.ini nếu có
        if os.path.exists(config_ini_path):
            try:
                config_parser = configparser.ConfigParser()
                config_parser.read(config_ini_path, encoding='utf-8')
                
                if config_parser.has_section('PROXY'):
                    self.PROXY_ENABLED = config_parser.getboolean('PROXY', 'enabled', fallback=False)
                    if self.PROXY_ENABLED:
                        self.PROXY_HOST = config_parser.get('PROXY', 'host', fallback='')
                        self.PROXY_PORT = config_parser.getint('PROXY', 'port', fallback=0)
                        self.PROXY_USERNAME = config_parser.get('PROXY', 'username', fallback='')
                        self.PROXY_PASSWORD = config_parser.get('PROXY', 'password', fallback='')
                        
                        if self.PROXY_HOST and self.PROXY_PORT and self.PROXY_USERNAME and self.PROXY_PASSWORD:
                            self.PROXY_URL = f"http://{self.PROXY_USERNAME}:{self.PROXY_PASSWORD}@{self.PROXY_HOST}:{self.PROXY_PORT}"
                        else:
                            self.PROXY_ENABLED = False
                            self.PROXY_URL = None
                    else:
                        self.PROXY_URL = None
                else:
                    self.PROXY_ENABLED = False
                    self.PROXY_URL = None
            except Exception as e:
                print(f"WARNING: Loi doc config.ini: {e}. Su dung .env hoac default.")
                self._load_proxy_from_env()
        else:
            # Fallback về .env hoặc default
            self._load_proxy_from_env()
    
    def _load_proxy_from_env(self) -> None:
        """Load proxy từ environment variable hoặc default"""
        proxy_str = os.getenv('PROXY', 'proxy05062.nproxy.online:41605:sophia598:odawntgzmdyxmw==')
        
        if proxy_str:
            parts = proxy_str.split(':')
            if len(parts) == 4:
                self.PROXY_HOST = parts[0]
                self.PROXY_PORT = int(parts[1])
                self.PROXY_USERNAME = parts[2]
                self.PROXY_PASSWORD = parts[3]
                self.PROXY_ENABLED = True
                self.PROXY_URL = f"http://{self.PROXY_USERNAME}:{self.PROXY_PASSWORD}@{self.PROXY_HOST}:{self.PROXY_PORT}"
            else:
                self.PROXY_ENABLED = False
                self.PROXY_URL = None
        else:
            self.PROXY_ENABLED = False
            self.PROXY_URL = None
    
    def toggle_proxy(self, enabled: bool) -> bool:
        """Bật/tắt proxy và lưu vào config.ini"""
        # base_dir là root của project (2 levels up từ src/core/config.py)
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        config_ini_path = os.path.join(base_dir, 'config.ini')
        
        try:
            config_parser = configparser.ConfigParser()
            if os.path.exists(config_ini_path):
                config_parser.read(config_ini_path, encoding='utf-8')
            else:
                config_parser.add_section('PROXY')
            
            if not config_parser.has_section('PROXY'):
                config_parser.add_section('PROXY')
            
            config_parser.set('PROXY', 'enabled', str(enabled).lower())
            
            # Giữ nguyên các giá trị khác nếu đã có
            if not config_parser.has_option('PROXY', 'host'):
                config_parser.set('PROXY', 'host', getattr(self, 'PROXY_HOST', 'proxy05062.nproxy.online'))
            if not config_parser.has_option('PROXY', 'port'):
                config_parser.set('PROXY', 'port', str(getattr(self, 'PROXY_PORT', 41605)))
            if not config_parser.has_option('PROXY', 'username'):
                config_parser.set('PROXY', 'username', getattr(self, 'PROXY_USERNAME', 'sophia598'))
            if not config_parser.has_option('PROXY', 'password'):
                config_parser.set('PROXY', 'password', getattr(self, 'PROXY_PASSWORD', 'odawntgzmdyxmw=='))
            
            with open(config_ini_path, 'w', encoding='utf-8') as f:
                config_parser.write(f)
            
            # Cập nhật runtime config
            self.PROXY_ENABLED = enabled
            if enabled and hasattr(self, 'PROXY_HOST'):
                self.PROXY_URL = f"http://{self.PROXY_USERNAME}:{self.PROXY_PASSWORD}@{self.PROXY_HOST}:{self.PROXY_PORT}"
            else:
                self.PROXY_URL = None
            
            return True
        except Exception as e:
            print(f"ERROR: Khong the cap nhat proxy config: {e}")
            return False

    def _setup_paths(self) -> None:
        """Setup file paths"""
        # base_dir là root của project (2 levels up từ src/core/config.py)
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        
        # Database paths
        self.DB_DIR = os.path.join(base_dir, 'src', 'database')
        os.makedirs(self.DB_DIR, exist_ok=True)
        self.DB_PATH = os.path.join(self.DB_DIR, 'chat_history.db')
        self.DB_BACKUP_PATH = os.path.join(self.DB_DIR, 'chat_history_backup.db')
        
        # Data directory for JSON files
        self.DATA_DIR = os.path.join(base_dir, 'data')
        os.makedirs(self.DATA_DIR, exist_ok=True)
        
        # Other paths
        self.NOTE_PATH = os.path.join(base_dir, 'notes.txt')
        self.MEMORY_PATH = os.path.join(self.DATA_DIR, 'short_term_memory.json')
        self.WEATHER_CACHE_PATH = os.path.join(self.DATA_DIR, 'weather_cache.json')
        self.FILE_STORAGE_PATH = os.path.join(base_dir, 'uploaded_files')
        self.MIN_FREE_SPACE_MB = 100
        
        # Instructions path
        self.INSTRUCTIONS_DIR = os.path.join(base_dir, 'src', 'instructions')
        self.PROMPT_PATH = os.path.join(self.INSTRUCTIONS_DIR, 'prompt.txt')


# Global instance
config = Config()

