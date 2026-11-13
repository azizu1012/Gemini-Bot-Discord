"""Offline test for MessageHandler.process_message full happy-path flow."""
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, ".")

from src.handlers.message_handler import MessageHandler
from src.services.messaging.redis_client import _RedisMsg


class NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass

    def exception(self, *a, **k):
        pass


def make_handler():
    h = object.__new__(MessageHandler)
    h.logger = NullLogger()
    h.config = MagicMock()
    h.config.FILE_CHUNK_DIR = "data/file_chunks"
    h.file_chunk_dir = "data/file_chunks"
    h.cache_mgr = MagicMock()
    h.db_repo = MagicMock()
    h.db_repo.log_message_db = AsyncMock()
    h.db_repo.count_distinct_message_users_db = AsyncMock(return_value=1)
    h.db_repo.has_other_users_history_db = AsyncMock(return_value=False)
    h.db_repo.get_user_history_from_db = AsyncMock(return_value=[])
    h.db_repo.clear_user_processing_state = AsyncMock()
    h.db_repo.set_user_processing_state = AsyncMock(return_value=None)
    h.resolver = MagicMock()
    h.resolver.is_configured = AsyncMock(return_value=True)
    h.premium_mgr = MagicMock()
    h.premium_mgr.is_admin_user = AsyncMock(return_value=True)
    h.premium_mgr.is_moderator_user = AsyncMock(return_value=False)
    h.premium_mgr.is_premium_user = AsyncMock(return_value=False)
    h.note_mgr = MagicMock()
    h.note_mgr.get_user_identity = AsyncMock(return_value="")
    h.file_parser = MagicMock()
    h.__dict__["_file_index_svc"] = MagicMock()
    h.tools_mgr = MagicMock()
    h.tools_mgr.pop_allowed_mentions = MagicMock(return_value=[])
    h.__dict__["_pipeline"] = MagicMock()
    h._incoming_consumer = None
    h._publish_outgoing = AsyncMock()
    h._image_download_sem = asyncio.Semaphore(1)
    h.kafka_service = MagicMock()
    h._call_easy_with_deadline = AsyncMock(return_value=None)
    h._call_pipeline_with_deadline = AsyncMock(return_value="final answer")
    h._build_admin_cross_user_evidence = AsyncMock(return_value="")
    h._split_text = MagicMock(return_value=["chunk1", "chunk2"])
    return h


def make_msg(payload):
    return _RedisMsg(value=payload, key="k", entry_id="1-1")


@pytest.mark.asyncio
async def test_process_message_full_happy_path():
    h = make_handler()
    h.cache_mgr.get_chat_history = MagicMock(return_value=[])
    await h.process_message(make_msg({
        "type": "message",
        "user_id": "u1",
        "content": "xin chào",
        "channel_id": "c1",
        "message_id": "m1",
        "attachments": [],
    }))
    # published a reply_batch
    publish_calls = h._publish_outgoing.call_args_list
    assert publish_calls
    actions = [call[0][0].get("action") for call in publish_calls]
    assert "reply_batch" in actions
    h.db_repo.log_message_db.assert_awaited()
    h._call_pipeline_with_deadline.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_message_easy_path():
    h = make_handler()
    h.cache_mgr.get_chat_history = MagicMock(return_value=[])
    h._call_easy_with_deadline = AsyncMock(return_value="easy reply")
    await h.process_message(make_msg({
        "type": "message",
        "user_id": "u1",
        "content": "xin chào bạn",
        "channel_id": "c1",
        "attachments": [],
    }))
    actions = [call[0][0].get("action") for call in h._publish_outgoing.call_args_list]
    assert "reply_batch" in actions
    h._call_pipeline_with_deadline.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_message_text_attachment_indexing():
    h = make_handler()
    h.cache_mgr.get_chat_history = MagicMock(return_value=[])
    h.file_parser.prepare_file_for_indexing = AsyncMock(
        return_value={"filename": "a.txt", "file_extension": ".txt", "chunk_manifest": [], "security_report": ""}
    )
    h.file_index_svc.build_file_index = AsyncMock(return_value={"chunk_count": 0})
    h.file_index_svc.validate_file_index = AsyncMock(return_value={"status": "ok"})
    h.file_index_svc.set_latest_index = MagicMock()
    await h.process_message(make_msg({
        "type": "message",
        "user_id": "u1",
        "content": "see file",
        "channel_id": "c1",
        "attachments": [{"filename": "doc.txt", "url": "http://x/doc.txt", "size": 100}],
    }))
    actions = [call[0][0].get("action") for call in h._publish_outgoing.call_args_list]
    assert "reply_batch" in actions
    h.file_index_svc.build_file_index.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_message_attachments_image():
    h = make_handler()
    h.cache_mgr.get_chat_history = MagicMock(return_value=[])
    h._download_file_with_sem = AsyncMock(return_value=b"imgdata")
    await h.process_message(make_msg({
        "type": "message",
        "user_id": "u1",
        "content": "look at this",
        "channel_id": "c1",
        "attachments": [{"filename": "photo.png", "url": "http://x/p.png", "size": 100}],
    }))
    actions = [call[0][0].get("action") for call in h._publish_outgoing.call_args_list]
    assert "reply_batch" in actions
