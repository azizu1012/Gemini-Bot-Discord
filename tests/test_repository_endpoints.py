"""Unit tests cho modular database repository (endpoints & model slots) — mock asyncpg.

Chạy offline, KHÔNG cần PostgreSQL thật. Dùng FakePool/FakeConn mô phỏng các
truy vấn asyncpg để kiểm chứng hành vi repository (thêm/sửa/đọc/active
endpoint + model slots). Phù hợp chạy trong CI không có hạ tầng DB.
"""
import asyncio
import os
import sys
from contextlib import asynccontextmanager

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.repository import DatabaseRepository


class FakeConn:
    """Mô phỏng asyncpg connection; duy trì state endpoints/slots in-memory."""

    def __init__(self, pool):
        self.pool = pool

    async def set_type_codec(self, *args, **kwargs):
        return None

    async def fetch(self, query, *args):
        if "FROM llm_model_slots" in query:
            return [
                {"slot": slot, "model_id": model_id}
                for (sdk, slot, model_id) in self.pool.slots
                if sdk == (args[0] if args else None)
            ]
        # llm_endpoints
        return [dict(v) for v in self.pool.endpoints.values()]

    async def fetchrow(self, query, *args):
        if "WHERE is_active = TRUE" in query:
            for v in self.pool.endpoints.values():
                if v["is_active"]:
                    return dict(v)
            return None
        if "FROM llm_endpoints" in query and args:
            v = self.pool.endpoints.get(args[0])
            return dict(v) if v else None
        return None

    async def execute(self, query, *args):
        q = query.strip()
        if q.startswith("INSERT INTO llm_endpoints"):
            sdk, base_url, api_key, updated_by = args
            self.pool.endpoints[sdk] = {
                "sdk": sdk,
                "base_url": base_url,
                "api_key_encrypted": api_key,
                "is_active": False,
                "updated_by": updated_by,
                "last_check_ok": None,
                "last_check_error": None,
            }
            return "INSERT 0 1"
        if q.startswith("UPDATE llm_endpoints SET is_active = FALSE"):
            for v in self.pool.endpoints.values():
                v["is_active"] = False
            return "UPDATE %d" % len(self.pool.endpoints)
        if q.startswith("UPDATE llm_endpoints") and "SET is_active = TRUE" in q:
            sdk, updated_by = args[0], args[1]
            if sdk in self.pool.endpoints:
                self.pool.endpoints[sdk]["is_active"] = True
                self.pool.endpoints[sdk]["updated_by"] = updated_by
                return "UPDATE 1"
            return "UPDATE 0"
        if q.startswith("INSERT INTO llm_model_slots"):
            sdk, slot, model_id, _ = args
            self.pool.slots = [
                (s, sl, m) for (s, sl, m) in self.pool.slots if (s, sl) != (sdk, slot)
            ]
            self.pool.slots.append((sdk, slot, model_id))
            return "INSERT 0 1"
        if q.startswith("UPDATE llm_endpoints") and "last_check_ok" in q:
            sdk, ok, error = args[0], args[1], args[2]
            if sdk in self.pool.endpoints:
                self.pool.endpoints[sdk]["last_check_ok"] = ok
                self.pool.endpoints[sdk]["last_check_error"] = error
            return "UPDATE 1"
        return "UPDATE 1"

    @asynccontextmanager
    async def transaction(self):
        yield self


class FakePool:
    def __init__(self):
        self.endpoints = {}
        self.slots = []

    @asynccontextmanager
    async def acquire(self):
        yield FakeConn(self)

    async def close(self):
        pass


def make_repo() -> DatabaseRepository:
    repo = DatabaseRepository("postgresql://mock")
    repo.pool = FakePool()
    repo._schema_ready = True
    return repo


@pytest.mark.asyncio
async def test_get_llm_endpoints_empty():
    assert await make_repo().get_llm_endpoints() == {}


@pytest.mark.asyncio
async def test_upsert_and_get_endpoints():
    repo = make_repo()
    await repo.upsert_llm_endpoint("genai", "https://example.test", "enc:key", "admin")
    eps = await repo.get_llm_endpoints()
    assert eps["genai"]["base_url"] == "https://example.test"
    assert eps["genai"]["api_key_encrypted"] == "enc:key"
    assert eps["genai"]["is_active"] is False


@pytest.mark.asyncio
async def test_set_active_sdk_switches_and_deactivates_others():
    repo = make_repo()
    await repo.upsert_llm_endpoint("genai", "u1", "k1", "a")
    await repo.upsert_llm_endpoint("openai", "u2", "k2", "a")

    assert await repo.set_active_sdk("genai", "a") is True
    assert await repo.get_active_sdk() == "genai"

    assert await repo.set_active_sdk("openai", "a") is True
    assert await repo.get_active_sdk() == "openai"
    eps = await repo.get_llm_endpoints()
    assert eps["genai"]["is_active"] is False
    assert eps["openai"]["is_active"] is True


@pytest.mark.asyncio
async def test_set_active_sdk_unknown_returns_false():
    assert await make_repo().set_active_sdk("nonexistent", "a") is False


@pytest.mark.asyncio
async def test_save_endpoint_config_activates_and_writes_slots():
    repo = make_repo()
    ok = await repo.save_endpoint_config(
        "genai",
        "https://example.test",
        "enc:key",
        {"reasoning": "m-reasoning", "final": "m-final", "fallback": None},
        "admin",
    )
    assert ok is True
    assert await repo.get_active_sdk() == "genai"
    slots = await repo.get_llm_model_slots("genai")
    assert slots == {"reasoning": "m-reasoning", "final": "m-final", "fallback": None}


@pytest.mark.asyncio
async def test_upsert_model_slots_overwrites_same_slot():
    repo = make_repo()
    await repo.upsert_llm_model_slots("genai", {"final": "m1"}, "a")
    await repo.upsert_llm_model_slots("genai", {"final": "m2"}, "a")
    slots = await repo.get_llm_model_slots("genai")
    assert slots == {"final": "m2"}


@pytest.mark.asyncio
async def test_update_endpoint_check_status():
    repo = make_repo()
    await repo.upsert_llm_endpoint("genai", "u", "k", "a")
    await repo.update_endpoint_check_status("genai", True, None)
    eps = await repo.get_llm_endpoints()
    assert eps["genai"]["last_check_ok"] is True
    assert eps["genai"]["last_check_error"] is None
