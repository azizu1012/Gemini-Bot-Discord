"""Regression tests for retaining Discord image parts during synthesis."""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.gemini_pipeline import GeminiPipeline
from src.core.llm.base import Candidate, Content, LLMResponse, Part


class FakeConfig:
    FINAL_MAX_API_RETRIES = 1
    FALLBACK_MAX_API_RETRIES = 1
    FINAL_MAX_OUTPUT_TOKENS = 100
    FALLBACK_MAX_OUTPUT_TOKENS = 100
    SEARCH_ALLOW_PARTIAL_ANSWER = False


class FakeGateway:
    def __init__(self):
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return LLMResponse([Candidate(Content([Part(text="đã đọc ảnh")]))])

    def _is_invalid_key_error(self, _error):
        return False

    def _is_rate_limit_error(self, _error):
        return False

    def _is_unavailable_error(self, _error):
        return False

    def _is_connection_error(self, _error):
        return False

    def log_exception(self, **_kwargs):
        pass


def build_pipeline(gateway):
    return GeminiPipeline(
        config=FakeConfig(),
        api_mgr=gateway,
        tools_mgr=SimpleNamespace(),
        identity_builder=lambda _context: "",
        reasoning_role="reasoning",
        final_role="final",
        fallback_role="fallback",
    )


def image_messages():
    return [{
        "role": "user",
        "parts": [
            {"text": "Ảnh này có gì?"},
            {"inline_data": {"data": b"image-bytes", "mime_type": "image/jpeg"}},
        ],
    }]


def test_final_synthesis_keeps_discord_image():
    gateway = FakeGateway()
    pipeline = build_pipeline(gateway)

    result = asyncio.run(pipeline._call_gemini_final(
        image_messages(), "reasoning", "", "user-1", {},
    ))

    assert result == "đã đọc ảnh"
    parts = gateway.calls[0]["messages"][0]["parts"]
    assert parts[1]["inline_data"]["data"] == b"image-bytes"
    assert parts[1]["inline_data"]["mime_type"] == "image/jpeg"


def test_final_synthesis_does_not_resend_image_after_vision_tool():
    gateway = FakeGateway()
    pipeline = build_pipeline(gateway)

    result = asyncio.run(pipeline._call_gemini_final(
        image_messages(),
        "reasoning",
        "[image_recognition] Đây là một con mèo.",
        "user-1",
        {},
    ))

    assert result == "đã đọc ảnh"
    parts = gateway.calls[0]["messages"][0]["parts"]
    assert all("inline_data" not in part for part in parts)


def test_image_tool_result_bypasses_final_synthesis():
    gateway = FakeGateway()
    pipeline = build_pipeline(gateway)

    async def reasoning_loop(_messages, _user_id, _privacy_context):
        return "Reasoning completed", "[image_recognition] Đây là một con mèo."

    pipeline._call_gemini_reasoning_loop = reasoning_loop

    result = asyncio.run(pipeline.call_gemini_api(image_messages(), "user-1", {}))

    assert result == "Đây là một con mèo."
    assert gateway.calls == []


def test_fallback_returns_image_tool_result_without_model_call():
    gateway = FakeGateway()
    pipeline = build_pipeline(gateway)

    result = asyncio.run(pipeline._fallback_lite_as_flash(
        image_messages(),
        "reasoning",
        "[image_recognition] Đây là một con mèo.",
        "user-1",
        {},
    ))

    assert result == "Đây là một con mèo."
    assert gateway.calls == []


if __name__ == "__main__":
    test_final_synthesis_keeps_discord_image()
    test_fallback_synthesis_keeps_discord_image()
    print("ALL PASS")
