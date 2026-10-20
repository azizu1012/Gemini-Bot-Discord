"""Shapes + lỗi dùng chung cho LLM adapter façade.

Định dạng nội bộ chuẩn = kiểu genai:
- messages: [{"role": "user"|"model", "parts": [{"text"|"inline_data"|"function_call"|"function_response": ...}]}]
- response: object có .candidates[0].content.parts[i].text / .function_call
  và .candidates[0].finish_reason.name (vd "STOP", "MAX_TOKENS").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

SLOTS = ("reasoning", "final", "fallback")


class LLMError(Exception):
    def __init__(self, kind: str, message: str, status_code: Optional[int] = None, raw: Any = None):
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code
        self.raw = raw


class LLMNotConfiguredError(LLMError):
    def __init__(self, message: str = "Bot chưa được cấu hình endpoint. Liên hệ admin."):
        super().__init__("not_configured", message)


class LLMUnsupportedError(LLMError):
    def __init__(self, message: str):
        super().__init__("unsupported", message)


@dataclass
class SlotModel:
    sdk: str        # "genai" | "openai"
    model_id: str   # id model thật trên endpoint (đã resolve theo default rule)
    role: str       # "reasoning" | "final" | "fallback"


@dataclass
class FunctionCall:
    name: str
    args: Dict[str, Any]
    id: Optional[str] = None


@dataclass
class Part:
    text: Optional[str] = None
    function_call: Optional[FunctionCall] = None
    inline_data: Optional[Dict[str, Any]] = None


@dataclass
class Content:
    parts: List[Any]
    role: str = "model"


@dataclass
class FinishReason:
    name: str


@dataclass
class Candidate:
    content: Optional[Content]
    finish_reason: FinishReason = field(default_factory=lambda: FinishReason("STOP"))


class LLMResponse:
    def __init__(self, candidates: Optional[List[Candidate]] = None, raw: Any = None, usage: Optional[Dict[str, Any]] = None):
        self.candidates = candidates or []
        self.raw = raw
        self.usage = usage


_AUTH_TOKENS = (
    "api key not valid",
    "api key invalid",
    "invalid api key",
    "invalid_api_key",
    "api_key_invalid",
    "api key not found",
    "key not found",
    "invalid argument: api key",
    "provided api key is invalid",
    "authenticationerror",
    "authentication error",
    "incorrect api key",
    "unauthorized",
    "unauthenticated",
    "permission denied",
    "permission_denied",
    "401",
    "403",
)
_RATE_LIMIT_TOKENS = (
    "429",
    "rate limit",
    "resource exhausted",
    "resource_exhausted",
    "quota",
    "too many requests",
    "overloaded",
)
_UNAVAILABLE_TOKENS = (
    "503",
    "service unavailable",
    "500",
    "internal server error",
    "internal_server_error",
    "unavailable",
    "deadline exceeded",
)
_CONNECTION_TOKENS = (
    "connection reset",
    "connection aborted",
    "connection refused",
    "connect timeout",
    "connecttimeout",
    "timed out",
    "timeout",
    "network",
    "getaddrinfo",
    "ssl",
    "server disconnected",
)
_NOT_FOUND_TOKENS = (
    "not found",
    "not_found",
    "404",
    "does not exist",
    "no such model",
)


def _text_of(error: Exception) -> str:
    return f"{type(error).__name__}: {error}".lower()


def is_invalid_key_error(text: str) -> bool:
    return any(token in text for token in _AUTH_TOKENS)


def is_rate_limit_error(text: str) -> bool:
    return any(token in text for token in _RATE_LIMIT_TOKENS)


def is_unavailable_error(text: str) -> bool:
    return any(token in text for token in _UNAVAILABLE_TOKENS)


def is_connection_error(error: Exception) -> bool:
    if isinstance(error, (TimeoutError, ConnectionError, OSError)):
        return True
    error_str = str(error)
    if isinstance(error, TypeError) and "'<=' not supported" in error_str and "NoneType" in error_str:
        return True
    class_name = type(error).__name__
    if any(
        marker in class_name
        for marker in ("ConnectError", "ConnectTimeout", "ReadTimeout", "ReadError", "TimeoutException", "NetworkError")
    ):
        return True
    text = _text_of(error)
    return any(token in text for token in _CONNECTION_TOKENS)


def classify_error(error: Exception) -> str:
    if isinstance(error, LLMError):
        return error.kind
    text = _text_of(error)
    if is_invalid_key_error(text):
        return "auth"
    if is_connection_error(error):
        return "connection"
    if is_rate_limit_error(text):
        return "rate_limit"
    if is_unavailable_error(text):
        return "unavailable"
    if any(token in text for token in _NOT_FOUND_TOKENS):
        return "not_found"
    return "other"
