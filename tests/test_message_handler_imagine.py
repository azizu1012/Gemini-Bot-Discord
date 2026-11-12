"""Offline tests for MessageHandler._process_imagine_command."""
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, ".")

from src.core.llm.base import LLMUnsupportedError
from src.handlers.message_handler import MessageHandler


class NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


def make_handler():
    h = object.__new__(MessageHandler)
    h.logger = NullLogger()
    h.config = MagicMock()
    h.config.FILE_STORAGE_PATH = "data/uploaded"
    h.resolver = MagicMock()
    h.gateway = MagicMock()
    h.db_repo = MagicMock()
    h._publish_outgoing = AsyncMock()
    h._image_download_sem = asyncio.Semaphore(1)
    return h


@pytest.mark.asyncio
async def test_imagine_no_user_id():
    h = make_handler()
    await h._process_imagine_command({})
    h._publish_outgoing.assert_not_called()


@pytest.mark.asyncio
async def test_imagine_no_prompt():
    h = make_handler()
    await h._process_imagine_command({"user_id": "u1", "interaction_id": "i1"})
    h._publish_outgoing.assert_awaited_once()
    assert "Prompt không hợp lệ" in h._publish_outgoing.call_args[0][0]["content"]


@pytest.mark.asyncio
async def test_imagine_not_configured():
    h = make_handler()
    h.resolver.is_configured = AsyncMock(return_value=False)
    await h._process_imagine_command({"user_id": "u1", "prompt": "cat", "interaction_id": "i1"})
    content = h._publish_outgoing.call_args[0][0]["content"]
    assert "chưa được cấu hình" in content


@pytest.mark.asyncio
async def test_imagine_unsupported_sdk():
    h = make_handler()
    h.resolver.is_configured = AsyncMock(return_value=True)
    h.gateway.get_raw_genai_client = AsyncMock(side_effect=LLMUnsupportedError("no"))
    await h._process_imagine_command({"user_id": "u1", "prompt": "cat", "interaction_id": "i1"})
    content = h._publish_outgoing.call_args[0][0]["content"]
    assert "genAI" in content


@pytest.mark.asyncio
async def test_imagine_success(monkeypatch):
    h = make_handler()
    h.resolver.is_configured = AsyncMock(return_value=True)
    raw_client = MagicMock()
    image = MagicMock()
    image.image.image_bytes = b"\x89PNG"
    image.rai_filtered_reason = None
    raw_client.models.generate_images = MagicMock(
        return_value=MagicMock(generated_images=[image])
    )
    h.gateway.get_raw_genai_client = AsyncMock(return_value=raw_client)
    h.db_repo.save_generated_image = AsyncMock(return_value=True)

    # avoid real sleep between attempts
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    await h._process_imagine_command({
        "user_id": "u1", "prompt": "a cat", "interaction_id": "i1", "channel_id": "c1",
    })
    payload = h._publish_outgoing.call_args[0][0]
    assert payload["action"] == "slash_reply"
    assert payload["file_base64"]
    assert payload["file_name"].endswith(".png")


@pytest.mark.asyncio
async def test_imagine_rai_blocked(monkeypatch):
    h = make_handler()
    h.resolver.is_configured = AsyncMock(return_value=True)
    raw_client = MagicMock()
    image = MagicMock()
    image.image = None
    image.rai_filtered_reason = "SAFETY"
    raw_client.models.generate_images = MagicMock(
        return_value=MagicMock(generated_images=[image])
    )
    h.gateway.get_raw_genai_client = AsyncMock(return_value=raw_client)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    await h._process_imagine_command({
        "user_id": "u1", "prompt": "x", "interaction_id": "i1",
    })
    payload = h._publish_outgoing.call_args[0][0]
    assert "không thể tạo ảnh" in payload["content"] or "RAI" in payload["content"]
