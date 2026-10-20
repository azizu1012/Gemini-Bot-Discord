"""Test NoteManager tóm tắt note qua LLMGateway (offline, không cần mạng)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.llm.base import LLMError
from src.managers.note_manager import NoteManager


class FakeDbRepo:
    def __init__(self):
        self.saved = []
        self.updated = None

    async def add_user_note_db(self, user_id, note_id, content, metadata, scope=None, importance=None, note_type=None, fact_hash=None):
        self.saved.append(content)
        return True

    async def get_file_note_by_filename_db(self, user_id, filename):
        if filename == "existing.txt":
            return {"note_id": "note-1"}
        return None

    async def update_user_note_db(self, note_id, user_id, content, metadata):
        self.updated = (note_id, user_id, content, metadata)
        return True

    async def count_distinct_users_by_fact_hash_db(self, fact_hash):
        return 0

    async def promote_fact_hash_to_global_db(self, fact_hash):
        return 0


class FakeGateway:
    def __init__(self, summary="Tóm tắt ngắn.", error=None):
        self.summary = summary
        self.error = error
        self.calls = []

    async def generate_text(self, prompt, role="final"):
        self.calls.append({"prompt": prompt, "role": role})
        if self.error is not None:
            raise self.error
        return self.summary


def test_long_note_summarized_via_gateway():
    db = FakeDbRepo()
    gw = FakeGateway(summary="Tóm tắt ngắn.")
    nm = NoteManager(db, gateway=gw)
    asyncio.run(nm.save_note_to_db("u1", "x" * 1500, "chat_inference"))
    assert len(gw.calls) == 1
    assert gw.calls[0]["role"] == "final"
    assert gw.calls[0]["prompt"].startswith("Bạn là trợ lý")
    assert db.saved == ["Tóm tắt ngắn."]


def test_short_note_skips_gateway():
    db = FakeDbRepo()
    gw = FakeGateway()
    nm = NoteManager(db, gateway=gw)
    asyncio.run(nm.save_note_to_db("u1", "Ghi chú ngắn", "manual"))
    assert gw.calls == []
    assert db.saved == ["Ghi chú ngắn"]


def test_gateway_error_falls_back_to_truncation():
    db = FakeDbRepo()
    gw = FakeGateway(error=LLMError("rate_limit", "boom"))
    nm = NoteManager(db, gateway=gw)
    asyncio.run(nm.save_note_to_db("u1", "y" * 1500, "manual"))
    assert len(db.saved) == 1
    assert db.saved[0].endswith("...")
    assert len(db.saved[0]) == 1003


def test_file_note_update_is_user_scoped():
    db = FakeDbRepo()
    nm = NoteManager(db, gateway=FakeGateway())
    asyncio.run(nm.save_file_note_to_db("u1", "nội dung mới", "existing.txt"))
    assert db.updated is not None
    assert db.updated[0] == "note-1"
    assert db.updated[1] == "u1"
    assert db.updated[2] == "nội dung mới"


class FailingDbRepo(FakeDbRepo):
    async def add_user_note_db(self, *args, **kwargs):
        raise RuntimeError("db password=super-secret")


def test_save_note_error_is_sanitized():
    nm = NoteManager(FailingDbRepo(), gateway=FakeGateway())
    result = asyncio.run(nm.save_note_to_db("u1", "Ghi chú ngắn", "manual"))
    assert result == "Lỗi khi lưu note. Vui lòng thử lại."
    assert "super-secret" not in result


if __name__ == "__main__":
    test_long_note_summarized_via_gateway()
    test_short_note_skips_gateway()
    test_gateway_error_falls_back_to_truncation()
    print("ALL PASS")
