"""Message worker concurrency: global limit, per-user serialization."""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

        async def claim_message_once(self, _message_id):
            self.claims += 1
            return self.claims == 1

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
