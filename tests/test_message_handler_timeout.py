"""The full pipeline call must be bounded by LLM_TOTAL_TIMEOUT_SECONDS."""
import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.handlers.message_handler import MessageHandler


def make_handler(timeout_seconds, call):
    handler = object.__new__(MessageHandler)
    handler.config = SimpleNamespace(LLM_TOTAL_TIMEOUT_SECONDS=timeout_seconds)
    handler._pipeline = SimpleNamespace(call_gemini_api=call)
    return handler


def test_deadline_returns_fast_result():
    async def fast(messages, user_id, privacy_context):
        return "ok"

    handler = make_handler(1, fast)
    assert asyncio.run(handler._call_pipeline_with_deadline(handler._pipeline, [], "u", {})) == "ok"


def test_deadline_raises_timeout_for_slow_pipeline():
    async def slow(messages, user_id, privacy_context):
        await asyncio.sleep(0.2)
        return "late"

    handler = make_handler(0.05, slow)
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(handler._call_pipeline_with_deadline(handler._pipeline, [], "u", {}))
