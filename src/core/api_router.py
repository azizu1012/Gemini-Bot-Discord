import os
import random
import threading
import asyncio
from typing import Optional, Tuple, Dict, List, Any
from datetime import datetime, timedelta

from .api_config import (
    BotRouterConfig,
    AVAILABLE_MODELS,
    MODEL_PRIORITY,
    GEMINI_LIMITER_MAX_OUTPUT_TOKENS,
    GEMINI_LIMITER_FIXED_OVERHEAD,
    GEMINI_LIMITER_SAFETY_FACTOR,
    initialize_key_pool,
)
from .api_proxy import APIProxy
from .gemini_rate_limiter import GeminiRateLimiter

class APIRouter:
    _instance = None
    _initialized = False

    def __new__(cls, config: BotRouterConfig = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config: BotRouterConfig = None):
        if APIRouter._initialized:
            return

        self.config = config or BotRouterConfig()

        # Database pool will be injected by the app startup or bot_core
        self.db_repo = None

        # Priority order for auto selection
        self.model_priority = [m for m in MODEL_PRIORITY if m in AVAILABLE_MODELS]
        self.active_models = list(self.model_priority)
        self.current_model = self.model_priority[0] if self.model_priority else "gemini-flash-35"

        # Build priority groups for same-priority rotation
        self._priority_groups: Dict[int, List[str]] = {}
        for alias in self.model_priority:
            prio = AVAILABLE_MODELS.get(alias, {}).get("priority", 99)
            self._priority_groups.setdefault(prio, []).append(alias)

        self.current_model_lock = threading.Lock()

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

        self.rate_limiters: Dict[str, GeminiRateLimiter] = {}
        for model_alias, cfg in AVAILABLE_MODELS.items():
            self.rate_limiters[model_alias] = GeminiRateLimiter(
                rpm=int(cfg.get("rpm", 15)),
                tpm=int(cfg.get("tpm", 250000)),
                rpd=0,
                max_output_tokens=GEMINI_LIMITER_MAX_OUTPUT_TOKENS,
                fixed_overhead=GEMINI_LIMITER_FIXED_OVERHEAD,
                safety_factor=GEMINI_LIMITER_SAFETY_FACTOR,
            )

        self._print_init_summary()
        APIRouter._initialized = True

    def set_db_repo(self, db_repo):
        self.db_repo = db_repo

    def _print_init_summary(self):
        print("\n" + "=" * 60)
        print("🔑 API ROUTER - FULL AUTO + PROXY SUPPORT (PostgreSQL Edition)")
        print("=" * 60)
        print(f"🤖 Models (priority): {', '.join(self.model_priority)}")

        if self.use_proxy:
            relay_url_display = self.config.proxy.relay_url[:50] if self.config.proxy.relay_url else "not set"
            print(f"🌐 Proxy: ENABLED → {relay_url_display}...")
            print(f"   Fallback to direct: {self.proxy_fallback}")
        else:
            print("🔗 Mode: DIRECT (no proxy)")
        print("=" * 60 + "\n")

    async def acquire_gemini_quota(self, prompt_text: str, max_output_tokens: int, model_alias: Optional[str] = None, image_count: int = 0) -> bool:
        target_model = model_alias or self.get_preferred_model()
        limiter = self.rate_limiters.get(target_model)
        if limiter is None and self.rate_limiters:
            limiter = next(iter(self.rate_limiters.values()))
        if limiter is None:
            return False

        reserved_tokens = limiter.estimate_request_tokens(prompt_text, max_output_tokens, image_count=image_count)
        return await limiter.acquire_quota(reserved_tokens)

    def get_preferred_model(self) -> str:
        return self.get_current_model()

    def get_current_model(self) -> str:
        with self.current_model_lock:
            return self.current_model

    def set_model(self, model_name: str) -> bool:
        if model_name in AVAILABLE_MODELS:
            with self.current_model_lock:
                self.current_model = model_name
            return True
        return False

    def get_model_id(self, model_alias: Optional[str]) -> str:
        if model_alias and model_alias in AVAILABLE_MODELS:
            model_id = AVAILABLE_MODELS[model_alias].get("model_id")
            if model_id:
                return str(model_id)

        fallback_alias = self.get_preferred_model()
        if fallback_alias in AVAILABLE_MODELS:
            fallback_id = AVAILABLE_MODELS[fallback_alias].get("model_id")
            if fallback_id:
                return str(fallback_id)

        for alias in MODEL_PRIORITY:
            cfg = AVAILABLE_MODELS.get(alias)
            if cfg and cfg.get("model_id"):
                return str(cfg["model_id"])

        raise RuntimeError("No Gemini model_id configured in AVAILABLE_MODELS.")

    async def get_next_key_reservation(self) -> Optional[Dict[str, str]]:
        if not self.db_repo:
            print("⚠️ DB repo not set in APIRouter. Falling back to default/first key if any or failure.")
            return None

        custom_enabled = os.getenv("ENABLE_CUSTOM_ENDPOINT", "false").lower() == "true"

        valid_models = []
        for prio, aliases in self._priority_groups.items():
            for alias in aliases:
                if custom_enabled and alias.startswith("custom-"):
                    valid_models.append(alias)
                elif not custom_enabled and not alias.startswith("custom-"):
                    valid_models.append(alias)

        model_alias = valid_models[0] if valid_models else self.current_model
        provider = "openai" if (custom_enabled and model_alias.startswith("custom-")) else "gemini"

        key_data = await self.db_repo.get_next_available_key(provider=provider)
        if not key_data or "api_key" not in key_data:
            print(f"   ❌ No available keys from PostgreSQL pool for provider: {provider}!")
            return None

        with self.current_model_lock:
            self.current_model = model_alias

        return {
            "key": key_data["api_key"],
            "model_alias": model_alias,
            "pool": "postgres",
            "counter_key": str(key_data.get("key_id", "unknown"))
        }

    async def get_next_key_for_model_reservation(self, model_alias: str) -> Optional[Dict[str, str]]:
        if not self.db_repo:
            print("⚠️ DB repo not set in APIRouter.")
            return None

        provider = "openai" if model_alias.startswith("custom-") else "gemini"
        key_data = await self.db_repo.get_next_available_key(provider=provider)
        if not key_data or "api_key" not in key_data:
            return None

        with self.current_model_lock:
            self.current_model = model_alias

        return {
            "key": key_data["api_key"],
            "model_alias": model_alias,
            "pool": "postgres",
            "counter_key": str(key_data.get("key_id", "unknown"))
        }

    def commit_key_usage(self, reservation: Optional[Dict[str, str]]) -> None:
        if not reservation:
            return

        self.total_requests += 1

    def mark_key_cooldown(
        self,
        key_str: str,
        model_name: str,
        wait_time: float,
        pool: str = "main",
        counter_key: Optional[str] = None,
    ):
        self.total_429_errors += 1
        print(f"   ❌ [429 LIMIT] API Key cooldown {wait_time:.1f}s")
        if self.db_repo:
            asyncio.create_task(self.db_repo.cooldown_key_db(key_str, wait_time))

    def mark_key_exhausted(
        self,
        key_str: str,
        model_name: str,
        pool: str = "main",
        counter_key: Optional[str] = None,
    ):
        print(f"   🚫 [EXHAUSTED] API Key marked exhausted")
        if self.db_repo:
            asyncio.create_task(self.db_repo.exhaust_key_db(key_str))

    def get_usage_report(self) -> str:
        return "PostgreSQL based API Key management is active. Metrics are stored in the database."

# Global instance (lazy initialization)
_router_instance: Optional[APIRouter] = None

def get_api_router() -> APIRouter:
    global _router_instance
    if _router_instance is None:
        _router_instance = APIRouter()
    return _router_instance


def create_model_pools(keys: List[str], key_to_name: Dict[str, str]) -> List[Dict[str, str]]:
    pool = initialize_key_pool(keys)
    for item in pool:
        item["key_name"] = key_to_name.get(item["key"], "")
    return pool


def create_summary_pool(keys: List[str], key_to_name: Dict[str, str]) -> List[Dict[str, str]]:
    return create_model_pools(keys, key_to_name)