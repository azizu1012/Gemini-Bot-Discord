"""
API Router Module - Full Auto Model Selection + Proxy Support

Features:
- Full auto model selection (không cần specify tier)
- Daily quota per model per key
- Proxy support để route qua external server (bypass VPS block)
- Auto-switch model khi exhausted
- Thread-safe operations
"""
import os
import json
import random
import threading
from typing import Optional, Tuple, Dict, List
from datetime import datetime, timedelta

from .api_config import (
    BotRouterConfig,
    DAILY_QUOTA,
    QUOTA_LIMIT_MIN_PERCENT,
    QUOTA_LIMIT_MAX_PERCENT,
    AVAILABLE_MODELS,
    MODEL_PRIORITY,
    GEMINI_LIMITER_MAX_OUTPUT_TOKENS,
    GEMINI_LIMITER_FIXED_OVERHEAD,
    GEMINI_LIMITER_SAFETY_FACTOR,
    auto_detect_api_keys,
    initialize_key_pool,
    get_quota_reset_time,
)
from .api_proxy import APIProxy
from .gemini_rate_limiter import GeminiRateLimiter


# ============================================================================
# MODEL POOLS
# ============================================================================

def get_model_daily_quota(model_alias: str) -> int:
    """Get configured daily request quota (RPD) for a model alias."""
    model_cfg = AVAILABLE_MODELS.get(model_alias, {})
    return int(model_cfg.get('rpd', DAILY_QUOTA))


def create_model_pools(main_keys: List[str], key_to_name: Dict[str, str]) -> Dict[str, Dict]:
    """Khởi tạo MODEL_POOLS cho từng model"""
    pools = {}
    for model in AVAILABLE_MODELS:
        pools[model] = {
            'key_pool': initialize_key_pool(main_keys, daily_quota=get_model_daily_quota(model)),
            'key_to_name': key_to_name,
            'quota_counters': {},
            'quota_reset_time': get_quota_reset_time(),
            'key_cooldowns': {},
            'is_exhausted': False
        }
    return pools


def create_summary_pool(summary_keys: List[str], key_to_name: Dict[str, str]) -> Dict:
    """Khởi tạo SUMMARY_POOL cho fallback"""
    return {
        'key_pool': initialize_key_pool(summary_keys),
        'key_to_name': key_to_name,
        'quota_counters': {},
        'quota_reset_time': get_quota_reset_time(),
        'key_cooldowns': {},
        'total_used': 0
    }


# ============================================================================
# API ROUTER CLASS - FULL AUTO + PROXY SUPPORT
# ============================================================================

