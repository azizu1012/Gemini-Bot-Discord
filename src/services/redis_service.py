"""Redis stream service facade for backward compatibility."""

from src.services.messaging.redis_client import RedisStreamService, RedisStreamConsumer, _RedisMsg

__all__ = ["RedisStreamService", "RedisStreamConsumer", "_RedisMsg"]
