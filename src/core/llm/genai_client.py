"""Adapter cho google-genai SDK. Nhận/trả định dạng canonical kiểu genai."""
from __future__ import annotations

import asyncio
import base64
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

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
            # Gemini 3 gắn thought_signature vào part (bytes) và yêu cầu gửi
            # lại nguyên vẹn khi echo functionCall trong history.
            # https://ai.google.dev/gemini-api/docs/thought-signatures
            if not isinstance(part, dict):
                # Object kiểu genai Part (model trả về) — trích các trường cần thiết
                text = getattr(part, "text", None)
                fc = getattr(part, "function_call", None)
                inline = getattr(part, "inline_data", None)
                signature = getattr(part, "thought_signature", None)
                if text is not None:
                    entry: Dict[str, Any] = {"text": text}
                    if signature is not None:
                        entry["thought_signature"] = signature
                    parts_out.append(entry)
                elif fc is not None:
                    entry = {
                        "function_call": {
                            "name": getattr(fc, "name", ""),
                            "args": dict(getattr(fc, "args", {}) or {}),
                        }
                    }
                    if signature is not None:
                        entry["thought_signature"] = signature
                    parts_out.append(entry)
                elif inline is not None:
                    parts_out.append({"inline_data": dict(inline)})
                continue

            signature = part.get("thought_signature") or part.get("thoughtSignature")
            if part.get("text") is not None:
                entry = {"text": part["text"]}
                if signature is not None:
                    entry["thought_signature"] = signature
                parts_out.append(entry)
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
                entry = {
                    "function_call": _strip_nulls({
                        "name": fc.get("name"),
                        "args": fc.get("args") or {},
                        "id": fc.get("id"),
                    })
                }
                if signature is not None:
                    entry["thought_signature"] = signature
                parts_out.append(entry)
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


def _bytes_to_standard_base64(data: Any) -> str:
    """Encode image bytes with the standard alphabet expected by router_api."""
    if isinstance(data, bytes):
        return base64.b64encode(data).decode("ascii")
    if isinstance(data, bytearray):
        return base64.b64encode(bytes(data)).decode("ascii")
    value = str(data or "")
    if value.startswith("data:") and ";base64," in value:
        value = value.split(";base64,", 1)[1]
    padding = "=" * (-len(value) % 4)
    try:
        decoded = base64.urlsafe_b64decode(value + padding)
    except Exception:
        return value
    return base64.b64encode(decoded).decode("ascii")


def _contents_to_router_wire(contents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    wire_contents: List[Dict[str, Any]] = []
    for content in contents:
        wire_parts: List[Dict[str, Any]] = []
        for part in content.get("parts", []) or []:
            if part.get("text") is not None:
                wire_parts.append({"text": part["text"]})
            elif part.get("inline_data"):
                inline = part["inline_data"] or {}
                wire_part = {
                    "inlineData": {
                        "data": _bytes_to_standard_base64(inline.get("data")),
                        "mimeType": inline.get("mime_type") or "application/octet-stream",
                    }
                }
                if part.get("thought_signature") is not None:
                    wire_part["thoughtSignature"] = _bytes_to_standard_base64(part["thought_signature"])
                wire_parts.append(wire_part)
            elif part.get("function_call"):
                call = part["function_call"] or {}
                wire_parts.append({
                    "functionCall": {
                        "name": call.get("name") or "",
                        "args": call.get("args") or {},
                    }
                })
            elif part.get("function_response"):
                response = part["function_response"] or {}
                wire_parts.append({
                    "functionResponse": {
                        "name": response.get("name") or "",
                        "response": response.get("response") or {},
                    }
                })
        if wire_parts:
            wire_contents.append({"role": content.get("role", "user"), "parts": wire_parts})
    return wire_contents


def _tools_to_router_wire(tools: Optional[List[Any]]) -> Optional[List[Dict[str, Any]]]:
    if not tools:
        return None
    result: List[Dict[str, Any]] = []
    for tool in tools:
        if hasattr(tool, "model_dump"):
            result.append(tool.model_dump(by_alias=True, exclude_none=True))
        elif isinstance(tool, dict):
            result.append(tool)
    return result or None


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
    def _uses_custom_endpoint(self) -> bool:
        return bool(self.base_url and self.base_url != DEFAULT_GENAI_BASE_URL)

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
        if self._uses_custom_endpoint:
            return await self._generate_custom_endpoint(
                model_id=model_id,
                system_instruction=system_instruction,
                generation_config=generation_config,
                messages=messages,
                tools=tools,
            )

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

    async def _generate_custom_endpoint(
        self,
        *,
        model_id: str,
        system_instruction: str,
        generation_config: Dict[str, Any],
        messages: List[Dict[str, Any]],
        tools: Optional[List[Any]],
    ) -> LLMResponse:
        contents = messages_to_genai_contents(None, messages)
        request_body: Dict[str, Any] = {
            "contents": _contents_to_router_wire(contents),
            "generationConfig": {
                "temperature": generation_config.get("temperature"),
                "topP": generation_config.get("top_p"),
                "topK": generation_config.get("top_k"),
                "maxOutputTokens": generation_config.get("max_output_tokens"),
            },
        }
        request_body["generationConfig"] = {
            key: value for key, value in request_body["generationConfig"].items()
            if value is not None
        }
        if system_instruction:
            request_body["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        wire_tools = _tools_to_router_wire(tools)
        if wire_tools:
            request_body["tools"] = wire_tools

        url = f"{self.base_url}/v1beta/models/{quote(model_id, safe='')}:generateContent"
        timeout_s = (self.timeout_ms / 1000.0) if self.timeout_ms else None
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.post(url, headers=headers, json=request_body)
            if response.is_error:
                detail = response.text[:800]
                raise RuntimeError(f"GenAI endpoint HTTP {response.status_code}: {detail}")
            payload = response.json()
            parsed = genai_types.GenerateContentResponse.model_validate(payload)
        except Exception as e:
            raise LLMError(classify_error(e), str(e), raw=e) from e
        return LLMResponse(candidates=list(parsed.candidates or []), raw=parsed)

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