class APIRouter:
    """
    Full Auto API Router với Proxy Support:
    - Tự động chọn model theo priority
    - Daily quota per model per key
    - Proxy support để bypass VPS block
    - Auto-switch khi exhausted
    - Thread-safe
    """
    
    _instance = None
    _initialized = False
    
    def __new__(cls, config: BotRouterConfig = None):
        """Singleton pattern"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, config: BotRouterConfig = None):
        if APIRouter._initialized:
            return
        
        self.config = config or BotRouterConfig()
        self.quota_state_file = self.config.quota_state_file
        
        # Ensure data directory exists
        os.makedirs(os.path.dirname(self.quota_state_file), exist_ok=True)
        
        # Load API keys
        all_keys, key_to_name = auto_detect_api_keys()
        self.main_keys = all_keys['main']
        self.summary_keys = all_keys['summary']
        self.key_to_name = key_to_name
        
        # Model pools
        self.model_pools: Dict[str, Dict] = create_model_pools(self.main_keys, key_to_name)
        self.summary_pool: Dict = create_summary_pool(self.summary_keys, key_to_name)
        
        # Priority order for auto selection
        self.model_priority = [m for m in MODEL_PRIORITY if m in self.model_pools]
        self.active_models = list(self.model_priority)
        self.current_model = self.model_priority[0] if self.model_priority else "gemini-flash-latest"
        
        # Locks
        self.model_pools_lock = threading.Lock()
        self.summary_pool_lock = threading.Lock()
        self.current_model_lock = threading.Lock()
        self.request_lock = threading.Lock()
        self.last_request_time = 0.0
        
        # Proxy setup
        self.proxy = APIProxy(
            relay_url=self.config.proxy.relay_url,
            relay_secret=self.config.proxy.relay_secret,
            timeout=self.config.proxy.relay_timeout
        )
        self.use_proxy = self.config.proxy.enabled
        self.proxy_fallback = self.config.proxy.fallback_direct
        
        # Stats
        self.total_requests = 0
        self.total_429_errors = 0
        self.proxy_calls = 0
        self.direct_calls = 0

        # Gemini limiters by model alias (RPM/TPM/RPD from AVAILABLE_MODELS)
        self.rate_limiters: Dict[str, GeminiRateLimiter] = {}
        for model_alias, cfg in AVAILABLE_MODELS.items():
            self.rate_limiters[model_alias] = GeminiRateLimiter(
                rpm=int(cfg.get('rpm', 15)),
                tpm=int(cfg.get('tpm', 250000)),
                rpd=int(cfg.get('rpd', 0)),
                max_output_tokens=GEMINI_LIMITER_MAX_OUTPUT_TOKENS,
                fixed_overhead=GEMINI_LIMITER_FIXED_OVERHEAD,
                safety_factor=GEMINI_LIMITER_SAFETY_FACTOR,
            )

        # Load state
        self._load_quota_state()
        self._print_init_summary()
        
        APIRouter._initialized = True
    
    def _print_init_summary(self):
        """Print init info"""
        print("\n" + "=" * 60)
        print("🔑 API ROUTER - FULL AUTO + PROXY SUPPORT")
        print("=" * 60)
        print(f"🤖 Models (priority): {', '.join(self.model_priority)}")
        print("📊 Per-model limits (RPM/TPM/RPD per key):")
        for model_alias in self.model_priority:
            cfg = AVAILABLE_MODELS.get(model_alias, {})
            rpm = int(cfg.get('rpm', 0))
            tpm = int(cfg.get('tpm', 0))
            rpd = int(cfg.get('rpd', get_model_daily_quota(model_alias)))
            print(f"   - {model_alias}: RPM={rpm}, TPM={tpm}, RPD={rpd}")
        print(f"🔑 Main keys: {len(self.main_keys)} | Summary: {len(self.summary_keys)}")

        if self.use_proxy:
            relay_url_display = self.config.proxy.relay_url[:50] if self.config.proxy.relay_url else "not set"
            print(f"🌐 Proxy: ENABLED → {relay_url_display}...")
            print(f"   Fallback to direct: {self.proxy_fallback}")
        else:
            print("🔗 Mode: DIRECT (no proxy)")

        print("=" * 60 + "\n")

        if not self.main_keys:
            print("⚠️ WARNING: No API keys found!")

    async def acquire_gemini_quota(self, prompt_text: str, max_output_tokens: int, model_alias: Optional[str] = None) -> bool:
        """Acquire RPM/TPM/RPD quota for a model alias before Gemini request."""
        target_model = model_alias or self.get_preferred_model()
        limiter = self.rate_limiters.get(target_model)
        if limiter is None and self.rate_limiters:
            limiter = next(iter(self.rate_limiters.values()))
        if limiter is None:
            return False

        reserved_tokens = limiter.estimate_request_tokens(prompt_text, max_output_tokens)
        return await limiter.acquire_quota(reserved_tokens)

    # ========================================================================
    # QUOTA STATE PERSISTENCE
    # ========================================================================
    
    def _save_quota_state(self):
        """Lưu quota state vào JSON file"""
        try:
            state = {}
            
            with self.model_pools_lock:
                for model_name, pool in self.model_pools.items():
                    state[model_name] = {
                        'quota_counters': pool['quota_counters'].copy(),
                        'quota_reset_time': pool['quota_reset_time'].isoformat(),
                        'is_exhausted': pool['is_exhausted']
                    }
            
            with self.summary_pool_lock:
                state['_summary_pool'] = {
                    'quota_counters': self.summary_pool['quota_counters'].copy(),
                    'quota_reset_time': self.summary_pool['quota_reset_time'].isoformat(),
                    'total_used': self.summary_pool['total_used']
                }
            
            with open(self.quota_state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ Không thể lưu quota state: {e}")
    
    def _load_quota_state(self):
        """Load quota state từ JSON file"""
        if not os.path.exists(self.quota_state_file):
            return
        
        try:
            with open(self.quota_state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
            
            with self.model_pools_lock:
                for model_name, data in state.items():
                    if model_name.startswith('_'):
                        continue
                    if model_name in self.model_pools:
                        pool = self.model_pools[model_name]
                        
                        # Load quota counters
                        pool['quota_counters'] = data.get('quota_counters', {})
                        
                        # Count exhausted keys
                        exhausted_count = sum(
                            1 for v in pool['quota_counters'].values() 
                            if v >= 9999
                        )
                        
                        # Load và validate reset time
                        try:
                            saved_reset = datetime.fromisoformat(
                                data.get('quota_reset_time', '')
                            )
                            now = datetime.now()
                            
                            if saved_reset > now:
                                pool['quota_reset_time'] = saved_reset
                                if exhausted_count > 0:
                                    print(f"   📂 Loaded '{model_name}': {exhausted_count} keys exhausted")
                            else:
                                # Reset time đã qua -> new day
                                pool['quota_reset_time'] = get_quota_reset_time(now)
                                pool['quota_counters'].clear()
                                pool['is_exhausted'] = False
                                print(f"   🔄 New day for '{model_name}'! Quota reset.")
                        except:
                            pool['quota_reset_time'] = get_quota_reset_time()
                            pool['quota_counters'].clear()
                        
                        pool['is_exhausted'] = data.get('is_exhausted', False)
            
            # Load summary pool state
            if '_summary_pool' in state:
                with self.summary_pool_lock:
                    summary_data = state['_summary_pool']
                    self.summary_pool['quota_counters'] = summary_data.get('quota_counters', {})
                    self.summary_pool['total_used'] = summary_data.get('total_used', 0)
                    
                    try:
                        saved_reset = datetime.fromisoformat(
                            summary_data.get('quota_reset_time', '')
                        )
                        now = datetime.now()
                        
                        if saved_reset > now:
                            self.summary_pool['quota_reset_time'] = saved_reset
                        else:
                            self.summary_pool['quota_reset_time'] = get_quota_reset_time(now)
                            self.summary_pool['quota_counters'].clear()
                            self.summary_pool['total_used'] = 0
                    except:
                        self.summary_pool['quota_reset_time'] = get_quota_reset_time()
        except Exception as e:
            print(f"⚠️ Không thể load quota state: {e}")
    
    # ========================================================================
    # QUOTA RESET (midnight)
    # ========================================================================
    
    def _reset_quota_if_needed(self, model_name: str):
        """Reset quota nếu đã qua midnight"""
        with self.model_pools_lock:
            if model_name not in self.model_pools:
                return
            
            pool = self.model_pools[model_name]
            now = datetime.now()
            
            if now >= pool['quota_reset_time']:
                pool['quota_reset_time'] = get_quota_reset_time(now)
                
                total_used = sum(pool['quota_counters'].values())
                if total_used > 0:
                    print(f"\n🌅 NEW DAY! Resetting '{model_name}' quota.")
                    print(f"   📊 Yesterday used: {total_used} requests")
                
                pool['quota_counters'].clear()
                pool['is_exhausted'] = False
                
                # Re-randomize limits
                model_daily_quota = get_model_daily_quota(model_name)
                for key_obj in pool['key_pool']:
                    key_obj['random_limit'] = int(model_daily_quota * random.uniform(
                        QUOTA_LIMIT_MIN_PERCENT,
                        QUOTA_LIMIT_MAX_PERCENT
                    ))
                
                self._save_quota_state()
    
    def _reset_summary_pool_if_needed(self):
        """Reset summary pool quota nếu đã qua midnight"""
        with self.summary_pool_lock:
            now = datetime.now()
            
            if now >= self.summary_pool['quota_reset_time']:
                self.summary_pool['quota_reset_time'] = get_quota_reset_time(now)
                self.summary_pool['quota_counters'].clear()
                self.summary_pool['total_used'] = 0
                
                # Re-randomize limits
                for key_obj in self.summary_pool['key_pool']:
                    key_obj['random_limit'] = int(DAILY_QUOTA * random.uniform(
                        QUOTA_LIMIT_MIN_PERCENT,
                        QUOTA_LIMIT_MAX_PERCENT
                    ))
                
                self._save_quota_state()
    
    # ========================================================================
    # MODEL SWITCHING
    # ========================================================================
    
    def _find_available_model(self) -> Optional[str]:
        """Tìm model còn quota"""
        for model in self.active_models:
            self._reset_quota_if_needed(model)

            with self.model_pools_lock:
                pool = self.model_pools[model]

                for key_obj in pool['key_pool']:
                    key_str = key_obj['key']

                    # Check cooldown
                    if 'key_cooldowns' in pool and key_str in pool['key_cooldowns']:
                        if datetime.now() < pool['key_cooldowns'][key_str]:
                            continue
                        else:
                            del pool['key_cooldowns'][key_str]

                    # Check quota
                    count = pool['quota_counters'].get(key_str, 0)
                    limit = key_obj.get('random_limit', get_model_daily_quota(model))

                    if count < limit:
                        return model

        return None

    def get_preferred_model(self) -> str:
        """Get best model alias currently available for the next request."""
        available = self._find_available_model()
        if available:
            return available
        return self.get_current_model()
    
    def _switch_model_if_needed(self) -> bool:
        """Auto-switch sang model khác theo priority"""
        for model in self.model_priority:
            if model not in self.model_pools:
                continue
            
            self._reset_quota_if_needed(model)
            
            with self.model_pools_lock:
                pool = self.model_pools[model]
                
                for key_obj in pool['key_pool']:
                    key_str = key_obj['key']
                    count = pool['quota_counters'].get(key_str, 0)
                    limit = key_obj.get('random_limit', get_model_daily_quota(model))

                    if count < limit:
                        if model != self.current_model:
                            with self.current_model_lock:
                                old = self.current_model
                                self.current_model = model
                                print(f"🔄 [AUTO SWITCH] {old} → {model}")
                        return True
        
        print("❌ ALL MODELS EXHAUSTED!")
        return False
    
    # ========================================================================
    # GET NEXT KEY - FULL AUTO (không cần specify tier)
    # ========================================================================
    
    def get_next_key(self) -> Tuple[Optional[str], Optional[str]]:
        """
        FULL AUTO: Lấy API key + model tự động theo priority.

        Thử lần lượt các model alias theo priority order:
        1. gemini-flash-latest
        2. gemini-flash-lite-latest

        Returns:
            (api_key, model_alias) hoặc (None, None) nếu hết quota
        """
        # Try each model in priority order
        for target_model in self.model_priority:
            if target_model not in self.model_pools:
                continue

            result = self._try_get_key_from_model(target_model)
            if result[0]:
                return result

        # All main pools exhausted - try summary pool
        print("   ⚠️ Main pools exhausted. Trying Summary Pool...")
        result = self._get_key_from_summary()
        if result[0]:
            return result

        print("   ❌ All pools exhausted!")
        return None, None

    def get_next_key_for_model(self, model_alias: str) -> Tuple[Optional[str], Optional[str]]:
        """Get next key for a specific model alias first, then summary fallback."""
        if model_alias in self.model_pools:
            result = self._try_get_key_from_model(model_alias)
            if result[0]:
                return result

            with self.current_model_lock:
                self.current_model = model_alias

            result = self._get_key_from_summary()
            if result[0]:
                return result
            return None, None

        return self.get_next_key()
    
    def _try_get_key_from_model(self, model_name: str) -> Tuple[Optional[str], Optional[str]]:
        """Try to get a key from specific model pool"""
        self._reset_quota_if_needed(model_name)
        
        with self.model_pools_lock:
            pool = self.model_pools[model_name]
            
            available = []
            for key_obj in pool['key_pool']:
                key_str = key_obj['key']
                
                # Check cooldown
                if 'key_cooldowns' in pool and key_str in pool['key_cooldowns']:
                    if datetime.now() < pool['key_cooldowns'][key_str]:
                        continue
                    else:
                        del pool['key_cooldowns'][key_str]
                
                # Check quota
                count = pool['quota_counters'].get(key_str, 0)
                limit = key_obj.get('random_limit', get_model_daily_quota(model_name))

                if count < limit:
                    available.append((key_obj, limit - count))
            
            if not available:
                return None, None
            
            # Weighted random selection
            if len(available) > 1:
                weights = [remaining + 1 for _, remaining in available]
                total_weight = sum(weights)
                weights = [w / total_weight for w in weights]
                chosen_idx = random.choices(range(len(available)), weights=weights, k=1)[0]
                chosen, _ = available[chosen_idx]
            else:
                chosen, _ = available[0]
            
            # INCREMENT
            pool['quota_counters'][chosen['key']] = pool['quota_counters'].get(chosen['key'], 0) + 1
        
        self._save_quota_state()
        self.total_requests += 1
        
        with self.current_model_lock:
            self.current_model = model_name
        
        return chosen['key'], model_name
    
    def _get_key_from_summary(self) -> Tuple[Optional[str], Optional[str]]:
        """Lấy key từ Summary Pool cho model hiện tại"""
        target_model = self.current_model
        self._reset_summary_pool_if_needed()
        
        with self.summary_pool_lock:
            available = []
            for key_obj in self.summary_pool['key_pool']:
                key_str = key_obj['key']
                composite_key = f"{target_model}::{key_str}"
                
                # Check cooldown
                if 'key_cooldowns' in self.summary_pool:
                    if composite_key in self.summary_pool['key_cooldowns']:
                        if datetime.now() < self.summary_pool['key_cooldowns'][composite_key]:
                            continue
                        else:
                            del self.summary_pool['key_cooldowns'][composite_key]
                
                # Check quota (summary counter is per model::key)
                count = self.summary_pool['quota_counters'].get(composite_key, 0)
                limit = get_model_daily_quota(target_model)

                if count < limit:
                    available.append((key_obj, limit - count, composite_key))
            
            if not available:
                return None, None
            
            # Weighted random selection
            if len(available) > 1:
                weights = [remaining + 1 for _, remaining, _ in available]
                total_weight = sum(weights)
                weights = [w / total_weight for w in weights]
                chosen_idx = random.choices(range(len(available)), weights=weights, k=1)[0]
                chosen, _, composite_key = available[chosen_idx]
            else:
                chosen, _, composite_key = available[0]
            
            # INCREMENT
            self.summary_pool['quota_counters'][composite_key] = \
                self.summary_pool['quota_counters'].get(composite_key, 0) + 1
            self.summary_pool['total_used'] += 1
        
        self._save_quota_state()
        self.total_requests += 1
        return chosen['key'], target_model
    
    # ========================================================================
    # API CALL UTILITIES
    # ========================================================================
    
    def mark_key_cooldown(self, key_str: str, model_name: str, wait_time: float):
        """Đánh dấu key bị cooldown (429 error)"""
        release_time = datetime.now() + timedelta(seconds=wait_time + 2)
        
        with self.model_pools_lock:
            if model_name in self.model_pools:
                if 'key_cooldowns' not in self.model_pools[model_name]:
                    self.model_pools[model_name]['key_cooldowns'] = {}
                self.model_pools[model_name]['key_cooldowns'][key_str] = release_time
        
        self.total_429_errors += 1
        key_name = self.key_to_name.get(key_str, "Unknown")
        print(f"   ❌ [429 LIMIT] {key_name} cooldown {wait_time:.1f}s")
    
    def mark_key_exhausted(self, key_str: str, model_name: str):
        """Đánh dấu key đã hết quota (soft exhaust)"""
        with self.model_pools_lock:
            if model_name in self.model_pools:
                pool = self.model_pools[model_name]
                # Set quota to limit to prevent reuse today
                pool['quota_counters'][key_str] = 9999
        self._save_quota_state()
    
    def get_current_model(self) -> str:
        """Lấy model alias đang active"""
        with self.current_model_lock:
            return self.current_model

    def get_model_id(self, model_alias: Optional[str]) -> str:
        """Resolve model alias to provider model id from configured AVAILABLE_MODELS."""
        if model_alias and model_alias in AVAILABLE_MODELS:
            model_id = AVAILABLE_MODELS[model_alias].get('model_id')
            if model_id:
                return str(model_id)

        fallback_alias = self.get_preferred_model()
        if fallback_alias in AVAILABLE_MODELS:
            fallback_id = AVAILABLE_MODELS[fallback_alias].get('model_id')
            if fallback_id:
                return str(fallback_id)

        for alias in MODEL_PRIORITY:
            cfg = AVAILABLE_MODELS.get(alias)
            if cfg and cfg.get('model_id'):
                return str(cfg['model_id'])

        for cfg in AVAILABLE_MODELS.values():
            model_id = cfg.get('model_id')
            if model_id:
                return str(model_id)

        raise RuntimeError("No Gemini model_id configured in AVAILABLE_MODELS.")

    def set_model(self, model_name: str) -> bool:
        """Set model alias cụ thể"""
        if model_name in AVAILABLE_MODELS:
            with self.current_model_lock:
                self.current_model = model_name
            return True
        return False

    def get_key_name(self, key_str: str) -> str:
        """Lấy tên key từ giá trị"""
        return self.key_to_name.get(key_str, "Unknown")
    
    # ========================================================================
    # USAGE REPORT
    # ========================================================================
    
    def get_usage_report(self) -> str:
        """Báo cáo sử dụng API keys (Daily Quota system)"""
        lines = [
            "",
            "=" * 80,
            "📊 BÁO CÁO SỬ DỤNG API - PER-MODEL DAILY QUOTA (RPD/key/ngày)",
            "=" * 80
        ]
        
        # Main pools
        for model_name in self.active_models:
            with self.model_pools_lock:
                if model_name not in self.model_pools:
                    continue
                pool = self.model_pools[model_name]
                
                lines.append(f"\n🤖 Model: {model_name}")
                lines.append("-" * 40)
                
                total_used = 0
                total_limit = 0
                
                for key_obj in pool['key_pool']:
                    key_str = key_obj['key']
                    key_name = self.key_to_name.get(key_str, "Unknown")
                    count = pool['quota_counters'].get(key_str, 0)
                    limit = key_obj.get('random_limit', get_model_daily_quota(model_name))

                    total_used += count
                    total_limit += limit
                    
                    # Status
                    if count >= 9999:
                        status = "🚫 BLOCKED"
                    elif count >= limit:
                        status = "❌ EXHAUSTED"
                    elif count >= limit * 0.8:
                        status = "⚠️ LOW"
                    else:
                        status = "✅ OK"
                    
                    lines.append(
                        f"  {status:<12} | {key_name:<25} | "
                        f"{count:2d}/{limit:2d} ({count*100//limit if limit > 0 else 0}%)"
                    )
                
                lines.append(f"  📈 Tổng: {total_used}/{total_limit}")
        
        # Summary pool
        with self.summary_pool_lock:
            lines.append(f"\n📝 SUMMARY POOL")
            lines.append("-" * 40)
            
            for key_obj in self.summary_pool['key_pool']:
                key_str = key_obj['key']
                key_name = self.key_to_name.get(key_str, "Unknown")
                
                total_count = 0
                for model in self.active_models:
                    composite = f"{model}::{key_str}"
                    total_count += self.summary_pool['quota_counters'].get(composite, 0)
                
                lines.append(f"  {key_name:<25} | Dùng: {total_count} lần")
        
        lines.append("\n" + "=" * 80)
        lines.append(f"📈 Tổng requests: {self.total_requests} | 429 errors: {self.total_429_errors}")
        lines.append(f"⏰ Reset tiếp theo: {get_quota_reset_time().strftime('%Y-%m-%d %H:%M')}")
        lines.append("")
        
        return "\n".join(lines)


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

# Global instance (lazy initialization)
_router_instance: Optional[APIRouter] = None

def get_api_router() -> APIRouter:
    """Get or create the global APIRouter instance"""
    global _router_instance
    if _router_instance is None:
        _router_instance = APIRouter()
    return _router_instance
