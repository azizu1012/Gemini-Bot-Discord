import asyncio
import json
import os
from typing import Any, Dict, Optional, AsyncIterator

from redis.asyncio import Redis
from src.core.config import logger


class _RedisMsg:
    """Mock message object to match the msg.value interface."""
    def __init__(self, value: Dict[str, Any], key: str, entry_id: str):
        self.value = value
        self.key = key
        self.entry_id = entry_id


class RedisStreamConsumer:
    """Async iterable wrapper around Redis Streams XREADGROUP.

    Usage:
        consumer = RedisStreamConsumer(redis, stream, group, consumer_name)
        async for msg in consumer:
            payload = msg.value
    """

    def __init__(self, redis: Redis, stream: str, group: str, consumer_name: str):
        self._redis = redis
        self._stream = stream
        self._group = group
        self._consumer_name = consumer_name
        self._running = True
        self._logger = logger

    def __aiter__(self):
        return self

    async def __anext__(self) -> _RedisMsg:
        while self._running:
            try:
                result = await self._redis.xreadgroup(
                    self._group,
                    self._consumer_name,
                    {self._stream: '>'},
                    count=1,
                    block=2000,
                )
                if not result:
                    await asyncio.sleep(0.05)
                    continue

                for stream_entry in result:
                    stream_name_bytes = stream_entry[0]
                    entries = stream_entry[1]
                    for entry_id, fields in entries:
                        if not self._running:
                            raise StopAsyncIteration

                        raw_key = fields.get(b'key') or fields.get('key') or b''
                        if isinstance(raw_key, bytes):
                            key = raw_key.decode('utf-8')
                        else:
                            key = str(raw_key)

                        raw_value = fields.get(b'value') or fields.get('value')
                        if raw_value is None:
                            continue
                        if isinstance(raw_value, bytes):
                            raw_value = raw_value.decode('utf-8')
                        value = json.loads(str(raw_value))

                        eid = entry_id
                        if isinstance(eid, bytes):
                            eid = eid.decode('utf-8')

                        await self._redis.xack(self._stream, self._group, entry_id)

                        return _RedisMsg(value, key, str(eid))

            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._logger.error(f"RedisStreamConsumer error on '{self._stream}': {e}")
                await asyncio.sleep(1)

        raise StopAsyncIteration

    async def stop(self):
        self._running = False


class RedisStreamService:
    """Central service managing Redis Streams producers, consumers, and message flows.

    Centralized message bus using Redis Streams.
    Interface: publish(), start_producer(), start_consumer(), stop().
    """

    def __init__(self, redis_url: str, client_id: str):
        self.redis_url = redis_url
        self.client_id = client_id
        self._redis: Optional[Redis] = None
        self.consumers: Dict[str, RedisStreamConsumer] = {}
        self._consumer_groups_created: set = set()
        self.logger = logger

    async def start_producer(self) -> None:
        """Initialize Redis connection (Redis doesn't need a separate producer)."""
        if self._redis is not None:
            return
        try:
            self._redis = Redis.from_url(
                self.redis_url,
                decode_responses=False,
                socket_connect_timeout=5,
                socket_timeout=10,
                protocol=2,
            )
            await asyncio.wait_for(self._redis.ping(), timeout=8)
            self.logger.info(f"Redis Streams producer started for {self.client_id}")
        except Exception as e:
            self.logger.error(f"Failed to connect Redis for {self.client_id}: {e}")
            self._redis = None
            raise

    async def start_consumer(self, stream: str, group_id: str) -> RedisStreamConsumer:
        """Start a Redis Streams consumer with consumer group."""
        if self._redis is None:
            await self.start_producer()

        stream = str(stream)
        group_id = str(group_id)

        if stream not in self._consumer_groups_created:
            try:
                await self._redis.xgroup_create(stream, group_id, id='$', mkstream=True)
                self.logger.info(f"Redis consumer group '{group_id}' created on stream '{stream}'")
            except Exception as e:
                if 'BUSYGROUP' not in str(e):
                    self.logger.warning(f"Redis xgroup_create warning for '{stream}': {e}")
            self._consumer_groups_created.add(stream)

        consumer_name = f"{self.client_id}-{stream}-{os.getpid()}"
        consumer = RedisStreamConsumer(self._redis, stream, group_id, consumer_name)
        self.consumers[stream] = consumer
        self.logger.info(f"Redis Streams consumer started for {self.client_id} on stream '{stream}' (group: {group_id}, consumer: {consumer_name})")
        return consumer

    async def publish(self, stream: str, payload: Dict[str, Any], key: Optional[str] = None) -> bool:
        """Publish a message to a Redis Stream with centralized logging and bounded retry."""
        if self._redis is None:
            self.logger.error(f"Cannot publish to stream '{stream}': Redis not connected")
            return False

        max_attempts = max(1, int(os.getenv("REDIS_PUBLISH_MAX_RETRIES", "3") or 3))
        base_delay = max(0.05, float(os.getenv("REDIS_PUBLISH_RETRY_BASE_DELAY", "0.25") or 0.25))
        stream_maxlen = int(os.getenv("REDIS_STREAM_MAXLEN", "100000"))
        user_id = payload.get("user_id") or key or "unknown"
        msg_id = payload.get("message_id") or payload.get("interaction_id") or payload.get("reply_group_id") or "none"
        action = payload.get("action") or payload.get("type")

        entry = {
            'value': json.dumps(payload, ensure_ascii=False),
            'key': key or '',
        }

        for attempt in range(1, max_attempts + 1):
            try:
                self.logger.info(
                    f"[REDIS-SEND] Publishing to stream '{stream}' | User: {user_id} | "
                    f"MsgID/IntID: {msg_id} | Payload Action: {action} | Attempt: {attempt}/{max_attempts}"
                )
                await self._redis.xadd(stream, entry, maxlen=stream_maxlen, approximate=True)
                return True
            except Exception as e:
                if attempt >= max_attempts:
                    self.logger.error(f"Failed to publish to stream '{stream}' after {max_attempts} attempts: {e}")
                    return False
                wait_time = base_delay * (2 ** (attempt - 1))
                self.logger.warning(
                    f"Redis publish retry {attempt}/{max_attempts} for stream '{stream}' action={action}: {e}"
                )
                await asyncio.sleep(wait_time)

        return False

    async def stop(self) -> None:
        """Stop all consumers and close Redis connection."""
        self.logger.info(f"Stopping RedisStreamService for {self.client_id}...")

        for stream, consumer in list(self.consumers.items()):
            try:
                await consumer.stop()
                self.logger.info(f"Stopped Redis consumer for stream '{stream}'")
            except Exception as e:
                self.logger.warning(f"Failed to stop Redis consumer for stream '{stream}': {e}")
        self.consumers.clear()

        if self._redis is not None:
            try:
                await self._redis.close()
                self.logger.info("Closed Redis connection")
            except Exception as e:
                self.logger.warning(f"Failed to close Redis connection cleanly: {e}")
            finally:
                self._redis = None
