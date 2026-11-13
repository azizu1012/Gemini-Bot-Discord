"""Offline tests for BotCore's outgoing-payload handling and Redis setup."""
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, ".")

from src.handlers.discord.bot_core import BotCore


def _make_bot_core():
    bc = object.__new__(BotCore)
    bc.config = MagicMock()
    bc.logger = MagicMock()
    bc._outgoing_queues = {}
    bc._outgoing_senders = {}
    bc.active_typing_tasks = {}
    bc.active_interactions = {}
    bc._interaction_timestamps = {}
    bc._interaction_ttl = 300.0
    bc._pending_outgoing_tasks = set()
    bc._active_user_locks = {}
    bc._delivery_state = {}
    bc._redis_client = None
    bc.bot = MagicMock()
    bc.kafka_service = MagicMock()
    bc._consume_task = None
    bc._outgoing_consumer = None
    return bc


# ---------------- handle_outgoing_payload ----------------
@pytest.mark.asyncio
async def test_payload_without_action_returns():
    bc = _make_bot_core()
    await bc.handle_outgoing_payload({"channel_id": "1"})
    bc.logger.info.assert_called()
    bc._ensure_sender_task = MagicMock()
    # no action -> should NOT create queue/sender
    assert bc._outgoing_queues == {}


@pytest.mark.asyncio
async def test_payload_reply_enqueues():
    bc = _make_bot_core()
    bc._ensure_sender_task = MagicMock()
    queue = asyncio.Queue()
    bc._outgoing_queues["u1"] = queue
    await bc.handle_outgoing_payload({"action": "reply", "user_id": "u1"})
    assert not queue.empty()
    payload = queue.get_nowait()
    assert payload["action"] == "reply"
    bc._ensure_sender_task.assert_called_once_with("u1")


@pytest.mark.asyncio
async def test_payload_reply_batch_enqueues():
    bc = _make_bot_core()
    bc._ensure_sender_task = MagicMock()
    queue = asyncio.Queue()
    bc._outgoing_queues["u2"] = queue
    await bc.handle_outgoing_payload({"action": "reply_batch", "user_id": "u2"})
    assert not queue.empty()


@pytest.mark.asyncio
async def test_payload_typing_active_sends_typing():
    bc = _make_bot_core()
    channel = MagicMock()
    channel.id = 123
    bc.bot.get_channel = MagicMock(return_value=channel)
    bc.bot.http.send_typing = AsyncMock()
    bc.active_typing_tasks["u1"] = MagicMock()
    await bc.handle_outgoing_payload(
        {"action": "typing", "channel_id": "123", "user_id": "u1", "typing": True}
    )
    bc.bot.http.send_typing.assert_awaited_once()


@pytest.mark.asyncio
async def test_payload_slash_reply_delivers_to_interaction():
    bc = _make_bot_core()
    interaction = MagicMock()
    interaction.user.id = 1000
    interaction.channel = MagicMock()
    interaction.followup.send = AsyncMock()
    bc.active_interactions["abc"] = interaction
    bc._sanitize_mentions = AsyncMock(return_value="hello")
    bc._cancel_typing_task = MagicMock()

    await bc.handle_outgoing_payload(
        {"action": "slash_reply", "interaction_id": "abc", "content": "hello"}
    )
    interaction.followup.send.assert_awaited_once()
    assert "abc" not in bc.active_interactions


@pytest.mark.asyncio
async def test_payload_slash_reply_missing_interaction_skips():
    bc = _make_bot_core()
    await bc.handle_outgoing_payload(
        {"action": "slash_reply", "interaction_id": "missing", "content": "x"}
    )
    bc.logger.warning.assert_called()


@pytest.mark.asyncio
async def test_payload_slash_reply_with_file(monkeypatch):
    bc = _make_bot_core()
    interaction = MagicMock()
    interaction.user.id = 5
    interaction.channel = MagicMock()
    interaction.followup.send = AsyncMock()
    bc.active_interactions["i1"] = interaction
    bc._sanitize_mentions = AsyncMock(return_value="content")

    import base64
    b64 = base64.b64encode(b"\x89PNG").decode()

    await bc.handle_outgoing_payload(
        {
            "action": "slash_reply",
            "interaction_id": "i1",
            "content": "content",
            "file_base64": b64,
            "file_name": "img.png",
        }
    )
    interaction.followup.send.assert_awaited_once()
    args = interaction.followup.send.call_args
    assert args.kwargs.get("files")
    assert args.kwargs.get("embed") is not None


# ---------------- setup_redis ----------------
@pytest.mark.asyncio
async def test_setup_redis_starts_consumer_and_loop():
    bc = _make_bot_core()
    consumer = MagicMock()
    consumer.reclaim_pending = AsyncMock(return_value=[])
    bc.kafka_service.start_producer = AsyncMock()
    bc.kafka_service.start_consumer = AsyncMock(return_value=consumer)
    bc.consume_outgoing_loop = AsyncMock()
    await bc.setup_redis()
    assert bc._outgoing_consumer is consumer
    bc.kafka_service.start_consumer.assert_awaited_once()
    # a background task is scheduled, not awaited inline
    assert bc._consume_task is not None


@pytest.mark.asyncio
async def test_setup_redis_error_raises():
    bc = _make_bot_core()
    bc.kafka_service.start_producer = AsyncMock(side_effect=ConnectionError("boom"))
    with pytest.raises(ConnectionError):
        await bc.setup_redis()
    bc.logger.error.assert_called()
