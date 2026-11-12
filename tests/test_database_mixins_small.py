"""Offline tests for the small DB mixins (schema, state, audit) — mock asyncpg.

Like test_repository_endpoints.py, these use FakePool/FakeConn so all tests
run without a real PostgreSQL server. Cross-layer checks: these mixins are
in src.database and must not import upward; tests only exercise DB logic.
"""
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest

sys.path.insert(0, ".")

from src.database.mixins.schema import SchemaMixin
from src.database.mixins.state import StateMixin
from src.database.mixins.audit import AuditMixin


class FakeConn:
    """Records executed SQL and returns scripted query results."""

    def __init__(self, pool):
        self.pool = pool
        self.executed = []
        self.fetchrow_result = None
        self.fetchval_result = None
        self.fetch_rows = []

    async def execute(self, query, *args):
        self.executed.append((query, args))
        self.pool.last_query = query
        self.pool.last_args = args
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


class FakePool:
    def __init__(self, conn):
        self._conn = conn
        self.last_query = None
        self.last_args = None

    @asynccontextmanager
    async def acquire(self):
        yield self._conn


def make_conn_pool():
    """Build a FakeConn<->FakePool pair wired together."""
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


# ---------------- SchemaMixin ----------------
def test_initialize_schema_runs_ddl_and_drop_legacy():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, SchemaMixin)

    class _Async:
        def __init__(self, cm):
            self.cm = cm

        async def __aenter__(self):
            return self.cm

        async def __aexit__(self, *exc):
            return False

    # override acquire with plain async context manager returning conn
    async def _acquire():
        return conn

    # Since acquire() is async, wrap: use an async CM here.
    pool.acquire = lambda: _Async(conn)

    async def run():
        await owner._initialize_schema()

    import asyncio

    asyncio.run(run())

    all_sql = " ".join(q for q, _ in conn.executed)
    assert "CREATE TABLE IF NOT EXISTS messages" in all_sql
    assert "CREATE EXTENSION IF NOT EXISTS pg_trgm" in all_sql
    assert "CREATE INDEX IF NOT EXISTS idx_user_notes_metadata_gin" in all_sql
    # Legacy tables are dropped.
    assert "DROP TABLE IF EXISTS" in all_sql


def test_initialize_schema_raises_without_pool():
    owner = make_owner(None, SchemaMixin)

    async def run():
        await owner._initialize_schema()

    import asyncio

    with pytest.raises(RuntimeError, match="pool is not initialized"):
        asyncio.run(run())


def test_backup_db_is_noop():
    owner = make_owner(None, SchemaMixin)

    async def run():
        result = await owner.backup_db()
        assert result is None

    import asyncio

    asyncio.run(run())


@pytest.mark.asyncio
async def test_cleanup_db_vacuumms():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, SchemaMixin)

    class _Async:
        def __init__(self, cm):
            self.cm = cm

        async def __aenter__(self):
            return self.cm

        async def __aexit__(self, *exc):
            return False

    pool.acquire = lambda: _Async(conn)

    await owner.cleanup_db()
    assert any("VACUUM" in q for q, _ in conn.executed)


# ---------------- StateMixin ----------------
def test_set_processing_state_acquires_lock():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, StateMixin)

    class _Async:
        def __init__(self, cm):
            self.cm = cm

        async def __aenter__(self):
            return self.cm

        async def __aexit__(self, *exc):
            return False

    pool.acquire = lambda: _Async(conn)

    async def run():
        return await owner.set_user_processing_state("u1", "working")

    import asyncio

    # row returned → returns None
    conn.fetchrow_result = {"current_stage": "working"}
    assert asyncio.run(run()) is None
    assert "INSERT INTO user_processing_states" in pool.last_query


@pytest.mark.asyncio
async def test_set_processing_state_busy_returns_stage():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, StateMixin)

    class _Async:
        def __init__(self, cm):
            self.cm = cm

        async def __aenter__(self):
            return self.cm

        async def __aexit__(self, *exc):
            return False

    pool.acquire = lambda: _Async(conn)

    conn.fetchrow_result = None  # conflict not matched
    conn.fetchval_result = "đang bận"

    assert await owner.set_user_processing_state("u1", "working") == "đang bận"


