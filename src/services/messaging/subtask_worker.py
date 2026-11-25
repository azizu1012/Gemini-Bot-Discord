import asyncio
from typing import Any, Dict, Set

from src.core.config import logger, Config
from src.services.redis_service import RedisStreamService
from src.tools.tools import ToolsManager


class SearchSubtaskWorker:
    """Worker to handle search-subtasks via Redis Streams and publish results to search-results."""

    def __init__(self, config: Config):
        self.config = config
        self.logger = logger
        self.kafka_service = RedisStreamService(redis_url=self.config.REDIS_URL, client_id="search-subtasks")
        self.tools_mgr = ToolsManager(enable_search_subtasks=False)
        # asyncio chỉ giữ weak reference tới Task, nên task con không được tham
        # chiếu ở đâu có thể bị GC thu hồi giữa chừng trước khi publish kết quả.
        self._tasks: Set[asyncio.Task] = set()

    async def start_worker(self) -> None:
        self.logger.info("Starting SearchSubtaskWorker...")
        try:
            await self.kafka_service.start_producer()
            consumer = await self.kafka_service.start_consumer("search-subtasks", group_id="azuris_search_subtasks")
        except Exception as e:
            self.logger.error(f"Failed to start SearchSubtaskWorker Redis services: {e}")
            await self.shutdown()
            return

        self.logger.info("SearchSubtaskWorker started. Listening for search-subtasks...")
        try:
            async for msg in consumer:
                payload = msg.value or {}
                task = asyncio.create_task(self._process_subtask(consumer, msg, payload))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
        except asyncio.CancelledError:
            self.logger.info("SearchSubtaskWorker task cancelled")
            raise
        except Exception as e:
            self.logger.error(f"SearchSubtaskWorker consumer loop error: {e}")
        finally:
            await self.shutdown()

    async def _process_subtask(
        self, consumer, msg, payload: Dict[str, Any]
    ) -> None:
        correlation_id = str(payload.get("correlation_id") or "")
        query = str(payload.get("query") or "").strip()
        mode = str(payload.get("mode") or "general").strip() or "general"
        user_id = str(payload.get("user_id") or "")

        if not correlation_id or not query:
            # Payload hỏng: không bao giờ xử lý được nên phải ACK, nếu không entry
            # sẽ nằm lại PEL vĩnh viễn (stream này không có vòng reclaim).
            self.logger.warning(f"SearchSubtaskWorker dropping invalid subtask payload for user {user_id}")
            await consumer.ack(msg)
            return

        result_text = ""
        error_text = ""
        try:
            result_text = await self.tools_mgr.run_search_apis(query, mode)
        except Exception as e:
            error_text = str(e)
            self.logger.error(f"SearchSubtaskWorker error: {e}")

        response_payload = {
            "type": "search_result",
            "correlation_id": correlation_id,
            "user_id": user_id,
            "result": result_text,
            "error": error_text,
        }

        published = await self.kafka_service.publish(
            "search-results", payload=response_payload, key=user_id or correlation_id
        )
        if published:
            await consumer.ack(msg)

    async def shutdown(self) -> None:
        # Cho các subtask đang chạy một khoảng ngắn để publish kết quả rồi mới cắt.
        pending = list(self._tasks)
        if pending:
            _done, still_pending = await asyncio.wait(pending, timeout=10)
            for task in still_pending:
                task.cancel()
            if still_pending:
                await asyncio.gather(*still_pending, return_exceptions=True)
            self._tasks.clear()
        await self.kafka_service.stop()
