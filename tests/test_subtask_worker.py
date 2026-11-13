"""Offline tests for SearchSubtaskWorker."""
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, ".")

from src.services.messaging.subtask_worker import SearchSubtaskWorker


class NullLogger:
    def info(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


def make_worker():
    worker = object.__new__(SearchSubtaskWorker)
    worker.logger = NullLogger()
    worker.config = MagicMock()
    worker.kafka_service = MagicMock()
    worker.tools_mgr = MagicMock()
    worker._consume_task = None
    return worker


@pytest.mark.asyncio
async def test_process_subtask_missing_correlation_returns():
    worker = make_worker()
    await worker._process_subtask({"query": "q"})
    worker.kafka_service.publish.assert_not_called()


@pytest.mark.asyncio
async def test_process_subtask_publishes_result():
    worker = make_worker()
    worker.tools_mgr.run_search_apis = AsyncMock(return_value="answer")
    worker.kafka_service.publish = AsyncMock()
    await worker._process_subtask(
        {"correlation_id": "c1", "query": "hello", "mode": "general", "user_id": "u1"}
    )
    worker.tools_mgr.run_search_apis.assert_awaited_once_with("hello", "general")
    worker.kafka_service.publish.assert_awaited_once()
    payload = worker.kafka_service.publish.call_args
    assert payload.args[0] == "search-results"
    assert payload.kwargs["payload"]["result"] == "answer"
    assert payload.kwargs["payload"]["correlation_id"] == "c1"


@pytest.mark.asyncio
async def test_process_subtask_error_captured():
    worker = make_worker()
    worker.tools_mgr.run_search_apis = AsyncMock(side_effect=RuntimeError("boom"))
    worker.kafka_service.publish = AsyncMock()
    await worker._process_subtask({"correlation_id": "c2", "query": "q"})
    payload = worker.kafka_service.publish.call_args.kwargs["payload"]
    assert "boom" in payload["error"]
    assert payload["result"] == ""


@pytest.mark.asyncio
async def test_start_worker_failure_shuts_down():
    worker = make_worker()
    worker.kafka_service.start_producer = AsyncMock(side_effect=ConnectionError("x"))
    worker.shutdown = AsyncMock()
    await worker.start_worker()
    worker.shutdown.assert_awaited_once()


@pytest.mark.asyncio
async def test_shutdown_stops_kafka():
    worker = make_worker()
    worker.kafka_service.stop = AsyncMock()
    await worker.shutdown()
    worker.kafka_service.stop.assert_awaited_once()





@pytest.mark.asyncio
async def test_subtask_worker_init_and_consumer_loop(monkeypatch):
    import src.services.messaging.subtask_worker as worker_mod

    monkeypatch.setattr(worker_mod, "RedisStreamService", MagicMock)
    monkeypatch.setattr(worker_mod, "ToolsManager", MagicMock)

    cfg = MagicMock()
    cfg.REDIS_URL = "redis://localhost:6379/0"
    worker = worker_mod.SearchSubtaskWorker(cfg)
    assert worker.config is cfg

    # Test the consumer loop with a breaking consumer
    msg = MagicMock()
    msg.value = {"correlation_id": "c1", "query": "q"}

    async def breaking_agen():
        yield msg
        raise RuntimeError("loop break for test")

    worker.kafka_service.start_producer = AsyncMock()
    worker.kafka_service.start_consumer = AsyncMock(return_value=breaking_agen())
    worker.shutdown = AsyncMock()
    worker._process_subtask = AsyncMock()

    await worker.start_worker()
    worker.shutdown.assert_awaited_once()
