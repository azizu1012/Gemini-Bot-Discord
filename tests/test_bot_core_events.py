"""Offline tests for BotCore event registration (on_ready/on_message)."""
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, ".")

from src.handlers.discord.bot_core import BotCore


class NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


def make_bc():
    bc = object.__new__(BotCore)
    bc.logger = NullLogger()
    bc._outgoing_queues = {}
    bc._outgoing_senders = {}
    bc.active_typing_tasks = {}
    bc._active_user_locks = {}
    bc._redis_client = None
    bc._delivery_state = {}
    bc._outgoing_consumer = None
    bc._voice_enforce_task = None
    bc.bot = MagicMock()
    bc.bot.user = MagicMock()
    bc.bot.user.name = "Bot"
    bc.bot.user.id = 1
    bc.db_repo = MagicMock()
    bc.cleanup_mgr = MagicMock()
    bc.health_checker = MagicMock()
    bc.config = MagicMock()
    bc.config.ADMIN_ID = ""
    bc.voice_lock_manager = None
    bc.room_lock_service = None
    bc.kafka_service = MagicMock()
    bc._register_slash_commands = MagicMock()
    return bc


def _capture_events(bc):
    events = {}

    def fake_event(func):
        events[func.__name__] = func
        return func

    bc.bot.event = fake_event
    bc._register_events()
    return events


@pytest.mark.asyncio
async def test_on_ready_runs_setup(monkeypatch):
    bc = make_bc()
    bc.db_repo.init_db = AsyncMock()
    bc.db_repo.cleanup_db = AsyncMock()
    bc.db_repo.backup_db = AsyncMock()
    bc.cleanup_mgr.cleanup_local_files = AsyncMock()
    bc.setup_redis = AsyncMock()
    bc.bot.tree.sync = AsyncMock(return_value=[])
    events = _capture_events(bc)
    assert "on_ready" in events
    await events["on_ready"]()
    bc.setup_redis.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_message_bot_ignored():
    bc = make_bc()
    events = _capture_events(bc)
    message = MagicMock()
    message.author.bot = True
    await events["on_message"](message)
    # returns early before any handling
    bc.db_repo.log_message_db.assert_not_called()


@pytest.mark.asyncio
async def test_on_message_dm_not_mentioned():
    bc = make_bc()
    events = _capture_events(bc)
    message = MagicMock()
    message.author.bot = False
    message.channel = MagicMock()
    message.mentions = []
    bc._handle_confirmation_message = AsyncMock(return_value=False)
    await events["on_message"](message)
    # not dm, not mentioned -> returns
