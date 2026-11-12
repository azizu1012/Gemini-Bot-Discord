"""Offline tests for the medium DB mixins (notes, chat, roles) — mock asyncpg."""
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest

sys.path.insert(0, ".")

from src.database.mixins.notes import NotesMixin
from src.database.mixins.chat import ChatMixin
from src.database.mixins.roles import RolesMixin


class FakeConn:
    def __init__(self, pool):
        self.pool = pool
        self.executed = []
        self.fetchrow_result = None
        self.fetchval_result = None
        self.fetch_rows = []
        self.transaction_entered = 0

    async def execute(self, query, *args):
        self.executed.append((query, args))
        self.pool.last_query = query
        self.pool.last_args = args
        # For update/delete command tags used in comparisons.
        if query.strip().upper().startswith("UPDATE"):
            return self.pool.execute_result or "UPDATE 1"
        if query.strip().upper().startswith("DELETE"):
            return self.pool.execute_result or "DELETE 1"
        return "OK 1"

    async def fetchrow(self, query, *args):
        self.pool.last_query = query
        self.pool.last_args = args
        return self.fetchrow_result

    async def fetchval(self, query, *args):
        self.pool.last_query = query
        self.pool.last_args = args
        return self.fetchval_result

    async def fetch(self, query, *args):
        self.pool.last_query = query
        self.pool.last_args = args
        return list(self.fetch_rows)

    @asynccontextmanager
    async def transaction(self):
        self.transaction_entered += 1
        yield self


class FakePool:
    def __init__(self, conn):
        self._conn = conn
        self.last_query = None
        self.last_args = None
        self.execute_result = None

    @asynccontextmanager
    async def acquire(self):
        yield self._conn


def make_conn_pool():
    conn = FakeConn(None)
    pool = FakePool(conn)
    conn.pool = pool
    return conn, pool


def make_owner(pool, *mixins):
    owner = type("Owner", mixins, {})()
    owner.pool = pool

    async def _ensure_pool():
        if owner.pool is None:
            raise RuntimeError("Database pool is not initialized")
        return owner.pool

    owner._ensure_pool = _ensure_pool
    return owner


def _ts():
    return datetime(2026, 11, 12, 10, 0, 0, tzinfo=timezone.utc)


# ================= NotesMixin =================
@pytest.mark.asyncio
async def test_add_user_note_db_dict_metadata():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, NotesMixin)
    assert await owner.add_user_note_db("u1", "n1", "content", {"filename": "a.txt"}) is True
    assert "INSERT INTO user_notes" in pool.last_query
    assert pool.last_args[3] == {"filename": "a.txt"}


@pytest.mark.asyncio
async def test_add_user_note_db_str_metadata():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, NotesMixin)
    assert await owner.add_user_note_db("u1", "n2", "c", '{"x": 1}') is True
    assert pool.last_args[3] == {"x": 1}


@pytest.mark.asyncio
async def test_add_user_note_db_invalid_str_metadata():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, NotesMixin)
    assert await owner.add_user_note_db("u1", "n3", "c", "{bad json") is True
    assert pool.last_args[3] == {}


@pytest.mark.asyncio
async def test_add_user_note_db_other_metadata_type():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, NotesMixin)
    assert await owner.add_user_note_db("u1", "n4", "c", 42) is True
    assert pool.last_args[3] == {}


@pytest.mark.asyncio
async def test_get_file_note_by_filename_found():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, NotesMixin)
    conn.fetchrow_result = {"note_id": "n1", "content": "c", "metadata": "{}", "created_at": _ts()}
    item = await owner.get_file_note_by_filename_db("u1", "a.txt")
    assert item["note_id"] == "n1"
    assert item["created_at"] == _ts().isoformat()
    assert isinstance(item["metadata"], dict)


@pytest.mark.asyncio
async def test_get_file_note_by_filename_not_found():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, NotesMixin)
    conn.fetchrow_result = None
    assert await owner.get_file_note_by_filename_db("u1", "a.txt") is None


@pytest.mark.asyncio
async def test_get_file_note_by_filename_invalid_json_metadata():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, NotesMixin)
    conn.fetchrow_result = {"note_id": "n1", "content": "c", "metadata": "{bad", "created_at": None}
    item = await owner.get_file_note_by_filename_db("u1", "a.txt")
    assert item["metadata"] == {}


@pytest.mark.asyncio
async def test_update_user_note_db_success():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, NotesMixin)
    pool.execute_result = "UPDATE 1"
    assert await owner.update_user_note_db("n1", "u1", "new", {"k": "v"}) is True


