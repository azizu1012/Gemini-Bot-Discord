import logging
import os
from pathlib import Path
from typing import Dict, Optional

from dotenv import load_dotenv


def _detect_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_runtime_env(project_root: Path) -> None:
    current = Path(__file__).resolve()
    root_env_path = current.parents[3] / ".env"
    project_env_path = project_root / ".env"

    if project_env_path.exists():
        load_dotenv(dotenv_path=project_env_path)
    elif root_env_path.exists():
        load_dotenv(dotenv_path=root_env_path)
    else:
        load_dotenv()


class Config:
    """Singleton configuration manager for the bot."""

    @staticmethod
    def _get_bool(name: str, default: bool) -> bool:
        raw = (os.getenv(name) or "").strip().lower()
        if not raw:
            return default
        return raw in {"1", "true", "yes", "on"}

    @staticmethod
    def _get_int(name: str, default: int, min_value: Optional[int] = None, max_value: Optional[int] = None) -> int:
        raw = (os.getenv(name) or "").strip()
        try:
            value = int(raw) if raw else default
        except ValueError:
            value = default
        if min_value is not None:
            value = max(min_value, value)
        if max_value is not None:
            value = min(max_value, value)
        return value

    def __init__(self):
        self.PROJECT_ROOT = _detect_project_root()
        _load_runtime_env(self.PROJECT_ROOT)

        # --- FILE PATHS (ABSOLUTE & CWD-INDEPENDENT) ---
        self.DB_PATH = self._resolve_db_path()
        self.DB_BACKUP_PATH = self._resolve_db_backup_path()
        self.NOTE_PATH = self._resolve_runtime_path("NOTE_PATH", "data/notes.txt")
        self.MEMORY_PATH = self._resolve_runtime_path("MEMORY_PATH", "data/short_term_memory.json")
        self.WEATHER_CACHE_PATH = self._resolve_runtime_path("WEATHER_CACHE_PATH", "data/weather_cache.json")
        self.FILE_STORAGE_PATH = self._resolve_runtime_path("FILE_STORAGE_PATH", "uploaded_files")
        self.QUOTA_STATE_PATH = self._resolve_runtime_path("ROUTER_QUOTA_STATE_FILE", "data/quota_state.json")
        self.LOG_PATH = self._resolve_runtime_path("BOT_LOG_PATH", "bot.log")

        # Keep router config aligned with absolute runtime path.
        os.environ["ROUTER_QUOTA_STATE_FILE"] = self.QUOTA_STATE_PATH

        # --- VOICE ROOM OWNER LOCK ---
        self.VOICE_LOCK_BASE_DIR = self._resolve_runtime_path("VOICE_LOCK_BASE_DIR", "data/voice_lock")
        self.VOICE_WHITELIST_FILE = str(Path(self.VOICE_LOCK_BASE_DIR) / "users.json")
        self.LOCKED_CHANNELS_FILE = str(Path(self.VOICE_LOCK_BASE_DIR) / "locked_channels.json")
        self.ENFORCED_NAMES_FILE = str(Path(self.VOICE_LOCK_BASE_DIR) / "enforced_names.json")
        self.VOICE_LOCK_LOG_FILE = str(Path(self.VOICE_LOCK_BASE_DIR) / "voice_lock.log")

        self._ensure_runtime_directories()

        # --- LOGGING SETUP ---
        self.logger = self._setup_logger()

        # --- DISCORD & BOT ---
        self.TOKEN = os.getenv("DISCORD_TOKEN")
        self.MODEL_NAME = os.getenv("MODEL_NAME", "gemini-3-flash-preview")
        self.ADMIN_ID = os.getenv("ADMIN_ID", "")
        self.ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
        self.HABE_USER_ID = os.getenv("HABE_USER_ID", "")
        self.MIRA_USER_ID = os.getenv("MIRA_USER_ID", "")
        self.ADO_FAT_USER_ID = os.getenv("ADO_FAT_USER_ID", "")
        self.MUC_RIM_USER_ID = os.getenv("MUC_RIM_USER_ID", "")
        self.SUC_VIEN_USER_ID = os.getenv("SUC_VIEN_USER_ID", "")
        self.CHUI_USER_ID = os.getenv("CHUI_USER_ID", "")

        # --- GEMINI API KEYS (DYNAMIC LOAD) ---
        self.GEMINI_API_KEYS = []
        seen_keys = set()

        for i in range(1, 21):
            key = (os.getenv(f"GEMINI_API_KEY_{i}") or "").strip()
            if key and key not in seen_keys:
                seen_keys.add(key)
                self.GEMINI_API_KEYS.append(key)

        for name in [
            "GEMINI_API_KEY_PROD",
            "GEMINI_API_KEY_TEST",
            "GEMINI_API_KEY_BACKUP",
            "GEMINI_API_KEY_EXTRA1",
            "GEMINI_API_KEY_EXTRA2",
        ]:
            key = (os.getenv(name) or "").strip()
            if key and key not in seen_keys:
                seen_keys.add(key)
                self.GEMINI_API_KEYS.append(key)

        if not self.GEMINI_API_KEYS:
            self.logger.error("Không tìm thấy Gemini API keys! Bot sẽ không thể hoạt động.")
        else:
            self.logger.info(f"✅ Đã thiết lập {len(self.GEMINI_API_KEYS)} Gemini API keys cho Smart Rotation.")

        # --- SEARCH API KEYS ---
        self.SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
        self.TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
        self.EXA_API_KEY = os.getenv("EXA_API_KEY")

        # --- WEATHER API ---
        self.WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
        self.CITY = os.getenv("CITY")

        # --- ANTI-SPAM ---
        self.SPAM_THRESHOLD = 3
        self.SPAM_WINDOW = 30

        # --- RATE & DM LIMITS ---
        self.DEFAULT_RATE_LIMIT = "10/60"
        self.PREMIUM_RATE_LIMIT = "20/60"
        self.DEFAULT_DM_LIMIT = 5
        self.PREMIUM_DM_LIMIT = 15
        self.ADMIN_USER_IDS = [self.ADMIN_ID] if self.ADMIN_ID else []

        # --- PRODUCTION STABILITY TUNING ---
        self.REASONING_MAX_API_RETRIES = self._get_int("REASONING_MAX_API_RETRIES", 3, min_value=1, max_value=6)
        self.REASONING_MAX_LOOPS = self._get_int("REASONING_MAX_LOOPS", 3, min_value=1, max_value=6)
        self.FINAL_MAX_API_RETRIES = self._get_int("FINAL_MAX_API_RETRIES", 3, min_value=1, max_value=6)
        self.FALLBACK_MAX_API_RETRIES = self._get_int("FALLBACK_MAX_API_RETRIES", 2, min_value=1, max_value=5)
        self.SEARCH_ENABLE_EXTRA_RETRIEVAL_PASS = self._get_bool("SEARCH_ENABLE_EXTRA_RETRIEVAL_PASS", True)
        self.SEARCH_ALLOW_PARTIAL_ANSWER = self._get_bool("SEARCH_ALLOW_PARTIAL_ANSWER", True)

        # --- GEMINI SAFETY SETTINGS ---
        self.SAFETY_SETTINGS = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]

        # --- MIN FREE SPACE ---
        self.MIN_FREE_SPACE_MB = 100

    def _resolve_runtime_path(self, env_name: str, default_relative_path: str) -> str:
        raw_path = (os.getenv(env_name) or "").strip()
        target = Path(raw_path) if raw_path else (self.PROJECT_ROOT / default_relative_path)
        if not target.is_absolute():
            target = self.PROJECT_ROOT / target
        return str(target.resolve())

    def _resolve_db_path(self) -> str:
        raw_db = (os.getenv("DB_PATH") or "").strip()
        if raw_db:
            return self._resolve_runtime_path("DB_PATH", "data/bot_database.db")

        data_dir = self.PROJECT_ROOT / "data"
        preferred = data_dir / "bot_database.db"
        legacy = data_dir / "chat_history.db"

        if preferred.exists():
            return str(preferred.resolve())
        if legacy.exists():
            return str(legacy.resolve())
        return str(preferred.resolve())

    def _resolve_db_backup_path(self) -> str:
        raw_backup = (os.getenv("DB_BACKUP_PATH") or "").strip()
        if raw_backup:
            return self._resolve_runtime_path("DB_BACKUP_PATH", "data/bot_database.db.backup")

        db_path = Path(self.DB_PATH)
        default_backup = db_path.with_suffix(db_path.suffix + ".backup")
        return str(default_backup.resolve())

    def _ensure_runtime_directories(self) -> None:
        runtime_dirs = {
            Path(self.DB_PATH).parent,
            Path(self.DB_BACKUP_PATH).parent,
            Path(self.MEMORY_PATH).parent,
            Path(self.WEATHER_CACHE_PATH).parent,
            Path(self.FILE_STORAGE_PATH),
            Path(self.QUOTA_STATE_PATH).parent,
            Path(self.VOICE_LOCK_BASE_DIR),
            Path(self.LOG_PATH).parent,
        }
        for directory in runtime_dirs:
            if directory:
                directory.mkdir(parents=True, exist_ok=True)

    def get_runtime_paths(self) -> Dict[str, str]:
        return {
            "project_root": str(self.PROJECT_ROOT),
            "db_path": self.DB_PATH,
            "db_backup_path": self.DB_BACKUP_PATH,
            "memory_path": self.MEMORY_PATH,
            "file_storage_path": self.FILE_STORAGE_PATH,
            "weather_cache_path": self.WEATHER_CACHE_PATH,
            "quota_state_path": self.QUOTA_STATE_PATH,
            "voice_lock_base_dir": self.VOICE_LOCK_BASE_DIR,
            "log_path": self.LOG_PATH,
        }

    def _setup_logger(self):
        """Setup logging system."""
        logger = logging.getLogger("bot_gemini")
        logger.setLevel(logging.INFO)

        if logger.handlers:
            return logger

        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

        file_handler = logging.FileHandler(self.LOG_PATH, encoding="utf-8")
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
REASONING_MAX_API_RETRIES = config.REASONING_MAX_API_RETRIES
REASONING_MAX_LOOPS = config.REASONING_MAX_LOOPS
FINAL_MAX_API_RETRIES = config.FINAL_MAX_API_RETRIES
FALLBACK_MAX_API_RETRIES = config.FALLBACK_MAX_API_RETRIES
SEARCH_ENABLE_EXTRA_RETRIEVAL_PASS = config.SEARCH_ENABLE_EXTRA_RETRIEVAL_PASS
SEARCH_ALLOW_PARTIAL_ANSWER = config.SEARCH_ALLOW_PARTIAL_ANSWER
PROJECT_ROOT = str(config.PROJECT_ROOT)
LOG_PATH = config.LOG_PATH
QUOTA_STATE_PATH = config.QUOTA_STATE_PATH
