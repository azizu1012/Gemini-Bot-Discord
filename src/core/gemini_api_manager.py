import asyncio
import time
import random
import traceback
import re
import unicodedata
from urllib.parse import urlsplit
import threading
from typing import Any, Optional, Dict, List, Tuple

from google import genai

from src.core.config import logger
from src.core.api_router import get_api_router
from src.core.custom_endpoint import normalize_custom_endpoint

class CustomFunctionCall:
    def __init__(self, name, args, id=None):
        self.name = name
        self.args = args
        self.id = id

class CustomAPIWrapperPart:
    def __init__(self, text=None, function_call=None):
        self.text = text
        self.function_call = function_call

class CustomAPIWrapperContent:
    def __init__(self, parts):
        self.parts = parts

class CustomAPIWrapperCandidate:
    def __init__(self, parts, finish_reason=None):
        self.content = CustomAPIWrapperContent(parts)
        self.finish_reason = finish_reason

class CustomAPIWrapperResponse:
    def __init__(self, parts, finish_reason=None):
        self.candidates = [CustomAPIWrapperCandidate(parts, finish_reason=finish_reason)]
        
    @property
    def text(self):
        if not self.candidates or not self.candidates[0].content.parts:
            return ""
        text_parts = [
            part.text for part in self.candidates[0].content.parts 
            if getattr(part, 'text', None) is not None
        ]
        return "".join(text_parts)


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

    # --- Key selection ---

    async def _get_best_api_key(self, preferred_model_alias: Optional[str] = None) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[Dict[str, Any]]]:
        if preferred_model_alias and not self.api_router.is_custom_model_alias(preferred_model_alias):
            if not self.api_router._allow_provider_request("gemini"):
                self.logger.warning("Gemini circuit breaker OPEN; no gemini key will be reserved.")
                return None, None, None, None
        if preferred_model_alias:
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

            # Prevent custom models from being used with standard Gemini keys during legacy fallback
            if self.api_router.is_custom_model_alias(fallback_alias):
                fallback_alias = "gemini-flash-35"

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

        model = model_alias or self.api_router.get_current_model()
        pool = (reservation or {}).get("pool", "main")
        counter_key = (reservation or {}).get("counter_key")

        if pool != "legacy" and not is_503:
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
        provider: str = "gemini",
        endpoint: Optional[str] = None,
    ):
        provider = str(provider or "gemini").strip().lower()
        if provider == "openai":
            raw_endpoint = str(endpoint or getattr(self.config, "OPENAI_CUSTOM_ENDPOINT", "") or "").strip()
            normalized_endpoint = normalize_custom_endpoint(raw_endpoint)
            cache_key = ("openai", normalized_endpoint, api_key)
        else:
            normalized_endpoint = ""
            cache_key = ("gemini", api_key)

        with self._gemini_clients_lock:
            existing = self._gemini_clients.get(cache_key)
            if existing is not None:
                return existing

            if provider == "openai":
                self.logger.info(f"🔄 Chuyển sang sử dụng custom API (OpenAI endpoint) với key: ...{api_key[-4:]}")
                from openai import AsyncOpenAI

                client = AsyncOpenAI(
                    api_key=api_key,
                    base_url=normalized_endpoint,
                )
                self._gemini_clients[cache_key] = client
                return client

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

    @staticmethod
    def _local_endpoint_port(endpoint_value: str) -> Optional[int]:
        raw_endpoint = str(endpoint_value or "").strip().lower()
        if not raw_endpoint:
            return None
        try:
            parts = urlsplit(raw_endpoint)
        except Exception:
            return None
        host = (parts.hostname or "").lower()
        if host not in {"127.0.0.1", "localhost", "0.0.0.0", "::1"}:
            return None
        return parts.port

    @classmethod
    def _is_lm_studio_endpoint(cls, provider: str, endpoint: Optional[str], endpoint_preset: Optional[str]) -> bool:
        provider_value = str(provider or "gemini").strip().lower()
        endpoint_preset_value = str(endpoint_preset or "").strip().lower()
        return provider_value == "openai" and (
            endpoint_preset_value == "lm_studio" or cls._local_endpoint_port(endpoint or "") == 1234
        )

    @classmethod
    def _is_local_openai_endpoint(cls, provider: str, endpoint: Optional[str], endpoint_preset: Optional[str]) -> bool:
        provider_value = str(provider or "gemini").strip().lower()
        endpoint_preset_value = str(endpoint_preset or "").strip().lower()
        return provider_value == "openai" and (
            endpoint_preset_value in {"lm_studio", "ollama"} or cls._local_endpoint_port(endpoint or "") in {1234, 11434}
        )

    @staticmethod
    def _has_lm_studio_correction_signal(text: str) -> bool:
        lowered = str(text or "").lower()
        no_diacritics = "".join(
            ch for ch in unicodedata.normalize("NFD", lowered)
            if unicodedata.category(ch) != "Mn"
        )
        normalized = re.sub(r"[^a-z0-9\s=]", " ", no_diacritics)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        markers = (
            "latest user correction",
            "lm studio user correction",
            "bia",
            "sai roi",
            "khong phai",
            "khong dung",
            "nham",
            "y toi la",
            "dinh chinh",
            "wrong",
            "correction",
        )
        if any(marker in normalized for marker in markers):
            return True
        return bool(re.search(r"\b[a-z0-9]{2,12}\s+la\s+.+\bma\b", normalized))

    @staticmethod
    def _lm_studio_correction_guard() -> str:
        return (
            "[LM STUDIO LOCAL CORRECTION GUARD]\n"
            "Tin nhắn user mới nhất có dấu hiệu sửa lỗi hoặc phủ định. "
            "Ưu tiên correction mới nhất hơn lịch sử/assistant cũ. "
            "Không lặp lại fact đã bị user bác bỏ; nếu không chắc, nói không chắc hoặc hỏi lại."
        )

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
        provider: str = "gemini",
        endpoint: Optional[str] = None,
        endpoint_preset: Optional[str] = None,
    ):
        request_config = dict(generation_config)
        request_config["system_instruction"] = system_instruction
        request_config["safety_settings"] = self.config.SAFETY_SETTINGS
        if tools:
            request_config["tools"] = tools

        client = self._get_or_create_gemini_client(api_key, provider=provider, endpoint=endpoint)

        if type(client).__name__ == "AsyncOpenAI":
            # Map Gemini format to OpenAI format
            openai_messages = [{"role": "system", "content": system_instruction}]

            for msg in messages:
                if isinstance(msg, dict):
                    gemini_role = msg.get("role")
                    if gemini_role == "model":
                        role = "assistant"
                    elif gemini_role == "function":
                        role = "tool"
                    else:
                        role = "user"
                        
                    parts = msg.get("parts", [])
                    
                    if role == "tool":
                        # Map function_response parts to OpenAI tool responses
                        for part in parts:
                            if isinstance(part, dict) and "function_response" in part:
                                func_res = part["function_response"]
                                tool_msg = {
                                    "role": "tool",
                                    "name": func_res.get("name", ""),
                                    "content": str(func_res.get("response", {}).get("content", ""))
                                }
                                if "id" in func_res:
                                    tool_msg["tool_call_id"] = func_res["id"]
                                openai_messages.append(tool_msg)
                        continue # Tool parts handled
                        
                    # Standard user/assistant message mapping
                    has_images = any(isinstance(p, dict) and "inline_data" in p for p in parts)
                    if has_images and role == "user":
                        import base64
                        content_list = []
                        for part in parts:
                            if isinstance(part, dict):
                                if "text" in part:
                                    content_list.append({"type": "text", "text": part["text"]})
                                elif "inline_data" in part:
                                    inline = part["inline_data"]
                                    base64_str = base64.b64encode(inline["data"]).decode("utf-8")
                                    content_list.append({
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:{inline['mime_type']};base64,{base64_str}"
                                        }
                                    })
                        openai_messages.append({"role": role, "content": content_list})
                    else:
                        if parts and isinstance(parts[0], dict) and "text" in parts[0]:
                            content = parts[0]["text"]
                        elif parts and isinstance(parts[0], str):
                            content = parts[0]
                        else:
                            content = str(parts)
                        openai_messages.append({"role": role, "content": content})
                else:
                    openai_messages.append({"role": "user", "content": str(msg)})

            is_lm_studio_endpoint = self._is_lm_studio_endpoint(provider, endpoint, endpoint_preset)
            is_local_endpoint = self._is_local_openai_endpoint(provider, endpoint, endpoint_preset)
            if is_local_endpoint:
                flattened = self._flatten_prompt_text(messages)
                combined = f"{system_instruction}\n\n{flattened}" if flattened else system_instruction
                combined = (combined or "").strip() or "Tiếp tục."
                if is_lm_studio_endpoint and self._has_lm_studio_correction_signal(combined):
                    combined = f"{self._lm_studio_correction_guard()}\n\n{combined}"
                if is_lm_studio_endpoint and tools:
                    combined += (
                        "\n\n[CẦU NỐI TOOL CHO LM STUDIO]\n"
                        "Không dùng native OpenAI tools trong request LM Studio này. "
                        "Nếu cần công cụ, chỉ trả về đúng một dòng theo mẫu `TOOL_CALL: tên_tool(tham_số=\"giá trị\")` và không thêm chữ khác.\n"
                        "Mẫu hợp lệ: `TOOL_CALL: web_search(query=\"từ khóa cần tìm\")`, "
                        "`TOOL_CALL: get_weather(city=\"Hanoi\")`, "
                        "`TOOL_CALL: calculate(equation=\"2+2\")`, "
                        "`TOOL_CALL: retrieve_notes(query=\"chủ đề\")`, "
                        "`TOOL_CALL: save_note(note_content=\"nội dung\", source=\"chat_inference\")`, "
                        "`TOOL_CALL: delete_note(note_id=\"id\")`, "
                        "`TOOL_CALL: image_recognition(image_url=\"url\", question=\"câu hỏi\")`.\n"
                        "Khi đã có kết quả công cụ trong hội thoại, hãy dùng kết quả đó để kết luận và không gọi lại cùng công cụ nếu không cần."
                    )
                openai_messages = [{"role": "user", "content": combined}]
            else:
                non_system_msgs = [m for m in openai_messages if m.get("role") != "system"]
                has_user_msg = any(
                    m.get("role") == "user" and m.get("content") not in (None, "", [])
                    for m in non_system_msgs
                )
                last_role = non_system_msgs[-1].get("role") if non_system_msgs else "system"
                if not has_user_msg or last_role == "tool":
                    openai_messages.append({"role": "user", "content": "Tiếp tục."})

            # Map Gemini tools to OpenAI tools
            openai_tools = None
            if tools:
                openai_tools = []
                for t in tools:
                    for decl in getattr(t, "function_declarations", []):
                        def map_schema(schema):
                            if not schema: return {}
                            res = {"type": getattr(schema, "type", "object").lower()}
                            if res["type"] == "type_unspecified" or not res["type"]: res["type"] = "object"
                            if hasattr(schema, "type") and hasattr(schema.type, "name"):
                                res["type"] = schema.type.name.lower()
                                if res["type"] in ["double", "number"]: res["type"] = "number"
                            if hasattr(schema, "description") and schema.description: res["description"] = schema.description
                            if hasattr(schema, "properties") and schema.properties:
                                res["properties"] = {k: map_schema(v) for k, v in schema.properties.items()}
                            if hasattr(schema, "required") and schema.required: res["required"] = schema.required
                            if hasattr(schema, "items") and schema.items: res["items"] = map_schema(schema.items)
                            if hasattr(schema, "enum") and schema.enum: res["enum"] = schema.enum
                            return res

                        tool = {
                            "type": "function",
                            "function": {
                                "name": decl.name,
                                "description": getattr(decl, "description", ""),
                                "parameters": map_schema(getattr(decl, "parameters", None))
                            }
                        }
                        openai_tools.append(tool)

            # Make OpenAI call natively async
            create_kwargs = {
                "model": model_name,
                "messages": openai_messages,
                "temperature": generation_config.get("temperature", 0.7),
                "max_tokens": generation_config.get("max_output_tokens", 2000),
                "top_p": generation_config.get("top_p", 0.95),
            }
            if openai_tools and not is_lm_studio_endpoint:
                create_kwargs["tools"] = openai_tools

            response = await client.chat.completions.create(**create_kwargs)
            
            choice = response.choices[0]
            msg = choice.message
            finish_reason = getattr(choice, "finish_reason", None)
            parts = []

            if msg.content:
                parts.append(CustomAPIWrapperPart(text=msg.content))

            import json
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc.type == "function":
                        args_dict = {}
                        try:
                            args_dict = json.loads(tc.function.arguments)
                        except Exception as e:
                            self.logger.error(f"OpenAI Wrapper: Failed to parse JSON args for tool {tc.function.name}: {e}")
                            args_dict = {
                                "_parsing_error": str(e),
                                "_raw_arguments": getattr(tc.function, 'arguments', '')
                            }
                        
                        func_call = CustomFunctionCall(tc.function.name, args_dict, id=getattr(tc, 'id', None))
                        parts.append(CustomAPIWrapperPart(function_call=func_call))
            
            if not parts:
                parts.append(CustomAPIWrapperPart(text=""))

            return CustomAPIWrapperResponse(parts=parts, finish_reason=finish_reason)
            
        else:
            from google.genai import types

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
                        if "text" in part:
                            sdk_parts.append(types.Part.from_text(text=part["text"]))
                        elif "inline_data" in part:
                            inline = part["inline_data"]
                            sdk_parts.append(types.Part.from_bytes(
                                data=inline["data"],
                                mime_type=inline["mime_type"]
                            ))
                        elif "function_response" in part:
                            fr = part["function_response"]
                            sdk_parts.append(types.Part(
                                function_response=types.FunctionResponse(
                                    name=fr.get("name"),
                                    response=fr.get("response", {})
                                )
                            ))
                        elif "function_call" in part:
                            fc = part["function_call"]
                            sdk_parts.append(types.Part(
                                function_call=types.FunctionCall(
                                    name=fc.get("name"),
                                    args=fc.get("args")
                                )
                            ))
                        else:
                            sdk_parts.append(part)
                    else:
                        sdk_parts.append(part)

                sdk_contents.append(types.Content(role=role, parts=sdk_parts))

            return await asyncio.to_thread(
                client.models.generate_content,
                model=model_name,
                contents=sdk_contents,
                config=request_config,
            )


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
                    provider=(reservation or {}).get("provider", "gemini"),
                    endpoint=(reservation or {}).get("endpoint"),
                    endpoint_preset=(reservation or {}).get("endpoint_preset"),
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
                else:
                    self.logger.error(f"call_gemini_direct failed on attempt {attempt}: {e}")
                    
        return "Error calling LLM."
