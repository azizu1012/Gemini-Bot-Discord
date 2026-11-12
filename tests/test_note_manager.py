"""Offline tests for NoteManager."""
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, ".")

from src.managers.note_manager import NoteManager


class NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


def make_mgr():
    mgr = NoteManager(db_repo=MagicMock(), gateway=None)
    mgr.logger = NullLogger()
    return mgr


# ---------------- pure helpers ----------------
def test_normalize_fact_text():
    mgr = make_mgr()
    assert mgr._normalize_fact_text("  Hello, World!  ") == "hello world"
    assert mgr._normalize_fact_text("") == ""


def test_classify_note_blocked():
    mgr = make_mgr()
    assert mgr._classify_note("phone number is 0123 and doxing")[0] == "blocked"


def test_classify_note_personal():
    mgr = make_mgr()
    ntype, scope, imp, _ = mgr._classify_note("tôi thích cà phê")
    assert ntype == "personal_preference"
    assert scope == "user"
    assert imp == 6


def test_classify_note_global():
    mgr = make_mgr()
    ntype, scope, imp, fact_hash = mgr._classify_note("Vũ trụ giãn nở không ngừng")
    assert ntype == "global_knowledge"
    assert scope == "candidate_global"
    assert fact_hash


def test_should_include_global():
    mgr = make_mgr()
    assert mgr._should_include_global("best practice gì đó") is True
    assert mgr._should_include_global("tôi thích x") is False
    assert mgr._should_include_global("") is False


# ---------------- get_user_identity ----------------
@pytest.mark.asyncio
async def test_get_user_identity_empty():
    mgr = make_mgr()
    mgr.db_repo.get_user_notes_db = AsyncMock(return_value=[])
    assert await mgr.get_user_identity("u1") == ""


@pytest.mark.asyncio
async def test_get_user_identity_formats():
    mgr = make_mgr()
    mgr.db_repo.get_user_notes_db = AsyncMock(
        return_value=[{"content": "likes coffee"}, {"content": "plays guitar"}]
    )
    identity = await mgr.get_user_identity("u1")
    assert "likes coffee" in identity
    assert "plays guitar" in identity


# ---------------- save_note_to_db ----------------
@pytest.mark.asyncio
async def test_save_note_blocked():
    mgr = make_mgr()
    result = await mgr.save_note_to_db("u1", "số điện thoại 0123", "chat_inference")
    assert "không an toàn" in result


@pytest.mark.asyncio
async def test_save_note_personal_success():
    mgr = make_mgr()
    mgr.db_repo.add_user_note_db = AsyncMock(return_value=True)
    result = await mgr.save_note_to_db("u1", "tôi thích cà phê", "chat_inference")
    assert "Đã ghi nhớ" in result


@pytest.mark.asyncio
async def test_save_note_global_promote():
    mgr = make_mgr()
    mgr.db_repo.add_user_note_db = AsyncMock(return_value=True)
    mgr.db_repo.count_distinct_users_by_fact_hash_db = AsyncMock(return_value=5)
    mgr.db_repo.promote_fact_hash_to_global_db = AsyncMock(return_value=1)
    result = await mgr.save_note_to_db("u1", "Định luật Newton về chuyển động", "chat_inference")
    assert "nâng thành kiến thức chung" in result


@pytest.mark.asyncio
async def test_save_note_global_candidate():
    mgr = make_mgr()
    mgr.db_repo.add_user_note_db = AsyncMock(return_value=True)
    mgr.db_repo.count_distinct_users_by_fact_hash_db = AsyncMock(return_value=1)
    result = await mgr.save_note_to_db("u1", "Trái đất quay quanh mặt trời", "chat_inference")
    assert "candidate" in result


@pytest.mark.asyncio
async def test_save_note_db_failure():
    mgr = make_mgr()
    mgr.db_repo.add_user_note_db = AsyncMock(return_value=False)
    result = await mgr.save_note_to_db("u1", "tôi thích nhạc", "chat_inference")
    assert "Lỗi" in result


@pytest.mark.asyncio
async def test_save_note_summarizes_long_content():
    mgr = make_mgr()
    mgr.gateway = MagicMock()
    mgr.gateway.generate_text = AsyncMock(return_value="tóm tắt ngắn gọn")
    mgr.db_repo.add_user_note_db = AsyncMock(return_value=True)
    mgr.db_repo.count_distinct_users_by_fact_hash_db = AsyncMock(return_value=1)
    long_content = "nội dung " * 200  # >1000 chars
    result = await mgr.save_note_to_db("u1", long_content, "chat_inference")
    assert "candidate" in result
    # content was summarized (short)
    assert len(mgr.db_repo.add_user_note_db.call_args[0][2]) < 200


@pytest.mark.asyncio
async def test_save_note_summary_fallback_truncate():
    mgr = make_mgr()
    mgr.gateway = MagicMock()
    mgr.gateway.generate_text = AsyncMock(side_effect=RuntimeError("llm down"))
    mgr.db_repo.add_user_note_db = AsyncMock(return_value=True)
    long_content = "x" * 2000
    await mgr.save_note_to_db("u1", long_content, "chat_inference")
    assert len(mgr.db_repo.add_user_note_db.call_args[0][2]) <= 1005


# ---------------- save_file_note_to_db ----------------
@pytest.mark.asyncio
async def test_save_file_note_new():
    mgr = make_mgr()
    mgr.db_repo.get_file_note_by_filename_db = AsyncMock(return_value=None)
    mgr.db_repo.add_user_note_db = AsyncMock(return_value=True)
    assert await mgr.save_file_note_to_db("u1", "content", "a.txt") is True
    assert mgr.db_repo.add_user_note_db.call_args.kwargs["note_type"] == "file_note"


@pytest.mark.asyncio
async def test_save_file_note_update():
    mgr = make_mgr()
    mgr.db_repo.get_file_note_by_filename_db = AsyncMock(return_value={"note_id": "n1"})
    mgr.db_repo.update_user_note_db = AsyncMock(return_value=True)
    assert await mgr.save_file_note_to_db("u1", "content", "a.txt") is True
    mgr.db_repo.update_user_note_db.assert_awaited_once()
    assert mgr.db_repo.update_user_note_db.call_args[0][0] == "n1"


# ---------------- retrieve ----------------
@pytest.mark.asyncio
async def test_retrieve_notes_none_found():
    mgr = make_mgr()
    mgr.db_repo.get_user_notes_db = AsyncMock(return_value=[])
    result = await mgr.retrieve_notes_from_db("u1", "anything")
    assert "Không tìm thấy" in result


@pytest.mark.asyncio
async def test_retrieve_notes_formats():
    mgr = make_mgr()
    mgr.db_repo.get_user_notes_db = AsyncMock(
        return_value=[{
            "note_id": "n1",
            "content": "some note",
            "created_at": "2026-01-01",
            "scope": "user",
            "note_type": "personal_preference",
            "metadata": {"type": "auto_note", "source": "chat_inference"},
        }]
    )
    result = await mgr.retrieve_notes_from_db("u1", "note")
    assert "n1" in result
    assert "some note" in result


@pytest.mark.asyncio
async def test_delete_note_success():
    mgr = make_mgr()
    mgr.db_repo.delete_user_note_db = AsyncMock(return_value=True)
    assert await mgr.delete_note_from_db("u1", "n1") == "Đã xóa note thành công."


@pytest.mark.asyncio
async def test_delete_note_failure():
    mgr = make_mgr()
    mgr.db_repo.delete_user_note_db = AsyncMock(return_value=False)
    result = await mgr.delete_note_from_db("u1", "n1")
    assert "Không thể xóa" in result
