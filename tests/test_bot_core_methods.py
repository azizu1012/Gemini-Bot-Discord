"""Offline tests for BotCore permission/autocomplete/mention/queue helpers."""
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock

import discord
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
    bc.config = MagicMock()
    bc.config.ADMIN_USER_IDS = ["1000"]
    bc.config.MODERATOR_USER_IDS = ["2000"]
    bc.logger = NullLogger()
    bc.db_repo = MagicMock()
    bc.bot = MagicMock()
    bc._outgoing_queues = {}
    bc._outgoing_senders = {}
    bc.active_typing_tasks = {}
    bc._active_user_locks = {}
    bc._redis_client = None
    bc.voice_lock_manager = MagicMock()
    bc.voice_lock_manager.locked_channels = set()
    bc.kafka_service = MagicMock()
    return bc


# ---------------- permission helpers ----------------
@pytest.mark.asyncio
async def test_is_admin_user_static():
    bc = make_bc()
    assert await bc._is_admin_user("1000") is True
    bc.db_repo.is_admin_user.assert_not_called()


@pytest.mark.asyncio
async def test_is_admin_user_db_fallback():
    bc = make_bc()
    bc.db_repo.is_admin_user = AsyncMock(return_value=True)
    assert await bc._is_admin_user("9999") is True
    bc.db_repo.is_admin_user.assert_awaited_once_with("9999")


@pytest.mark.asyncio
async def test_is_moderator_user_static():
    bc = make_bc()
    assert await bc._is_moderator_user("2000") is True
    bc.db_repo.is_moderator_user.assert_not_called()


@pytest.mark.asyncio
async def test_is_moderator_user_db_fallback():
    bc = make_bc()
    bc.db_repo.is_moderator_user = AsyncMock(return_value=False)
    assert await bc._is_moderator_user("8888") is False
    bc.db_repo.is_moderator_user.assert_awaited_once_with("8888")


# ---------------- autocomplete ----------------
@pytest.mark.asyncio
async def test_voice_channel_autocomplete_filters():
    bc = make_bc()
    interaction = MagicMock()
    guild = MagicMock()
    vc = MagicMock(spec=discord.VoiceChannel)
    vc.id = 1
    vc.name = "Gaming"
    sc = MagicMock(spec=discord.StageChannel)
    sc.id = 2
    sc.name = "Stage"
    tc = MagicMock(spec=discord.TextChannel)
    tc.id = 3
    tc.name = "Text"
    guild.channels = [vc, sc, tc]
    interaction.guild = guild
    result = await bc._voice_channel_autocomplete(interaction, "gam")
    assert len(result) == 1
    assert result[0].value == "1"


@pytest.mark.asyncio
async def test_member_autocomplete_skips_bots():
    bc = make_bc()
    interaction = MagicMock()
    guild = MagicMock()
    m1 = MagicMock()
    m1.bot = False
    m1.display_name = "Alice"
    m1.id = 10
    m2 = MagicMock()
    m2.bot = True
    m2.display_name = "Botty"
    guild.members = [m1, m2]
    interaction.guild = guild
    result = await bc._member_autocomplete(interaction, "ali")
    assert len(result) == 1
    assert result[0].value == "10"


# ---------------- display name ----------------
@pytest.mark.asyncio
async def test_resolve_user_display_name_from_guild_member():
    bc = make_bc()
    channel = MagicMock()
    guild = MagicMock()
    member = MagicMock()
    member.display_name = "Bob"
    guild.get_member = MagicMock(return_value=member)
    channel.guild = guild
    assert await bc._resolve_user_display_name(5, channel) == "Bob"


@pytest.mark.asyncio
async def test_resolve_user_display_name_fallback_user():
    bc = make_bc()
    user = MagicMock()
    user.display_name = "Carol"
    bc.bot.get_user = MagicMock(return_value=user)
    assert await bc._resolve_user_display_name(7, None) == "Carol"


@pytest.mark.asyncio
async def test_resolve_user_display_name_no_user():
    bc = make_bc()
    bc.bot.get_user = MagicMock(return_value=None)
    bc.bot.fetch_user = AsyncMock(return_value=None)
    assert await bc._resolve_user_display_name(9, None) == "User 9"


