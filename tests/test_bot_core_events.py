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


@pytest.mark.asyncio
async def test_on_message_redis_lock_busy():
    bc = make_bc()
    bc._redis_client = MagicMock()
    bc._redis_client.set = AsyncMock(return_value=False)  # not acquired
    bc._handle_confirmation_message = AsyncMock(return_value=False)
    events = _capture_events(bc)
    message = MagicMock()
    message.author.bot = False
    message.author.id = 42
    message.channel = MagicMock()
    message.mentions = []
    message.reply = AsyncMock()
    # make it a DM so it proceeds past mention check
    message.channel = MagicMock()
    from discord import DMChannel

    message.channel = MagicMock(spec=DMChannel)
    await events["on_message"](message)
    assert message.reply.called


def _voice_state(channel=None):
    st = MagicMock()
    st.channel = channel
    return st


@pytest.mark.asyncio
async def test_on_voice_state_update_kicks_non_whitelisted():
    bc = make_bc()
    bc.bot.user.id = 1
    bc.voice_lock_manager = MagicMock()
    bc.voice_lock_manager.owner_id = 9
    bc.voice_lock_manager.load_whitelist = MagicMock(return_value={})
    events = _capture_events(bc)

    member = MagicMock()
    member.id = 50
    member.name = "Intruder"
    member.move_to = AsyncMock()
    channel = MagicMock()
    channel.id = 100
    channel.name = "Lobby"
    bc.voice_lock_manager.locked_channels = {100}

    await events["on_voice_state_update"](member, _voice_state(None), _voice_state(channel))
    member.move_to.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_voice_state_update_no_lock_manager():
    bc = make_bc()
    bc.voice_lock_manager = None
    events = _capture_events(bc)
    member = MagicMock()
    await events["on_voice_state_update"](member, _voice_state(None), _voice_state(None))  # no-op


@pytest.mark.asyncio
async def test_on_message_success_publishes():
    bc = make_bc()
    bc._redis_client = MagicMock()
    bc._redis_client.set = AsyncMock(return_value=True)  # acquired
    bc._handle_confirmation_message = AsyncMock(return_value=False)
    bc.kafka_service.publish = AsyncMock(return_value=True)
    bc._collect_message_attachments = AsyncMock(return_value=[])
    bc._resolve_referenced_message = AsyncMock(return_value=None)
    bc.db_repo.clear_user_processing_state = AsyncMock()
    events = _capture_events(bc)
    message = MagicMock()
    message.author.bot = False
    message.author.id = 42
    message.author.name = "Bob"
    message.author.display_name = "Bob"
    message.id = 1
    message.content = "hello"
    message.reference = None
    message.mentions = []
    message.channel = MagicMock()
    message.channel.id = 5
    from discord import DMChannel

    message.channel = MagicMock(spec=DMChannel)
    await events["on_message"](message)
    bc.kafka_service.publish.assert_awaited_once()
