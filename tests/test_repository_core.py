"""Offline tests for DatabaseRepository core (init/close/_ensure_pool)."""
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, ".")

from src.database.repository import DatabaseRepository


def make_repo(db_url="postgresql://mock:5432/db"):
    repo = DatabaseRepository(db_url)
    return repo


@pytest.mark.asyncio
async def test_init_db_creates_pool_and_schema(monkeypatch):
    repo = make_repo()
    fake_pool = MagicMock()
    fake_pool.acquire = MagicMock()
    repo._initialize_schema = AsyncMock()
    monkeypatch.setattr("asyncpg.create_pool", AsyncMock(return_value=fake_pool))
    await repo.init_db()
    assert repo.pool is fake_pool
    assert repo._schema_ready is True
    repo._initialize_schema.assert_awaited_once()


@pytest.mark.asyncio
async def test_init_db_skips_when_ready(monkeypatch):
    repo = make_repo()
    repo.pool = MagicMock()
    repo._schema_ready = True
    repo._initialize_schema = AsyncMock()
    await repo.init_db()
    repo._initialize_schema.assert_not_awaited()


@pytest.mark.asyncio
async def test_close_resets_owned_pool():
    repo = make_repo()
    pool = MagicMock()
    pool.close = AsyncMock()
    repo.pool = pool
    repo._owns_pool = True
    repo._schema_ready = True
    await repo.close()
    pool.close.assert_awaited_once()
    assert repo.pool is None
    assert repo._schema_ready is False

@pytest.mark.asyncio
async def test_close_preserves_shared_pool():
    repo = make_repo()
    pool = MagicMock()
    pool.close = AsyncMock()
    repo.pool = pool
    repo._owns_pool = False
    repo._schema_ready = True
    await repo.close()
    pool.close.assert_not_awaited()
    assert repo.pool is pool
    assert repo._schema_ready is True


@pytest.mark.asyncio
async def test_close_no_pool():
    repo = make_repo()
    await repo.close()  # no exception


@pytest.mark.asyncio
async def test_ensure_pool_returns_pool(monkeypatch):
    repo = make_repo()
    repo.init_db = AsyncMock()
    repo.pool = MagicMock()
    assert await repo._ensure_pool() is repo.pool


@pytest.mark.asyncio
async def test_ensure_pool_raises_if_none(monkeypatch):
    repo = make_repo()
    repo.init_db = AsyncMock()
    repo.pool = None
    with pytest.raises(RuntimeError, match="not initialized"):
        await repo._ensure_pool()


def test_command_count_valid():
    assert DatabaseRepository._command_count("UPDATE 3") == 3
    assert DatabaseRepository._command_count("INSERT 0 1") == 1


def test_command_count_invalid():
    assert DatabaseRepository._command_count("") == 0
    assert DatabaseRepository._command_count(None) == 0
    assert DatabaseRepository._command_count("UPDATE ABC") == 0
