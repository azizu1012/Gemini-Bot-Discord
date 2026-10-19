"""Adapter cho endpoint OpenAI-compatible.

Dịch 2 chiều giữa định dạng canonical (kiểu genai) và wire format OpenAI:
- messages: {"role","parts"} <-> chat.completions messages (+ tool_calls, image_url data-URL)
- tools: genai FunctionDeclaration <-> OpenAI tools (JSON schema)
- response: completion -> LLMResponse với candidates[0].content.parts canonical
"""
from __future__ import annotations

import base64
import json
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from src.core.llm.base import (
    Candidate,
    Content,
    FinishReason,
    FunctionCall,
    LLMError,
    LLMResponse,
    Part,
    classify_error,
)

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"

_FINISH_MAP = {
    "length": "MAX_TOKENS",
    "max_tokens": "MAX_TOKENS",
    "tool_calls": "STOP",
    "stop": "STOP",
    "content_filter": "SAFETY",
}


def data_url_from_inline(inline: Dict[str, Any]) -> str:
    inline = inline or {}
    data = inline.get("data")
    mime = inline.get("mime_type") or "application/octet-stream"
    if isinstance(data, bytes):
        b64 = base64.b64encode(data).decode("ascii")
    else:
        b64 = str(data or "")
    return f"data:{mime};base64,{b64}"


def part_object_to_dict(part: Any) -> Dict[str, Any]:
    """Object kiểu genai Part -> dict canonical. Trả {} nếu không nhận dạng được."""
    text = getattr(part, "text", None)
    fc = getattr(part, "function_call", None)
    inline = getattr(part, "inline_data", None)
    if text is not None:
        return {"text": text}
    if fc is not None:
        return {
            "function_call": {
                "name": getattr(fc, "name", "") or "",
                "args": dict(getattr(fc, "args", {}) or {}),
                "id": getattr(fc, "id", None),
            }
        }
    if inline is not None:
        return {"inline_data": dict(inline)}
    return {}


def normalize_schema(node: Any) -> Any:
    if isinstance(node, dict):
        out: Dict[str, Any] = {}
        for k, v in node.items():
            if k == "type" and isinstance(v, str):
                out[k] = v.lower()
            else:
                out[k] = normalize_schema(v)
        return out
    if isinstance(node, list):
        return [normalize_schema(v) for v in node]
    value = getattr(node, "value", None)
    if isinstance(value, str):
        return value.lower()
    return node


def to_json_schema(parameters: Any) -> Dict[str, Any]:
    if parameters is None:
        return {"type": "object", "properties": {}}
    if isinstance(parameters, dict):
        return normalize_schema(json.loads(json.dumps(parameters)))
    dump = getattr(parameters, "model_dump", None)
    if callable(dump):
        return normalize_schema(dump(exclude_none=True))
    return {"type": "object", "properties": {}}


