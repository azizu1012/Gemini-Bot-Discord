import os
import random
import threading
import asyncio
import time
from typing import Optional, Tuple, Dict, List, Any
from datetime import datetime, timedelta

from .api_config import (
    BotRouterConfig,
    AVAILABLE_MODELS,
    MODEL_PRIORITY,
    GEMINI_LIMITER_MAX_OUTPUT_TOKENS,
    GEMINI_LIMITER_FIXED_OVERHEAD,
    GEMINI_LIMITER_SAFETY_FACTOR,
    CUSTOM_API_DEFAULT_RPM,
    CUSTOM_API_DEFAULT_TPM,
    CUSTOM_API_DEFAULT_RPD,
    DEFAULT_REASONING_MODEL_ALIAS,
    DEFAULT_FINAL_MODEL_ALIAS,
    DEFAULT_FALLBACK_MODEL_ALIAS,
    initialize_key_pool,
)
from .api_proxy import APIProxy
from .custom_endpoint import normalize_custom_endpoint
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
        self.custom_model_alias_prefix = "custom:"
        self.custom_models_cache: Dict[str, Dict[str, Any]] = {}
        self.custom_models_cache_expires_at = 0.0
        self.custom_models_cache_ttl_seconds = 60.0
        self.custom_provider_config_cache: Optional[Dict[str, Any]] = None
        self.custom_provider_config_cache_loaded = False
        self.custom_provider_config_cache_expires_at = 0.0
        self.custom_provider_config_cache_ttl_seconds = 30.0

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

        # Circuit breaker (Gemini)
        self.circuit_enabled = os.getenv("GEMINI_CIRCUIT_ENABLED", "true").lower() == "true"
        self.circuit_failure_threshold = int(os.getenv("GEMINI_CIRCUIT_FAILURE_THRESHOLD", "5"))
        self.circuit_window_seconds = int(os.getenv("GEMINI_CIRCUIT_WINDOW_SECONDS", "10"))
        self.circuit_open_seconds = int(os.getenv("GEMINI_CIRCUIT_OPEN_SECONDS", "30"))
        self._circuit_failures: Dict[str, List[float]] = {"gemini": []}
        self._circuit_state: Dict[str, str] = {"gemini": "closed"}
        self._circuit_open_until: Dict[str, float] = {"gemini": 0.0}

        self.rate_limiters: Dict[str, GeminiRateLimiter] = {}
        for model_alias, cfg in AVAILABLE_MODELS.items():
            self.rate_limiters[model_alias] = GeminiRateLimiter(
                rpm=int(cfg.get("rpm", 15)),
                tpm=int(cfg.get("tpm", 250000)),
                rpd=int(cfg.get("rpd", 0)),
                max_output_tokens=GEMINI_LIMITER_MAX_OUTPUT_TOKENS,
                fixed_overhead=GEMINI_LIMITER_FIXED_OVERHEAD,
                safety_factor=GEMINI_LIMITER_SAFETY_FACTOR,
            )

        self._print_init_summary()
        APIRouter._initialized = True

    def set_db_repo(self, db_repo):
        self.db_repo = db_repo

    def custom_model_alias(self, model_id: str) -> str:
        return f"{self.custom_model_alias_prefix}{str(model_id or '').strip()}"

    def is_custom_model_alias(self, model_alias: Optional[str]) -> bool:
        return bool(model_alias and model_alias.startswith(self.custom_model_alias_prefix))

    def get_custom_model_id(self, model_alias: Optional[str]) -> Optional[str]:
        if not self.is_custom_model_alias(model_alias):
            return None
        model_id = str(model_alias or "")[len(self.custom_model_alias_prefix):].strip()
        return model_id or None

    def is_custom_enabled(self) -> bool:
        return os.getenv("ENABLE_CUSTOM_ENDPOINT", "false").lower() == "true"

    def clear_custom_provider_config_cache(self) -> None:
        self.custom_provider_config_cache = None
        self.custom_provider_config_cache_loaded = False
        self.custom_provider_config_cache_expires_at = 0.0

    async def refresh_custom_provider_config(self, force: bool = False) -> Optional[Dict[str, Any]]:
        if not self.db_repo:
            self.clear_custom_provider_config_cache()
            return None
        now = time.time()
        if not force and self.custom_provider_config_cache_loaded and now < self.custom_provider_config_cache_expires_at:
            return dict(self.custom_provider_config_cache) if self.custom_provider_config_cache else None
        try:
            config = await self.db_repo.get_custom_provider_config(provider="openai")
        except Exception as e:
            print(f"⚠️ Failed to refresh custom provider config from DB: {e}")
            return dict(self.custom_provider_config_cache) if self.custom_provider_config_cache else None
        self.custom_provider_config_cache = dict(config) if config else None
        self.custom_provider_config_cache_loaded = True
        self.custom_provider_config_cache_expires_at = now + self.custom_provider_config_cache_ttl_seconds
        return dict(self.custom_provider_config_cache) if self.custom_provider_config_cache else None

    async def get_custom_provider_config(self, force: bool = False) -> Optional[Dict[str, Any]]:
        return await self.refresh_custom_provider_config(force=force)

    def _legacy_custom_endpoint(self) -> str:
        endpoint = os.getenv("OPENAI_CUSTOM_ENDPOINT", "").strip()
        if not endpoint:
            return ""
        try:
            return normalize_custom_endpoint(endpoint)
        except ValueError:
            return ""

    async def is_custom_enabled_async(self, force: bool = False) -> bool:
        provider_config = await self.get_custom_provider_config(force=force)
        if provider_config is not None:
            return bool(
                provider_config.get("is_enabled")
                and provider_config.get("normalized_base_url")
                and provider_config.get("active_key_id") is not None
            )
        return bool(self.is_custom_enabled() and self._legacy_custom_endpoint())

    async def get_custom_endpoint_base_url(self, force: bool = False) -> str:
        provider_config = await self.get_custom_provider_config(force=force)
        if provider_config is not None:
            return str(provider_config.get("normalized_base_url") or "").strip()
        return self._legacy_custom_endpoint()

    def _static_alias_or_default(self, alias: Optional[str], fallback: str) -> str:
        alias = str(alias or "").strip()
        return alias if alias in AVAILABLE_MODELS else fallback

    def _ensure_custom_rate_limiter(self, model_alias: str) -> None:
        if model_alias in self.rate_limiters:
            return
        self.rate_limiters[model_alias] = GeminiRateLimiter(
            rpm=CUSTOM_API_DEFAULT_RPM,
            tpm=CUSTOM_API_DEFAULT_TPM,
            rpd=CUSTOM_API_DEFAULT_RPD,
            max_output_tokens=GEMINI_LIMITER_MAX_OUTPUT_TOKENS,
            fixed_overhead=GEMINI_LIMITER_FIXED_OVERHEAD,
            safety_factor=GEMINI_LIMITER_SAFETY_FACTOR,
        )

    async def refresh_custom_models_from_db(self, force: bool = False) -> List[Dict[str, Any]]:
        if not self.db_repo:
            return []
        now = time.time()
        if not force and now < self.custom_models_cache_expires_at:
            return list(self.custom_models_cache.values())
        try:
            rows = await self.db_repo.get_alive_custom_api_models(provider="openai")
        except Exception as e:
            print(f"⚠️ Failed to refresh custom models from DB: {e}")
            return list(self.custom_models_cache.values())
        self.custom_models_cache = {str(row.get("model_id")): dict(row) for row in rows if row.get("model_id")}
        self.custom_models_cache_expires_at = now + self.custom_models_cache_ttl_seconds
        for model_id in self.custom_models_cache:
            self._ensure_custom_rate_limiter(self.custom_model_alias(model_id))
        return list(self.custom_models_cache.values())

    async def get_selected_model_aliases(self, force_refresh: bool = False) -> Dict[str, Optional[str]]:
        default_reasoning = self._static_alias_or_default(DEFAULT_REASONING_MODEL_ALIAS, "gemini-flash-lite")
        default_final = self._static_alias_or_default(DEFAULT_FINAL_MODEL_ALIAS, "gemini-flash-35")
        default_fallback = self._static_alias_or_default(DEFAULT_FALLBACK_MODEL_ALIAS, default_reasoning)
        selected: Dict[str, Optional[str]] = {
            "reasoning": default_reasoning,
            "final": default_final,
            "fallback": default_fallback,
            "image_generator_model_id": None,
        }
        if not self.db_repo or not await self.is_custom_enabled_async(force=force_refresh):
            return selected
        try:
            config = await self.db_repo.get_bot_model_config()
            models = await self.refresh_custom_models_from_db(force=force_refresh)
        except Exception as e:
            print(f"⚠️ Failed to load bot model config: {e}")
            return selected
        alive_model_ids = {str(model.get("model_id")) for model in models if model.get("model_id")}

        reasoning_model_id = str(config.get("reasoning_model_id") or "").strip()
        final_model_id = str(config.get("final_model_id") or "").strip()
        image_model_id = str(config.get("image_generator_model_id") or "").strip()

        def should_route_custom(model_id: str) -> bool:
            if not model_id:
                return False
            return model_id in alive_model_ids

        if should_route_custom(reasoning_model_id):
            selected["reasoning"] = self.custom_model_alias(reasoning_model_id)
        if should_route_custom(final_model_id):
            selected["final"] = self.custom_model_alias(final_model_id)
        if should_route_custom(image_model_id):
            selected["image_generator_model_id"] = image_model_id
        return selected

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
        if self.is_custom_model_alias(target_model):
            self._ensure_custom_rate_limiter(target_model)
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
        if model_name in AVAILABLE_MODELS or self.is_custom_model_alias(model_name):
            if self.is_custom_model_alias(model_name):
                self._ensure_custom_rate_limiter(model_name)
            with self.current_model_lock:
                self.current_model = model_name
            return True
        return False

    def get_model_id(self, model_alias: Optional[str]) -> str:
        if model_alias and model_alias in AVAILABLE_MODELS:
            model_id = AVAILABLE_MODELS[model_alias].get("model_id")
            if model_id:
                return str(model_id)

        custom_model_id = self.get_custom_model_id(model_alias)
        if custom_model_id:
            return custom_model_id

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

        selected = await self.get_selected_model_aliases()
        model_alias = selected.get("final") or self.current_model
        return await self.get_next_key_for_model_reservation(model_alias)

    async def get_next_key_for_model_reservation(self, model_alias: str) -> Optional[Dict[str, Any]]:
        if not self.db_repo:
            print("⚠️ DB repo not set in APIRouter.")
            return None

        provider = "gemini"
        rpm_limit = None
        active_key_id = None
        custom_endpoint = ""
        endpoint_preset = ""
        if self.is_custom_model_alias(model_alias):
            provider_config = await self.get_custom_provider_config()
            if provider_config is not None:
                active_key_id = provider_config.get("active_key_id")
                custom_endpoint = str(provider_config.get("normalized_base_url") or "").strip()
                endpoint_preset = str(provider_config.get("endpoint_preset") or "").strip().lower()
                if not provider_config.get("is_enabled") or not custom_endpoint or active_key_id is None:
                    return None
            else:
                if not self.is_custom_enabled():
                    return None
                custom_endpoint = self._legacy_custom_endpoint()
                endpoint_preset = "manual"
                if not custom_endpoint:
                    return None

            model_id = self.get_custom_model_id(model_alias)
            alive_models = await self.refresh_custom_models_from_db()
            alive_model_ids = {str(model.get("model_id")) for model in alive_models if model.get("model_id")}
            if not model_id or model_id not in alive_model_ids:
                return None
            provider = "openai"
            rpm_limit = CUSTOM_API_DEFAULT_RPM
            self._ensure_custom_rate_limiter(model_alias)

        if provider == "gemini" and not self._allow_provider_request("gemini"):
            print("⚠️ Gemini circuit breaker is OPEN; blocking new gemini reservations.")
            return None

        key_data = await self.db_repo.get_next_available_key(
            provider=provider,
            rpm_limit=rpm_limit,
            key_id=active_key_id if provider == "openai" else None,
        )
        if not key_data or "api_key" not in key_data:
            return None

        with self.current_model_lock:
            self.current_model = model_alias

        reservation: Dict[str, Any] = {
            "key": key_data["api_key"],
            "model_alias": model_alias,
            "pool": "postgres",
            "counter_key": str(key_data.get("key_id", "unknown")),
            "provider": provider,
        }
        if provider == "openai":
            reservation["endpoint"] = custom_endpoint
            reservation["endpoint_preset"] = endpoint_preset
        return reservation

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

    def _prune_circuit_failures(self, provider: str, now: float) -> None:
        if provider not in self._circuit_failures:
            self._circuit_failures[provider] = []
        window_start = now - float(self.circuit_window_seconds)
        self._circuit_failures[provider] = [ts for ts in self._circuit_failures[provider] if ts >= window_start]

    def _allow_provider_request(self, provider: str) -> bool:
        if not self.circuit_enabled:
            return True
        state = self._circuit_state.get(provider, "closed")
        now = time.time()
        if state == "open":
            if now >= self._circuit_open_until.get(provider, 0.0):
                self._circuit_state[provider] = "half_open"
                return True
            return False
        return True

    def record_provider_failure(self, provider: str, reason: str) -> None:
        if not self.circuit_enabled:
            return
        now = time.time()
        self._prune_circuit_failures(provider, now)
        self._circuit_failures.setdefault(provider, []).append(now)
        state = self._circuit_state.get(provider, "closed")
        if state == "half_open":
            self._circuit_state[provider] = "open"
            self._circuit_open_until[provider] = now + float(self.circuit_open_seconds)
            print("⚠️ Gemini circuit breaker re-opened during half-open state.")
            return

        if len(self._circuit_failures.get(provider, [])) >= int(self.circuit_failure_threshold):
            self._circuit_state[provider] = "open"
            self._circuit_open_until[provider] = now + float(self.circuit_open_seconds)
            print("⚠️ Gemini circuit breaker OPEN: too many failures in window.")

    def record_provider_success(self, provider: str) -> None:
        if not self.circuit_enabled:
            return
        state = self._circuit_state.get(provider, "closed")
        if state in {"open", "half_open"}:
            self._circuit_state[provider] = "closed"
            self._circuit_failures[provider] = []
            self._circuit_open_until[provider] = 0.0
            print("✅ Gemini circuit breaker CLOSED after success.")

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