import logging
from logging.handlers import RotatingFileHandler
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
        load_dotenv(dotenv_path=project_env_path, override=True)
    elif root_env_path.exists():
        load_dotenv(dotenv_path=root_env_path, override=True)
    else:
        load_dotenv(override=True)


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

        # --- DATABASE & KAFKA ---
        self.DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/azuris")
        self.KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

        # --- FILE PATHS (ABSOLUTE & CWD-INDEPENDENT) ---
        self.NOTE_PATH = self._resolve_runtime_path("NOTE_PATH", "data/notes.txt")
        self.WEATHER_CACHE_PATH = self._resolve_runtime_path("WEATHER_CACHE_PATH", "data/weather_cache.json")
        self.FILE_STORAGE_PATH = self._resolve_runtime_path("FILE_STORAGE_PATH", "uploaded_files")
        self.FILE_CHUNK_DIR = self._resolve_runtime_path("FILE_CHUNK_DIR", "data/file_chunks")
        self.LOG_PATH = self._resolve_runtime_path("BOT_LOG_PATH", "bot.log")

        # Keep router config aligned with absolute runtime path.

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

        # --- DONATE ENCRYPTION ---
        self.DONATE_ENCRYPTION_KEY = os.getenv("DONATE_ENCRYPTION_KEY", "")

        # --- GEMINI API KEYS (PATTERN-BASED DYNAMIC LOAD) ---
        # Accept any env var like GEMINI_API_KEY_1..N and optional named extras.
        # Exclude summary-only keys (GEMINI_API_KEY_TOMTAT_*).
        self.GEMINI_API_KEYS = []
        seen_keys = set()

        indexed_key_names = sorted(
            [
                env_name
                for env_name in os.environ.keys()
                if env_name.upper().startswith("GEMINI_API_KEY_")
                and "TOMTAT" not in env_name.upper()
            ],
            key=lambda name: (
                0 if name.upper().replace("GEMINI_API_KEY_", "").isdigit() else 1,
                int(name.upper().replace("GEMINI_API_KEY_", "")) if name.upper().replace("GEMINI_API_KEY_", "").isdigit() else 10**9,
                name,
            ),
        )

        fallback_named_keys = [
            "GEMINI_API_KEY_PROD",
            "GEMINI_API_KEY_TEST",
            "GEMINI_API_KEY_BACKUP",
            "GEMINI_API_KEY_EXTRA1",
            "GEMINI_API_KEY_EXTRA2",
        ]

        for name in indexed_key_names + fallback_named_keys:
            key = (os.getenv(name) or "").strip()
            if key and key not in seen_keys:
                seen_keys.add(key)
                self.GEMINI_API_KEYS.append(key)

        if not self.GEMINI_API_KEYS:
            self.logger.error("Không tìm thấy Gemini API keys! Bot sẽ không thể hoạt động.")
        else:
            self.logger.info(f"✅ Đã thiết lập {len(self.GEMINI_API_KEYS)} Gemini API keys cho Smart Rotation.")

        # --- SEARCH API KEYS ---
        # --- OPENAI / CUSTOM ENDPOINT ---
        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
        self.OPENAI_CUSTOM_ENDPOINT = os.getenv("OPENAI_CUSTOM_ENDPOINT", "")

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

        self.ADMIN_ID_RAW = os.getenv("ADMIN_IDS", os.getenv("ADMIN_ID", ""))
        self.ADMIN_USER_IDS = [i.strip() for i in self.ADMIN_ID_RAW.split(",") if i.strip()] if self.ADMIN_ID_RAW else []

        self.MODERATOR_ID_RAW = os.getenv("MODERATOR_IDS", "")
        self.MODERATOR_USER_IDS = [i.strip() for i in self.MODERATOR_ID_RAW.split(",") if i.strip()] if self.MODERATOR_ID_RAW else []

        # --- PRODUCTION STABILITY TUNING ---
        self.REASONING_MAX_API_RETRIES = self._get_int("REASONING_MAX_API_RETRIES", 3, min_value=1, max_value=6)
        self.REASONING_MAX_LOOPS = self._get_int("REASONING_MAX_LOOPS", 3, min_value=1, max_value=6)
        self.FINAL_MAX_API_RETRIES = self._get_int("FINAL_MAX_API_RETRIES", 3, min_value=1, max_value=6)
        self.FALLBACK_MAX_API_RETRIES = self._get_int("FALLBACK_MAX_API_RETRIES", 2, min_value=1, max_value=5)
        self.FINAL_MAX_OUTPUT_TOKENS = self._get_int("FINAL_MAX_OUTPUT_TOKENS", 8192, min_value=512, max_value=65536)
        self.FALLBACK_MAX_OUTPUT_TOKENS = self._get_int("FALLBACK_MAX_OUTPUT_TOKENS", self.FINAL_MAX_OUTPUT_TOKENS, min_value=512, max_value=65536)
        self.FINAL_CONTINUATION_MAX_CALLS = self._get_int("FINAL_CONTINUATION_MAX_CALLS", 5, min_value=1, max_value=8)
        self.SEARCH_ENABLE_EXTRA_RETRIEVAL_PASS = self._get_bool("SEARCH_ENABLE_EXTRA_RETRIEVAL_PASS", True)
        self.SEARCH_ALLOW_PARTIAL_ANSWER = self._get_bool("SEARCH_ALLOW_PARTIAL_ANSWER", True)

        # --- GEMINI CIRCUIT BREAKER ---
        self.GEMINI_CIRCUIT_ENABLED = self._get_bool("GEMINI_CIRCUIT_ENABLED", True)
        self.GEMINI_CIRCUIT_FAILURE_THRESHOLD = self._get_int("GEMINI_CIRCUIT_FAILURE_THRESHOLD", 5, min_value=1, max_value=50)
        self.GEMINI_CIRCUIT_WINDOW_SECONDS = self._get_int("GEMINI_CIRCUIT_WINDOW_SECONDS", 10, min_value=2, max_value=300)
        self.GEMINI_CIRCUIT_OPEN_SECONDS = self._get_int("GEMINI_CIRCUIT_OPEN_SECONDS", 30, min_value=5, max_value=600)

        # --- GEMINI SAFETY SETTINGS ---
        self.SAFETY_SETTINGS = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]

        # --- MIN FREE SPACE ---
        self.MIN_FREE_SPACE_MB = self._get_int("MIN_FREE_SPACE_MB", 100)

        # --- SEARCH TUNING ---
        self.MAX_SEARCH_CALLS_PER_TURN = self._get_int("MAX_SEARCH_CALLS_PER_TURN", 5, min_value=1, max_value=20)

    def _resolve_runtime_path(self, env_name: str, default_relative_path: str) -> str:
        raw_path = (os.getenv(env_name) or "").strip()
        target = Path(raw_path) if raw_path else (self.PROJECT_ROOT / default_relative_path)
        if not target.is_absolute():
            target = self.PROJECT_ROOT / target
        return str(target.resolve())



    def _ensure_runtime_directories(self) -> None:
        runtime_dirs = {
            Path(self.WEATHER_CACHE_PATH).parent,
            Path(self.FILE_STORAGE_PATH),
            Path(self.FILE_CHUNK_DIR),
            Path(self.VOICE_LOCK_BASE_DIR),
            Path(self.LOG_PATH).parent,
        }
        for directory in runtime_dirs:
            if directory:
                directory.mkdir(parents=True, exist_ok=True)

    def get_runtime_paths(self) -> Dict[str, str]:
        return {
            "project_root": str(self.PROJECT_ROOT),
            "file_storage_path": self.FILE_STORAGE_PATH,
            "file_chunk_dir": self.FILE_CHUNK_DIR,
            "weather_cache_path": self.WEATHER_CACHE_PATH,
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

        file_handler = RotatingFileHandler(
            self.LOG_PATH,
            maxBytes=10 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8"
        )
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
NOTE_PATH = config.NOTE_PATH
WEATHER_CACHE_PATH = config.WEATHER_CACHE_PATH
FILE_STORAGE_PATH = config.FILE_STORAGE_PATH
FILE_CHUNK_DIR = config.FILE_CHUNK_DIR
VOICE_LOCK_BASE_DIR = config.VOICE_LOCK_BASE_DIR
VOICE_WHITELIST_FILE = config.VOICE_WHITELIST_FILE
LOCKED_CHANNELS_FILE = config.LOCKED_CHANNELS_FILE
ENFORCED_NAMES_FILE = config.ENFORCED_NAMES_FILE
VOICE_LOCK_LOG_FILE = config.VOICE_LOCK_LOG_FILE
MIN_FREE_SPACE_MB = config.MIN_FREE_SPACE_MB
MAX_SEARCH_CALLS_PER_TURN = config.MAX_SEARCH_CALLS_PER_TURN
DEFAULT_RATE_LIMIT = config.DEFAULT_RATE_LIMIT
PREMIUM_RATE_LIMIT = config.PREMIUM_RATE_LIMIT
DEFAULT_DM_LIMIT = config.DEFAULT_DM_LIMIT
PREMIUM_DM_LIMIT = config.PREMIUM_DM_LIMIT
ADMIN_USER_IDS = config.ADMIN_USER_IDS
MODERATOR_USER_IDS = config.MODERATOR_USER_IDS
REASONING_MAX_API_RETRIES = config.REASONING_MAX_API_RETRIES
REASONING_MAX_LOOPS = config.REASONING_MAX_LOOPS
FINAL_MAX_API_RETRIES = config.FINAL_MAX_API_RETRIES
FALLBACK_MAX_API_RETRIES = config.FALLBACK_MAX_API_RETRIES
FINAL_MAX_OUTPUT_TOKENS = config.FINAL_MAX_OUTPUT_TOKENS
FALLBACK_MAX_OUTPUT_TOKENS = config.FALLBACK_MAX_OUTPUT_TOKENS
FINAL_CONTINUATION_MAX_CALLS = config.FINAL_CONTINUATION_MAX_CALLS
SEARCH_ENABLE_EXTRA_RETRIEVAL_PASS = config.SEARCH_ENABLE_EXTRA_RETRIEVAL_PASS
SEARCH_ALLOW_PARTIAL_ANSWER = config.SEARCH_ALLOW_PARTIAL_ANSWER
PROJECT_ROOT = str(config.PROJECT_ROOT)
LOG_PATH = config.LOG_PATH
DONATE_ENCRYPTION_KEY = config.DONATE_ENCRYPTION_KEY


# Global DB pool
_db_pool = None

def get_db_pool():
    return _db_pool
    
def set_db_pool(pool):
    global _db_pool
    _db_pool = pool
