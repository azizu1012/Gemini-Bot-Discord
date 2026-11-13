"""Offline tests for BotCore outgoing reply processing."""
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, ".")

from src.handlers.discord.bot_core import BotCore


class NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


def make_bc():
    bc = object.__new__(BotCore)
    bc.logger = NullLogger()
    bc._outgoing_queues = {}
    bc._outgoing_senders = {}
    bc._pending_outgoing_tasks = set()
    bc.active_typing_tasks = {}
    bc._active_user_locks = {}
    bc._redis_client = None
    bc._delivery_state = {}
    bc._outgoing_consumer = None
    bc.kafka_service = MagicMock()
    bc.bot = MagicMock()
    bc._sanitize_mentions = AsyncMock(side_effect=lambda c, ch, allow: c)
    bc._cancel_typing_task = MagicMock()
    bc._send_message_with_retry = AsyncMock(return_value=MagicMock())
    bc._edit_message_with_retry = AsyncMock(return_value=MagicMock())
    return bc


@pytest.mark.asyncio
async def test_process_outgoing_payload_unknown_action():
    bc = make_bc()
    await bc._process_outgoing_payload({"action": "typing"})  # no-op


@pytest.mark.asyncio
async def test_process_reply_missing_channel():
    bc = make_bc()
    payload = {"action": "reply", "channel_id": ""}
    await bc._process_reply(payload)  # returns early


@pytest.mark.asyncio
async def test_process_reply_channel_not_found():
    bc = make_bc()
    bc.bot.get_channel = MagicMock(return_value=None)
    bc.bot.fetch_channel = AsyncMock(return_value=None)
    await bc._process_reply({"action": "reply", "channel_id": "123", "user_id": "u1"})


@pytest.mark.asyncio
async def test_process_reply_batch_edit_placeholder():
    bc = make_bc()
    channel = MagicMock()
    channel.id = 123
    bc.bot.get_channel = MagicMock(return_value=channel)

    payload = {
        "action": "reply_batch",
        "channel_id": "123",
        "user_id": "u1",
        "chunks": ["single chunk"],
        "chunk_total": 1,
        "mode_hint": "edit_then_batch",
        "reference_message_id": "456",
    }
    await bc._process_reply_batch(payload)
    assert bc._send_message_with_retry.await_count >= 1
    assert bc._edit_message_with_retry.await_count >= 1


@pytest.mark.asyncio
async def test_process_reply_batch_simple():
    bc = make_bc()
    channel = MagicMock()
    bc.bot.get_channel = MagicMock(return_value=channel)
    payload = {
        "action": "reply_batch",
        "channel_id": "1",
        "user_id": "u1",
        "chunks": ["a", "b", "c"],
        "chunk_total": 3,
        "mode_hint": "",
    }
    await bc._process_reply_batch(payload)
    assert bc._send_message_with_retry.await_count == 3


@pytest.mark.asyncio
async def test_process_reply_batch_send_fail_breaks():
    bc = make_bc()
    channel = MagicMock()
    bc.bot.get_channel = MagicMock(return_value=channel)
    bc._send_message_with_retry = AsyncMock(return_value=None)  # all sends fail
    payload = {
        "action": "reply_batch",
        "channel_id": "1",
        "user_id": "u1",
        "chunks": ["a", "b"],
        "chunk_total": 2,
    }
    await bc._process_reply_batch(payload)
    assert bc._send_message_with_retry.await_count == 1  # broke after first failure


@pytest.mark.asyncio
async def test_process_reply_success():
    bc = make_bc()
    channel = MagicMock()
    channel.id = 123
    bc.bot.get_channel = MagicMock(return_value=channel)
    bc._cancel_typing_task = MagicMock()

    payload = {
        "action": "reply",
        "channel_id": "123",
        "user_id": "u1",
        "content": "A direct reply",
        "reference_message_id": "999",
    }
    await bc._process_reply(payload)
    bc._send_message_with_retry.assert_awaited_once()
    bc._cancel_typing_task.assert_called_once_with("u1")


@pytest.mark.asyncio
async def test_consume_outgoing_loop_success():
    bc = make_bc()
    msg = MagicMock()
    msg.value = {"action": "reply", "user_id": "u1"}
    msg.entry_id = "1-1"

    async def breaking_agen():
        yield msg
        raise asyncio.CancelledError()

    consumer = breaking_agen()
    bc.kafka_service.consumers = {"discord-outgoing": consumer}
    bc.handle_outgoing_payload = AsyncMock()

    await bc.consume_outgoing_loop()


@pytest.mark.asyncio
async def test_consume_outgoing_loop_no_consumer():
    bc = make_bc()
    bc.kafka_service.consumers = {}
    await bc.consume_outgoing_loop()


@pytest.mark.asyncio
async def test_run_with_retry_429(monkeypatch):
    import discord

    bc = make_bc()
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            class Fake429(discord.HTTPException):
                def __init__(self):
                    self.status = 429
                    self.retry_after = 0.01
            raise Fake429()
        return "success"

    res = await bc._run_with_retry(flaky, label="test_429", max_attempts=2, base_delay=0.01)
    assert res == "success"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_run_with_retry_server_error(monkeypatch):
    import discord

    bc = make_bc()
    calls = {"n": 0}

    async def flaky_500():
        calls["n"] += 1
        if calls["n"] == 1:
            class Fake502(discord.HTTPException):
                def __init__(self):
                    self.status = 502
            raise Fake502()
        return "ok_after_502"

    res = await bc._run_with_retry(flaky_500, label="test_502", max_attempts=2, base_delay=0.01)
    assert res == "ok_after_502"


@pytest.mark.asyncio
async def test_run_with_retry_oserror_exhausted():
    bc = make_bc()

    async def always_oserror():
        raise OSError("network unreachable")

    with pytest.raises(OSError):
        await bc._run_with_retry(always_oserror, label="test_oserror", max_attempts=2, base_delay=0.01)
