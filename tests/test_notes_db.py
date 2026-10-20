"""Unit tests for user-scoped note database operations."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.mixins.notes import NotesMixin


class FakeConnection:
    def __init__(self):
        self.calls = []

    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        return "UPDATE 1"


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return FakeAcquire(self.conn)


class Repo(NotesMixin):
    def __init__(self, pool):
        self.pool = pool

    async def _ensure_pool(self):
        return self.pool


def test_update_user_note_is_scoped_by_user():
    conn = FakeConnection()
    repo = Repo(FakePool(conn))

    ok = asyncio.run(repo.update_user_note_db("note-1", "user-1", "content", {}))

    assert ok is True
    assert len(conn.calls) == 1
    sql, args = conn.calls[0]
    assert "note_id = $3" in sql
    assert "user_id = $4" in sql
    assert args == ("content", {}, "note-1", "user-1")
