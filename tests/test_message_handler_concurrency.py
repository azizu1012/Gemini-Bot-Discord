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


def message(user_id):
    return SimpleNamespace(value={"user_id": user_id})


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


def test_image_pipeline_uses_native_vision_capable_roles():
    handler = object.__new__(MessageHandler)
    base = SimpleNamespace(
        reasoning_role="reasoning",
        final_role="final",
        fallback_role="fallback",
    )
    handler._pipeline = base

    normal = handler._pipeline_for_message(False)
    vision = handler._pipeline_for_message(True)

    assert normal is base
    assert vision is base
    assert vision.reasoning_role == "reasoning"
    assert vision.final_role == "final"
    assert vision.fallback_role == "fallback"
    assert base.reasoning_role == "reasoning"
    assert base.final_role == "final"
    assert base.fallback_role == "fallback"
