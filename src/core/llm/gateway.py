"""LLMGateway — façade thay thế cơ chế quản lý API key cũ (đã xóa).

Không quản lý key rotation/quota (router_api bên ngoài lo phần đó).
- generate(): resolve slot theo role; lỗi transient (role != "fallback") thử thêm 1 lần
  bằng slot fallback CÙNG provider; lỗi auth raise ngay; không tự đổi SDK active.
- Vòng retry tổng thể nằm ở pipeline (giữ nguyên cấu trúc cũ).
"""
from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional, Tuple

from src.core.config import get_config, logger
from src.core.llm.base import (
    LLMError,
    LLMNotConfiguredError,
    LLMResponse,
    LLMUnsupportedError,
    classify_error,
    is_connection_error,
    is_invalid_key_error,
    is_rate_limit_error,
    is_unavailable_error,
)
from src.core.llm.genai_client import GenAIClient
from src.core.llm.openai_client import OpenAIClient
from src.core.llm.resolver import EndpointResolver, get_endpoint_resolver


def _extract_text(response: LLMResponse) -> str:
    for candidate in response.candidates:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            text = getattr(part, "text", None)
            if text:
                return str(text)
    return ""


class LLMGateway:
    def __init__(self, *, resolver: EndpointResolver, logger: Any, config: Any = None, client_factory=None):
        self._resolver = resolver
        self.logger = logger
        self.config = config or get_config()
        self._clients: Dict[Tuple[str, str, str], Any] = {}
        self._lock = threading.Lock()
        self._client_factory = client_factory or self._default_client_factory

    def _default_client_factory(self, sdk: str, base_url: str, api_key: str):
        if sdk == "genai":
            return GenAIClient(
                base_url=base_url,
                api_key=api_key,
                logger=self.logger,
                timeout_ms=getattr(self.config, "GEMINI_TIMEOUT_MS", None),
                safety_settings=getattr(self.config, "SAFETY_SETTINGS", None),
            )
        if sdk == "openai":
            timeout_ms = getattr(self.config, "GEMINI_TIMEOUT_MS", None)
            timeout_s = (float(timeout_ms) / 1000.0) if timeout_ms else None
            return OpenAIClient(base_url=base_url, api_key=api_key, logger=self.logger, timeout_s=timeout_s)
        raise LLMUnsupportedError(f"SDK không hỗ trợ: {sdk}")

    async def _get_client(self, sdk: str):
        ep = await self._resolver.get_endpoint(sdk)
        if not ep:
            raise LLMNotConfiguredError(f"SDK `{sdk}` chưa được cấu hình.")
        cache_key = (sdk, ep["base_url"], ep["api_key"])
        with self._lock:
            client = self._clients.get(cache_key)
        if client is None:
            client = self._client_factory(sdk, ep["base_url"], ep["api_key"])
            with self._lock:
                self._clients[cache_key] = client
        return client

    async def generate(
        self,
        *,
        role: str,
        system_instruction: str,
        generation_config: Dict[str, Any],
        messages: List[Dict[str, Any]],
        tools: Optional[List[Any]] = None,
    ) -> LLMResponse:
        primary = await self._resolver.resolve_role(role)
        if primary is None:
            raise LLMNotConfiguredError()

        attempts = [primary]
        if role != "fallback":
            fb = await self._resolver.resolve_role("fallback")
            if fb is not None and fb.model_id != primary.model_id:
                attempts.append(fb)

        last_error: Optional[LLMError] = None
        for idx, slot_model in enumerate(attempts):
            client = await self._get_client(slot_model.sdk)
            try:
                return await client.generate(
                    model_id=slot_model.model_id,
                    system_instruction=system_instruction,
                    generation_config=generation_config,
                    messages=messages,
                    tools=tools,
                )
            except Exception as e:
                err = e if isinstance(e, LLMError) else LLMError(classify_error(e), str(e), raw=e)
                last_error = err
                if err.kind == "auth":
                    raise
                is_last = idx == len(attempts) - 1
                if is_last:
                    self.logger.warning(
                        f"[LLM] {slot_model.sdk}:{slot_model.model_id} (role={slot_model.role}) lỗi {err.kind}: {err}"
                    )
                else:
                    self.logger.warning(
                        f"[LLM] {slot_model.sdk}:{slot_model.model_id} (role={slot_model.role}) lỗi {err.kind}; "
                        f"thử fallback cùng provider: {attempts[-1].model_id}"
                    )
        raise last_error or LLMError("other", "LLM call failed")

    async def list_models_for(self, *, sdk: str, base_url: str, api_key: str) -> List[Dict[str, str]]:
        client = self._client_factory(sdk, base_url or "", api_key)
        try:
            return await client.list_models()
        finally:
            close = getattr(client, "close", None)
            if close is not None:
                try:
                    await close()
                except Exception:
                    pass

    async def generate_text(self, prompt: str, role: str = "final") -> str:
        response = await self.generate(
            role=role,
            system_instruction="",
            generation_config={"temperature": 0.2},
            messages=[{"role": "user", "parts": [{"text": prompt}]}],
        )
        return _extract_text(response)

    async def generate_vision(self, *, image_bytes: bytes, mime_type: str, question: str) -> str:
        response = await self.generate(
            role="vision",
            system_instruction="",
            generation_config={"temperature": 0.2},
            messages=[{
                "role": "user",
                "parts": [
                    {"text": question or "Mô tả nội dung hình ảnh này."},
                    {"inline_data": {"data": image_bytes, "mime_type": mime_type or "image/png"}},
                ],
            }],
        )
        return _extract_text(response)

    async def get_raw_genai_client(self):
        sdk = await self._resolver.get_active_sdk()
        if sdk != "genai":
            raise LLMUnsupportedError("Tính năng chỉ hỗ trợ ở chế độ genAI (endpoint hiện tại dùng OpenAI).")
        client = await self._get_client("genai")
        return client.raw_client

    def log_exception(self, *, stage: str, error: Exception, user_id: str, role: str, attempt: int, max_attempts: int) -> None:
        kind = classify_error(error)
        self.logger.error(
            f"[LLM][{stage}] role={role} kind={kind} attempt={attempt}/{max_attempts} "
            f"user={user_id} error={type(error).__name__}: {str(error)[:300]}"
        )

    @staticmethod
    def _is_invalid_key_error(text: str) -> bool:
        return is_invalid_key_error(text)

    @staticmethod
    def _is_rate_limit_error(text: str) -> bool:
        return is_rate_limit_error(text)

    @staticmethod
    def _is_unavailable_error(text: str) -> bool:
        return is_unavailable_error(text)

    @staticmethod
    def _is_connection_error(error: Exception) -> bool:
        return is_connection_error(error)

    async def close(self) -> None:
        with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for client in clients:
            close = getattr(client, "close", None)
            if close is None:
                continue
            try:
                await close()
            except Exception:
                pass


_gateway_instance: Optional[LLMGateway] = None
_gateway_lock = threading.Lock()


def get_llm_gateway() -> LLMGateway:
    global _gateway_instance
    if _gateway_instance is None:
        with _gateway_lock:
            if _gateway_instance is None:
                _gateway_instance = LLMGateway(resolver=get_endpoint_resolver(), logger=logger)
    return _gateway_instance
