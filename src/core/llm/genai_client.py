"""Adapter cho google-genai SDK. Nhận/trả định dạng canonical kiểu genai."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types as genai_types

from src.core.llm.base import LLMError, LLMResponse, classify_error

DEFAULT_GENAI_BASE_URL = "https://generativelanguage.googleapis.com"


def _strip_nulls(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


def messages_to_genai_contents(system_instruction: Optional[str], messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    contents: List[Dict[str, Any]] = []
    if system_instruction:
        contents.append({"role": "user", "parts": [{"text": system_instruction}]})

    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "user")
        if role not in ("user", "model"):
            role = "user"

        parts_out: List[Dict[str, Any]] = []
        for part in msg.get("parts", []) or []:
            if not isinstance(part, dict):
                # Object kiểu genai Part (model trả về) — trích các trường cần thiết
                text = getattr(part, "text", None)
                fc = getattr(part, "function_call", None)
                inline = getattr(part, "inline_data", None)
                if text is not None:
                    parts_out.append({"text": text})
                elif fc is not None:
                    parts_out.append({
                        "function_call": {
                            "name": getattr(fc, "name", ""),
                            "args": dict(getattr(fc, "args", {}) or {}),
                        }
                    })
                elif inline is not None:
                    parts_out.append({"inline_data": dict(inline)})
                continue

            if part.get("text") is not None:
                parts_out.append({"text": part["text"]})
            elif part.get("inline_data"):
                inline = part["inline_data"] or {}
                parts_out.append({
                    "inline_data": _strip_nulls({
                        "data": inline.get("data"),
                        "mime_type": inline.get("mime_type"),
                    })
                })
            elif part.get("function_call"):
                fc = part["function_call"] or {}
                parts_out.append({
                    "function_call": _strip_nulls({
                        "name": fc.get("name"),
                        "args": fc.get("args") or {},
                        "id": fc.get("id"),
                    })
                })
            elif part.get("function_response"):
                fr = part["function_response"] or {}
                response = fr.get("response") or {}
                if isinstance(response, dict) and "content" in response:
                    content = str(response.get("content") or "")
                    response_out = {"content": content}
                else:
                    response_out = response
                parts_out.append({
                    "function_response": _strip_nulls({
                        "name": fr.get("name"),
                        "response": response_out,
                        "id": fr.get("id"),
                    })
                })

        if parts_out:
            contents.append({"role": role, "parts": parts_out})
    return contents


def build_request_config(
    generation_config: Dict[str, Any],
    safety_settings: Any,
    tools: Optional[List[Any]],
) -> Dict[str, Any]:
    request_config: Dict[str, Any] = dict(generation_config or {})
    if safety_settings:
        request_config["safety_settings"] = safety_settings
    if tools:
        request_config["tools"] = tools
    return request_config


class GenAIClient:
    sdk = "genai"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        logger: Any,
        timeout_ms: Optional[int] = None,
        safety_settings: Any = None,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.logger = logger
        self.safety_settings = safety_settings
        self.timeout_ms = timeout_ms

        http_kwargs: Dict[str, Any] = {}
        if self.base_url and self.base_url != DEFAULT_GENAI_BASE_URL:
            http_kwargs["base_url"] = self.base_url
            http_kwargs["headers"] = {"Authorization": f"Bearer {api_key}"}
        if timeout_ms:
            http_kwargs["timeout"] = int(timeout_ms)

        http_options = genai_types.HttpOptions(**http_kwargs) if http_kwargs else None
        self._client = genai.Client(api_key=api_key, http_options=http_options)

    @property
    def raw_client(self):
        return self._client

    async def generate(
        self,
        *,
        model_id: str,
        system_instruction: str,
        generation_config: Dict[str, Any],
        messages: List[Dict[str, Any]],
        tools: Optional[List[Any]] = None,
    ) -> LLMResponse:
        contents = messages_to_genai_contents(system_instruction, messages)
        config_dict = build_request_config(generation_config, self.safety_settings, tools)
        config = genai_types.GenerateContentConfig(**config_dict)
        try:
            response = await asyncio.to_thread(
                self._client.models.generate_content,
                model=model_id,
                contents=contents,
                config=config,
            )
        except Exception as e:
            raise LLMError(classify_error(e), str(e), raw=e) from e
        return LLMResponse(candidates=list(response.candidates or []), raw=response)

    async def list_models(self) -> List[Dict[str, str]]:
        def _list() -> List[Dict[str, str]]:
            out: List[Dict[str, str]] = []
            for model in self._client.models.list():
                name = getattr(model, "name", "") or ""
                model_id = name.split("/", 1)[1] if name.startswith("models/") else name
                if not model_id:
                    continue
                display = getattr(model, "display_name", "") or model_id
                out.append({"id": model_id, "display_name": display})
            return out

        try:
            return await asyncio.to_thread(_list)
        except Exception as e:
            raise LLMError(classify_error(e), str(e), raw=e) from e

    async def close(self) -> None:
        return None
