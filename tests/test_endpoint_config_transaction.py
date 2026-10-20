"""Unit tests for atomic endpoint configuration persistence."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.mixins.endpoints import EndpointsMixin


class FakeTransaction:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        self.conn.transaction_open = True
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.conn.transaction_open = False
        self.conn.transaction_exc = exc_type
        return False


class FakeConnection:
    def __init__(self):
        self.calls = []
        self.transaction_open = False
        self.transaction_exc = None

    def transaction(self):
        return FakeTransaction(self)

    async def execute(self, sql, *args):
        assert self.transaction_open is True
        self.calls.append((sql, args))
        if "SET is_active = TRUE" in sql:
            return "UPDATE 1"
        return "INSERT 0 1"


class FailingConnection(FakeConnection):
    async def execute(self, sql, *args):
        if "llm_model_slots" in sql:
            raise RuntimeError("slot write failed")
        return await super().execute(sql, *args)


class InactiveConnection(FakeConnection):
    async def execute(self, sql, *args):
        if "SET is_active = TRUE" in sql:
            assert self.transaction_open is True
            self.calls.append((sql, args))
            return "UPDATE 0"
        return await super().execute(sql, *args)


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


class Repo(EndpointsMixin):
    def __init__(self, pool):
        self.pool = pool

    async def _ensure_pool(self):
        return self.pool


def _save(repo):
    return asyncio.run(
        repo.save_endpoint_config(
            "genai",
            "http://127.0.0.1:58100",
            "fernet:test",
            {"reasoning": "m1", "final": "m2", "fallback": None},
            "admin:1",
        )
    )


def test_save_endpoint_config_writes_everything_in_one_transaction():
    conn = FakeConnection()
    repo = Repo(FakePool(conn))

    assert _save(repo) is True
    assert conn.transaction_exc is None
    assert len(conn.calls) == 6
    assert "INSERT INTO llm_endpoints" in conn.calls[0][0]
    assert "INSERT INTO llm_model_slots" in conn.calls[1][0]
    assert "is_active = FALSE" in conn.calls[4][0]
    assert "SET is_active = TRUE" in conn.calls[5][0]


def test_save_endpoint_config_rolls_back_on_slot_failure():
    conn = FailingConnection()
    repo = Repo(FakePool(conn))

    try:
        _save(repo)
    except RuntimeError as exc:
        assert str(exc) == "slot write failed"
    else:
        raise AssertionError("expected slot write failure")

    assert conn.transaction_exc is RuntimeError


def test_save_endpoint_config_fails_if_activation_updates_no_row():
    conn = InactiveConnection()
    repo = Repo(FakePool(conn))

    try:
        _save(repo)
    except RuntimeError as exc:
        assert "Failed to activate endpoint" in str(exc)
    else:
        raise AssertionError("expected activation failure")

    assert conn.transaction_exc is RuntimeError
