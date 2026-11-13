"""Offline tests for run_bot.py single-worker Redis instance-lock.

Tests _acquire_worker_lock: acquiring the lock returns a release callback,
a held lock exits with SystemExit (no second worker starts), and Redis
unavailability fails open (returns None instead of raising). All Redis
interaction is mocked — no live Redis required.
"""
import sys
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, ".")

import redis.asyncio as aioredis

from run_bot import (
    _acquire_worker_lock,
    _WORKER_LOCK_KEY,
    _WORKER_LOCK_VALUE,
)


def _config():
    return SimpleNamespace(REDIS_URL="redis://localhost:6379/0")


def _make_client(set_result=True, get_value=None):
    client = MagicMock()
    client.set = AsyncMock(return_value=set_result)
    client.get = AsyncMock(return_value=get_value)
    client.delete = AsyncMock(return_value=1)
    client.close = AsyncMock()
    return client


# ---------------- Acquisition ----------------

@pytest.mark.asyncio
async def test_acquire_lock_returns_release_when_not_held(monkeypatch):
    client = _make_client(set_result=True, get_value=_WORKER_LOCK_VALUE)
    monkeypatch.setattr(aioredis, "from_url", lambda url, **kw: client)

    release = await _acquire_worker_lock(_config())

    assert callable(release)
    client.set.assert_awaited_once_with(
        _WORKER_LOCK_KEY, _WORKER_LOCK_VALUE, nx=True, ex=3600
    )

    await release()
    client.get.assert_awaited_once_with(_WORKER_LOCK_KEY)
    client.delete.assert_awaited_once_with(_WORKER_LOCK_KEY)


@pytest.mark.asyncio
async def test_acquire_lock_exits_when_held(monkeypatch):
    client = _make_client(set_result=False)
    monkeypatch.setattr(aioredis, "from_url", lambda url, **kw: client)

    with pytest.raises(SystemExit) as excinfo:
        await _acquire_worker_lock(_config())

    assert excinfo.value.code == 1
    # Lock is not released/acquired on the exit path; client is closed.
    client.close.assert_awaited()


@pytest.mark.asyncio
async def test_acquire_lock_fail_open_on_from_url_error(monkeypatch):
    def _boom(*args, **kwargs):
        raise ConnectionError("no redis")

    monkeypatch.setattr(aioredis, "from_url", _boom)

    release = await _acquire_worker_lock(_config())

    assert release is None


@pytest.mark.asyncio
async def test_acquire_lock_fail_open_on_set_error(monkeypatch):
    client = _make_client()
    client.set = AsyncMock(side_effect=ConnectionError("redis down"))
    monkeypatch.setattr(aioredis, "from_url", lambda url, **kw: client)

    release = await _acquire_worker_lock(_config())

    assert release is None
    client.close.assert_awaited()


# ---------------- Release ----------------

@pytest.mark.asyncio
async def test_release_keeps_key_when_not_owned(monkeypatch):
    client = _make_client(set_result=True, get_value="another-instance-id")
    monkeypatch.setattr(aioredis, "from_url", lambda url, **kw: client)

    release = await _acquire_worker_lock(_config())
    assert callable(release)

    await release()
    # Value mismatch -> lock must not be deleted, but client still closed.
    client.delete.assert_not_awaited()
    client.close.assert_awaited()


@pytest.mark.asyncio
async def test_release_closes_client_even_when_get_fails(monkeypatch):
    client = _make_client(set_result=True)
    client.get = AsyncMock(side_effect=ConnectionError("down"))
    monkeypatch.setattr(aioredis, "from_url", lambda url, **kw: client)

    release = await _acquire_worker_lock(_config())

    await release()  # must not raise
    client.close.assert_awaited()
