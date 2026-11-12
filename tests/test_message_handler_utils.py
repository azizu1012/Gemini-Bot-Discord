"""Offline tests for MessageHandler pure text/intent/identity helpers."""
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, ".")

from src.handlers.message_handler import MessageHandler


class NullLogger:
    def info(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass


def make_handler():
    h = object.__new__(MessageHandler)
    h.logger = NullLogger()
    h.config = MagicMock()
    h.db_repo = MagicMock()
    h.tools_mgr = MagicMock()
    h.kafka_service = MagicMock()
    h.gateway = MagicMock()
    return h


def test_normalize_intent_text():
    h = make_handler()
    assert h._normalize_intent_text("  Xin chào  Hà Nội  ") == "xin chao ha noi"
    assert h._normalize_intent_text("") == ""


def test_detect_user_correction_none():
    h = make_handler()
    assert h._detect_user_correction("what is today") == {}


def test_detect_user_correction_marker():
    h = make_handler()
    result = h._detect_user_correction("sai roi, tên tôi là Minh")
    assert result.get("is_user_correction") is True
    assert result.get("active_user_correction")


def test_is_identity_question():
    h = make_handler()
    assert h._is_identity_question("Bạn là ai?") is True
    assert h._is_identity_question("what is your name") is True
    assert h._is_identity_question("thời tiết hôm nay") is False


def test_is_capability_question():
    h = make_handler()
    assert h._is_capability_question("what can you do") is True
    assert h._is_capability_question("capabilities") is True
    assert h._is_capability_question("xin chào") is False


def test_is_cross_user_presence_question():
    h = make_handler()
    assert h._is_cross_user_presence_question("Bạn có chat với ai khác không") is True
    assert h._is_cross_user_presence_question("hello") is False


def test_get_runtime_tool_capabilities_filters_admin_tool():
    from types import SimpleNamespace

    h = make_handler()

    def fake_tool(name, desc):
        return MagicMock(function_declarations=[SimpleNamespace(name=name, description=desc)])

    h.tools_mgr.get_all_tools = MagicMock(
        return_value=[
            fake_tool("calculate", "do math"),
            fake_tool("manage_user_role", "admin only"),
            fake_tool("get_weather", "weather"),
        ]
    )
    caps = h._get_runtime_tool_capabilities(is_admin=False)
    names = [n for n, _ in caps]
    assert "calculate" in names
    assert "manage_user_role" not in names  # filtered for non-admin
    assert "get_weather" in names


def test_get_runtime_tool_capabilities_admin_includes():
    from types import SimpleNamespace

    h = make_handler()
    h.tools_mgr.get_all_tools = MagicMock(
        return_value=[MagicMock(function_declarations=[SimpleNamespace(name="manage_user_role", description="x")])]
    )
    caps = h._get_runtime_tool_capabilities(is_admin=True)
    assert any(n == "manage_user_role" for n, _ in caps)


def test_build_identity_instruction_includes_bot_name():
    h = make_handler()
    h._get_runtime_tool_capabilities = MagicMock(return_value=[("calculate", "math")])
    prompt = h._build_identity_instruction({"is_admin": False, "bot_name": "MyBot"})
    assert "MyBot" in prompt


def test_build_identity_instruction_includes_user_identity():
    h = make_handler()
    h._get_runtime_tool_capabilities = MagicMock(return_value=[])
    prompt = h._build_identity_instruction(
        {"is_admin": False, "user_identity": "likes cats", "bot_name": "Bot"}
    )
    assert "likes cats" in prompt


@pytest.mark.asyncio
async def test_build_admin_cross_user_evidence_no_rows():
    h = make_handler()
    h.db_repo.search_user_messages_db = AsyncMock(return_value=[])
    evidence = await h._build_admin_cross_user_evidence("q", "u1")
    assert "No matching records" in evidence


@pytest.mark.asyncio
async def test_build_admin_cross_user_evidence_rows():
    h = make_handler()
    h.db_repo.search_user_messages_db = AsyncMock(
        return_value=[{"user_id": "u2", "content": "hello there"}]
    )
    evidence = await h._build_admin_cross_user_evidence("hello", "u1")
    assert "u2" in evidence
    assert "hello there" in evidence


def test_split_text_basic():
    h = make_handler()
    text = " ".join(["word"] * 500)
    chunks = h._split_text(text, limit=200)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)


def test_split_text_empty():
    h = make_handler()
    assert h._split_text("") == []
    assert h._split_text("   ") == []


def test_split_text_code_fence_not_split():
    h = make_handler()
    text = "intro\n```python\n" + "x" * 100 + "\n```\noutro"
    chunks = h._split_text(text, limit=150)
    # should not split inside the fence — at least each chunk is stable
    assert any("```" in c for c in chunks)


@pytest.mark.asyncio
async def test_call_pipeline_with_deadline():
    h = make_handler()
    h.config.LLM_TOTAL_TIMEOUT_SECONDS = 10
    pipeline = MagicMock()
    pipeline.call_gemini_api = AsyncMock(return_value="answer")
    result = await h._call_pipeline_with_deadline(pipeline, [], "u1", {})
    assert result == "answer"
    pipeline.call_gemini_api.assert_awaited_once()


@pytest.mark.asyncio
async def test_call_easy_with_deadline_success():
    h = make_handler()
    h._build_identity_instruction = MagicMock(return_value="identity")
    h.gateway = MagicMock()
    response = MagicMock()
    response.candidates = [MagicMock(content=MagicMock(parts=[MagicMock(text="easy answer")]))]
    h.gateway.generate = AsyncMock(return_value=response)
    result = await h._call_easy_with_deadline("hello", "u1", {"bot_name": "Bot"})
    assert result == "easy answer"


@pytest.mark.asyncio
async def test_call_easy_with_deadline_empty_raises():
    h = make_handler()
    h._build_identity_instruction = MagicMock(return_value="")
    h.gateway = MagicMock()
    h.gateway.generate = AsyncMock(return_value=MagicMock(candidates=[]))
    with pytest.raises(ValueError, match="Easy response"):
        await h._call_easy_with_deadline("hi", "u1", {})
