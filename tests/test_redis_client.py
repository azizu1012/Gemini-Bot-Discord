"""Offline tests for src/services/messaging/redis_client.py — mock Redis.

No live Redis required. We substitute a FakeRedis implementing the asyncpg
subset the code calls (xreadgroup, xack, xpending, xpending_range, xclaim,
xgroup_create, xadd, set, ping, close).
"""
import asyncio
import json
import sys

import pytest
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, ".")

from src.services.messaging.redis_client import (
    RedisStreamConsumer,
    RedisStreamService,
    _RedisMsg,
)


class FakeRedis:
    """In-memory async fake for the Redis bits we use."""

    def __init__(self):
        self.messages = []  # list of (fields dict)
        self.pending_entries = []
        self.claimed_entries = []
        self.acked = []
        self.xadd_calls = 0
        self.ping_ok = True
        self.set_claim = None
        self.closed = False
        self.xgroup_error = None

    async def ping(self):
        if not self.ping_ok:
            raise ConnectionError("no ping")
        return True

    async def xreadgroup(self, group, consumer, streams, count, block):
        if not self.messages:
            return []
        fields = self.messages.pop(0)
        eid = fields.pop("_eid", "1-1")
        return [("mystream", [(eid, fields)])]

    async def xack(self, stream, group, eid):
        self.acked.append(eid)
        return 1

    async def xpending(self, stream, group):
        if not self.pending_entries:
            return [0]
        return [len(self.pending_entries)]

    async def xpending_range(self, stream, group, min, max, count):
        return list(self.pending_entries)

    async def xclaim(self, stream, group, consumer, min_idle_ms, msg_ids):
        return self.claimed_entries

    async def xgroup_create(self, stream, group, id, mkstream):
        if self.xgroup_error:
            raise self.xgroup_error
        return True

    async def xadd(self, stream, entry, maxlen, approximate):
        self.xadd_calls += 1
        return "1-0"

    async def set(self, key, value, nx, ex):
        self.set_claim = (key, value, nx, ex)
        return True

    async def close(self):
        self.closed = True

    @classmethod
    def from_url(cls, *a, **kw):
        return cls()


# ---------------- _RedisMsg ----------------
def test_redismsg_holds_fields():
    msg = _RedisMsg({"k": "v"}, "key1", "1-1")
    assert msg.value == {"k": "v"}
    assert msg.key == "key1"
    assert msg.entry_id == "1-1"


# ---------------- RedisStreamConsumer ----------------
async def _consumer_with(redis):
    return RedisStreamConsumer(redis, "mystream", "grp", "c1")


@pytest.mark.asyncio
async def test_consumer_reads_message_with_bytes_fields():
    redis = FakeRedis()
    redis.messages.append(
        {"_eid": "1-1", b"key": b"topic", b"value": json.dumps({"a": 1}).encode()}
    )
    consumer = await _consumer_with(redis)
    msg = await consumer.__anext__()
    assert msg.key == "topic"
    assert msg.value == {"a": 1}
    assert msg.entry_id == "1-1"
    await consumer.stop()


@pytest.mark.asyncio
async def test_consumer_reads_message_with_str_fields():
    redis = FakeRedis()
    redis.messages.append(
        {"_eid": "2-2", "key": "topic2", "value": json.dumps({"b": 2})}
    )
    consumer = await _consumer_with(redis)
    msg = await consumer.__anext__()
    assert msg.key == "topic2"
    assert msg.value == {"b": 2}
    await consumer.stop()


@pytest.mark.asyncio
async def test_consumer_skips_message_without_value():
    redis = FakeRedis()
    redis.messages.append({"_eid": "3-3", b"key": b"k"})  # no value -> skipped
    consumer = await _consumer_with(redis)
    # no message left -> loop until stop then StopAsyncIteration
    await consumer.stop()
    with pytest.raises(StopAsyncIteration):
        await consumer.__anext__()


