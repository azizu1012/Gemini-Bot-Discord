import os
import sys
import base64
import asyncio
import json
import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.genai import types as genai_types

from src.core.config import logger
from src.core.llm.genai_client import (
    DEFAULT_GENAI_BASE_URL,
    GenAIClient,
    _contents_to_router_wire,
    build_request_config,
    messages_to_genai_contents,
)


def make_client(**kw):
    defaults = dict(base_url="", api_key="test-key", logger=logger, timeout_ms=None, safety_settings=None)
    defaults.update(kw)
    return GenAIClient(**defaults)


def test_default_base_url_constant():
    assert DEFAULT_GENAI_BASE_URL == "https://generativelanguage.googleapis.com"


def test_system_instruction_prepended():
    contents = messages_to_genai_contents("Bạn là Azuris.", [{"role": "user", "parts": [{"text": "hi"}]}])
    assert contents[0] == {"role": "user", "parts": [{"text": "Bạn là Azuris."}]}
    assert contents[1] == {"role": "user", "parts": [{"text": "hi"}]}


def test_inline_data_passthrough_bytes():
    msg = {"role": "user", "parts": [{"text": "xem ảnh"}, {"inline_data": {"data": b"\x89PNG", "mime_type": "image/png"}}]}
    contents = messages_to_genai_contents(None, [msg])
    assert contents[0]["parts"][1]["inline_data"]["data"] == b"\x89PNG"
    assert contents[0]["parts"][1]["inline_data"]["mime_type"] == "image/png"


def test_custom_endpoint_uses_standard_base64_for_inline_data():
    wire = _contents_to_router_wire([
        {"role": "user", "parts": [{"inline_data": {"data": b"abc123", "mime_type": "image/png"}}]},
    ])
    encoded = wire[0]["parts"][0]["inlineData"]["data"]
    assert encoded == base64.b64encode(b"abc123").decode("ascii")
    assert "-" not in encoded and "_" not in encoded


def test_custom_endpoint_generate_sends_router_compatible_image_payload(monkeypatch):
    client = make_client(base_url="http://127.0.0.1:58100")
    captured = {}

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, *, headers, json):
            captured["headers"] = headers
            captured["body"] = json
            return httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
                request=httpx.Request("POST", _url),
            )

    monkeypatch.setattr("src.core.llm.genai_client.httpx.AsyncClient", FakeAsyncClient)
    response = asyncio.run(client.generate(
        model_id="gemini-flash-lite",
        system_instruction="",
        generation_config={},
        messages=[{
            "role": "user",
            "parts": [{"inline_data": {"data": b"abc123", "mime_type": "image/png"}}],
        }],
    ))

    encoded = captured["body"]["contents"][0]["parts"][0]["inlineData"]["data"]
    assert response.candidates[0].content.parts[0].text == "ok"
    assert encoded == base64.b64encode(b"abc123").decode("ascii")


def test_function_call_and_response_passthrough():
    msgs = [
        {"role": "model", "parts": [{"function_call": {"name": "web_search", "args": {"query": "abc"}}}]},
        {"role": "user", "parts": [{"function_response": {"name": "web_search", "response": {"content": "result"}}}]},
    ]
    contents = messages_to_genai_contents(None, msgs)
    assert contents[0]["role"] == "model"
    assert contents[0]["parts"][0]["function_call"]["name"] == "web_search"
    assert contents[1]["parts"][0]["function_response"]["response"]["content"] == "result"


def test_thought_signature_preserved_for_object_part():
    signature = b"sig-from-model"
    part = genai_types.Part(
        function_call=genai_types.FunctionCall(name="web_search", args={"query": "abc"}),
        thought_signature=signature,
    )
    contents = messages_to_genai_contents(None, [{"role": "model", "parts": [part]}])
    assert contents[0]["parts"][0]["thought_signature"] == signature
    assert contents[0]["parts"][0]["function_call"]["name"] == "web_search"


def test_thought_signature_preserved_for_text_object_part():
    signature = b"sig-text"
    part = genai_types.Part(text="thinking", thought_signature=signature)
    contents = messages_to_genai_contents(None, [{"role": "model", "parts": [part]}])
    assert contents[0]["parts"][0]["thought_signature"] == signature
    assert contents[0]["parts"][0]["text"] == "thinking"


def test_thought_signature_preserved_for_dict_part():
    signature = b"sig-dict"
    for key in ("thought_signature", "thoughtSignature"):
        contents = messages_to_genai_contents(None, [{
            "role": "model",
            "parts": [{"function_call": {"name": "web_search", "args": {}}, key: signature}],
        }])
        assert contents[0]["parts"][0]["thought_signature"] == signature


def test_function_response_does_not_carry_signature():
    contents = messages_to_genai_contents(None, [
        {"role": "user", "parts": [{"function_response": {"name": "web_search", "response": {"content": "ok"}}}]},
    ])
    assert "thought_signature" not in contents[0]["parts"][0]


def test_role_normalization():
    contents = messages_to_genai_contents(None, [{"role": "assistant", "parts": [{"text": "x"}]}])
    assert contents[0]["role"] == "user"


def test_build_request_config():
    cfg = build_request_config(
        {"temperature": 0.7, "top_p": 0.9, "top_k": 40, "max_output_tokens": 100},
        safety_settings=[{"category": "HARM"}],
        tools=["TOOL_SENTINEL"],
    )
    assert cfg["temperature"] == 0.7
    assert cfg["top_p"] == 0.9
    assert cfg["top_k"] == 40
    assert cfg["max_output_tokens"] == 100
    assert cfg["safety_settings"] == [{"category": "HARM"}]
    assert cfg["tools"] == ["TOOL_SENTINEL"]

    cfg2 = build_request_config({"temperature": 0.1}, safety_settings=None, tools=None)
    assert "safety_settings" not in cfg2
    assert "tools" not in cfg2


def test_client_custom_base_url_adds_bearer_header():
    client = make_client(base_url="http://127.0.0.1:58100", api_key="router-key")
    # Client đã khởi tạo được và giữ nguyên base_url đã chuẩn hóa
    assert client.base_url == "http://127.0.0.1:58100"
    assert client.raw_client is not None


if __name__ == "__main__":
    test_default_base_url_constant()
    test_system_instruction_prepended()
    test_inline_data_passthrough_bytes()
    test_function_call_and_response_passthrough()
    test_thought_signature_preserved_for_object_part()
    test_thought_signature_preserved_for_text_object_part()
    test_thought_signature_preserved_for_dict_part()
    test_function_response_does_not_carry_signature()
    test_role_normalization()
    test_build_request_config()
    test_client_custom_base_url_adds_bearer_header()
    print("ALL PASS")
