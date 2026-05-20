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
from typing import Optional, Tuple, Dict, List, Any
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
        is_custom_model = model.startswith('custom-')

        model_specific_keys = []
        for key in main_keys:
            key_name = key_to_name.get(key, "")
            is_openai_key = key_name == 'OPENAI_API_KEY' or key.startswith('sk-')

            if is_custom_model and is_openai_key:
                model_specific_keys.append(key)
            elif not is_custom_model and not is_openai_key:
                model_specific_keys.append(key)

        pools[model] = {
            'key_pool': initialize_key_pool(model_specific_keys, daily_quota=get_model_daily_quota(model)),
            'key_to_name': key_to_name,
            'quota_counters': {},
            'quota_reset_time': get_quota_reset_time(),
            'key_cooldowns': {},
            'is_exhausted': len(model_specific_keys) == 0
        }
    return pools


def create_summary_pool(summary_keys: List[str], key_to_name: Dict[str, str]) -> Dict:
    """Khởi tạo SUMMARY_POOL cho fallback"""
    gemini_keys = []
    for key in summary_keys:
        key_name = key_to_name.get(key, "")
        is_openai_key = key_name == 'OPENAI_API_KEY' or key.startswith('sk-')
        if not is_openai_key:
            gemini_keys.append(key)

    return {
        'key_pool': initialize_key_pool(gemini_keys),
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
        self.current_model = self.model_priority[0] if self.model_priority else "gemini-flash-35"

        # Build priority groups for same-priority rotation
        self._priority_groups: Dict[int, List[str]] = {}
        for alias in self.model_priority:
            prio = AVAILABLE_MODELS.get(alias, {}).get("priority", 99)
            self._priority_groups.setdefault(prio, []).append(alias)
        
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

        # Gemini limiters by model alias (RPM/TPM).
        # Daily quota authority lives in per-key router counters; limiter RPD is advisory-only and disabled for blocking.
        self.rate_limiters: Dict[str, GeminiRateLimiter] = {}
        for model_alias, cfg in AVAILABLE_MODELS.items():
            self.rate_limiters[model_alias] = GeminiRateLimiter(
                rpm=int(cfg.get('rpm', 15)),
                tpm=int(cfg.get('tpm', 250000)),
                rpd=0,
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
        print("📊 Per-model limits (RPM/TPM + RPD per-key and effective):")
        total_main_keys = max(1, len(self.main_keys))
        for model_alias in self.model_priority:
            cfg = AVAILABLE_MODELS.get(model_alias, {})
            rpm = int(cfg.get('rpm', 0))
            tpm = int(cfg.get('tpm', 0))
            rpd_per_key = int(cfg.get('rpd', get_model_daily_quota(model_alias)))
            rpd_effective = rpd_per_key * total_main_keys
            print(f"   - {model_alias}: RPM={rpm}, TPM={tpm}, RPD/key={rpd_per_key}, RPD/effective={rpd_effective}")
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

    async def acquire_gemini_quota(self, prompt_text: str, max_output_tokens: int, model_alias: Optional[str] = None, image_count: int = 0) -> bool:
        """Acquire RPM/TPM/RPD quota for a model alias before Gemini request."""
        target_model = model_alias or self.get_preferred_model()
        limiter = self.rate_limiters.get(target_model)
        if limiter is None and self.rate_limiters:
            limiter = next(iter(self.rate_limiters.values()))
        if limiter is None:
            return False

        reserved_tokens = limiter.estimate_request_tokens(prompt_text, max_output_tokens, image_count=image_count)
        return await limiter.acquire_quota(reserved_tokens)

    # ========================================================================
    # QUOTA STATE PERSISTENCE
    # ========================================================================
    
    def _build_quota_state_snapshot(self) -> Dict[str, Any]:
        state: Dict[str, Any] = {}

        with self.model_pools_lock:
            for model_name, pool in self.model_pools.items():
                state[model_name] = {
                    'quota_counters': pool['quota_counters'].copy(),
                    'quota_reset_time': pool['quota_reset_time'].isoformat(),
                    'is_exhausted': pool['is_exhausted'],
                }

        with self.summary_pool_lock:
            state['_summary_pool'] = {
                'quota_counters': self.summary_pool['quota_counters'].copy(),
                'quota_reset_time': self.summary_pool['quota_reset_time'].isoformat(),
                'total_used': self.summary_pool['total_used'],
            }

        return state

    def _write_quota_state(self, state: Dict[str, Any]) -> None:
        try:
            with open(self.quota_state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ Không thể lưu quota state: {e}")

    def _save_quota_state(self):
        """Lưu quota state vào JSON file"""
        state = self._build_quota_state_snapshot()
        self._write_quota_state(state)
    
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
                        load_persisted_exhausted = False
                        try:
                            saved_reset = datetime.fromisoformat(
                                data.get('quota_reset_time', '')
                            )
                            now = datetime.now()

                            if saved_reset > now:
                                pool['quota_reset_time'] = saved_reset
                                load_persisted_exhausted = True
                                if exhausted_count > 0:
                                    print(f"   📂 Loaded '{model_name}': {exhausted_count} keys exhausted")
                            else:
                                # Reset time đã qua -> new day
                                pool['quota_reset_time'] = get_quota_reset_time(now)
                                pool['quota_counters'].clear()
                                pool['is_exhausted'] = False
                                print(f"   🔄 New day for '{model_name}'! Quota reset.")
                        except Exception:
                            pool['quota_reset_time'] = get_quota_reset_time()
                            pool['quota_counters'].clear()
                            pool['is_exhausted'] = False

                        if load_persisted_exhausted:
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
        should_persist = False
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
                should_persist = True

        if should_persist:
            self._save_quota_state()

    def _reset_summary_pool_if_needed(self):
        """Reset summary pool quota nếu đã qua midnight"""
        should_persist = False
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
                should_persist = True

        if should_persist:
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
        """Compatibility API: return key/model without reservation metadata."""
        reservation = self.get_next_key_reservation()
        if not reservation:
            return None, None
        return reservation['key'], reservation['model_alias']

    def get_next_key_for_model(self, model_alias: str) -> Tuple[Optional[str], Optional[str]]:
        """Compatibility API: return key/model for target model without reservation metadata."""
        reservation = self.get_next_key_for_model_reservation(model_alias)
        if not reservation:
            return None, None
        return reservation['key'], reservation['model_alias']

    def get_next_key_reservation(self) -> Optional[Dict[str, str]]:
        """Reserve a key/model candidate without consuming daily quota yet.

        Models within the active priority groups are shuffled for load balancing.
        The active priority groups only contain custom endpoints if ENABLE_CUSTOM_ENDPOINT is true,
        otherwise they only contain standard endpoints.
        """
        custom_enabled = os.getenv("ENABLE_CUSTOM_ENDPOINT", "false").lower() == "true"

        # Filter available priorities based on custom toggle
        valid_models = []
        for prio, aliases in self._priority_groups.items():
            for alias in aliases:
                if custom_enabled and alias.startswith("custom-"):
                    valid_models.append(alias)
                elif not custom_enabled and not alias.startswith("custom-"):
                    valid_models.append(alias)

        # Group back into priorities
        active_priorities_to_models = {}
        for alias in valid_models:
            prio = AVAILABLE_MODELS.get(alias, {}).get("priority", 99)
            active_priorities_to_models.setdefault(prio, []).append(alias)

        priorities_to_check = sorted(list(active_priorities_to_models.keys()))

        seen_priorities: set = set()
        for prio in priorities_to_check:
            if prio in seen_priorities:
                continue
            seen_priorities.add(prio)

            peers = list(active_priorities_to_models.get(prio, []))
            if not peers:
                continue
            random.shuffle(peers)
            for peer in peers:
                if peer not in self.model_pools:
                    continue
                result = self._try_get_key_from_model(peer)
                if result:
                    return result

        print("   ⚠️ Main pools exhausted. Trying Summary Pool...")
        result = self._get_key_from_summary()
        if result:
            return result

        print("   ❌ All pools exhausted!")
        return None

    def get_next_key_for_model_reservation(self, model_alias: str) -> Optional[Dict[str, str]]:
        """Reserve candidate for a specific model alias first, then rotation peers, then summary fallback."""
        if model_alias in self.model_pools:
            result = self._try_get_key_from_model(model_alias)
            if result:
                return result

            prio = AVAILABLE_MODELS.get(model_alias, {}).get("priority", 99)
            peers = [p for p in self._priority_groups.get(prio, []) if p != model_alias]
            if peers:
                random.shuffle(peers)
                for peer in peers:
                    if peer in self.model_pools:
                        result = self._try_get_key_from_model(peer)
                        if result:
                            return result

            with self.current_model_lock:
                self.current_model = model_alias

            result = self._get_key_from_summary()
            if result:
                return result

            # If the specific model and its peers are completely exhausted,
            # fall back to the global logic rather than returning None
            return self.get_next_key_reservation()

        return self.get_next_key_reservation()

    def _try_get_key_from_model(self, model_name: str) -> Optional[Dict[str, str]]:
        """Reserve a key candidate from a specific model pool."""
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
                    del pool['key_cooldowns'][key_str]

                # Check quota
                count = pool['quota_counters'].get(key_str, 0)
                limit = key_obj.get('random_limit', get_model_daily_quota(model_name))

                if count < limit:
                    available.append((key_obj, limit - count))

            if not available:
                return None

            if len(available) > 1:
                weights = [remaining + 1 for _, remaining in available]
                total_weight = sum(weights)
                weights = [w / total_weight for w in weights]
                chosen_idx = random.choices(range(len(available)), weights=weights, k=1)[0]
                chosen, _ = available[chosen_idx]
            else:
                chosen, _ = available[0]

        with self.current_model_lock:
            self.current_model = model_name

        return {
            "key": chosen['key'],
            "model_alias": model_name,
            "pool": "main",
            "counter_key": chosen['key'],
        }

    def _get_key_from_summary(self) -> Optional[Dict[str, str]]:
        """Reserve key candidate from Summary Pool for current model."""
        target_model = self.current_model
        self._reset_summary_pool_if_needed()

        with self.summary_pool_lock:
            available = []
            for key_obj in self.summary_pool['key_pool']:
                key_str = key_obj['key']
                composite_key = f"{target_model}::{key_str}"

                # Check cooldown
                if 'key_cooldowns' in self.summary_pool and composite_key in self.summary_pool['key_cooldowns']:
                    if datetime.now() < self.summary_pool['key_cooldowns'][composite_key]:
                        continue
                    del self.summary_pool['key_cooldowns'][composite_key]

                count = self.summary_pool['quota_counters'].get(composite_key, 0)
                limit = get_model_daily_quota(target_model)

                if count < limit:
                    available.append((key_obj, limit - count, composite_key))

            if not available:
                return None

            if len(available) > 1:
                weights = [remaining + 1 for _, remaining, _ in available]
                total_weight = sum(weights)
                weights = [w / total_weight for w in weights]
                chosen_idx = random.choices(range(len(available)), weights=weights, k=1)[0]
                chosen, _, composite_key = available[chosen_idx]
            else:
                chosen, _, composite_key = available[0]

        return {
            "key": chosen['key'],
            "model_alias": target_model,
            "pool": "summary",
            "counter_key": composite_key,
        }

    def commit_key_usage(self, reservation: Optional[Dict[str, str]]) -> None:
        """Commit one successful request against daily quota counters."""
        if not reservation:
            return

        pool_name = reservation.get("pool", "main")
        model_name = reservation.get("model_alias")
        counter_key = reservation.get("counter_key")
        if not model_name or not counter_key:
            return

        if pool_name == "summary":
            with self.summary_pool_lock:
                self.summary_pool['quota_counters'][counter_key] = self.summary_pool['quota_counters'].get(counter_key, 0) + 1
                self.summary_pool['total_used'] += 1
        else:
            with self.model_pools_lock:
                if model_name not in self.model_pools:
                    return
                pool = self.model_pools[model_name]
                pool['quota_counters'][counter_key] = pool['quota_counters'].get(counter_key, 0) + 1

        self.total_requests += 1
        self._save_quota_state()

    # ========================================================================
    # API CALL UTILITIES
    # ========================================================================

    def mark_key_cooldown(
        self,
        key_str: str,
        model_name: str,
        wait_time: float,
        pool: str = "main",
        counter_key: Optional[str] = None,
    ):
        """Đánh dấu key bị cooldown (429/unavailable error)."""
        release_time = datetime.now() + timedelta(seconds=wait_time + 2)

        if pool == "summary":
            composite_key = counter_key or f"{model_name}::{key_str}"
            with self.summary_pool_lock:
                if 'key_cooldowns' not in self.summary_pool:
                    self.summary_pool['key_cooldowns'] = {}
                self.summary_pool['key_cooldowns'][composite_key] = release_time
        else:
            with self.model_pools_lock:
                if model_name in self.model_pools:
                    if 'key_cooldowns' not in self.model_pools[model_name]:
                        self.model_pools[model_name]['key_cooldowns'] = {}
                    self.model_pools[model_name]['key_cooldowns'][key_str] = release_time

        self.total_429_errors += 1
        key_name = self.key_to_name.get(key_str, "Unknown")
        print(f"   ❌ [429 LIMIT] {key_name} cooldown {wait_time:.1f}s")
        self._save_quota_state()

    def mark_key_exhausted(
        self,
        key_str: str,
        model_name: str,
        pool: str = "main",
        counter_key: Optional[str] = None,
    ):
        """Đánh dấu key đã hết quota (soft exhaust)."""
        if pool == "summary":
            composite_key = counter_key or f"{model_name}::{key_str}"
            with self.summary_pool_lock:
                self.summary_pool['quota_counters'][composite_key] = 9999
        else:
            with self.model_pools_lock:
                if model_name in self.model_pools:
                    pool_data = self.model_pools[model_name]
                    pool_data['quota_counters'][key_str] = 9999
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
