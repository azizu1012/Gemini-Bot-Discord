"""Test gate endpoint chưa cấu hình + gate /imagine ở chế độ OpenAI.

Chạy: .venv\\Scripts\\python.exe tests\\test_endpoint_gate.py
(pytest-compatible: các hàm test_* độc lập, không cần mạng)
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import logger
from src.core.llm.base import LLMUnsupportedError
from src.handlers.message_handler import MessageHandler


class FakeRedisMsg:
    def __init__(self, value):
        self.value = value


class FakeResolver:
    def __init__(self, configured=True, active_sdk="genai"):
        self.configured = configured
        self.active_sdk = active_sdk

    async def is_configured(self):
        return self.configured

    async def get_active_sdk(self):
        return self.active_sdk


class FakeGateway:
    def __init__(self, unsupported=False):
        self.unsupported = unsupported

    async def get_raw_genai_client(self):
        if self.unsupported:
            raise LLMUnsupportedError("chỉ hỗ trợ genAI")
        raise AssertionError("Gate test không được gọi tới client thật")


class FakeKafka:
    def __init__(self):
        self.published = []

    async def publish(self, channel, payload=None, key=None):
        self.published.append(payload)
        return True


def make_handler(configured=True, active_sdk="genai", unsupported=False):
    h = MessageHandler.__new__(MessageHandler)
    h.logger = logger
    h.resolver = FakeResolver(configured=configured, active_sdk=active_sdk)
    h.gateway = FakeGateway(unsupported=unsupported)
    h.kafka_service = FakeKafka()
    h._incoming_consumer = None
    return h


def test_chat_gate_unconfigured():
    h = make_handler(configured=False)
    msg = FakeRedisMsg({"user_id": "1", "channel_id": "2", "message_id": "3", "content": "xin chào"})
    asyncio.run(h.process_message(msg))
    assert len(h.kafka_service.published) == 1
    payload = h.kafka_service.published[0]
    assert payload["action"] == "reply"
    assert payload["reference_message_id"] == "3"
    assert "chưa được cấu hình" in payload["content"]


def test_imagine_gate_unconfigured():
    h = make_handler(configured=False)
    asyncio.run(h._process_imagine_command({"user_id": "1", "interaction_id": "9", "prompt": "mèo"}))
    payload = h.kafka_service.published[0]
    assert payload["action"] == "slash_reply"
    assert payload["ephemeral"] is True
    assert "chưa được cấu hình" in payload["content"]


def test_imagine_gate_openai_mode():
    h = make_handler(configured=True, active_sdk="openai", unsupported=True)
    asyncio.run(h._process_imagine_command({"user_id": "1", "interaction_id": "9", "prompt": "mèo"}))
    payload = h.kafka_service.published[0]
    assert payload["action"] == "slash_reply"
    assert payload["ephemeral"] is True
    assert "chỉ hỗ trợ ở chế độ genAI" in payload["content"]


if __name__ == "__main__":
    test_chat_gate_unconfigured()
    test_imagine_gate_unconfigured()
    test_imagine_gate_openai_mode()
    print("ALL PASS")
