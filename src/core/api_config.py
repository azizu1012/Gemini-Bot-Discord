"""
API Router Configuration
Full Auto Model Selection + Proxy Support for VPS deployment
"""
import os
import random
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta

# ============================================================================
# AVAILABLE MODELS (Full Auto - Priority Order)
# Router sẽ tự động chọn model available theo priority
# ============================================================================
AVAILABLE_MODELS = {
    "gemini-flash-35": {
        "display": "Gemini Flash Latest",
        "priority": 1,
        "model_id": os.getenv('GEMINI_FLASH_35_MODEL', 'gemini-3.5-flash'),
        "rpm": int(os.getenv('GEMINI_FLASH_35_RPM', '5')),
        "tpm": int(os.getenv('GEMINI_FLASH_35_TPM', '250000')),
        "rpd": int(os.getenv('GEMINI_FLASH_35_RPD', '20')),
    },
    "gemini-flash-30": {
        "display": "Gemini Flash 3.0 Latest",
        "priority": 1,
        "model_id": os.getenv('GEMINI_FLASH_30_MODEL', 'gemini-3-flash-preview'),
        "rpm": int(os.getenv('GEMINI_FLASH_30_RPM', '5')),
        "tpm": int(os.getenv('GEMINI_FLASH_30_TPM', '250000')),
        "rpd": int(os.getenv('GEMINI_FLASH_30_RPD', '20')),
    },
    "gemini-flash-lite": {
        "display": "Gemini Flash Lite Latest",
        "priority": 2,
        "model_id": os.getenv('GEMINI_FLASH_LITE_MODEL', 'gemini-3.1-flash-lite'),
        "rpm": int(os.getenv('GEMINI_FLASH_LITE_RPM', '15')),
        "tpm": int(os.getenv('GEMINI_FLASH_LITE_TPM', '250000')),
        "rpd": int(os.getenv('GEMINI_FLASH_LITE_RPD', '500')),
    },
    # Custom Endpoint OpenAI Compatible Models
    "custom-flash-high": {
        "display": "Custom Flash High",
        "priority": 0, # Highest priority so it gets picked first if available
        "model_id": "gemini-3.5-flash-high",
        "rpm": 60,
        "tpm": 1000000,
        "rpd": 5000,
    },
    "custom-flash-low": {
        "display": "Custom Flash Low",
        "priority": 0,
        "model_id": "gemini-3.5-flash-low",
        "rpm": 60,
        "tpm": 1000000,
        "rpd": 5000,
    },
    "custom-flash-lite": {
        "display": "Custom Flash Lite",
        "priority": 1, # Used for reasoning
        "model_id": "gemini-3.1-flash-lite",
        "rpm": 60,
        "tpm": 1000000,
        "rpd": 5000,
    },
    "custom-pro-image": {
        "display": "Custom Pro Image",
        "priority": 0,
        "model_id": "gemini-3.1-pro-image",
        "rpm": 10,
        "tpm": 100000,
        "rpd": 500,
    }
}

# Priority list (sorted) - Router sẽ thử từ trên xuống
MODEL_PRIORITY = ["custom-flash-high", "custom-flash-low", "gemini-flash-35", "gemini-flash-30", "custom-flash-lite", "gemini-flash-lite"]


# ============================================================================
# QUOTA SETTINGS
# ============================================================================
DAILY_QUOTA = int(os.getenv('ROUTER_DAILY_QUOTA', '500'))
QUOTA_RESET_HOUR = int(os.getenv('ROUTER_QUOTA_RESET_HOUR', '0'))
QUOTA_LIMIT_MIN_PERCENT = float(os.getenv('ROUTER_QUOTA_MIN_PERCENT', '1.0'))
QUOTA_LIMIT_MAX_PERCENT = float(os.getenv('ROUTER_QUOTA_MAX_PERCENT', '1.0'))
ROUTER_COUNTER_LOG_ENABLED = os.getenv('ROUTER_COUNTER_LOG_ENABLED', 'true').lower() == 'true'

# Gemini limiter token-estimation settings
GEMINI_LIMITER_MAX_OUTPUT_TOKENS = int(os.getenv('GEMINI_LIMITER_MAX_OUTPUT_TOKENS', '2000'))
GEMINI_LIMITER_FIXED_OVERHEAD = int(os.getenv('GEMINI_LIMITER_FIXED_OVERHEAD', '80'))
GEMINI_LIMITER_SAFETY_FACTOR = float(os.getenv('GEMINI_LIMITER_SAFETY_FACTOR', '1.25'))

