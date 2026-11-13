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
    h.search_subtask_client = MagicMock()
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


@pytest.mark.asyncio
async def test_message_handler_init_with_mocks(monkeypatch):
    import src.handlers.message_handler as mh_mod

    def fake_mock(*a, **kw):
        return MagicMock()
    monkeypatch.setattr(mh_mod, "DatabaseRepository", fake_mock)
    monkeypatch.setattr(mh_mod, "RedisStreamService", fake_mock)
    monkeypatch.setattr(mh_mod, "NoteManager", fake_mock)
    monkeypatch.setattr(mh_mod, "SearchSubtaskClient", fake_mock)
    monkeypatch.setattr(mh_mod, "ToolsManager", fake_mock)
    monkeypatch.setattr(mh_mod, "FileParserService", fake_mock)
    monkeypatch.setattr(mh_mod, "PremiumManager", fake_mock)
    monkeypatch.setattr(mh_mod, "CleanupManager", fake_mock)

    cfg = MagicMock()
    cfg.DATABASE_URL = "postgresql://mock"
    cfg.REDIS_URL = "redis://mock"
    cfg.FILE_CHUNK_DIR = "chunks"
    cfg.MAX_CONCURRENT_MESSAGES = 2

    handler = mh_mod.MessageHandler(cfg)
    assert handler.config is cfg


@pytest.mark.asyncio
async def test_message_handler_start_worker_and_shutdown():
    h = make_handler()
    h.db_repo.init_db = AsyncMock()
    h.db_repo.close = AsyncMock()
    h.kafka_service.start_producer = AsyncMock()
    h.kafka_service.stop = AsyncMock()
    h.search_subtask_client.close = AsyncMock()
    h._worker_tasks = set()

    msg = MagicMock()
    async def breaking_consumer():
        yield msg
        raise RuntimeError("break worker loop")

    consumer = MagicMock()
    consumer.reclaim_pending = AsyncMock(return_value=[MagicMock()])
    consumer.__aiter__ = lambda self: breaking_consumer()

    h.kafka_service.start_consumer = AsyncMock(return_value=consumer)
    h._process_message_guarded = AsyncMock()

    await h.start_worker()
    h.db_repo.init_db.assert_awaited_once()
    h.kafka_service.start_producer.assert_awaited_once()
    h.kafka_service.start_consumer.assert_awaited_once()
    consumer.reclaim_pending.assert_awaited_once()
    h.kafka_service.stop.assert_awaited_once()
    h.db_repo.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_message_handler_start_worker_start_producer_fails():
    h = make_handler()
    h.db_repo.init_db = AsyncMock()
    h.kafka_service.start_producer = AsyncMock(side_effect=RuntimeError("producer fail"))
    h.shutdown = AsyncMock()

    await h.start_worker()
    h.shutdown.assert_awaited_once()