@pytest.mark.asyncio
async def test_consumer_stop_raises_stopiteration():
    redis = FakeRedis()
    consumer = await _consumer_with(redis)
    await consumer.stop()
    with pytest.raises(StopAsyncIteration):
        await consumer.__anext__()


@pytest.mark.asyncio
async def test_consumer_ack_ack_id():
    redis = FakeRedis()
    consumer = await _consumer_with(redis)
    assert await consumer.ack(_RedisMsg({}, "k", "1-1")) is True
    assert "1-1" in redis.acked
    assert await consumer.ack_id("2-2") is True
    assert "2-2" in redis.acked
    await consumer.stop()


@pytest.mark.asyncio
async def test_consumer_ack_failure_returns_false():
    redis = FakeRedis()

    async def boom(*a, **kw):
        raise ConnectionError("xack fail")

    redis.xack = boom
    consumer = await _consumer_with(redis)
    assert await consumer.ack_id("1-1") is False
    await consumer.stop()


@pytest.mark.asyncio
async def test_consumer_reclaim_pending_empty():
    redis = FakeRedis()
    redis.pending_entries = []
    consumer = await _consumer_with(redis)
    assert await consumer.reclaim_pending() == []
    await consumer.stop()


@pytest.mark.asyncio
async def test_consumer_reclaim_pending_selects_idle():
    redis = FakeRedis()
    redis.pending_entries = [
        {b"message_id": b"1-1", b"time_since_delivered": 50000},
        {b"message_id": b"1-2", b"time_since_delivered": 1000},
    ]
    redis.claimed_entries = [("mystream", [("1-1", {b"key": b"k", b"value": b"{\"x\":1}"})])]
    consumer = await _consumer_with(redis)
    reclaimed = await consumer.reclaim_pending(min_idle_ms=30000)
    assert len(reclaimed) == 1
    assert reclaimed[0].entry_id == "1-1"
    assert reclaimed[0].value == {"x": 1}
    await consumer.stop()


@pytest.mark.asyncio
async def test_consumer_reclaim_pending_exception_safe():
    redis = FakeRedis()

    async def boom(*a, **kw):
        raise ConnectionError("xpending fail")

    redis.xpending = boom
    consumer = await _consumer_with(redis)
    assert await consumer.reclaim_pending() == []
    await consumer.stop()


# ---------------- RedisStreamService ----------------
@pytest.mark.asyncio
async def test_start_producer_connects(monkeypatch):
    import src.services.messaging.redis_client as mod

    monkeypatch.setattr(mod.Redis, "from_url", lambda *a, **kw: FakeRedis())
    service = RedisStreamService("redis://x:6379/0", "c1")
    await service.start_producer()
    assert service._redis is not None


@pytest.mark.asyncio
async def test_start_producer_skips_when_set():
    service = RedisStreamService("redis://x:6379/0", "c1")
    fake = FakeRedis()
    service._redis = fake
    await service.start_producer()  # should return early
    assert service._redis is fake


@pytest.mark.asyncio
async def test_start_producer_failure_raises(monkeypatch):
    import src.services.messaging.redis_client as mod

    class BoomRedis(FakeRedis):
        async def ping(self):
            raise ConnectionError("no ping")

    monkeypatch.setattr(mod.Redis, "from_url", lambda *a, **kw: BoomRedis())
    service = RedisStreamService("redis://x:6379/0", "c1")
    with pytest.raises(ConnectionError):
        await service.start_producer()
    assert service._redis is None


@pytest.mark.asyncio
async def test_start_consumer_creates_group_and_consumer():
    service = RedisStreamService("redis://x:6379/0", "c1")
    service._redis = FakeRedis()
    consumer = await service.start_consumer("mystream", "grp")
    assert "mystream" in service.consumers
    assert consumer is service.consumers["mystream"]
    assert consumer._group == "grp"