# ---------------- sanitize mentions ----------------
@pytest.mark.asyncio
async def test_sanitize_mentions_replaces_everyone_and_roles():
    bc = make_bc()
    bc._resolve_user_display_name = AsyncMock(return_value="Bob")
    guild = MagicMock()
    role = MagicMock()
    role.name = "Moderators"
    guild.get_role = MagicMock(return_value=role)
    channel = MagicMock()
    channel.guild = guild
    content = "hello @everyone <@&123> <@999>"
    result = await bc._sanitize_mentions(content, channel, allow_user_mentions=["999"])
    assert "everyone" in result
    assert "Moderators" in result
    assert "<@999>" in result  # allowed mention kept as-is


@pytest.mark.asyncio
async def test_sanitize_mentions_empty_returns_none():
    bc = make_bc()
    assert await bc._sanitize_mentions(None, None) is None
    assert await bc._sanitize_mentions("", None) == ""


# ---------------- queues ----------------
def test_get_outgoing_queue_creates_and_caches():
    bc = make_bc()
    q1 = bc._get_outgoing_queue("u1")
    q2 = bc._get_outgoing_queue("u1")
    assert q1 is q2
    assert q1.empty()  # freshly created


@pytest.mark.asyncio
async def test_ensure_sender_task_creates():
    bc = make_bc()
    bc._outgoing_sender_loop = AsyncMock()
    bc._ensure_sender_task("u1")
    assert "u1" in bc._outgoing_senders


def test_ensure_sender_task_skips_existing_active():
    bc = make_bc()
    task = MagicMock()
    task.done = MagicMock(return_value=False)
    bc._outgoing_senders["u1"] = task
    bc._ensure_sender_task("u1")
    assert bc._outgoing_senders["u1"] is task


def test_cancel_typing_task_cancels():
    bc = make_bc()
    task = MagicMock()
    bc.active_typing_tasks["u1"] = task
    bc._cancel_typing_task("u1")
    task.cancel.assert_called_once()
    assert "u1" not in bc.active_typing_tasks


def test_cancel_typing_task_no_task():
    bc = make_bc()
    bc._cancel_typing_task("u1")
    # no exception


def test_build_voice_lock_manager_invalid_admin_id():
    bc = make_bc()
    bc.config.ADMIN_ID = "not-an-int"
    assert bc._build_voice_lock_manager() is None


def test_build_voice_lock_manager_missing_admin_id():
    bc = make_bc()
    bc.config.ADMIN_ID = None
    assert bc._build_voice_lock_manager() is None


def test_build_voice_lock_manager_valid():
    bc = make_bc()
    bc.config.ADMIN_ID = "12345"
    bc.config.VOICE_WHITELIST_FILE = "data/wl.json"
    bc.config.LOCKED_CHANNELS_FILE = "data/lc.json"
    bc.config.ENFORCED_NAMES_FILE = "data/en.json"
    bc.config.VOICE_LOCK_LOG_FILE = "data/vl.log"
    mgr = bc._build_voice_lock_manager()
    assert mgr is not None
    assert mgr.owner_id == 12345


@pytest.mark.asyncio
async def test_shutdown_cancels_and_closes():
    bc = make_bc()
    async def _noop():
        await asyncio.sleep(0)

    task = asyncio.create_task(_noop())
    bc._consume_task = task
    bc.kafka_service.stop = AsyncMock()
    bc.db_repo.close = AsyncMock()
    await bc.shutdown()
    assert task.cancelled() is True
    bc.kafka_service.stop.assert_awaited_once()
    bc.db_repo.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_shutdown_no_task():
    bc = make_bc()
    bc._consume_task = None
    bc.kafka_service.stop = AsyncMock()
    bc.db_repo.close = AsyncMock()
    await bc.shutdown()
    bc.kafka_service.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_voice_lock_enforce_loop_empty():
    bc = make_bc()
    # closed after first iteration
    bc.bot.is_closed = MagicMock(side_effect=[False, True])
    bc.voice_lock_manager = MagicMock()
    bc.voice_lock_manager.locked_channels = set()
    bc.voice_lock_manager.load_whitelist = MagicMock(return_value={})
    await bc._voice_lock_enforce_loop()  # exits after one empty iteration