# ============================================================================
# PROXY/RELAY SETTINGS
# Để bypass VPS bị Google chặn, có thể route qua external server
# ============================================================================
@dataclass
class ProxyConfig:
    """Config cho proxy/relay server"""
    enabled: bool = False
    
    # Relay server URL (Google Colab, Cloudflare Worker, hoặc self-hosted)
    relay_url: str = ""
    
    # Auth cho relay server
    relay_secret: str = ""
    
    # Fallback: nếu relay fail, thử direct call không
    fallback_direct: bool = True
    
    # Timeout settings
    relay_timeout: int = 60


@dataclass 
class BotRouterConfig:
    """Cấu hình cho API Router"""
    # Paths
    quota_state_file: str = field(default_factory=lambda: os.path.join(
        os.path.dirname(__file__), '../../data/quota_state.json'
    ))
    
    # Retry settings
    retry_limit: int = 5
    retry_initial_delay: float = 2.0
    retry_max_delay: float = 30.0
    min_request_interval: float = 2.0
    
    # Proxy config
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    
    def __post_init__(self):
        # Load proxy settings from env
        self.proxy.enabled = os.getenv('GEMINI_PROXY_ENABLED', 'false').lower() == 'true'
        self.proxy.relay_url = os.getenv('GEMINI_RELAY_URL', '')
        self.proxy.relay_secret = os.getenv('GEMINI_RELAY_SECRET', '')


# ============================================================================
# API KEY AUTO-DETECT
# ============================================================================
def auto_detect_api_keys() -> Tuple[Dict[str, List[str]], Dict[str, str]]:
    """Auto-detect API keys từ environment variables"""
    all_keys = {'main': [], 'summary': []}
    key_to_name = {}
    
    env_vars = os.environ.copy()
    main_keys = []
    summary_keys = []
    
    for key_name, key_value in env_vars.items():
        if not key_value or not key_value.strip():
            continue
            
        # Add Custom OpenAI API Key to main keys so it goes into the router pool
        custom_endpoint_enabled = os.getenv("ENABLE_CUSTOM_ENDPOINT", "false").lower() == "true"
        if custom_endpoint_enabled and key_name.upper() == 'OPENAI_API_KEY' and env_vars.get('OPENAI_CUSTOM_ENDPOINT'):
            main_keys.append((key_name, key_value))
            key_to_name[key_value] = key_name
            continue
        
        if key_name.upper().startswith('GEMINI_API_KEY_') and 'TOMTAT' not in key_name.upper():
            main_keys.append((key_name, key_value))
            key_to_name[key_value] = key_name
        elif key_name.upper().startswith('GEMINI_API_KEY_TOMTAT_'):
            summary_keys.append((key_name, key_value))
            key_to_name[key_value] = key_name
    
    main_keys.sort(key=lambda x: x[0])
    summary_keys.sort(key=lambda x: x[0])
    
    # Prepend OPENAI_API_KEY to ensure it gets highest priority if present
    openai_keys = [val for name, val in main_keys if name == 'OPENAI_API_KEY']
    other_keys = [val for name, val in main_keys if name != 'OPENAI_API_KEY']
    
    all_keys['main'] = openai_keys + other_keys
    all_keys['summary'] = [val for _, val in summary_keys]
    
    return all_keys, key_to_name


def initialize_key_pool(keys: List[str], daily_quota: int = DAILY_QUOTA) -> List[dict]:
    """Convert list of keys to tracked key objects"""
    key_pool = []
    for k in keys:
        random_limit = int(daily_quota * random.uniform(
            QUOTA_LIMIT_MIN_PERCENT,
            QUOTA_LIMIT_MAX_PERCENT
        ))
        key_pool.append({
            'key': k,
            'random_limit': random_limit
        })
    return key_pool


def get_quota_reset_time(reference_time: Optional[datetime] = None) -> datetime:
    """Get next quota reset time (midnight)"""
    if reference_time is None:
        reference_time = datetime.now()
    
    reset_time = reference_time.replace(
        hour=QUOTA_RESET_HOUR, 
        minute=0, 
        second=0, 
        microsecond=0
    )
    if reset_time <= reference_time:
        reset_time += timedelta(days=1)
    return reset_time