@pytest.mark.asyncio
async def test_start_consumer_busygroup_is_tolerated():
    service = RedisStreamService("redis://x:6379/0", "c1")
    redis = FakeRedis()
    redis.xgroup_error = Exception("BUSYGROUP Consumer group name already exists")
    service._redis = redis
    consumer = await service.start_consumer("s1", "g1")
    assert consumer is not None


@pytest.mark.asyncio
async def test_publish_returns_false_without_redis():
    service = RedisStreamService("redis://x:6379/0", "c1")
    assert await service.publish("s1", {"user_id": "u"}) is False


@pytest.mark.asyncio
async def test_publish_success_adds_stream():
    service = RedisStreamService("redis://x:6379/0", "c1")
    redis = FakeRedis()
    service._redis = redis
    ok = await service.publish("s1", {"user_id": "u", "message_id": "m1", "action": "x"})
    assert ok is True
    assert redis.xadd_calls == 1


@pytest.mark.asyncio
async def test_publish_retries_then_fails(monkeypatch):
    service = RedisStreamService("redis://x:6379/0", "c1")

    class FailRedis(FakeRedis):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def xadd(self, *a, **kw):
            self.calls += 1
            raise ConnectionError("xadd fail")

    redis = FailRedis()
    service._redis = redis
    monkeypatch.setattr(asyncio, "sleep", lambda s: _noop())
    ok = await service.publish("s1", {"user_id": "u"})
    assert ok is False
    assert redis.calls == 3  # max_attempts default


async def _noop():
    return None


@pytest.mark.asyncio
async def test_claim_message_once_redirects_when_no_redis():
    service = RedisStreamService("redis://x:6379/0", "c1")
    assert await service.claim_message_once("m1") is True


@pytest.mark.asyncio
async def test_claim_message_once_uses_redis_set():
    service = RedisStreamService("redis://x:6379/0", "c1")
    redis = FakeRedis()
    service._redis = redis
    assert await service.claim_message_once("m1", ttl_seconds=100) is True
    assert redis.set_claim is not None
    key, value, nx, ex = redis.set_claim
    assert "m1" in key
    assert value == "1"
    assert nx is True
    assert ex == 100


@pytest.mark.asyncio
async def test_stop_closes_redis_and_stops_consumers():
    service = RedisStreamService("redis://x:6379/0", "c1")
    redis = FakeRedis()
    service._redis = redis
    consumer = RedisStreamConsumer(redis, "s1", "g1", "c1")
    service.consumers["s1"] = consumer
    await service.stop()
    assert service._redis is None
    assert consumer._running is False
    assert service.consumers == {}


@pytest.mark.asyncio
async def test_claim_message_once_exception_handled():
    service = RedisStreamService("redis://x:6379/0", "c1")
    redis = FakeRedis()
    async def boom(*a, **kw):
        raise ConnectionError("redis down")
    redis.set = boom
    service._redis = redis
    assert await service.claim_message_once("m1") is True


@pytest.mark.asyncio
async def test_stop_consumer_exception_handled():
    service = RedisStreamService("redis://x:6379/0", "c1")
    redis = FakeRedis()
    service._redis = redis
    consumer = MagicMock()
    consumer.stop = AsyncMock(side_effect=RuntimeError("stop error"))
    service.consumers["s1"] = consumer
    await service.stop()
    assert service.consumers == {}


@pytest.mark.asyncio
async def test_stop_redis_close_exception_handled():
    service = RedisStreamService("redis://x:6379/0", "c1")
    redis = FakeRedis()
    redis.close = AsyncMock(side_effect=RuntimeError("close error"))
    service._redis = redis
    await service.stop()
    assert service._redis is None


@pytest.mark.asyncio
async def test_consumer_reclaim_pending_empty_msg_ids():
    redis = FakeRedis()
    redis.pending_entries = [{"message_id": "1-1", "time_since_delivered": 100}]
    consumer = await _consumer_with(redis)
    # min_idle_ms = 30000 -> 100 < 30000 -> msg_ids is empty
    assert await consumer.reclaim_pending(min_idle_ms=30000) == []
    await consumer.stop()
