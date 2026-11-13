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


# ---------------- egress backpressure & sender resilience ----------------
def test_get_outgoing_queue_is_bounded():
    bc = _make_bot_core()
    queue = bc._get_outgoing_queue("u1")
    assert queue.maxsize == 100
    assert bc._outgoing_queues["u1"] is queue
    # repeated calls reuse the same queue
    assert bc._get_outgoing_queue("u1") is queue

@pytest.mark.asyncio
async def test_payload_full_queue_drops_oldest_keeps_latest():
    bc = _make_bot_core()
    bc._ensure_sender_task = MagicMock()
    queue = asyncio.Queue(maxsize=100)
    for i in range(100):
        queue.put_nowait({"action": "reply", "user_id": "u1", "seq": i})
    bc._outgoing_queues["u1"] = queue

    await bc.handle_outgoing_payload(
        {"action": "reply", "user_id": "u1", "seq": 100}
    )

    # queue stays bounded and the newest payload is present
    assert queue.qsize() == 100
    bc.logger.warning.assert_called()

    seqs = []
    while not queue.empty():
        seqs.append(queue.get_nowait()["seq"])
    # oldest (seq 0) was dropped; newest (seq 100) is queued
    assert seqs[0] == 1
    assert 100 in seqs
    assert 0 not in seqs

@pytest.mark.asyncio
async def test_sender_loop_survives_payload_exception():
    bc = _make_bot_core()
    queue = asyncio.Queue()
    bc._outgoing_queues["u1"] = queue
    await queue.put({"action": "reply", "user_id": "u1", "seq": 1})
    await queue.put({"action": "reply", "user_id": "u1", "seq": 2})

    processed = []
    calls = {"n": 0}

    async def flaky(payload):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        processed.append(payload["seq"])

    bc._process_outgoing_payload = flaky

    # After the queue is drained, raise TimeoutError with an empty queue so the
    # loop exits fast instead of blocking on the real 15s timeout.
    original_get = queue.get

    async def get_with_timeout_after_drain():
        if queue.empty():
            raise asyncio.TimeoutError
        return await original_get()

    queue.get = get_with_timeout_after_drain

    await bc._outgoing_sender_loop("u1")

    # first payload raised, loop kept going and processed the next one
    assert calls["n"] == 2
    assert processed == [2]
    # fully drained -> cleanup removes queue and sender
    assert queue.empty()
    assert "u1" not in bc._outgoing_queues
    assert "u1" not in bc._outgoing_senders

@pytest.mark.asyncio
async def test_sender_loop_exit_leaves_queue_in_place_when_nonempty():
    bc = _make_bot_core()
    queue = asyncio.Queue()
    bc._outgoing_queues["u1"] = queue
    queue.put_nowait({"action": "reply", "user_id": "u1", "seq": 1})

    # Force get() to raise a non-timeout error so the loop exits early while
    # items are still queued (simulating an abnormal exit).
    queue.get = AsyncMock(side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        await bc._outgoing_sender_loop("u1")

    # queue is left in place, not popped, so _ensure_sender_task can recreate
    assert "u1" in bc._outgoing_queues
    assert bc._outgoing_queues["u1"] is queue
    assert not queue.empty()

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
