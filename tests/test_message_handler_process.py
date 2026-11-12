"""Offline tests for MessageHandler.process_message early branches."""
import asyncio
import sys
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