@pytest.mark.asyncio
async def test_update_user_note_db_no_match():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, NotesMixin)
    pool.execute_result = "UPDATE 0"
    assert await owner.update_user_note_db("n1", "u1", "new", {"k": "v"}) is False


@pytest.mark.asyncio
async def test_update_user_note_db_invalid_str_metadata():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, NotesMixin)
    pool.execute_result = "UPDATE 1"
    assert await owner.update_user_note_db("n1", "u1", "new", "{bad") is True
    assert pool.last_args[1] == {}


@pytest.mark.asyncio
async def test_delete_user_note_db_success():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, NotesMixin)
    pool.execute_result = "DELETE 1"
    assert await owner.delete_user_note_db("n1", "u1") is True


@pytest.mark.asyncio
async def test_delete_user_note_db_no_match():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, NotesMixin)
    pool.execute_result = "DELETE 0"
    assert await owner.delete_user_note_db("n1", "u1") is False


@pytest.mark.asyncio
async def test_get_user_notes_db_basic():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, NotesMixin)
    conn.fetch_rows = [
        {"note_id": "n1", "content": "c", "metadata": "{}",
         "created_at": _ts(), "updated_at": None, "scope": "user",
         "importance": 0, "note_type": "personal_preference", "fact_hash": ""}
    ]
    rows = await owner.get_user_notes_db("u1")
    assert len(rows) == 1
    assert rows[0]["created_at"] == _ts().isoformat()


@pytest.mark.asyncio
async def test_get_user_notes_db_with_search_and_type():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, NotesMixin)
    conn.fetch_rows = []
    rows = await owner.get_user_notes_db("u1", search_query="q", note_type="fact", include_global=True)
    assert rows == []
    assert "scope = 'global'" in pool.last_query
    assert pool.last_args == ("u1", "fact", "%q%", 20)


@pytest.mark.asyncio
async def test_count_distinct_users_by_fact_hash():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, NotesMixin)
    conn.fetchval_result = 3
    assert await owner.count_distinct_users_by_fact_hash_db("h") == 3
    conn.fetchval_result = None
    assert await owner.count_distinct_users_by_fact_hash_db("h") == 0


@pytest.mark.asyncio
async def test_promote_fact_hash_to_global():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, NotesMixin)
    pool.execute_result = "UPDATE 2"
    assert await owner.promote_fact_hash_to_global_db("h") == 2


@pytest.mark.asyncio
async def test_get_global_notes_db():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, NotesMixin)
    conn.fetch_rows = [
        {"note_id": "g1", "user_id": "u1", "content": "c", "created_at": _ts(),
         "updated_at": _ts(), "scope": "global", "importance": 1,
         "note_type": "global_knowledge", "fact_hash": "h"}
    ]
    rows = await owner.get_global_notes_db(limit=5)
    assert len(rows) == 1
    assert rows[0]["created_at"] == _ts().isoformat()


@pytest.mark.asyncio
async def test_demote_global_note_by_id():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, NotesMixin)
    pool.execute_result = "UPDATE 1"
    assert await owner.demote_global_note_by_id_db("g1") is True
    pool.execute_result = "UPDATE 0"
    assert await owner.demote_global_note_by_id_db("g1") is False


@pytest.mark.asyncio
async def test_demote_global_fact_hash():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, NotesMixin)
    pool.execute_result = "UPDATE 4"
    assert await owner.demote_global_fact_hash_db("h") == 4


@pytest.mark.asyncio
async def test_search_similar_chunks():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, NotesMixin)
    conn.fetch_rows = [
        {"chunk_id": "c1", "document_id": "d1", "content": "x", "chunk_summary": "s",
         "keywords": ["k"], "metadata": "{}", "created_at": _ts()}
    ]
    rows = await owner.search_similar_chunks("text", limit=5)
    assert rows[0]["chunk_id"] == "c1"
    assert rows[0]["created_at"] == _ts().isoformat()


# ================= ChatMixin =================
@pytest.mark.asyncio
async def test_count_user_messages_today_db():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, ChatMixin)
    conn.fetchval_result = 7
    assert await owner.count_user_messages_today_db("u1") == 7
    conn.fetchval_result = None
    assert await owner.count_user_messages_today_db("u1") == 0


@pytest.mark.asyncio
async def test_log_message_db_generates_uuid_when_missing():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, ChatMixin)
    await owner.log_message_db("u1", "user", "hello")
    assert "INSERT INTO messages" in pool.last_query
    assert len(str(pool.last_args[0])) == 36  # uuid4


