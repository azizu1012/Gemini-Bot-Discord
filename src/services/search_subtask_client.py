import asyncio
import uuid
from typing import Any, Dict, Optional

from src.core.config import logger
from src.services.redis_service import RedisStreamService


class SearchSubtaskClient:
    """Client for dispatching web search subtasks over Redis Streams and awaiting results."""

    def __init__(self, kafka_service: RedisStreamService, group_id: Optional[str] = None):
        self.kafka_service = kafka_service
        self.group_id = group_id or f"azuris_search_results_{uuid.uuid4()}"
        self._consumer = None
        self._listener_task: Optional[asyncio.Task] = None
        self._pending: Dict[str, asyncio.Future] = {}
        self.logger = logger

    async def start(self) -> None:
        if self._listener_task and not self._listener_task.done():
            return

        await self.kafka_service.start_producer()
        self._consumer = await self.kafka_service.start_consumer("search-results", group_id=self.group_id)
        self._listener_task = asyncio.create_task(self._listen_results())

    async def close(self) -> None:
        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass

        for future in list(self._pending.values()):
            if not future.done():
                future.cancel()
        self._pending.clear()

    async def _listen_results(self) -> None:
        if not self._consumer:
            return

        try:
            async for msg in self._consumer:
                payload = msg.value or {}
                correlation_id = str(payload.get("correlation_id") or "")
                if not correlation_id:
                    continue
                future = self._pending.pop(correlation_id, None)
                if future and not future.done():
                    future.set_result(payload)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error(f"SearchSubtaskClient listener error: {e}")

    async def request_search(self, user_id: str, query: str, mode: str = "general", timeout: int = 18) -> Optional[str]:
        await self.start()

        correlation_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending[correlation_id] = future

        payload = {
            "type": "search_subtask",
            "correlation_id": correlation_id,
            "user_id": str(user_id or ""),
            "query": query,
            "mode": mode,
        }

        ok = await self.kafka_service.publish("search-subtasks", payload=payload, key=str(user_id or correlation_id))
        if not ok:
            self._pending.pop(correlation_id, None)
            return None

        try:
            result_payload: Dict[str, Any] = await asyncio.wait_for(future, timeout=timeout)
            return str(result_payload.get("result") or "")
        except asyncio.TimeoutError:
            self._pending.pop(correlation_id, None)
            return None
        except Exception:
            self._pending.pop(correlation_id, None)
            return None