@pytest.mark.asyncio
async def test_resolve_referenced_message_no_reference():
    bc = make_bc()
    message = MagicMock()
    message.reference = None
    assert await bc._resolve_referenced_message(message) is None


@pytest.mark.asyncio
async def test_resolve_referenced_message_resolved():
    bc = make_bc()
    message = MagicMock()
    reference = MagicMock()
    reference.message_id = 1
    resolved = MagicMock(spec=discord.Message)
    reference.resolved = resolved
    message.reference = reference
    assert await bc._resolve_referenced_message(message) is resolved


@pytest.mark.asyncio
async def test_resolve_referenced_message_fetch_error():
    bc = make_bc()
    message = MagicMock()
    reference = MagicMock()
    reference.message_id = 1
    reference.channel_id = None
    reference.resolved = None
    message.reference = reference
    message.channel = MagicMock()
    message.channel.fetch_message = AsyncMock(side_effect=discord.NotFound(MagicMock(), "x"))
    assert await bc._resolve_referenced_message(message) is None


@pytest.mark.asyncio
async def test_collect_message_attachments():
    bc = make_bc()
    message = MagicMock()
    att = MagicMock()
    att.id = 1
    att.url = "http://x/a.png"
    att.proxy_url = "http://x/a.png"
    att.filename = "a.png"
    att.size = 10
    att.content_type = "image/png"
    message.attachments = [att]
    message.reference = None
    bc._build_attachment_payload = MagicMock(return_value={"id": "1"})
    result = await bc._collect_message_attachments(message)
    assert result == [{"id": "1"}]


@pytest.mark.asyncio
async def test_send_message_with_retry_success():
    bc = make_bc()
    channel = MagicMock()
    channel.send = AsyncMock(return_value=MagicMock())
    result = await bc._send_message_with_retry(channel, content="hi", reference=None, mention_author=False, label="reply")
    assert result is not None
    channel.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_with_retry_failure_returns_none():
    bc = make_bc()
    channel = MagicMock()
    channel.send = AsyncMock(side_effect=ConnectionError("boom"))
    result = await bc._send_message_with_retry(channel, content="hi", reference=None, mention_author=False, label="reply")
    assert result is None


@pytest.mark.asyncio
async def test_edit_message_with_retry_success():
    bc = make_bc()
    message = MagicMock()
    message.edit = AsyncMock()
    ok = await bc._edit_message_with_retry(message, content="new", label="edit")
    assert ok is True
    message.edit.assert_awaited_once()


@pytest.mark.asyncio
async def test_edit_message_with_retry_failure():
    bc = make_bc()
    message = MagicMock()
    message.edit = AsyncMock(side_effect=RuntimeError("x"))
    ok = await bc._edit_message_with_retry(message, content="new", label="edit")
    assert ok is False


@pytest.mark.asyncio
async def test_voice_lock_enforce_loop_kicks_non_whitelist():
    bc = make_bc()
    bc.bot.is_closed = MagicMock(side_effect=[False, True])
    bc.bot.user = MagicMock()
    bc.bot.user.id = 1
    bc.voice_lock_manager = MagicMock()
    bc.voice_lock_manager.owner_id = 9
    whitelist = {"5": "A"}
    bc.voice_lock_manager.load_whitelist = MagicMock(return_value=whitelist)

    channel = MagicMock(spec=discord.VoiceChannel)
    channel.id = 100
    member_bad = MagicMock()
    member_bad.id = 50
    member_bad.move_to = AsyncMock()
    channel.members = [member_bad]
    bc.bot.get_channel = MagicMock(return_value=channel)
    bc.voice_lock_manager.locked_channels = {100}
    bc.voice_lock_manager.enforced_names = {}

    await bc._voice_lock_enforce_loop()
    member_bad.move_to.assert_awaited_once()
