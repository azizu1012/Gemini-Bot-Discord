"""Offline tests for MessageHandler slash-command dispatch and small helpers."""
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, ".")

from src.handlers.message_handler import MessageHandler


class NullLogger:
    def info(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass


def make_handler():
    h = object.__new__(MessageHandler)
    h.config = MagicMock()
    h.logger = NullLogger()
    h.kafka_service = MagicMock()
    h.db_repo = MagicMock()
    h.resolver = MagicMock()
    h.gateway = MagicMock()
    h._image_download_sem = asyncio.Semaphore(1)
    return h


@pytest.mark.asyncio
async def test_process_slash_command_imagine_dispatch():
    h = make_handler()
    h._process_imagine_command = AsyncMock()
    await h.process_slash_command({"command": "imagine", "user_id": "u1"})
    h._process_imagine_command.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_slash_command_unknown():
    h = make_handler()
    await h.process_slash_command({"command": "nope", "user_id": "u1"})
    # no crash, logs warning


@pytest.mark.asyncio
async def test_process_slash_command_error_handled():
    h = make_handler()

    async def boom(payload):
        raise RuntimeError("crash")

    h._process_imagine_command = boom
    await h.process_slash_command({"command": "imagine", "user_id": "u1"})
    # no exception propagates


@pytest.mark.asyncio
async def test_publish_outgoing_success():
    h = make_handler()
    h.kafka_service.publish = AsyncMock(return_value=True)
    ok = await h._publish_outgoing({"action": "reply"}, "u1")
    assert ok is True
    h.kafka_service.publish.assert_awaited_once_with("discord-outgoing", payload={"action": "reply"}, key="u1")


@pytest.mark.asyncio
async def test_publish_outgoing_failure_raises():
    h = make_handler()
    h.kafka_service.publish = AsyncMock(return_value=False)
    with pytest.raises(RuntimeError, match="publish"):
        await h._publish_outgoing({"action": "reply"}, "u1")


@pytest.mark.asyncio
async def test_download_file_success(monkeypatch):
    h = make_handler()

    class FakeResp:
        status = 200

        async def read(self):
            return b"data"

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

        def get(self, url, timeout=None):
            return FakeResp()

    import aiohttp

    monkeypatch.setattr(aiohttp, "ClientSession", FakeSession)
    data = await h._download_file("http://x/file")
    assert data == b"data"


@pytest.mark.asyncio
async def test_download_file_non_200(monkeypatch):
    h = make_handler()

    class FakeResp:
        status = 404

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

        def get(self, url, timeout=None):
            return FakeResp()

    import aiohttp

    monkeypatch.setattr(aiohttp, "ClientSession", FakeSession)
    data = await h._download_file("http://x/file")
    assert data is None


@pytest.mark.asyncio
async def test_download_file_exception(monkeypatch):
    h = make_handler()

    class FakeSession:
        def __init__(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, timeout=None):
            raise ConnectionError("no net")

    import aiohttp

    monkeypatch.setattr(aiohttp, "ClientSession", FakeSession)
    data = await h._download_file("http://x/file")
    assert data is None


@pytest.mark.asyncio
async def test_download_file_with_sem():
    h = make_handler()
    h._download_file = AsyncMock(return_value=b"x")
    data = await h._download_file_with_sem("http://x")
    assert data == b"x"
