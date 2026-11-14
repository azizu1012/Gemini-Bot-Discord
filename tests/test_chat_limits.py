"""Chat admission limits with shared, atomic mock Redis transactions; no services."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.handlers.discord.bot_core import BotCore
from src.services.messaging.redis_client import RedisStreamService


class CounterRedis:
    """Small fake of Redis INCR/EXPIRE NX and transaction semantics, with a clock."""

    def __init__(self):
        self.now = 0
        self.values = {}
        self.expirations = {}
        self.lock = asyncio.Lock()

    def pipeline(self, *, transaction):
        assert transaction is True
        redis = self

        class Pipeline:
            def __init__(self):
                self.commands = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def incr(self, key):
                self.commands.append(("incr", key))

            def expire(self, key, seconds, *, nx):
                assert nx is True
                self.commands.append(("expire", key, seconds))

            async def execute(self):
                async with redis.lock:
                    result = []
                    for command, key, *args in self.commands:
                        if redis.expirations.get(key, float("inf")) <= redis.now:
                            redis.values.pop(key, None)
                            redis.expirations.pop(key, None)
                        if command == "incr":
                            redis.values[key] = redis.values.get(key, 0) + 1
                            result.append(redis.values[key])
                        else:
                            result.append(key not in redis.expirations)
                            redis.expirations.setdefault(key, redis.now + args[0])
                    return result

        return Pipeline()


def make_core(redis=None, *, premium=False):
    core = object.__new__(BotCore)
    core.config = SimpleNamespace(
        CHAT_LIMITS_ENABLED=True,
        ADMIN_USER_IDS=[], MODERATOR_USER_IDS=[],
        SPAM_THRESHOLD=3, SPAM_WINDOW=30,
        DEFAULT_RATE_LIMIT="10/60", PREMIUM_RATE_LIMIT="20/60",
        DEFAULT_DM_LIMIT=5, PREMIUM_DM_LIMIT=15,
    )
    core.db_repo = MagicMock()
    core.db_repo.is_admin_user = AsyncMock(return_value=False)
    core.db_repo.is_moderator_user = AsyncMock(return_value=False)
    core.db_repo.is_premium_user = AsyncMock(return_value=premium)
    core.kafka_service = RedisStreamService(redis_url="redis://unused", client_id="test")
    core.kafka_service._redis = redis if redis is not None else CounterRedis()
    return core


@pytest.mark.asyncio
@pytest.mark.parametrize("is_dm", [False, True])
async def test_disabled_chat_limits_skip_counters_and_redis(is_dm):
    redis = MagicMock()
    core = make_core(redis)
    core.config.CHAT_LIMITS_ENABLED = False
    core.kafka_service.increment_counter = AsyncMock(side_effect=AssertionError("Counter must not be called"))

    for _ in range(25):
        assert await core._chat_limit_reply("u1", is_dm=is_dm) is None

    core.kafka_service.increment_counter.assert_not_called()
    assert redis.mock_calls == []
    assert core.db_repo.mock_calls == []


@pytest.mark.asyncio
async def test_counter_is_atomic_across_clients_and_keeps_original_expiry():
    redis = CounterRedis()
    clients = [make_core(redis).kafka_service for _ in range(2)]
    counts = await asyncio.gather(*(clients[i % 2].increment_counter("shared", 30) for i in range(20)))
    assert sorted(counts) == list(range(1, 21))
    redis.now = 15
    assert await clients[0].increment_counter("shared", 30) == 21
    assert redis.expirations["shared"] == 30
    redis.now = 30
    assert await clients[1].increment_counter("shared", 30) == 1


@pytest.mark.asyncio
async def test_counter_requires_redis():
    service = make_core().kafka_service
    service._redis = None
    with pytest.raises(RuntimeError, match="Redis not connected"):
        await service.increment_counter("key", 30)


@pytest.mark.asyncio
async def test_spam_threshold_boundary_expiry_and_user_isolation():
    core = make_core()
    for _ in range(3):
        assert await core._chat_limit_reply("u1", is_dm=False) is None
    assert "quá nhanh" in await core._chat_limit_reply("u1", is_dm=False)
    assert await core._chat_limit_reply("u2", is_dm=False) is None
    core.kafka_service._redis.now = 30
    assert await core._chat_limit_reply("u1", is_dm=False) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("premium, limit", [(False, 10), (True, 20)])
async def test_rate_limits_use_current_premium_role(premium, limit):
    core = make_core(premium=premium)
    core.config.SPAM_THRESHOLD = 100
    for _ in range(limit):
        assert await core._chat_limit_reply("u1", is_dm=False) is None
    assert f"{limit}/60s" in await core._chat_limit_reply("u1", is_dm=False)
    core.db_repo.is_premium_user.assert_awaited()
    core.kafka_service._redis.now = 60
    assert await core._chat_limit_reply("u1", is_dm=False) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("premium, limit", [(False, 5), (True, 15)])
async def test_daily_dm_limit_atomic_across_cores_and_resets_at_utc_midnight(monkeypatch, premium, limit):
    class Clock(datetime):
        current = datetime(2026, 11, 14, 23, 59, 30, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr("src.handlers.discord.bot_core.datetime", Clock)
    redis = CounterRedis()
    cores = [make_core(redis, premium=premium) for _ in range(2)]
    for core in cores:
        core.config.SPAM_THRESHOLD = 100
        core.config.DEFAULT_RATE_LIMIT = core.config.PREMIUM_RATE_LIMIT = "100/60"
    replies = await asyncio.gather(*(
        cores[i % 2]._chat_limit_reply("u1", is_dm=True) for i in range(limit + 4)
    ))
    assert replies.count(None) == limit
    assert all(reply is None or f"DM hôm nay ({limit}/{limit})" in reply for reply in replies)
    # Exhausted DMs do not prevent guild mentions.
    assert await cores[0]._chat_limit_reply("u1", is_dm=False) is None
    assert redis.expirations["azuris:chat-limits:u1:dm:2026-11-14"] == 31
    Clock.current = datetime(2026, 11, 15, tzinfo=timezone.utc)
    redis.now = 30
    assert await cores[1]._chat_limit_reply("u1", is_dm=True) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("role, static", [("admin", True), ("admin", False), ("moderator", True), ("moderator", False)])
async def test_admin_and_moderator_roles_bypass_limits(role, static):
    core = make_core()
    if static:
        getattr(core.config, f"{role.upper()}_USER_IDS").append("u1")
    else:
        getattr(core.db_repo, f"is_{role}_user").return_value = True
    core.kafka_service.increment_counter = AsyncMock()
    assert await core._chat_limit_reply("u1", is_dm=True) is None
    core.kafka_service.increment_counter.assert_not_awaited()
