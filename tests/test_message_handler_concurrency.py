"""Message worker concurrency: global limit, per-user serialization."""
import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import OrderedDict

from src.handlers.message_handler import MessageHandler


def make_handler(limit):
    handler = object.__new__(MessageHandler)
    handler.config = SimpleNamespace(MAX_CONCURRENT_MESSAGES=limit)
    handler._worker_semaphore = asyncio.Semaphore(limit)
    handler._user_locks = {}
    return handler


def message(user_id, message_id=None):
    value = {"user_id": user_id}
    if message_id is not None:
        value["message_id"] = message_id
    return SimpleNamespace(value=value)


def install_tracker(handler):
    state = {"active": 0, "max_active": 0}

    async def fake_process(msg):
        state["active"] += 1
        state["max_active"] = max(state["max_active"], state["active"])
        await asyncio.sleep(0.05)
        state["active"] -= 1

    handler.process_message = fake_process
    return state


def test_different_users_run_concurrently():
    handler = make_handler(2)
    state = install_tracker(handler)

    async def run():
        await asyncio.gather(
            handler._process_message_guarded(message("u1")),
            handler._process_message_guarded(message("u2")),
        )

    asyncio.run(run())
    assert state["max_active"] == 2


def test_global_concurrency_limit_is_enforced():
    handler = make_handler(2)
    state = install_tracker(handler)

    async def run():
        await asyncio.gather(
            handler._process_message_guarded(message("u1")),
            handler._process_message_guarded(message("u2")),
            handler._process_message_guarded(message("u3")),
        )

    asyncio.run(run())
    assert state["max_active"] == 2


def test_same_user_messages_are_serialized():
    handler = make_handler(3)
    state = install_tracker(handler)

    async def run():
        await asyncio.gather(
            handler._process_message_guarded(message("u1")),
            handler._process_message_guarded(message("u1")),
        )

    asyncio.run(run())
    assert state["max_active"] == 1


def test_duplicate_message_is_claimed_once():
    handler = make_handler(1)
    handler.logger = SimpleNamespace(warning=lambda _message: None)
    handler._incoming_consumer = None

    class FakeKafka:
        def __init__(self):
            self.claims = 0

        async def claim_message_once(self, _message_id, **_kwargs):
            self.claims += 1
            return self.claims == 1

        is_message_completed = AsyncMock(return_value=False)
        release_message_claim = AsyncMock()

    handler.kafka_service = FakeKafka()
    calls = []

    async def fake_process(_msg):
        calls.append(True)

    handler.process_message = fake_process
    async def run():
        await asyncio.gather(
            handler._process_message_guarded(message("u1", "m1")),
            handler._process_message_guarded(message("u1", "m1")),
        )

    asyncio.run(run())
    assert len(calls) == 1


def make_lock_handler(max_locks):
    handler = make_handler(limit=1)
    handler._MAX_USER_LOCKS = max_locks
    handler._user_locks = OrderedDict()
    return handler


@pytest.mark.asyncio
async def test_eviction_preserves_held_lock():
    """Eviction must not remove a lock that is currently held (locked)."""
    handler = make_lock_handler(max_locks=2)
    lock_a = handler._get_user_lock("u1")
    await lock_a.acquire()
    try:
        handler._get_user_lock("u2")
        # Fill past the cap; u1 is held, so it must survive eviction.
        handler._get_user_lock("u3")
        handler._get_user_lock("u4")
        assert "u1" in handler._user_locks
        assert lock_a.locked()
    finally:
        lock_a.release()


@pytest.mark.asyncio
async def test_eviction_stops_when_all_locks_are_held():
    """When every lock is in use, eviction stops rather than shrinking below the held count."""
    handler = make_lock_handler(max_locks=2)
    lock_a = handler._get_user_lock("u1")
    lock_b = handler._get_user_lock("u2")
    await lock_a.acquire()
    await lock_b.acquire()
    try:
        # Both held locks and the newest lock must survive. The older idle
        # u3 lock may be evicted when u4 is created.
        handler._get_user_lock("u3")
        lock_d = handler._get_user_lock("u4")
        assert list(handler._user_locks.keys()) == ["u1", "u2", "u4"]
        assert handler._user_locks["u4"] is lock_d
        assert lock_a.locked()
        assert lock_b.locked()
    finally:
        lock_a.release()
        lock_b.release()