@pytest.mark.asyncio
async def test_clear_processing_state_updates_row():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, StateMixin)

    class _Async:
        def __init__(self, cm):
            self.cm = cm

        async def __aenter__(self):
            return self.cm

        async def __aexit__(self, *exc):
            return False

    pool.acquire = lambda: _Async(conn)

    await owner.clear_user_processing_state("u1")
    assert "UPDATE user_processing_states" in pool.last_query
    assert pool.last_args == ("u1",)


# ---------------- AuditMixin ----------------
@pytest.mark.asyncio
async def test_log_usage_inserts():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, AuditMixin)

    class _Async:
        def __init__(self, cm):
            self.cm = cm

        async def __aenter__(self):
            return self.cm

        async def __aexit__(self, *exc):
            return False

    pool.acquire = lambda: _Async(conn)

    assert await owner.log_usage("u1", "reasoning", "modelX", 10, "{}") is True
    assert "INSERT INTO usage_logs" in pool.last_query
    assert pool.last_args == ("u1", "reasoning", "modelX", 10, "{}")


@pytest.mark.asyncio
async def test_log_web_search_inserts():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, AuditMixin)

    class _Async:
        def __init__(self, cm):
            self.cm = cm

        async def __aenter__(self):
            return self.cm

        async def __aexit__(self, *exc):
            return False

    pool.acquire = lambda: _Async(conn)

    assert await owner.log_web_search("u1", "question", "results") is True
    assert "INSERT INTO web_history" in pool.last_query


@pytest.mark.asyncio
async def test_get_web_history_returns_isoformat_dates():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, AuditMixin)

    class _Async:
        def __init__(self, cm):
            self.cm = cm

        async def __aenter__(self):
            return self.cm

        async def __aexit__(self, *exc):
            return False

    pool.acquire = lambda: _Async(conn)

    ts = datetime(2026, 11, 12, 10, 0, 0, tzinfo=timezone.utc)
    conn.fetch_rows = [{"query": "? ", "results": "r", "timestamp": ts}]

    rows = await owner.get_web_history("u1", limit=10)
    assert rows[0]["timestamp"] == ts.isoformat()
    assert rows[0]["query"] == "? "
    assert pool.last_args == ("u1", 10)


@pytest.mark.asyncio
async def test_get_web_history_clamps_limit():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, AuditMixin)

    class _Async:
        def __init__(self, cm):
            self.cm = cm

        async def __aenter__(self):
            return self.cm

        async def __aexit__(self, *exc):
            return False

    pool.acquire = lambda: _Async(conn)
    conn.fetch_rows = []

    await owner.get_web_history("u1", limit=999)
    assert pool.last_args == ("u1", 100)


@pytest.mark.asyncio
async def test_save_generated_image_inserts():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, AuditMixin)

    class _Async:
        def __init__(self, cm):
            self.cm = cm

        async def __aenter__(self):
            return self.cm

        async def __aexit__(self, *exc):
            return False

    pool.acquire = lambda: _Async(conn)

    assert await owner.save_generated_image("u1", "a cat", "http://img") is True
    assert "INSERT INTO generated_images" in pool.last_query


@pytest.mark.asyncio
async def test_get_generated_images_returns_isoformat_dates():
    conn, pool = make_conn_pool()
    owner = make_owner(pool, AuditMixin)

    class _Async:
        def __init__(self, cm):
            self.cm = cm

        async def __aenter__(self):
            return self.cm

        async def __aexit__(self, *exc):
            return False

    pool.acquire = lambda: _Async(conn)

    ts = datetime(2026, 11, 12, 9, 0, 0, tzinfo=timezone.utc)
    conn.fetch_rows = [{"prompt": "p", "image_url": "u", "timestamp": ts}]

    rows = await owner.get_generated_images("u1")
    assert rows[0]["timestamp"] == ts.isoformat()
