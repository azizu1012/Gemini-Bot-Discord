import asyncio
import json
import logging
from typing import Any, Dict, Optional

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from src.core.config import logger


class KafkaService:
    """Central service managing Kafka producers, consumers, and message flows.

    Designed to be shared across BotCore and MessageHandler Worker to avoid duplicate
    Kafka logic and enable clean centralized logging.
    """

    def __init__(self, bootstrap_servers: str, client_id: str):
        self.bootstrap_servers = bootstrap_servers
        self.client_id = client_id
        self.producer: Optional[AIOKafkaProducer] = None
        self.consumers: Dict[str, AIOKafkaConsumer] = {}
        self.logger = logger

    async def start_producer(self) -> None:
        """Initialize and start the Kafka producer."""
        if self.producer is not None:
            return

        try:
            self.producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
                key_serializer=lambda k: k.encode("utf-8") if k else None,
                client_id=f"{self.client_id}-producer"
            )
            await asyncio.wait_for(self.producer.start(), timeout=12)
            self.logger.info(f"Kafka producer started for {self.client_id}")
        except Exception as e:
            self.logger.error(f"Failed to start Kafka producer for {self.client_id}: {e}")
            self.producer = None
            raise

    async def start_consumer(self, topic: str, group_id: str) -> AIOKafkaConsumer:
        """Initialize and start a Kafka consumer for a specific topic."""
        if topic in self.consumers:
            return self.consumers[topic]

        try:
            consumer = AIOKafkaConsumer(
                topic,
                bootstrap_servers=self.bootstrap_servers,
                group_id=group_id,
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
                auto_offset_reset="latest",
                client_id=f"{self.client_id}-consumer-{topic}"
            )
            await asyncio.wait_for(consumer.start(), timeout=12)
            self.consumers[topic] = consumer
            self.logger.info(f"Kafka consumer started for {self.client_id} on topic '{topic}' (group: {group_id})")
            return consumer
        except Exception as e:
            self.logger.error(f"Failed to start Kafka consumer for topic '{topic}': {e}")
            raise

    async def publish(self, topic: str, payload: Dict[str, Any], key: Optional[str] = None) -> bool:
        """Publish a message to a Kafka topic with centralized logging."""
        if self.producer is None:
            self.logger.error(f"Cannot publish message to topic '{topic}': Producer is not started.")
            return False

        try:
            user_id = payload.get("user_id") or key or "unknown"
            msg_id = payload.get("message_id") or payload.get("interaction_id") or "none"
            self.logger.info(
                f"[KAFKA-SEND] Publishing to topic '{topic}' | User: {user_id} | MsgID/IntID: {msg_id} | Payload Action: {payload.get('action') or payload.get('type')}"
            )
            await self.producer.send_and_wait(topic, value=payload, key=key)
            return True
        except Exception as e:
            self.logger.error(f"Failed to publish to topic '{topic}': {e}")
            return False

    async def stop(self) -> None:
        """Stop all consumers and the producer cleanly."""
        self.logger.info(f"Stopping KafkaService for {self.client_id}...")

        # Stop consumers
        for topic, consumer in list(self.consumers.items()):
            try:
                await consumer.stop()
                self.logger.info(f"Stopped Kafka consumer for topic '{topic}'")
            except Exception as e:
                self.logger.warning(f"Failed to stop Kafka consumer for topic '{topic}' cleanly: {e}")
        self.consumers.clear()

        # Stop producer
        if self.producer is not None:
            try:
                await self.producer.stop()
                self.logger.info("Stopped Kafka producer")
            except Exception as e:
                self.logger.warning(f"Failed to stop Kafka producer cleanly: {e}")
            finally:
                self.producer = None
