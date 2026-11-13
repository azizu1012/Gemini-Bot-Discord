"""Offline tests for MessageHandler.process_message early branches."""
import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, ".")

from src.handlers.message_handler import MessageHandler
from src.services.messaging.redis_client import _RedisMsg


class NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass

    def exception(self, *a, **k):
        pass


def make_handler():
    h = object.__new__(MessageHandler)
    h.logger = NullLogger()
    h.config = MagicMock()
    h.cache_mgr = MagicMock()
    h.db_repo = MagicMock()
    h.resolver = MagicMock()
    h.premium_mgr = MagicMock()
    h._incoming_consumer = None
    h._publish_outgoing = AsyncMock()
    h._image_download_sem = asyncio.Semaphore(1)
    h.kafka_service = MagicMock()
    h.db_repo.clear_user_processing_state = AsyncMock()
    h.db_repo.set_user_processing_state = AsyncMock(return_value=None)
    return h


def make_msg(payload):
    return _RedisMsg(value=payload, key="k", entry_id="1-1")


@pytest.mark.asyncio
async def test_process_cache_invalidation():
    h = make_handler()
    h.cache_mgr.invalidate_chat_history = MagicMock()
    await h.process_message(make_msg({"type": "invalidate_cache", "user_id": "u1"}))
    h.cache_mgr.invalidate_chat_history.assert_called_once_with("u1")


@pytest.mark.asyncio
async def test_process_cache_invalidation_all():
    h = make_handler()
    h.cache_mgr.clear_all_caches = MagicMock()
    await h.process_message(make_msg({"type": "invalidate_all_cache"}))
    h.cache_mgr.clear_all_caches.assert_called_once()


@pytest.mark.asyncio
async def test_process_no_user_id():
    h = make_handler()
    consumer = MagicMock()
    consumer.ack = AsyncMock()
    h._incoming_consumer = consumer
    await h.process_message(make_msg({"type": "message", "content": "hi"}))
    consumer.ack.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_slash_command_dispatch():
    h = make_handler()
    h.process_slash_command = AsyncMock()
    consumer = MagicMock()
    consumer.ack = AsyncMock()
    h._incoming_consumer = consumer
    await h.process_message(make_msg({"type": "slash_command", "user_id": "u1", "command": "imagine"}))
    h.process_slash_command.assert_awaited_once()
    consumer.ack.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_not_configured_publishes_warning():
    h = make_handler()
    h.resolver.is_configured = AsyncMock(return_value=False)
    await h.process_message(make_msg({"type": "message", "user_id": "u1", "content": "hi", "channel_id": "c1"}))
    h._publish_outgoing.assert_awaited_once()
    payload = h._publish_outgoing.call_args[0][0]
    assert payload["action"] == "reply"
    assert "chưa được cấu hình" in payload["content"]


@pytest.mark.asyncio
async def test_process_daily_limit_reached(monkeypatch):
    """Free-tier user at the daily limit gets the limit reply and returns."""

    h = make_handler()
    h.resolver.is_configured = AsyncMock(return_value=True)
    h.premium_mgr.is_admin_user = AsyncMock(return_value=False)
    h.premium_mgr.is_moderator_user = AsyncMock(return_value=False)
    h.premium_mgr.is_premium_user = AsyncMock(return_value=False)
    h.db_repo.count_user_messages_today_db = AsyncMock(return_value=50)

    # patch the rest of the pipeline so it can't run if the branch does not return
    h._process_message_guarded = AsyncMock()

    await h.process_message(make_msg({"type": "message", "user_id": "u1", "content": "hi", "channel_id": "c1", "message_id": "m1"}))
    h._publish_outgoing.assert_awaited()
    first_payload = h._publish_outgoing.call_args_list[0][0][0]
    assert first_payload["action"] == "reply"
    assert "giới hạn" in first_payload["content"]


def make_full_handler(monkeypatch):
    """Handler configured for the full, successful message-processing path."""
    h = make_handler()
    h.resolver.is_configured = AsyncMock(return_value=True)
    h.premium_mgr.is_admin_user = AsyncMock(return_value=False)
    h.premium_mgr.is_moderator_user = AsyncMock(return_value=False)
    h.premium_mgr.is_premium_user = AsyncMock(return_value=False)
    h.db_repo.count_user_messages_today_db = AsyncMock(return_value=0)
    h.db_repo.log_message_db = AsyncMock()
    h.db_repo.count_distinct_message_users_db = AsyncMock(return_value=0)
    h.db_repo.has_other_users_history_db = AsyncMock(return_value=False)
    h.db_repo.get_user_history_from_db = AsyncMock(return_value=[])
    h.note_mgr = MagicMock()
    h.note_mgr.get_user_identity = AsyncMock(return_value="")
    h.tools_mgr = MagicMock()
    h.tools_mgr.pop_allowed_mentions = MagicMock(return_value=[])
    h.tools_mgr.vision = None
    h._pipeline = MagicMock()
    h._call_pipeline_with_deadline = AsyncMock(return_value="Chào bạn!")
    h.cache_mgr.get_chat_history = MagicMock(return_value=None)
    h.cache_mgr.set_chat_history = MagicMock()
    # Force the full (non-EASY) pipeline path so the main reply is a
    # reply_batch publish.
    monkeypatch.setattr("src.handlers.message_handler.classify", lambda text: ("HARD", 0.0))
    consumer = MagicMock()
    consumer.ack = AsyncMock()
    h._incoming_consumer = consumer
    return h, consumer


