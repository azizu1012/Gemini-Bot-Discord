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
    "gemini-flash": {
        "display": "Gemini Flash",
        "priority": 1,
        "model_id": os.getenv('GEMINI_FLASH_MODEL', 'gemini-flash'),
        "direct_model_id": os.getenv('GEMINI_FLASH_DIRECT_MODEL', ''),
        "rpm": int(os.getenv('GEMINI_FLASH_RPM', '5')),
        "tpm": int(os.getenv('GEMINI_FLASH_TPM', '250000')),
        "rpd": int(os.getenv('GEMINI_FLASH_RPD', '20')),
    },
    "gemini-flash-lite": {
        "display": "Gemini Flash Lite",
        "priority": 2,
        "model_id": os.getenv('GEMINI_FLASH_LITE_MODEL', 'gemini-flash-lite'),
        "direct_model_id": os.getenv('GEMINI_FLASH_LITE_DIRECT_MODEL', 'gemini-flash-lite-lasted'),
        "rpm": int(os.getenv('GEMINI_FLASH_LITE_RPM', '15')),
        "tpm": int(os.getenv('GEMINI_FLASH_LITE_TPM', '250000')),
        "rpd": int(os.getenv('GEMINI_FLASH_LITE_RPD', '500')),
    },
}

# Priority list (sorted) - Router sẽ thử từ trên xuống
MODEL_PRIORITY = ["gemini-flash", "gemini-flash-lite"]


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

DEFAULT_REASONING_MODEL_ALIAS = os.getenv('REASONING_MODEL_ALIAS', 'gemini-flash-lite').strip() or 'gemini-flash-lite'
DEFAULT_FINAL_MODEL_ALIAS = os.getenv('FINAL_MODEL_ALIAS', 'gemini-flash').strip() or 'gemini-flash'
DEFAULT_FALLBACK_MODEL_ALIAS = os.getenv('FALLBACK_MODEL_ALIAS', DEFAULT_REASONING_MODEL_ALIAS).strip() or DEFAULT_REASONING_MODEL_ALIAS
VISION_MODEL_ALIAS = 'gemini-flash'

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
        
        if key_name.upper().startswith('GEMINI_API_KEY_') and 'TOMTAT' not in key_name.upper():
            main_keys.append((key_name, key_value))
            key_to_name[key_value] = key_name
        elif key_name.upper().startswith('GEMINI_API_KEY_TOMTAT_'):
            summary_keys.append((key_name, key_value))
            key_to_name[key_value] = key_name
    
    main_keys.sort(key=lambda x: x[0])
    summary_keys.sort(key=lambda x: x[0])
    
    all_keys['main'] = [val for _, val in main_keys]
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
