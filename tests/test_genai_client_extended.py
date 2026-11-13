"""Offline tests for GenAIClient conversion helpers and generate paths."""
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, ".")

from src.core.llm.base import LLMError, Part
from src.core.llm.genai_client import (
    GenAIClient,
    _bytes_to_standard_base64,
    _contents_to_router_wire,
    _strip_nulls,
    _tools_to_router_wire,
    build_request_config,
    messages_to_genai_contents,
)


class NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


def make_client():
    c = GenAIClient(base_url="http://custom", api_key="k", logger=NullLogger())
    c._client = MagicMock()
    return c


# ---------------- pure helpers ----------------
def test_strip_nulls():
    assert _strip_nulls({"a": 1, "b": None}) == {"a": 1}


def test_messages_to_genai_contents_system_and_text():
    out = messages_to_genai_contents("sys", [{"role": "user", "parts": [{"text": "hi"}]}])
    assert out[0]["parts"][0]["text"] == "sys"
    assert out[1]["parts"][0]["text"] == "hi"


def test_messages_to_genai_contents_part_object():
    p = Part(text="obj text")
    out = messages_to_genai_contents(None, [{"role": "model", "parts": [p]}])
    assert out[0]["parts"][0]["text"] == "obj text"


def test_messages_to_genai_contents_inline():
    out = messages_to_genai_contents(None, [{"role": "user", "parts": [{"inline_data": {"data": b"x", "mime_type": "image/png"}}]}])
    assert out[0]["parts"][0]["inline_data"]["mime_type"] == "image/png"


def test_bbytes_to_standard_base64_bytes():
    out = _bytes_to_standard_base64(b"\x89PNG")
    assert out == "iVBORw=="


def test_bytes_to_standard_base64_urlsafe():
    out = _bytes_to_standard_base64("aGVsbG8")
    assert out == "aGVsbG8="


def test_bytes_to_standard_base64_urlsafe_padding():
    # urlsafe base64 with padding decodes and re-encodes to standard base64
    out = _bytes_to_standard_base64("aGVsbG8")
    assert out == "aGVsbG8="


def test_contents_to_router_wire():
    contents = [{"role": "user", "parts": [{"text": "hi"}, {"inline_data": {"data": b"x", "mime_type": "image/png"}}]}]
    wire = _contents_to_router_wire(contents)
    assert wire[0]["parts"][0]["text"] == "hi"
    assert wire[0]["parts"][1]["inlineData"]["mimeType"] == "image/png"


def test_tools_to_router_wire_dict():
    assert _tools_to_router_wire([{"type": "function"}]) == [{"type": "function"}]


def test_tools_to_router_wire_none():
    assert _tools_to_router_wire(None) is None
    assert _tools_to_router_wire([]) is None


def test_build_request_config():
    cfg = build_request_config({"temperature": 0.5}, ["safety"], [{"type": "function"}])
    assert cfg["temperature"] == 0.5
    assert cfg["safety_settings"] == ["safety"]
    assert cfg["tools"] == [{"type": "function"}]


def test_build_request_config_empty():
    assert build_request_config({}, None, None) == {}


# ---------------- custom endpoint generate ----------------
@pytest.mark.asyncio
async def test_generate_custom_endpoint_success(monkeypatch):
    c = make_client()
    response = MagicMock()
    response.is_error = False
    response.json = MagicMock(return_value={"candidates": []})
    post = AsyncMock(return_value=response)

    class FakeAsyncClient:
        def __init__(self, timeout=None):
            self.post = post

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr("httpx.AsyncClient", FakeAsyncClient)
    result = await c._generate_custom_endpoint(
        model_id="m1", system_instruction="", generation_config={}, messages=[], tools=None
    )
    assert result.candidates == []


@pytest.mark.asyncio
async def test_generate_custom_endpoint_http_error(monkeypatch):
    c = make_client()
    response = MagicMock()
    response.is_error = True
    response.status_code = 400
    response.text = "bad request"
    post = AsyncMock(return_value=response)

    class FakeAsyncClient:
        def __init__(self, timeout=None):
            self.post = post

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr("httpx.AsyncClient", FakeAsyncClient)
    with pytest.raises(LLMError):
        await c._generate_custom_endpoint(model_id="m1", system_instruction="", generation_config={}, messages=[], tools=None)