def make_normal_msg():
    return make_msg({"type": "message", "user_id": "u1", "content": "hi", "channel_id": "c1"})


@pytest.mark.asyncio
async def test_process_main_reply_success_acks_message(monkeypatch):
    """When the main reply publish succeeds, the message is ACKed once."""
    h, consumer = make_full_handler(monkeypatch)
    await h.process_message(make_normal_msg())
    consumer.ack.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_main_reply_fails_busy_succeeds_acks(monkeypatch):
    """Main reply publish fails, but the busy reply succeeds -> still ACKed."""
    h, consumer = make_full_handler(monkeypatch)

    async def flaky_publish(payload, user_id):
        if payload.get("action") == "reply_batch":
            raise RuntimeError("main publish failed")

    h._publish_outgoing = flaky_publish
    await h.process_message(make_normal_msg())
    consumer.ack.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_main_and_busy_publish_fail_message_not_acked(monkeypatch):
    """Both the main and the busy reply publishes fail -> NOT ACKed."""
    h, consumer = make_full_handler(monkeypatch)

    async def failing_publish(payload, user_id):
        action = payload.get("action")
        if action == "reply_batch":
            raise RuntimeError("main publish failed")
        if action == "reply" and "bận" in payload.get("content", ""):
            raise RuntimeError("busy publish failed")

    h._publish_outgoing = failing_publish
    await h.process_message(make_normal_msg())
    consumer.ack.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_sets_and_clears_processing_state(monkeypatch):
    """set_user_processing_state is called during processing; clear runs in finally."""
    h, consumer = make_full_handler(monkeypatch)
    await h.process_message(make_normal_msg())
    h.db_repo.set_user_processing_state.assert_awaited_once_with("u1", "processing")
    h.db_repo.clear_user_processing_state.assert_awaited_once_with("u1")


@pytest.mark.asyncio
async def test_start_worker_reclaims_pending_at_startup_and_periodically():
    """Periodic reclaim runs alongside the startup reclaim.

    start_worker calls consumer.reclaim_pending(min_idle_ms=30000) once at
    startup, then spawns a background task (_periodic_reclaim) that keeps
    calling it every RECLAIM_PENDING_INTERVAL_SECONDS. We verify both by
    setting a tiny interval, leaving the worker's consumer loop blocked on a
    gate so the periodic task can fire several times before we shut the
    worker down.
    """
    h = make_handler()
    h.config = SimpleNamespace(RECLAIM_PENDING_INTERVAL_SECONDS=60)
    h.db_repo.init_db = AsyncMock()
    h.db_repo.close = AsyncMock()
    h.kafka_service.start_producer = AsyncMock()
    h.kafka_service.stop = AsyncMock()
    h.search_subtask_client = MagicMock()
    h.search_subtask_client.close = AsyncMock()
    h._worker_tasks = set()

    consumer = MagicMock()
    consumer.reclaim_pending = AsyncMock(return_value=[])
    # Keep the worker's consume loop alive until we release the gate.
    gate = asyncio.Event()

    async def blocking_consumer():
        await gate.wait()
        if False:
            yield None

    consumer.__aiter__ = lambda self: blocking_consumer()
    h.kafka_service.start_consumer = AsyncMock(return_value=consumer)
    h._process_message_guarded = AsyncMock()

    # Force the periodic loop's interval to something tiny (1 ms) so the
    # background reclaim task calls reclaim_pending in real time while we let
    # the worker run briefly.
    h.config.RECLAIM_PENDING_INTERVAL_SECONDS = 0.001

    worker = asyncio.create_task(h.start_worker())

    # Give the periodic background task time to fire several times.
    await asyncio.sleep(0.05)

    # Periodic reclaim loop fired at least once after the startup reclaim.
    assert consumer.reclaim_pending.await_count >= 2
    consumer.reclaim_pending.assert_awaited_with(min_idle_ms=30000)

    # Release the consume loop so the worker shuts down cleanly.
    gate.set()
    await worker

    # Worker cleaned up its background tasks.
    assert h._worker_tasks == set()
    h.kafka_service.stop.assert_awaited_once()
    h.db_repo.close.assert_awaited_once()
