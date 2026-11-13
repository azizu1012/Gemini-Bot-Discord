"""Offline tests for VisionTool._download_image and cache/mime helpers."""
import sys

import pytest

sys.path.insert(0, ".")

from src.tools.builtin.vision import VisionTool


class NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


def make_vision():
    v = VisionTool(gateway=None, logger_override=NullLogger())
    v._turn_images = {}
    v.image_recognition_cache = {}
    return v


# ---------------- cache/mime helpers ----------------
def test_guess_mime_type():
    v = make_vision()
    assert v._guess_mime_type("http://x/a.png") == "image/png"
    assert v._guess_mime_type("http://x/a.webp") == "image/webp"
    assert v._guess_mime_type("http://x/a.gif") == "image/gif"
    assert v._guess_mime_type("http://x/a.jpg") == "image/jpeg"


def test_set_cache_evicts_oldest():
    v = make_vision()
    for i in range(1005):
        v._set_cache(f"url{i}", "q", "data")
    assert len(v.image_recognition_cache) <= 1000
    assert v._get_cache("url0", "q") is None  # evicted
    assert v._get_cache("url1004", "q") == "data"


# ---------------- _download_image ----------------
@pytest.mark.asyncio
async def test_download_image_turn_cache_hit():
    v = make_vision()
    v._turn_images["http://x/a.png"] = (b"img", "image/png")
    result = await v._download_image("http://x/a.png")
    assert result[0] == b"img"
    assert result[1] == "image/png"


@pytest.mark.asyncio
async def test_download_image_unsafe_url(monkeypatch):
    v = make_vision()
    result = await v._download_image("http://localhost:9999/x.png")
    assert result[0] is None
    assert "bị chặn" in result[2]


@pytest.mark.asyncio
async def test_download_image_success(monkeypatch):
    v = make_vision()

    class FakeResp:
        status = 200
        headers = {"Content-Type": "image/png", "Content-Length": "4"}

        async def read(self):
            return b"imgdata"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class FakeSession:
        def __init__(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def get(self, url, timeout=None, allow_redirects=False):
            return FakeResp()

    import aiohttp

    monkeypatch.setattr(aiohttp, "ClientSession", FakeSession)
    result = await v._download_image("http://example.com/a.png")
    assert result[0] == b"imgdata"
    assert result[1] == "image/png"


@pytest.mark.asyncio
async def test_download_image_redirect(monkeypatch):
    v = make_vision()

    class RedirectResp:
        status = 302
        headers = {"Location": "http://example.com/final.png"}

        async def read(self):
            return b""

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class FinalResp:
        status = 200
        headers = {"Content-Type": "image/png", "Content-Length": "3"}

        async def read(self):
            return b"abc"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class FakeSession:
        def __init__(self):
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def get(self, url, timeout=None, allow_redirects=False):
            self.calls += 1
            return RedirectResp() if self.calls == 1 else FinalResp()

    import aiohttp

    monkeypatch.setattr(aiohttp, "ClientSession", FakeSession)
    result = await v._download_image("http://example.com/start.png")
    assert result[0] == b"abc"


@pytest.mark.asyncio
async def test_download_image_non_image_content_type(monkeypatch):
    v = make_vision()

    class FakeResp:
        status = 200
        headers = {"Content-Type": "text/html", "Content-Length": "4"}

        async def read(self):
            return b"<html>"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class FakeSession:
        def __init__(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def get(self, url, timeout=None, allow_redirects=False):
            return FakeResp()

    import aiohttp

    monkeypatch.setattr(aiohttp, "ClientSession", FakeSession)
    result = await v._download_image("http://example.com/a.png")
    assert result[0] is None
    assert "không trả về hình ảnh" in result[2]


@pytest.mark.asyncio
async def test_download_image_oversize(monkeypatch):
    v = make_vision()

    class FakeResp:
        status = 200
        headers = {"Content-Type": "image/png", "Content-Length": "999999999"}

        async def read(self):
            return b"x" * 100

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class FakeSession:
        def __init__(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def get(self, url, timeout=None, allow_redirects=False):
            return FakeResp()

    import aiohttp

    monkeypatch.setattr(aiohttp, "ClientSession", FakeSession)
    result = await v._download_image("http://example.com/big.png")
    assert result[0] is None
    assert "20 MB" in result[2]


@pytest.mark.asyncio
async def test_download_image_redirect_missing_location(monkeypatch):
    v = make_vision()

    class RedirectNoLocation:
        status = 301
        headers = {}

        async def read(self):
            return b""

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class FakeSession:
        def __init__(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def get(self, url, timeout=None, allow_redirects=False):
            return RedirectNoLocation()

    import aiohttp
    monkeypatch.setattr(aiohttp, "ClientSession", FakeSession)
    res = await v._download_image("http://example.com/a.png")
    assert "không có Location" in res[2]


@pytest.mark.asyncio
async def test_download_image_empty_bytes(monkeypatch):
    v = make_vision()

    class EmptyResp:
        status = 200
        headers = {"Content-Type": "image/png"}

        async def read(self):
            return b""

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class FakeSession:
        def __init__(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def get(self, url, timeout=None, allow_redirects=False):
            return EmptyResp()

    import aiohttp
    monkeypatch.setattr(aiohttp, "ClientSession", FakeSession)
    res = await v._download_image("http://example.com/a.png")
    assert "tải về rỗng" in res[2]


@pytest.mark.asyncio
async def test_download_image_fallback_content_type(monkeypatch):
    v = make_vision()

    class OctetResp:
        status = 200
        headers = {"Content-Type": "application/octet-stream"}

        async def read(self):
            return b"some_bytes"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class FakeSession:
        def __init__(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def get(self, url, timeout=None, allow_redirects=False):
            return OctetResp()

    import aiohttp
    monkeypatch.setattr(aiohttp, "ClientSession", FakeSession)
    res = await v._download_image("http://example.com/photo.png")
    assert res[0] == b"some_bytes"
    assert res[1] == "image/png"


@pytest.mark.asyncio
async def test_run_image_recognition_empty_url():
    v = make_vision()
    assert "Không tìm thấy URL" in await v.run_image_recognition("", "q")


@pytest.mark.asyncio
async def test_run_image_recognition_cache_hit():
    v = make_vision()
    v._set_cache("http://img", "what", "a cached cat")
    assert await v.run_image_recognition("http://img", "what") == "a cached cat"
