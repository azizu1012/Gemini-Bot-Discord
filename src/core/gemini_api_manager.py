import asyncio
import time
import random
import traceback
import re
import unicodedata
import base64
from urllib.parse import urlsplit
import threading
from typing import Any, Optional, Dict, List, Tuple

from google import genai
from google.genai import types as genai_types

from src.core.config import logger
from src.core.api_router import get_api_router


class GeminiApiManager:
    """API key management, throttling, client pool, and error detection for Gemini."""

    API_REQUEST_QUEUE = asyncio.Queue()
    API_REQUEST_SEMAPHORE = asyncio.Semaphore(2)
    LAST_API_REQUEST_TIME = 0.0
    MIN_REQUEST_INTERVAL = 0.6
    COOLDOWN_WINDOW = 1800
    MAX_REQUESTS_PER_WINDOW = 15

    def __init__(self, config, api_router=None):
        self.config = config
        self.logger = logger
        self.api_router = api_router or get_api_router()

        self.key_status = {k: {'usage': 0, 'frozen_until': 0.0} for k in self.config.GEMINI_API_KEYS}
        self.key_lock = threading.Lock()
        self.api_key_request_history: Dict[str, List[float]] = {}
        self.api_key_history_lock = threading.Lock()
        self._gemini_clients: Dict[Any, Any] = {}
        self._gemini_clients_lock = threading.Lock()
        self.router_bypass_until = 0.0

    # --- Key selection ---

    async def _get_best_api_key(self, preferred_model_alias: Optional[str] = None) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[Dict[str, Any]]]:
        if preferred_model_alias:
            if not self.api_router._allow_provider_request("gemini"):
                self.logger.warning("Gemini circuit breaker OPEN; no gemini key will be reserved.")
                return None, None, None, None
            reservation = await self.api_router.get_next_key_for_model_reservation(preferred_model_alias)
        else:
            reservation = await self.api_router.get_next_key_reservation()

        if reservation:
            api_key = reservation.get("key")
            model_alias = reservation.get("model_alias")
            if api_key and model_alias:
                return api_key, self.api_router.get_model_id(model_alias), model_alias, reservation

        self.logger.warning("⚠️ Router exhausted, trying legacy key selection...")
        with self.key_lock:
            now = time.time()
            active_keys = [k for k, v in self.key_status.items() if v['frozen_until'] < now]

            if not active_keys:
                self.logger.error("ALL API KEYS ARE FROZEN!")
                return None, None, None, None

            min_usage = min(self.key_status[k]['usage'] for k in active_keys)
            best_candidates = [k for k in active_keys if self.key_status[k]['usage'] == min_usage]

            chosen_key = random.choice(best_candidates)
            self.key_status[chosen_key]['usage'] += 1
            fallback_alias = preferred_model_alias or self.api_router.get_preferred_model()

            legacy_reservation = {
                "key": chosen_key,
                "model_alias": fallback_alias,
                "pool": "legacy",
                "counter_key": chosen_key,
                "provider": "gemini",
            }
            return chosen_key, self.api_router.get_model_id(fallback_alias), fallback_alias, legacy_reservation

    def _mark_key_as_failed(
        self,
        key: str,
        model_alias: Optional[str] = None,
        duration: int = 60,
        reason: str = "rate_limit",
        permanently_exhaust: bool = False,
        reservation: Optional[Dict[str, Any]] = None,
    ):
        # 503 Unavailable is a transient Google server error, not a quota limit.
        # We enforce a short delay, but do not exhaust/affect router quota for this key.
        is_503 = reason == "unavailable"

        if reason == "endpoint_down":
            self.router_bypass_until = time.time() + 30
            self.logger.warning("⚠️ [ROUTER-DOWN] Router API endpoint is unreachable. Bypassing Router and calling Google directly for 30 seconds.")

        model = model_alias or self.api_router.get_current_model()
        pool = (reservation or {}).get("pool", "main")
        counter_key = (reservation or {}).get("counter_key")

        if pool != "legacy" and not is_503 and reason != "endpoint_down":
            if permanently_exhaust:
                self.api_router.mark_key_exhausted(key, model, pool=pool, counter_key=counter_key)
            else:
                self.api_router.mark_key_cooldown(key, model, duration, pool=pool, counter_key=counter_key)

        provider = (reservation or {}).get("provider", "gemini")
        if provider == "gemini" and reason in {"rate_limit", "unavailable", "empty_candidate", "quota"}:
            self.api_router.record_provider_failure("gemini", reason)

        with self.key_lock:
            if key in self.key_status:
                self.key_status[key]['frozen_until'] = time.time() + duration

        if reason == "invalid_key":
            self.logger.warning(f"🚫 API Key ...{key[-4:]} marked invalid and excluded for current quota cycle.")
        elif is_503:
            self.logger.warning(f"⚠️ API Key ...{key[-4:]} delayed for {duration}s due to Google Server 503 (Unavailable).")
        elif reason == "endpoint_down":
            self.logger.warning(f"🔌 Connection to Router failed. API Key ...{key[-4:]} marked cooldown for {duration}s.")
        else:
            self.logger.warning(f"❄️ API Key ...{key[-4:]} frozen for {duration}s due to rate limit/quota.")

    def _commit_selected_key(self, reservation: Optional[Dict[str, Any]]) -> None:
        if not reservation:
            return
        if reservation.get("pool") == "legacy":
            return
        self.api_router.commit_key_usage(reservation)
        if reservation.get("provider") == "gemini":
            self.api_router.record_provider_success("gemini")

    # --- Error classification ---

    @staticmethod
    def _is_rate_limit_error(error_str: str) -> bool:
        lowered = (error_str or "").lower()
        return any(token in lowered for token in [
            "429",
            "quota",
            "resource exhausted",
            "resource_exhausted",
            "rate limit",
            "503",
            "unavailable",
            "service unavailable",
            "overloaded",
        ])

    @staticmethod
    def _is_unavailable_error(error_str: str) -> bool:
        lowered = (error_str or "").lower()
        return any(token in lowered for token in [
            "503",
            "unavailable",
            "service unavailable",
            "overloaded",
        ])

    @staticmethod
    def _is_connection_error(error: Exception) -> bool:
        error_str = str(error)
        if isinstance(error, TypeError) and "'<=' not supported" in error_str and "NoneType" in error_str:
            return True
        error_class = type(error).__name__
        if any(marker in error_class for marker in ("ConnectError", "ConnectTimeout", "ReadTimeout", "ReadError", "TimeoutException", "NetworkError")):
            return True
        return isinstance(error, (ConnectionError, TimeoutError, OSError))


    @staticmethod
    def _is_invalid_key_error(error_str: str) -> bool:
        lowered = (error_str or "").lower()
        strict_invalid_markers = [
            "api_key_invalid",
            "api key invalid",
            "invalid api key",
            "invalid_api_key",
            "api key not found",
            "key not found",
            "invalid argument: api key",
            "provided api key is invalid",
            "authenticationerror",
            "authentication error",
            "error code: 401",
            "401",
            "unauthorized",
            "malformed lm studio api token",
            "lm studio api token",
            "incorrect api key",
            "invalid api_key",
        ]
        return any(token in lowered for token in strict_invalid_markers)

    # --- Client pool ---

    def _get_or_create_gemini_client(
        self,
        api_key: str,
    ):
        base_url = getattr(self.config, "GEMINI_BASE_URL", "") or ""
        if time.time() < getattr(self, "router_bypass_until", 0.0):
            base_url = ""

        cache_key = ("gemini", base_url, api_key)

        with self._gemini_clients_lock:
            existing = self._gemini_clients.get(cache_key)
            if existing is not None:
                return existing

            if base_url:
                router_key = getattr(self.config, "ROUTER_AUTH_KEY", "")
                if not router_key:
                    # ROUTER_AUTH_KEY rỗng → không gửi Google Key lên Router,
                    # quay về xoay vòng key cơ bản qua Google trực tiếp
                    client = genai.Client(api_key=api_key)
                else:
                    headers = {"Authorization": f"Bearer {router_key}"}
                    client = genai.Client(
                        api_key=router_key,
                        http_options=genai_types.HttpOptions(
                            base_url=base_url,
                            headers=headers,
                            timeout=self.config.GEMINI_TIMEOUT_MS
                        ),
                    )
            else:
                client = genai.Client(api_key=api_key)
            self._gemini_clients[cache_key] = client
            return client

    @staticmethod
    def _extract_errno(error: Exception) -> Optional[int]:
        candidates = [error, getattr(error, "__cause__", None), getattr(error, "__context__", None)]
        for candidate in candidates:
            if candidate is None:
                continue
            errno_value = getattr(candidate, "errno", None)
            if isinstance(errno_value, int):
                return errno_value
        return None

    def _log_gemini_exception(
        self,
        *,
        stage: str,
        error: Exception,
        user_id: Optional[str] = None,
        model_alias: Optional[str] = None,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
        attempt: Optional[int] = None,
        max_attempts: Optional[int] = None,
    ) -> None:
        key_alias = f"...{api_key[-4:]}" if api_key else "<none>"
        errno_value = self._extract_errno(error)
        attempt_label = ""
        if attempt is not None and max_attempts is not None:
            attempt_label = f" attempt={attempt}/{max_attempts}"

        self.logger.error(
            f"[{stage}] exception{attempt_label} user={user_id or '<unknown>'} "
            f"model_alias={model_alias or '<unknown>'} model_name={model_name or '<unknown>'} "
            f"key={key_alias} errno={errno_value} error={type(error).__name__}: {error}"
        )
        self.logger.error(traceback.format_exc())

    async def _close_client(self, client: Any) -> None:
        close_method = getattr(client, "close", None)
        if not close_method:
            return
        result = close_method()
        if asyncio.iscoroutine(result):
            await result

    async def close_gemini_clients(self) -> None:
        clients_to_close: List[Any] = []
        with self._gemini_clients_lock:
            for client in self._gemini_clients.values():
                clients_to_close.append(client)
            self._gemini_clients.clear()

        for client in clients_to_close:
            try:
                await self._close_client(client)
            except Exception as close_error:
                self.logger.warning(f"Gemini client close warning: {close_error}")

    async def clear_custom_api_clients(self) -> None:
        clients_to_close: List[Any] = []
        with self._gemini_clients_lock:
            custom_keys = [
                cache_key for cache_key in self._gemini_clients
                if isinstance(cache_key, tuple) and cache_key and cache_key[0] == "openai"
            ]
            for cache_key in custom_keys:
                clients_to_close.append(self._gemini_clients.pop(cache_key))

        for client in clients_to_close:
            try:
                await self._close_client(client)
            except Exception as close_error:
                self.logger.warning(f"Custom API client close warning: {close_error}")

    # --- Throttling ---

    async def _throttle_api_request(self, api_key: str) -> None:
        async with self.API_REQUEST_SEMAPHORE:
            current_time = time.time()
            time_since_last = current_time - self.LAST_API_REQUEST_TIME

            if time_since_last < self.MIN_REQUEST_INTERVAL:
                sleep_duration = self.MIN_REQUEST_INTERVAL - time_since_last
                await asyncio.sleep(sleep_duration)

            self.LAST_API_REQUEST_TIME = time.time()

            with self.api_key_history_lock:
                now = time.time()
                if api_key not in self.api_key_request_history:
                    self.api_key_request_history[api_key] = []

                self.api_key_request_history[api_key].append(now)

                self.api_key_request_history[api_key] = [
                    ts for ts in self.api_key_request_history[api_key]
                    if now - ts < self.COOLDOWN_WINDOW
                ]

                if len(self.api_key_request_history[api_key]) > self.MAX_REQUESTS_PER_WINDOW:
                    self.logger.debug(
                        f"Key ...{api_key[-4:]} usage high: {len(self.api_key_request_history[api_key])}/{self.MAX_REQUESTS_PER_WINDOW} in 30m."
                    )

    # --- Prompt helpers ---

    @staticmethod
    def _flatten_prompt_text(messages: List[Dict[str, Any]]) -> str:
        chunks: List[str] = []
        for msg in messages:
            parts = msg.get("parts", [])
            for part in parts:
                text = part.get("text") if isinstance(part, dict) else None
                if text:
                    chunks.append(text)
        return "\n".join(chunks)

    async def _acquire_gemini_quota(
        self,
        messages: List[Dict[str, Any]],
        max_output_tokens: int,
        model_alias: Optional[str] = None,
        extra_text: str = "",
    ) -> bool:
        prompt_text = self._flatten_prompt_text(messages)
        if extra_text:
            prompt_text = f"{extra_text}\n{prompt_text}" if prompt_text else extra_text
        target_model = model_alias or self.api_router.get_preferred_model()
        return await self.api_router.acquire_gemini_quota(prompt_text, max_output_tokens, target_model)

    async def _generate_gemini_content(
        self,
        api_key: str,
        model_name: str,
        system_instruction: str,
        generation_config: Dict[str, Any],
        messages: List[Dict[str, Any]],
        tools: Optional[List[Any]] = None,
    ):
        if time.time() < getattr(self, "router_bypass_until", 0.0):
            model_name = "gemini-flash-lite-latest"

        request_config = dict(generation_config)
        request_config["system_instruction"] = system_instruction
        request_config["safety_settings"] = self.config.SAFETY_SETTINGS
        if tools:
            request_config["tools"] = tools

        client = self._get_or_create_gemini_client(api_key)

        sdk_contents = []
        for msg in messages:
            if not isinstance(msg, dict):
                sdk_contents.append(msg)
                continue

            role = msg.get("role")
            parts = msg.get("parts", [])
            sdk_parts = []

            for part in parts:
                if isinstance(part, dict):
                    thought = part.get("thought")
                    thought_sig = part.get("thought_signature") or part.get("thoughtSignature")
                    if isinstance(thought_sig, str):
                        try:
                            thought_sig = base64.b64decode(thought_sig)
                        except Exception:
                            thought_sig = thought_sig.encode("utf-8")

                    part_kwargs = {}
                    if thought is not None:
                        part_kwargs["thought"] = thought
                    if thought_sig is not None:
                        part_kwargs["thought_signature"] = thought_sig

                    if "text" in part:
                        part_kwargs["text"] = part["text"]
                        sdk_parts.append(genai_types.Part(**part_kwargs))
                    elif "inline_data" in part:
                        inline = part["inline_data"]
                        part_kwargs["inline_data"] = genai_types.Blob(
                            data=inline["data"],
                            mime_type=inline["mime_type"]
                        )
                        sdk_parts.append(genai_types.Part(**part_kwargs))
                    elif "function_response" in part:
                        fr = part["function_response"]
                        part_kwargs["function_response"] = genai_types.FunctionResponse(
                            name=fr.get("name"),
                            response=fr.get("response", {})
                        )
                        sdk_parts.append(genai_types.Part(**part_kwargs))
                    elif "function_call" in part:
                        fc = part["function_call"]
                        part_kwargs["function_call"] = genai_types.FunctionCall(
                            name=fc.get("name"),
                            args=fc.get("args")
                        )
                        sdk_parts.append(genai_types.Part(**part_kwargs))
                    elif thought is not None or thought_sig is not None:
                        sdk_parts.append(genai_types.Part(**part_kwargs))
                    else:
                        sdk_parts.append(part)
                else:
                    sdk_parts.append(part)

            sdk_contents.append(genai_types.Content(role=role, parts=sdk_parts))

        return await asyncio.to_thread(
            client.models.generate_content,
            model=model_name,
            contents=sdk_contents,
            config=request_config,
        )

    async def _generate_gemini_content_stream(
        self,
        api_key: str,
        model_name: str,
        system_instruction: str,
        generation_config: Dict[str, Any],
        messages: List[Dict[str, Any]],
        tools: Optional[List[Any]] = None,
    ):
        if time.time() < getattr(self, "router_bypass_until", 0.0):
            model_name = "gemini-flash-lite-latest"

        request_config = dict(generation_config)
        request_config["system_instruction"] = system_instruction
        request_config["safety_settings"] = self.config.SAFETY_SETTINGS
        if tools:
            request_config["tools"] = tools

        client = self._get_or_create_gemini_client(api_key)

        sdk_contents = []
        for msg in messages:
            if not isinstance(msg, dict):
                sdk_contents.append(msg)
                continue

            role = msg.get("role")
            parts = msg.get("parts", [])
            sdk_parts = []

            for part in parts:
                if isinstance(part, dict):
                    thought = part.get("thought")
                    thought_sig = part.get("thought_signature") or part.get("thoughtSignature")
                    if isinstance(thought_sig, str):
                        try:
                            thought_sig = base64.b64decode(thought_sig)
                        except Exception:
                            thought_sig = thought_sig.encode("utf-8")

                    part_kwargs = {}
                    if thought is not None:
                        part_kwargs["thought"] = thought
                    if thought_sig is not None:
                        part_kwargs["thought_signature"] = thought_sig

                    if "text" in part:
                        part_kwargs["text"] = part["text"]
                        sdk_parts.append(genai_types.Part(**part_kwargs))
                    elif "inline_data" in part:
                        inline = part["inline_data"]
                        part_kwargs["inline_data"] = genai_types.Blob(
                            data=inline["data"],
                            mime_type=inline["mime_type"]
                        )
                        sdk_parts.append(genai_types.Part(**part_kwargs))
                    elif "function_response" in part:
                        fr = part["function_response"]
                        part_kwargs["function_response"] = genai_types.FunctionResponse(
                            name=fr.get("name"),
                            response=fr.get("response", {})
                        )
                        sdk_parts.append(genai_types.Part(**part_kwargs))
                    elif "function_call" in part:
                        fc = part["function_call"]
                        part_kwargs["function_call"] = genai_types.FunctionCall(
                            name=fc.get("name"),
                            args=fc.get("args")
                        )
                        sdk_parts.append(genai_types.Part(**part_kwargs))
                    elif thought is not None or thought_sig is not None:
                        sdk_parts.append(genai_types.Part(**part_kwargs))
                    else:
                        sdk_parts.append(part)
                else:
                    sdk_parts.append(part)

            sdk_contents.append(genai_types.Content(role=role, parts=sdk_parts))

        stream = await asyncio.to_thread(
            client.models.generate_content_stream,
            model=model_name,
            contents=sdk_contents,
            config=request_config,
        )
        for chunk in stream:
            yield chunk


    async def call_gemini_direct(self, prompt: str) -> str:
        """Simple direct call for background services (like health check) without pipeline overhead."""
        messages = [{"role": "user", "parts": [{"text": prompt}]}]
        model_alias = "gemini-flash-lite"
        max_output_tokens = 1000
        
        for attempt in range(3):
            api_key, model_id, final_alias, reservation = await self._get_best_api_key(model_alias)
            
            if not api_key or not model_id:
                self.logger.error("call_gemini_direct: No API key available.")
                return "Error calling LLM."
                
            try:
                await self._throttle_api_request(api_key)
                
                has_quota = await self._acquire_gemini_quota(
                    messages=messages, 
                    max_output_tokens=max_output_tokens, 
                    model_alias=final_alias
                )
                
                if not has_quota:
                    self._mark_key_as_failed(api_key, final_alias, reason="rate_limit", reservation=reservation)
                    continue

                generation_config = {
                    "temperature": 0.7,
                    "max_output_tokens": max_output_tokens
                }

                response = await self._generate_gemini_content(
                    api_key=api_key,
                    model_name=model_id,
                    system_instruction="You are a helpful assistant.",
                    generation_config=generation_config,
                    messages=messages,
                    tools=None,
                )
                
                self._commit_selected_key(reservation)
                return response.text if response else "Error calling LLM."
                
            except Exception as e:
                error_str = str(e)
                if self._is_invalid_key_error(error_str):
                    self._mark_key_as_failed(api_key, final_alias, reason="invalid_key", reservation=reservation, permanently_exhaust=True)
                elif self._is_rate_limit_error(error_str):
                    self._mark_key_as_failed(api_key, final_alias, reason="rate_limit", reservation=reservation)
                elif self._is_unavailable_error(error_str):
                    self._mark_key_as_failed(api_key, final_alias, reason="unavailable", reservation=reservation, duration=5)
                elif self._is_connection_error(e):
                    self._mark_key_as_failed(api_key, final_alias, reason="endpoint_down", reservation=reservation, duration=120)
                else:
                    self.logger.error(f"call_gemini_direct failed on attempt {attempt}: {e}")
                    
        return "Error calling LLM."
