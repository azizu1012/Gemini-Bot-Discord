import asyncio
from typing import Any, Dict, Optional

from src.core.config import logger, Config
from src.services.kafka_service import KafkaService
from src.tools.tools import ToolsManager


class SearchSubtaskWorker:
    """Kafka worker to handle search-subtasks and publish results to search-results."""

    def __init__(self, config: Config):
        self.config = config
        self.logger = logger
        self.kafka_service = KafkaService(bootstrap_servers=self.config.KAFKA_BOOTSTRAP_SERVERS, client_id="search-subtasks")
        self.tools_mgr = ToolsManager(enable_search_subtasks=False)
        self._consume_task: Optional[asyncio.Task] = None

    async def start_worker(self) -> None:
        self.logger.info("Starting SearchSubtaskWorker...")
        try:
            await self.kafka_service.start_producer()
            consumer = await self.kafka_service.start_consumer("search-subtasks", group_id="azuris_search_subtasks")
        except Exception as e:
            self.logger.error(f"Failed to start SearchSubtaskWorker Kafka services: {e}")
            await self.shutdown()
            return

        self.logger.info("SearchSubtaskWorker started. Listening for search-subtasks...")
        try:
            async for msg in consumer:
                payload = msg.value or {}
                asyncio.create_task(self._process_subtask(payload))
        except asyncio.CancelledError:
            self.logger.info("SearchSubtaskWorker task cancelled")
            raise
        except Exception as e:
            self.logger.error(f"SearchSubtaskWorker consumer loop error: {e}")
        finally:
            await self.shutdown()

    async def _process_subtask(self, payload: Dict[str, Any]) -> None:
        correlation_id = str(payload.get("correlation_id") or "")
        query = str(payload.get("query") or "").strip()
        mode = str(payload.get("mode") or "general").strip() or "general"
        user_id = str(payload.get("user_id") or "")

        if not correlation_id or not query:
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

        await self.kafka_service.publish("search-results", payload=response_payload, key=user_id or correlation_id)

    async def shutdown(self) -> None:
        await self.kafka_service.stop()