def test_lru_move_to_end_still_works():
    """Re-requesting a lock moves it to the end of the OrderedDict (LRU)."""
    handler = make_lock_handler(max_locks=10)
    handler._get_user_lock("u1")
    handler._get_user_lock("u2")
    handler._get_user_lock("u3")
    assert list(handler._user_locks.keys()) == ["u1", "u2", "u3"]
    handler._get_user_lock("u1")
    assert list(handler._user_locks.keys()) == ["u2", "u3", "u1"]


@pytest.mark.asyncio
async def test_eviction_preserves_lock_during_waiter_handoff():
    handler = make_lock_handler(max_locks=1)
    handler.process_message = AsyncMock()
    original = handler._get_user_lock("u1")
    await original.acquire()
    waiter = asyncio.create_task(handler._process_message_guarded(message("u1")))
    try:
        await asyncio.sleep(0)
        original.release()
        # The waiter has been woken but has not yet resumed: locked() is false.
        handler._get_user_lock("u2")
        assert handler._get_user_lock("u1") is original
    finally:
        await waiter


class LeaseService:
    """Shared lease/completion state for worker redelivery tests."""

    def __init__(self):
        self.leases = {}
        self.completed = set()

    async def claim_message_once(self, message_id, *, token="legacy-owner"):
        if message_id in self.leases or message_id in self.completed:
            return False
        self.leases[message_id] = token
        return True

    async def is_message_completed(self, message_id):
        return message_id in self.completed

    async def complete_message(self, message_id, token):
        assert self.leases[message_id] == token
        self.completed.add(message_id)
        del self.leases[message_id]

    async def release_message_claim(self, message_id, token):
        if self.leases.get(message_id) == token:
            del self.leases[message_id]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_failed_or_cancelled_claim_can_retry_then_deduplicate(failure):
    handler = make_handler(1)
    handler.logger = MagicMock()
    handler.kafka_service = LeaseService()
    handler._incoming_consumer = SimpleNamespace(ack=AsyncMock())
    handler.process_message = AsyncMock(side_effect=failure())
    with pytest.raises(failure):
        await handler._process_message_guarded(message("u1", "m1"))
    assert handler.kafka_service.leases == {}
    assert handler.kafka_service.completed == set()
    handler._incoming_consumer.ack.assert_not_awaited()

    handler.process_message = AsyncMock(side_effect=handler._ack_incoming)
    await handler._process_message_guarded(message("u1", "m1"))
    await handler._process_message_guarded(message("u1", "m1"))
    handler.process_message.assert_awaited_once()
    assert handler._incoming_consumer.ack.await_count == 2
    assert handler.kafka_service.completed == {"m1"}


@pytest.mark.asyncio
async def test_active_duplicate_is_not_acked_or_marked_completed():
    handler = make_handler(1)
    handler.logger = MagicMock()
    handler.kafka_service = LeaseService()
    handler.kafka_service.leases["m1"] = "another-worker"
    handler._incoming_consumer = SimpleNamespace(ack=AsyncMock())
    handler.process_message = AsyncMock()
    await handler._process_message_guarded(message("u1", "m1"))
    handler.process_message.assert_not_awaited()
    handler._incoming_consumer.ack.assert_not_awaited()
    assert handler.kafka_service.leases["m1"] == "another-worker"


@pytest.mark.asyncio
async def test_unacked_processing_releases_claim_without_marking_complete():
    handler = make_handler(1)
    handler.logger = MagicMock()
    handler.kafka_service = LeaseService()
    handler.process_message = AsyncMock()  # e.g. both main and busy publishes failed
    await handler._process_message_guarded(message("u1", "m1"))
    await handler._process_message_guarded(message("u1", "m1"))
    assert handler.process_message.await_count == 2
    assert handler.kafka_service.completed == set()