@pytest.mark.asyncio
async def test_log_message_db_uses_provided_id():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, ChatMixin)
    await owner.log_message_db("u1", "assistant", "reply", message_id="m1")
    assert pool.last_args[0] == "m1"


@pytest.mark.asyncio
async def test_get_user_history_from_db():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, ChatMixin)
    conn.fetch_rows = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]
    rows = await owner.get_user_history_from_db("u1")
    assert rows == [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]


@pytest.mark.asyncio
async def test_count_distinct_message_users_db():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, ChatMixin)
    conn.fetchval_result = 12
    assert await owner.count_distinct_message_users_db() == 12


@pytest.mark.asyncio
async def test_has_other_users_history_db():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, ChatMixin)
    conn.fetchval_result = 1
    assert await owner.has_other_users_history_db("u1") is True
    conn.fetchval_result = None
    assert await owner.has_other_users_history_db("u1") is False


@pytest.mark.asyncio
async def test_search_user_messages_db_exclude_user():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, ChatMixin)
    conn.fetch_rows = [{"user_id": "u2", "content": "q", "timestamp": _ts()}]
    rows = await owner.search_user_messages_db("q", exclude_user_id="u1")
    assert rows[0]["timestamp"] == _ts().isoformat()
    assert pool.last_args[1] == "u1"
    assert pool.last_args[2] == 30


@pytest.mark.asyncio
async def test_search_user_messages_db_no_exclude():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, ChatMixin)
    conn.fetch_rows = []
    rows = await owner.search_user_messages_db("q")
    assert rows == []
    assert "user_id != " not in pool.last_query


@pytest.mark.asyncio
async def test_clear_user_data_db_uses_transaction():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, ChatMixin)
    assert await owner.clear_user_data_db("u1") is True
    assert conn.transaction_entered == 1
    assert any("DELETE FROM messages" in q for q, _ in conn.executed)
    assert any("DELETE FROM user_notes" in q for q, _ in conn.executed)


@pytest.mark.asyncio
async def test_clear_all_data_db_uses_transaction():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, ChatMixin)
    assert await owner.clear_all_data_db() is True
    assert conn.transaction_entered == 1
    assert any("TRUNCATE TABLE messages" in q for q, _ in conn.executed)
    assert any("TRUNCATE TABLE user_notes" in q for q, _ in conn.executed)


# ================= RolesMixin =================
@pytest.mark.asyncio
async def test_add_remove_premium():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, RolesMixin)
    assert await owner.add_premium_user("u1") is True
    assert "INSERT INTO premium_users" in pool.last_query
    pool.execute_result = "DELETE 1"
    assert await owner.remove_premium_user("u1") is True
    pool.execute_result = "DELETE 0"
    assert await owner.remove_premium_user("u1") is False


@pytest.mark.asyncio
async def test_is_premium_user():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, RolesMixin)
    conn.fetchval_result = 1
    assert await owner.is_premium_user("u1") is True
    conn.fetchval_result = None
    assert await owner.is_premium_user("u1") is False


@pytest.mark.asyncio
async def test_add_remove_moderator():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, RolesMixin)
    assert await owner.add_moderator_user("u1") is True
    assert "INSERT INTO moderator_users" in pool.last_query
    pool.execute_result = "DELETE 1"
    assert await owner.remove_moderator_user("u1") is True
    pool.execute_result = "DELETE 0"
    assert await owner.remove_moderator_user("u1") is False


@pytest.mark.asyncio
async def test_is_moderator_user():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, RolesMixin)
    conn.fetchval_result = 1
    assert await owner.is_moderator_user("u1") is True
    conn.fetchval_result = None
    assert await owner.is_moderator_user("u1") is False


@pytest.mark.asyncio
async def test_add_remove_admin():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, RolesMixin)
    assert await owner.add_admin_user("u1") is True
    assert "INSERT INTO admin_users" in pool.last_query
    pool.execute_result = "DELETE 1"
    assert await owner.remove_admin_user("u1") is True
    pool.execute_result = "DELETE 0"
    assert await owner.remove_admin_user("u1") is False


@pytest.mark.asyncio
async def test_is_admin_user():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, RolesMixin)
    conn.fetchval_result = 1
    assert await owner.is_admin_user("u1") is True
    conn.fetchval_result = None
    assert await owner.is_admin_user("u1") is False
