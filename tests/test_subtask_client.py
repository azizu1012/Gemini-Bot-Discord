"""Offline tests for SearchSubtaskClient (Redis subtask dispatch/client)."""
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, ".")

from src.services.messaging.subtask_client import SearchSubtaskClient


class NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


def make_client(kafka=None):
    kafka = kafka or MagicMock()
    client = SearchSubtaskClient(kafka)
    client.logger = NullLogger()
    return client, kafka


@pytest.mark.asyncio
async def test_init_uses_stable_group_id():
    client, _ = make_client()
    assert client.group_id == "azuris_search_results"

@pytest.mark.asyncio
async def test_init_generates_same_group_id_for_separate_instances():
    client1, _ = make_client()
    client2, _ = make_client()
    assert client1.group_id == client2.group_id


@pytest.mark.asyncio
async def test_start_skips_when_listener_running():
    client, kafka = make_client()

    class FakeTask:
        def done(self):
            return False  # not done -> early return

    client._listener_task = FakeTask()
    await client.start()
    kafka.start_producer.assert_not_called()


@pytest.mark.asyncio
async def test_start_consumes_and_starts_listener():
    client, kafka = make_client()
    consumer = MagicMock()
    kafka.start_producer = AsyncMock()
    kafka.start_consumer = AsyncMock(return_value=consumer)
    client._listen_results = AsyncMock()

    await client.start()
    assert client._consumer is consumer
    kafka.start_consumer.assert_awaited_once_with("search-results", group_id=client.group_id)
    assert client._listener_task is not None


@pytest.mark.asyncio
async def test_listen_results_consumes_and_resolves_future():
    client, kafka = make_client()
    loop = asyncio.get_running_loop()

    future = loop.create_future()
    client._pending["corr-1"] = future

    payload = {"correlation_id": "corr-1", "result": "hello"}
    msg = MagicMock()
    msg.value = payload

    async def agen():
        yield msg

    # manually drive listener using fake consumer
    client._consumer = agen()
    await client._listen_results()
    assert future.done()
    assert future.result() == payload


@pytest.mark.asyncio
async def test_listen_results_ignores_no_correlation():
    client, kafka = make_client()
    msg = MagicMock()
    msg.value = {"result": "x"}  # no correlation_id

    async def agen():
        yield msg

    client._consumer = agen()
    await client._listen_results()  # should not raise


@pytest.mark.asyncio
async def test_request_search_publish_fails_returns_none():
    client, kafka = make_client()
    kafka.start_producer = AsyncMock()
    kafka.start_consumer = AsyncMock(return_value=MagicMock())
    kafka.publish = AsyncMock(return_value=False)
    client._listen_results = AsyncMock()

    result = await client.request_search("u1", "query")
    assert result is None


@pytest.mark.asyncio
async def test_request_search_success(monkeypatch):
    client, kafka = make_client()
    kafka.start_producer = AsyncMock()
    kafka.start_consumer = AsyncMock(return_value=MagicMock())
    client._listen_results = AsyncMock()

    # replace wait_for to resolve immediately with payload
    async def fake_wait_for(future, timeout):
        return {"correlation_id": "x", "result": "answer"}

    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
    kafka.publish = AsyncMock(return_value=True)

    result = await client.request_search("u1", "query")
    assert result == "answer"


@pytest.mark.asyncio
async def test_request_search_timeout_raises(monkeypatch):
    client, kafka = make_client()
    kafka.start_producer = AsyncMock()
    kafka.start_consumer = AsyncMock(return_value=MagicMock())
    client._listen_results = AsyncMock()

    async def fake_wait_for(future, timeout):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
    kafka.publish = AsyncMock(return_value=True)

    with pytest.raises(asyncio.TimeoutError):
        await client.request_search("u1", "query", timeout=1)
    # The pending future must be cleaned up so a late result can't be delivered.
    assert client._pending == {}


@pytest.mark.asyncio
async def test_close_cancels_tasks_and_futures():
    client, kafka = make_client()
    loop = asyncio.get_running_loop()

    # ongoing future
    future = loop.create_future()
    client._pending["c"] = future

    # fake listener task
    class FakeTask:
        def __init__(self):
            self.cancelled = False

        def done(self):
            return False

        def cancel(self):
            self.cancelled = True

        def __await__(self):
            try:
                if False:
                    yield
            except asyncio.CancelledError:
                pass

    task = FakeTask()
    client._listener_task = task
    await client.close()
    assert task.cancelled is True
    assert future.cancelled() is True
    assert client._pending == {}
