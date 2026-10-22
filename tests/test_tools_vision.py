"""Test image recognition đi qua LLMGateway (offline, không cần mạng)."""
import asyncio
import os
import sys
from contextlib import contextmanager

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.llm.base import LLMError
from src.tools.builtin import vision as vision_mod
from src.tools.builtin.vision import VisionTool
from src.tools.tools import ToolsManager


class FakeResponse:
    def __init__(self, status=200, content_type="image/png", body=b"fake-image-bytes", headers=None):
        self.status = status
        self.headers = {"Content-Type": content_type}
        if headers:
            self.headers.update(headers)
        self._body = body

    async def read(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeSession:
    response = FakeResponse()

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def get(self, url, timeout=None, allow_redirects=True):
        return type(self).response


class FakeGateway:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    async def generate_vision(self, *, image_bytes, mime_type, question):
        self.calls.append((image_bytes, mime_type, question))
        if self.error is not None:
            raise self.error
        return "Mô tả: một chú mèo."


@contextmanager
def _patch_session(response=None):
    original = vision_mod.aiohttp.ClientSession
    FakeSession.response = response or FakeResponse()
    vision_mod.aiohttp.ClientSession = FakeSession
    try:
        yield
    finally:
        vision_mod.aiohttp.ClientSession = original


def test_vision_uses_gateway_and_caches():
    with _patch_session():
        gw = FakeGateway()
        tool = VisionTool(gateway=gw)

        result = asyncio.run(tool.run_image_recognition("https://example.com/cat.png", "Đây là gì?"))
        assert result == "Mô tả: một chú mèo."
        assert len(gw.calls) == 1
        image_bytes, mime_type, question = gw.calls[0]
        assert image_bytes == b"fake-image-bytes"
        assert mime_type == "image/png"
        assert question == "Đây là gì?"

        # Lần 2 phải ăn cache — không gọi gateway thêm
        result2 = asyncio.run(tool.run_image_recognition("https://example.com/cat.png", "Đây là gì?"))
        assert result2 == "Mô tả: một chú mèo."
        assert len(gw.calls) == 1


def test_vision_without_gateway_returns_error():
    tool = VisionTool(gateway=None)
    result = asyncio.run(tool.run_image_recognition("https://example.com/cat.png", "Đây là gì?"))
    assert "gateway" in result.lower()


def test_vision_gateway_error_returns_message():
    with _patch_session():
        gw = FakeGateway(error=LLMError("rate_limit", "boom"))
        tool = VisionTool(gateway=gw)
        result = asyncio.run(tool.run_image_recognition("https://example.com/cat.png", "Đây là gì?"))
        assert "Lỗi khi xử lý hình ảnh" in result
        assert "boom" in result


def test_vision_rejects_non_image_response():
    with _patch_session(FakeResponse(content_type="text/html", body=b"<html></html>")):
        gw = FakeGateway()
        tool = VisionTool(gateway=gw)
        result = asyncio.run(tool.run_image_recognition("https://example.com/not-an-image", "Đây là gì?"))
        assert "không trả về hình ảnh" in result
        assert gw.calls == []


def test_vision_blocks_redirect_to_internal_host():
    redirect = FakeResponse(
        status=302,
        content_type="text/plain",
        body=b"",
        headers={"Location": "http://127.0.0.1:55432/secret"},
    )
    with _patch_session(redirect):
        gw = FakeGateway()
        tool = VisionTool(gateway=gw)
        result = asyncio.run(tool.run_image_recognition("https://example.com/redirect", "Đây là gì?"))
        assert "bị chặn" in result
        assert gw.calls == []


def test_manager_delegates_image_recognition():
    class FakeVision:
        async def run_image_recognition(self, image_url, question):
            return f"delegated:{image_url}:{question}"

    mgr = ToolsManager.__new__(ToolsManager)
    mgr.vision = FakeVision()
    result = asyncio.run(mgr.run_image_recognition("https://example.com/a.png", "hỏi"))
    assert result == "delegated:https://example.com/a.png:hỏi"


def test_vision_turn_cache_hit_without_network():
    gw = FakeGateway()
    tool = VisionTool(gateway=gw)
    tool.register_turn_image(
        "https://cdn.discordapp.com/attachments/123/456/test.png?ex=abc&hm=xyz",
        b"cached-bytes",
        "image/png",
        filename="test.png",
    )

    # Gọi với URL bị model cắt cụt query string
    result = asyncio.run(tool.run_image_recognition(
        "https://cdn.discordapp.com/attachments/123/456/test.png",
        "Xem ảnh này",
    ))
    assert result == "Mô tả: một chú mèo."
    assert len(gw.calls) == 1
    assert gw.calls[0][0] == b"cached-bytes"

    # Gọi với filename
    tool.clear_turn_images()
    assert tool._turn_images == {}


def test_vision_refreshes_discord_cdn_url_on_404():
    gw = FakeGateway()
    tool = VisionTool(gateway=gw)

    # Giả lập Discord CDN trả về 404 lần đầu, và sau khi refresh trả về 200
    called_urls = []

    class RefreshingSession:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def get(self, url, timeout=None, allow_redirects=True):
            called_urls.append(url)
            if "refreshed=true" in url:
                return FakeResponse(status=200, content_type="image/png", body=b"refreshed-bytes")
            return FakeResponse(status=404, content_type="text/plain", body=b"Not Found")

    async def fake_refresh(url):
        return f"{url}?refreshed=true"

    original_session = vision_mod.aiohttp.ClientSession
    vision_mod.aiohttp.ClientSession = RefreshingSession
    tool._refresh_discord_url = fake_refresh
    try:
        result = asyncio.run(tool.run_image_recognition(
            "https://cdn.discordapp.com/attachments/123/456/pic.jpg?ex=expired",
            "Mô tả",
        ))
        assert result == "Mô tả: một chú mèo."
        assert len(gw.calls) == 1
        assert gw.calls[0][0] == b"refreshed-bytes"
        assert len(called_urls) >= 2
    finally:
        vision_mod.aiohttp.ClientSession = original_session


if __name__ == "__main__":
    test_vision_uses_gateway_and_caches()
    test_vision_without_gateway_returns_error()
    test_vision_gateway_error_returns_message()
    test_vision_rejects_non_image_response()
    test_vision_blocks_redirect_to_internal_host()
    test_manager_delegates_image_recognition()
    print("ALL PASS")
