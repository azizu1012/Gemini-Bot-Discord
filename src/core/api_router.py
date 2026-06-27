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
    DEFAULT_REASONING_MODEL_ALIAS,
    DEFAULT_FINAL_MODEL_ALIAS,
    DEFAULT_FALLBACK_MODEL_ALIAS,
    initialize_key_pool,
)
from .gemini_rate_limiter import GeminiRateLimiter

class APIRouter:
    _instance = None
    _initialized = False

    def __new__(cls, config: Optional[BotRouterConfig] = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config: Optional[BotRouterConfig] = None):
        if APIRouter._initialized:
            return

        self.config = config or BotRouterConfig()

        # Database pool will be injected by the app startup or bot_core
        self.db_repo = None

        # Priority order for auto selection
        self.model_priority = [m for m in MODEL_PRIORITY if m in AVAILABLE_MODELS]
        self.active_models = list(self.model_priority)
        self.current_model = self.model_priority[0] if self.model_priority else "gemini-flash"

        # Build priority groups for same-priority rotation
        self._priority_groups: Dict[int, List[str]] = {}
        for alias in self.model_priority:
            prio = AVAILABLE_MODELS.get(alias, {}).get("priority", 99)
            self._priority_groups.setdefault(prio, []).append(alias)

        self.current_model_lock = threading.Lock()

        # Stats
        self.total_requests = 0
        self.total_429_errors = 0

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

    def _print_init_summary(self):
        print("\n" + "=" * 60)
        print("🔑 API ROUTER - FULL AUTO (PostgreSQL Edition)")
        print("=" * 60)
        print(f"🤖 Models (priority): {', '.join(self.model_priority)}")
        print("🔗 Mode: DIRECT (GEMINI_BASE_URL có thể cấu hình trong .env)")
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
        is_router_mode = bool(os.getenv("GEMINI_BASE_URL", "")) and bool(os.getenv("ROUTER_AUTH_KEY", ""))

        def _resolve(cfg: dict) -> str | None:
            if is_router_mode:
                return str(cfg["model_id"]) if cfg.get("model_id") else None
            else:
                direct = cfg.get("direct_model_id")
                if direct:
                    return str(direct)
                return str(cfg["model_id"]) if cfg.get("model_id") else None

        if model_alias and model_alias in AVAILABLE_MODELS:
            resolved = _resolve(AVAILABLE_MODELS[model_alias])
            if resolved:
                return resolved

        fallback_alias = self.get_preferred_model()
        if fallback_alias in AVAILABLE_MODELS:
            resolved = _resolve(AVAILABLE_MODELS[fallback_alias])
            if resolved:
                return resolved

        for alias in MODEL_PRIORITY:
            cfg = AVAILABLE_MODELS.get(alias)
            if cfg:
                resolved = _resolve(cfg)
                if resolved:
                    return resolved

        raise RuntimeError("No Gemini model_id configured in AVAILABLE_MODELS.")

    async def get_selected_model_aliases(self, force_refresh: bool = False) -> Dict[str, Optional[str]]:
        default_reasoning = DEFAULT_REASONING_MODEL_ALIAS if DEFAULT_REASONING_MODEL_ALIAS in AVAILABLE_MODELS else "gemini-flash-lite"
        default_final = DEFAULT_FINAL_MODEL_ALIAS if DEFAULT_FINAL_MODEL_ALIAS in AVAILABLE_MODELS else "gemini-flash"
        default_fallback = DEFAULT_FALLBACK_MODEL_ALIAS if DEFAULT_FALLBACK_MODEL_ALIAS in AVAILABLE_MODELS else default_reasoning
        return {
            "reasoning": default_reasoning,
            "final": default_final,
            "fallback": default_fallback,
            "image_generator_model_id": None,
        }

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

        if not self._allow_provider_request("gemini"):
            print("⚠️ Gemini circuit breaker is OPEN; blocking new gemini reservations.")
            return None

        key_data = await self.db_repo.get_next_available_key(
            provider="gemini",
            rpm_limit=None,
            key_id=None,
        )
        if not key_data or "api_key" not in key_data:
            return None

        with self.current_model_lock:
            self.current_model = model_alias

        return {
            "key": key_data["api_key"],
            "model_alias": model_alias,
            "pool": "postgres",
            "counter_key": str(key_data.get("key_id", "unknown")),
            "provider": "gemini",
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