# ---------------- default generate ----------------
@pytest.mark.asyncio
async def test_generate_default_with_custom_endpoint(monkeypatch):
    # when base_url is custom, generate routes to custom endpoint
    c = make_client()
    c._generate_custom_endpoint = AsyncMock(return_value=SimpleNamespace(candidates=[]))
    result = await c.generate(model_id="m1", system_instruction="", generation_config={}, messages=[])
    assert result.candidates == []
    c._generate_custom_endpoint.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_default_public_endpoint():
    c = GenAIClient(base_url="", api_key="k", logger=NullLogger())
    c._client.models.generate_content = MagicMock(return_value=SimpleNamespace(candidates=[]))
    result = await c.generate(model_id="m1", system_instruction="", generation_config={}, messages=[{"role": "user", "parts": [{"text": "hi"}]}])
    assert result.candidates == []


@pytest.mark.asyncio
async def test_generate_default_raises():
    c = GenAIClient(base_url="", api_key="k", logger=NullLogger())
    c._client.models.generate_content = MagicMock(side_effect=RuntimeError("boom"))
    with pytest.raises(LLMError):
        await c.generate(model_id="m1", system_instruction="", generation_config={}, messages=[])


# ---------------- list_models ----------------
@pytest.mark.asyncio
async def test_list_models():
    c = GenAIClient(base_url="", api_key="k", logger=NullLogger())
    model = SimpleNamespace(name="models/gemini-1", display_name="Gemini")
    c._client.models.list = MagicMock(return_value=[model])
    out = await c.list_models()
    assert out == [{"id": "gemini-1", "display_name": "Gemini"}]


# ---------------- misc ----------------
def test_properties():
    c = make_client()
    assert c._uses_custom_endpoint is True
    assert c.raw_client is c._client
    c2 = GenAIClient(base_url="https://generativelanguage.googleapis.com", api_key="k", logger=NullLogger())
    assert c2._uses_custom_endpoint is False


@pytest.mark.asyncio
async def test_close():
    c = make_client()
    assert await c.close() is None


def test_contents_to_router_wire_all_parts():
    contents = [{
        "role": "model",
        "parts": [
            {"inline_data": {"data": b"x"}, "thought_signature": b"sig"},
            {"function_call": {"name": "calc", "args": {"a": 1}}},
            {"function_response": {"name": "calc", "response": {"result": 2}}},
        ]
    }]
    wire = _contents_to_router_wire(contents)
    assert "thoughtSignature" in wire[0]["parts"][0]
    assert "functionCall" in wire[0]["parts"][1]
    assert "functionResponse" in wire[0]["parts"][2]


def test_messages_to_genai_contents_with_thought_signature():
    msg = {
        "role": "model",
        "parts": [
            {"text": "reasoning", "thought_signature": b"sig1"},
            {"function_call": {"name": "tool1", "args": {}}, "thoughtSignature": b"sig2"},
            {"function_response": {"name": "tool1", "response": "plain_string_result"}},
        ]
    }
    out = messages_to_genai_contents(None, [msg])
    assert out[0]["parts"][0]["thought_signature"] == b"sig1"
    assert out[0]["parts"][1]["thought_signature"] == b"sig2"
    assert out[0]["parts"][2]["function_response"]["response"] == "plain_string_result"


@pytest.mark.asyncio
async def test_generate_custom_endpoint_with_system_instruction_and_tools(monkeypatch):
    c = GenAIClient(base_url="http://custom:8000", api_key="k", logger=NullLogger(), timeout_ms=5000)
    response = MagicMock()
    response.is_error = False
    response.json = MagicMock(return_value={"candidates": []})
    post = AsyncMock(return_value=response)

    class FakeAsyncClient:
        def __init__(self, timeout=None):
            self.post = post

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr("httpx.AsyncClient", FakeAsyncClient)
    res = await c._generate_custom_endpoint(
        model_id="m1",
        system_instruction="You are Chad",
        generation_config={"temperature": 0.5},
        messages=[],
        tools=[{"type": "function"}],
    )
    assert res.candidates == []
    call_json = post.call_args.kwargs["json"]
    assert "systemInstruction" in call_json
    assert "tools" in call_json
