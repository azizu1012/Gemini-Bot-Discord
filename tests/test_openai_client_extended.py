"""Offline tests for OpenAIClient conversion helpers and generate."""
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, ".")

from src.core.llm.base import FunctionCall, LLMError, Part
from src.core.llm.openai_client import (
    OpenAIClient,
    data_url_from_inline,
    normalize_schema,
    part_object_to_dict,
    to_json_schema,
    tools_to_openai,
)


class NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


def make_client():
    client = OpenAIClient(base_url="http://x/v1", api_key="k", logger=NullLogger())
    client._client = MagicMock()
    return client


# ---------------- pure helpers ----------------
def test_data_url_from_inline_bytes():
    assert data_url_from_inline({"data": b"\x89PNG", "mime_type": "image/png"}).startswith("data:image/png;base64,")


def test_data_url_from_inline_str():
    # non-bytes data is embedded as-is
    assert data_url_from_inline({"data": "abc", "mime_type": "image/jpeg"}) == "data:image/jpeg;base64,abc"


def test_part_object_to_dict_text():
    assert part_object_to_dict(Part(text="hi")) == {"text": "hi"}


def test_part_object_to_dict_function_call():
    p = Part(function_call=FunctionCall(name="calc", args={"equation": "1+1"}, id="c1"))
    d = part_object_to_dict(p)
    assert d["function_call"]["name"] == "calc"
    assert d["function_call"]["args"] == {"equation": "1+1"}


def test_part_object_to_dict_empty():
    assert part_object_to_dict(SimpleNamespace(text=None, function_call=None, inline_data=None)) == {}


def test_normalize_schema_dict():
    assert normalize_schema({"type": "STRING", "properties": {"a": {"type": "INTEGER"}}}) == {
        "type": "string", "properties": {"a": {"type": "integer"}}
    }


def test_normalize_schema_list():
    assert normalize_schema([{"type": "BOOLEAN"}]) == [{"type": "boolean"}]


def test_to_json_schema_none():
    assert to_json_schema(None) == {"type": "object", "properties": {}}


def test_to_json_schema_dict():
    assert to_json_schema({"type": "object"}) == {"type": "object"}


def test_tools_to_openai():
    decl = SimpleNamespace(name="get_weather", description="Get weather", parameters={"type": "object"})
    tool = SimpleNamespace(function_declarations=[decl])
    out = tools_to_openai([tool])
    assert out[0]["type"] == "function"
    assert out[0]["function"]["name"] == "get_weather"
    assert out[0]["function"]["parameters"] == {"type": "object"}


def test_tools_to_openai_empty():
    assert tools_to_openai(None) == []
    assert tools_to_openai([]) == []


# ---------------- convert_messages ----------------
def test_convert_messages_system_and_text():
    c = make_client()
    out = c.convert_messages("sys", [{"role": "user", "parts": [{"text": "hi"}]}])
    assert out[0] == {"role": "system", "content": "sys"}
    assert out[1] == {"role": "user", "content": "hi"}


def test_convert_messages_image():
    c = make_client()
    out = c.convert_messages(None, [{"role": "user", "parts": [{"text": "what"}, {"inline_data": {"data": b"x", "mime_type": "image/png"}}]}])
    assert out[0]["content"][0]["type"] == "text"
    assert out[0]["content"][1]["type"] == "image_url"


def test_convert_messages_tool_call_and_response():
    c = make_client()
    # message with function_call then function_response
    fc_msg = {"role": "model", "parts": [{"function_call": {"name": "calc", "args": {"equation": "1"}, "id": "call_1"}}]}
    fr_msg = {"role": "user", "parts": [{"function_response": {"name": "calc", "id": "call_1", "response": {"content": "2"}}}]}
    out = c.convert_messages(None, [fc_msg, fr_msg])
    assert out[0]["role"] == "assistant"
    assert out[0]["tool_calls"][0]["id"] == "call_1"
    assert out[1]["role"] == "tool"
    assert out[1]["tool_call_id"] == "call_1"


# ---------------- emulate_response ----------------
def test_emulate_response_text():
    c = make_client()
    choice = SimpleNamespace(
        message=SimpleNamespace(content="hello", tool_calls=[]),
        finish_reason="stop",
    )
    completion = SimpleNamespace(choices=[choice])
    resp = c.emulate_response(completion)
    assert resp.candidates[0].content.parts[0].text == "hello"


def test_emulate_response_tool_call():
    c = make_client()
    fn = SimpleNamespace(name="calc", arguments='{"equation":"1+1"}')
    tc = SimpleNamespace(id="c1", function=fn)
    choice = SimpleNamespace(
        message=SimpleNamespace(content=None, tool_calls=[tc]),
        finish_reason="tool_calls",
    )
    completion = SimpleNamespace(choices=[choice])
    resp = c.emulate_response(completion)
    part = resp.candidates[0].content.parts[0]
    assert part.function_call.name == "calc"
    assert part.function_call.args == {"equation": "1+1"}


def test_emulate_response_invalid_arguments():
    c = make_client()
    fn = SimpleNamespace(name="calc", arguments="{bad json")
    tc = SimpleNamespace(id="c2", function=fn)
    choice = SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[tc]), finish_reason="stop")
    resp = c.emulate_response(SimpleNamespace(choices=[choice]))
    assert resp.candidates[0].content.parts[0].function_call.args.get("_raw") == "{bad json"


# ---------------- generate ----------------
@pytest.mark.asyncio
async def test_generate_success():
    c = make_client()
    completion = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="answer", tool_calls=[]), finish_reason="stop")])
    c._client.chat.completions.create = AsyncMock(return_value=completion)
    resp = await c.generate(model_id="m1", system_instruction="", generation_config={"temperature": 0.5}, messages=[], tools=None)
    assert resp.candidates[0].content.parts[0].text == "answer"


@pytest.mark.asyncio
async def test_generate_raises_llm_error():
    c = make_client()
    c._client.chat.completions.create = AsyncMock(side_effect=RuntimeError("boom"))
    with pytest.raises(LLMError):
        await c.generate(model_id="m1", system_instruction="", generation_config={}, messages=[])


# ---------------- misc ----------------
def test_next_call_id_sequence():
    c = make_client()
    assert c._next_call_id() == "call_1"
    assert c._next_call_id() == "call_2"


def test_raw_client_property():
    c = make_client()
    assert c.raw_client is c._client