def tools_to_openai(tools: Optional[List[Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for tool in tools or []:
        decls = getattr(tool, "function_declarations", None)
        if decls is None and isinstance(tool, dict):
            decls = tool.get("function_declarations")
        for decl in decls or []:
            if isinstance(decl, dict):
                name = decl.get("name")
                desc = decl.get("description") or ""
                params = decl.get("parameters")
            else:
                name = getattr(decl, "name", None)
                desc = getattr(decl, "description", None) or ""
                params = getattr(decl, "parameters", None)
            out.append({
                "type": "function",
                "function": {
                    "name": name or "",
                    "description": desc,
                    "parameters": to_json_schema(params),
                },
            })
    return out


class OpenAIClient:
    sdk = "openai"

    def __init__(self, *, base_url: str, api_key: str, logger: Any, timeout_s: Optional[float] = None):
        self.base_url = (base_url or DEFAULT_OPENAI_BASE_URL).rstrip("/")
        self.api_key = api_key
        self.logger = logger
        kwargs: Dict[str, Any] = {"base_url": self.base_url, "api_key": api_key}
        if timeout_s:
            kwargs["timeout"] = float(timeout_s)
        self._client = AsyncOpenAI(**kwargs)
        self._tool_call_seq = 0

    @property
    def raw_client(self):
        return self._client

    def _next_call_id(self) -> str:
        self._tool_call_seq += 1
        return f"call_{self._tool_call_seq}"

    def convert_messages(self, system_instruction: Optional[str], messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if system_instruction:
            out.append({"role": "system", "content": system_instruction})

        pending_calls_by_name: Dict[str, List[str]] = {}
        for msg in messages or []:
            if not isinstance(msg, dict):
                continue
            role = "assistant" if msg.get("role") == "model" else (msg.get("role") or "user")

            text_chunks: List[str] = []
            images: List[Dict[str, Any]] = []
            tool_calls: List[Dict[str, Any]] = []
            tool_results: List[Dict[str, Any]] = []

            for raw_part in msg.get("parts", []) or []:
                part = raw_part if isinstance(raw_part, dict) else part_object_to_dict(raw_part)
                if not part:
                    continue
                if part.get("text") is not None:
                    text_chunks.append(str(part["text"]))
                elif part.get("inline_data"):
                    images.append({
                        "type": "image_url",
                        "image_url": {"url": data_url_from_inline(part["inline_data"] or {})},
                    })
                elif part.get("function_call"):
                    fc = part["function_call"] or {}
                    call_id = fc.get("id") or self._next_call_id()
                    name = fc.get("name") or ""
                    pending_calls_by_name.setdefault(name, []).append(call_id)
                    tool_calls.append({
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(fc.get("args") or {}, ensure_ascii=False),
                        },
                    })
                elif part.get("function_response"):
                    fr = part["function_response"] or {}
                    name = fr.get("name") or ""
                    response = fr.get("response") or {}
                    content = response.get("content") if isinstance(response, dict) else response
                    call_id = fr.get("id")
                    if not call_id:
                        queue = pending_calls_by_name.get(name) or []
                        call_id = queue.pop(0) if queue else f"call_{name or 'tool'}"
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": "" if content is None else str(content),
                    })

            if tool_results:
                out.extend(tool_results)
                continue
            if tool_calls:
                out.append({
                    "role": "assistant",
                    "content": "\n".join(text_chunks) if text_chunks else None,
                    "tool_calls": tool_calls,
                })
                continue
            if images:
                content_arr: List[Dict[str, Any]] = []
                if text_chunks:
                    content_arr.append({"type": "text", "text": "\n".join(text_chunks)})
                content_arr.extend(images)
                out.append({"role": role, "content": content_arr})
                continue
            if text_chunks:
                out.append({"role": role, "content": "\n".join(text_chunks)})
        return out

    def emulate_response(self, completion: Any) -> LLMResponse:
        choices = getattr(completion, "choices", None) or []
        choice = choices[0] if choices else None
        message = getattr(choice, "message", None)
        parts: List[Part] = []
        if message is not None:
            content_text = getattr(message, "content", None)
            if content_text:
                parts.append(Part(text=str(content_text)))
            for tc in getattr(message, "tool_calls", None) or []:
                fn = getattr(tc, "function", None)
                raw_args = getattr(fn, "arguments", "") if fn is not None else ""
                try:
                    args = json.loads(raw_args or "{}")
                except Exception:
                    args = {"_raw": raw_args}
                if not isinstance(args, dict):
                    args = {"_value": args}
                parts.append(Part(function_call=FunctionCall(
                    name=getattr(fn, "name", "") if fn is not None else "",
                    args=args,
                    id=getattr(tc, "id", None),
                )))
        finish_raw = str(getattr(choice, "finish_reason", "stop") or "stop").lower()
        finish = FinishReason(_FINISH_MAP.get(finish_raw, "STOP"))
        candidate = Candidate(content=Content(parts=parts, role="model"), finish_reason=finish)
        return LLMResponse(candidates=[candidate], raw=completion)

    async def generate(
        self,
        *,
        model_id: str,
        system_instruction: str,
        generation_config: Dict[str, Any],
        messages: List[Dict[str, Any]],
        tools: Optional[List[Any]] = None,
    ) -> LLMResponse:
        generation_config = generation_config or {}
        request: Dict[str, Any] = {
            "model": model_id,
            "messages": self.convert_messages(system_instruction, messages),
        }
        if "temperature" in generation_config:
            request["temperature"] = generation_config["temperature"]
        if "top_p" in generation_config:
            request["top_p"] = generation_config["top_p"]
        max_tokens = generation_config.get("max_output_tokens")
        if max_tokens:
            request["max_tokens"] = int(max_tokens)
        openai_tools = tools_to_openai(tools)
        if openai_tools:
            request["tools"] = openai_tools
        try:
            completion = await self._client.chat.completions.create(**request)
        except Exception as e:
            raise LLMError(classify_error(e), str(e), raw=e) from e
        return self.emulate_response(completion)

    async def list_models(self) -> List[Dict[str, str]]:
        try:
            listing = await self._client.models.list()
        except Exception as e:
            raise LLMError(classify_error(e), str(e), raw=e) from e
        data = getattr(listing, "data", None) or []
        out: List[Dict[str, str]] = []
        for model in data:
            mid = getattr(model, "id", None)
            if not mid:
                continue
            out.append({"id": str(mid), "display_name": str(mid)})
        return out

    async def close(self) -> None:
        try:
            await self._client.close()
        except Exception:
            pass
