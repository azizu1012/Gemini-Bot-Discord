"""Test image recognition đi qua LLMGateway (offline, không cần mạng)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import logger
from src.core.llm.base import LLMError
from src.tools.tools import ToolsManager


class FakeResponse:
    content = b"fake-image-bytes"


class FakeRequests:
    def get(self, url, timeout=None):
        return FakeResponse()


class FakeGateway:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    async def generate_vision(self, *, image_bytes, mime_type, question):
        self.calls.append((image_bytes, mime_type, question))
        if self.error is not None:
            raise self.error
        return "Mô tả: một chú mèo."


def make_tools(gateway):
    t = ToolsManager.__new__(ToolsManager)
    t.logger = logger
    t.gateway = gateway
    t.image_recognition_cache = {}
    return t


def test_vision_uses_gateway_and_caches():
    import src.tools.tools as tools_mod

    original_requests = tools_mod.requests
    tools_mod.requests = FakeRequests()
    try:
        gw = FakeGateway()
        t = make_tools(gw)
        result = asyncio.run(t.run_image_recognition("https://example.com/cat.png", "Đây là gì?"))
        assert result == "Mô tả: một chú mèo."
        assert len(gw.calls) == 1
        image_bytes, mime_type, question = gw.calls[0]
        assert image_bytes == b"fake-image-bytes"
        assert mime_type == "image/png"
        assert question == "Đây là gì?"

        # Lần 2 phải ăn cache — không gọi gateway thêm
        result2 = asyncio.run(t.run_image_recognition("https://example.com/cat.png", "Đây là gì?"))
        assert result2 == "Mô tả: một chú mèo."
        assert len(gw.calls) == 1
    finally:
        tools_mod.requests = original_requests


def test_vision_without_gateway_returns_error():
    t = make_tools(None)
    result = asyncio.run(t.run_image_recognition("https://example.com/cat.png", "Đây là gì?"))
    assert "gateway" in result.lower()


def test_vision_gateway_error_returns_message():
    import src.tools.tools as tools_mod

    original_requests = tools_mod.requests
    tools_mod.requests = FakeRequests()
    try:
        gw = FakeGateway(error=LLMError("rate_limit", "boom"))
        t = make_tools(gw)
        result = asyncio.run(t.run_image_recognition("https://example.com/cat.png", "Đây là gì?"))
        assert "Đã xảy ra lỗi" in result
        assert "boom" in result
    finally:
        tools_mod.requests = original_requests


if __name__ == "__main__":
    test_vision_uses_gateway_and_caches()
    test_vision_without_gateway_returns_error()
    test_vision_gateway_error_returns_message()
    print("ALL PASS")
