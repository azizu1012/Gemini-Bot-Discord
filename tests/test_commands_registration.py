"""Offline smoke tests for register_slash_commands wiring and its error handler.

We patch the discord app_commands surface with no-op collectors so the large
command-registration function can run without a live Discord client, exercising
every command definition + the shared error handler.
"""
import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from discord import app_commands

sys.path.insert(0, ".")

from src.handlers.discord.commands import register_slash_commands


def _noop_decorator(*a, **kw):
    def deco(func):
        return func

    return deco


class FakeCommandDecorator:
    """Collects the wrapped functions, applies the decorator chain."""

    def __init__(self):
        self.registered = []

    def __call__(self, name=None, description=None, **kw):
        def deco(func):
            self.registered.append(func)
            return func

        return deco


class FakeTree:
    def __init__(self):
        self.commands = {}
        self.added = []
        self.error_handler = None
        self._cmd = FakeCommandDecorator()
        self._group_cmds = []

    def command(self, *a, **kw):
        return self._cmd(*a, **kw)

    def add_command(self, cmd):
        self.added.append(cmd)

    def error(self, func):
        self.error_handler = func
        return func


class FakeGroup:
    _all = {}

    def __init__(self, *a, **kw):
        self._cmd = FakeCommandDecorator()
        name = kw.get("name", "unknown")
        FakeGroup._all[name] = self

    def command(self, *a, **kw):
        return self._cmd(*a, **kw)


def _install_app_commands_mocks(monkeypatch):
    # app_commands decorators used in commands.py
    for name in ("describe", "choices", "check", "autocomplete"):
        monkeypatch.setattr(app_commands, name, _noop_decorator, raising=False)
    monkeypatch.setattr(app_commands, "Group", FakeGroup, raising=False)
    # Choice / Range are just referenced as types (annotation) — no-op classes
    class _Choice:
        def __init__(self, *a, **kw):
            pass

        def __class_getitem__(cls, item):
            return cls

    class _Range:
        def __init__(self, *a, **kw):
            pass

        def __class_getitem__(cls, item):
            return cls

    monkeypatch.setattr(app_commands, "Choice", _Choice, raising=False)
    monkeypatch.setattr(app_commands, "Range", _Range, raising=False)
    _CheckFailure = type("CheckFailure", (Exception,), {})
    _AppCommandError = type("AppCommandError", (Exception,), {})
    monkeypatch.setattr(app_commands, "CheckFailure", _CheckFailure, raising=False)
    monkeypatch.setattr(app_commands, "AppCommandError", _AppCommandError, raising=False)


def _make_bot_core():
    tree = FakeTree()
    bot = MagicMock()
    bot.tree = tree
    bot_core = MagicMock()
    bot_core.bot = bot
    from unittest.mock import AsyncMock

    bot_core.db_repo = MagicMock()
    bot_core.db_repo.add_moderator_user = AsyncMock()
    bot_core.db_repo.remove_moderator_user = AsyncMock()
    bot_core.db_repo.add_premium_user = AsyncMock()
    bot_core.db_repo.is_premium_user = AsyncMock(return_value=False)
    bot_core.db_repo.is_admin_user = AsyncMock(return_value=False)
    bot_core.db_repo.is_moderator_user = AsyncMock(return_value=False)
    bot_core.config = SimpleNamespace(
        ADMIN_USER_IDS=[],
        MODERATOR_USER_IDS=[],
        TOKEN="t",
    )
    bot_core.logger = MagicMock()
    bot_core.kafka_service = MagicMock()
    bot_core._is_admin_user = MagicMock(return_value=True)
    bot_core._is_moderator_user = MagicMock(return_value=True)
    bot_core.voice_lock_manager = MagicMock()
    # is_owner_check returns an async predicate decorator
    async def _owner_predicate(interaction):
        return True

    def _is_owner_check():
        return lambda f: f

    bot_core.voice_lock_manager.is_owner_check = _is_owner_check
    bot_core.room_lock_service = MagicMock()
    bot_core.room_tools_service = MagicMock()
    # field used by some commands
    bot_core._current_imagine = MagicMock()
    bot_core._premium_users = set()
    return bot_core, tree


def test_register_slash_commands_runs_and_registers(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    register_slash_commands(bot_core)
    # many commands + a group command added
    assert tree._cmd.registered
    assert len(tree._cmd.registered) >= 10


def test_on_app_command_error_checkfailure(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    register_slash_commands(bot_core)
    handler = tree.error_handler
    assert handler is not None

    from unittest.mock import AsyncMock

    interaction = MagicMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.response.send_message = AsyncMock()
    error = app_commands.CheckFailure("no")

    async def run():
        await handler(interaction, error)

    asyncio.run(run())
    interaction.response.send_message.assert_awaited_once()
    assert "owner" in interaction.response.send_message.call_args[0][0]


def test_on_app_command_error_generic_done(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    register_slash_commands(bot_core)
    handler = tree.error_handler

    from unittest.mock import AsyncMock

    interaction = MagicMock()
    interaction.response.is_done = MagicMock(return_value=True)
    interaction.followup.send = AsyncMock()

    async def run():
        await handler(interaction, Exception("boom"))

    asyncio.run(run())
    interaction.followup.send.assert_awaited_once()
    assert "boom" in interaction.followup.send.call_args[0][0]


def _find_registered(tree, name):
    for func in tree._cmd.registered:
        if getattr(func, "__name__", "") == name:
            return func
    return None


@pytest.mark.asyncio
async def test_allow_member_handler_adds_to_whitelist(monkeypatch):
    from unittest.mock import AsyncMock

    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    # set up room_lock_service
    room_lock_service = MagicMock()
    room_lock_service.whitelist = MagicMock()
    room_lock_service.grant_access = AsyncMock(return_value=2)
    bot_core.room_lock_service = room_lock_service
    register_slash_commands(bot_core)

    handler = _find_registered(tree, "allow_member")
    assert handler is not None

    interaction = MagicMock()
    interaction.user.id = 1000
    interaction.response.send_message = AsyncMock()
    member = MagicMock()
    member.id = 5000
    member.mention = "<@5000>"
    member.display_name = "Alice"

    await handler(interaction, member)
    room_lock_service.whitelist.add.assert_called_once_with(5000, "Alice")
    room_lock_service.grant_access.assert_awaited_once_with(member)
    interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_member_handler_removes_from_whitelist(monkeypatch):
    from unittest.mock import AsyncMock

    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    room_lock_service = MagicMock()
    room_lock_service.whitelist = MagicMock()
    room_lock_service.whitelist.contains = MagicMock(return_value=True)
    room_lock_service.revoke_access = AsyncMock(return_value=1)
    bot_core.room_lock_service = room_lock_service
    register_slash_commands(bot_core)

    handler = _find_registered(tree, "allow_remove_member")
    assert handler is not None

    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()
    member = MagicMock()
    member.id = 5000
    member.mention = "<@5000>"

    await handler(interaction, member)
    room_lock_service.whitelist.remove.assert_called_once_with(5000)
    room_lock_service.revoke_access.assert_awaited_once_with(member)
    interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_allow_member_handler_self_returns(monkeypatch):
    from unittest.mock import AsyncMock

    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    room_lock_service = MagicMock()
    room_lock_service.whitelist = MagicMock()
    bot_core.room_lock_service = room_lock_service
    register_slash_commands(bot_core)

    handler = _find_registered(tree, "allow_member")
    assert handler is not None

    interaction = MagicMock()
    interaction.user.id = 5000
    interaction.response.send_message = AsyncMock()
    member = MagicMock()
    member.id = 5000  # same as user -> early return

    await handler(interaction, member)
    room_lock_service.whitelist.add.assert_not_called()


# ---------------- command handlers ----------------
def _interaction(user_id=1000):
    from unittest.mock import AsyncMock

    interaction = MagicMock()
    interaction.user = MagicMock()
    interaction.user.id = user_id
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


@pytest.mark.asyncio
async def test_premium_slash_add_non_admin(monkeypatch):
    from unittest.mock import AsyncMock

    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core._is_admin_user = AsyncMock(return_value=False)
    register_slash_commands(bot_core)

    handler = _find_registered(tree, "premium_slash")
    assert handler is not None

    interaction = _interaction()
    action = MagicMock()
    action.value = "add"
    user = MagicMock()
    user.id = 2000
    user.display_name = "Bob"
    await handler(interaction, action, user)
    interaction.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_premium_slash_check_admin(monkeypatch):
    from unittest.mock import AsyncMock

    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core._is_admin_user = AsyncMock(side_effect=lambda uid: uid == "2000")
    register_slash_commands(bot_core)

    handler = _find_registered(tree, "premium_slash")
    interaction = _interaction()
    action = MagicMock()
    action.value = "check"
    user = MagicMock()
    user.id = 2000
    user.display_name = "Bob"
    await handler(interaction, action, user)
    assert "Admin" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_moderator_slash_add(monkeypatch):
    from unittest.mock import AsyncMock

    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core._is_admin_user = AsyncMock(return_value=True)
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "moderator_slash")
    assert handler is not None

    interaction = _interaction()
    action = MagicMock()
    action.value = "add"
    user = MagicMock()
    user.id = 2000
    user.display_name = "Bob"
    await handler(interaction, action, user)
    bot_core.db_repo.add_moderator_user.assert_awaited_once()


@pytest.mark.asyncio
async def test_donate_slash_missing_file(monkeypatch):

    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    # point PROJECT_ROOT to an empty temp dir so the QR file doesn't exist
    import tempfile

    tmp = tempfile.mkdtemp()
    bot_core.config.PROJECT_ROOT = tmp
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "donate_slash")
    assert handler is not None

    interaction = _interaction()
    await handler(interaction, None)  # defaults to kofi -> missing file
    interaction.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_global_notes_slash_empty(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core.db_repo.get_global_notes_db = AsyncMock(return_value=[])
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "global_notes_slash")
    assert handler is not None
    interaction = _interaction()
    await handler(interaction, 40)
    interaction.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_global_note_demote_by_id(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core.db_repo.demote_global_note_by_id_db = AsyncMock(return_value=True)
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "global_note_demote_slash")
    assert handler is not None
    interaction = _interaction()
    await handler(interaction, "note-123")
    assert "Demoted global note by id" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_lock_room_not_in_voice(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "lock_room")
    assert handler is not None
    interaction = _interaction()
    interaction.guild = MagicMock()
    interaction.user.voice = None  # not in voice
    await handler(interaction)
    interaction.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_unlock_room_not_locked(monkeypatch):

    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    room_lock_service = MagicMock()
    room_lock_service.is_locked = MagicMock(return_value=False)
    bot_core.room_lock_service = room_lock_service
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "unlock_room")
    assert handler is not None

    interaction = _interaction()
    interaction.guild = MagicMock()
    channel = MagicMock()
    channel.id = 1
    channel.name = "Lobby"
    interaction.user.voice = MagicMock(channel=channel)
    await handler(interaction)
    interaction.followup.send.assert_awaited_once()


def _find_group_handler(monkeypatch, group_name, handler_name):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    register_slash_commands(bot_core)
    group = FakeGroup._all.get(group_name)
    assert group is not None, f"group {group_name} not registered"
    for func in group._cmd.registered:
        if getattr(func, "__name__", "") == handler_name:
            return bot_core, func
    raise AssertionError(f"handler {handler_name} not found in group {group_name}")


@pytest.mark.asyncio
async def test_endpoint_view(monkeypatch):
    bot_core, handler = _find_group_handler(monkeypatch, "endpoint", "endpoint_view")
    bot_core.db_repo.get_llm_endpoints = AsyncMock(return_value={})
    bot_core.db_repo.get_active_sdk = AsyncMock(return_value="genai")
    interaction = _interaction()
    await handler(interaction)
    interaction.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_endpoint_switch_chooses(monkeypatch):
    bot_core, handler = _find_group_handler(monkeypatch, "endpoint", "endpoint_switch")
    bot_core.db_repo.get_llm_endpoints = AsyncMock(return_value={"genai": {}})
    bot_core.db_repo.set_active_sdk = AsyncMock(return_value=True)
    bot_core.config = SimpleNamespace(ADMIN_USER_IDS=[], MODERATOR_USER_IDS=[])
    interaction = _interaction()
    await handler(interaction)
    interaction.followup.send.assert_awaited_once()





@pytest.mark.asyncio
async def test_message_to_slash_dm(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core._is_admin_user = AsyncMock(return_value=True)
    bot_core._is_moderator_user = AsyncMock(return_value=False)
    target = MagicMock()
    target.id = 999
    target.display_name = "Target"
    target.send = AsyncMock()
    bot_core.bot.fetch_user = AsyncMock(return_value=target)
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "message_to_slash")
    assert handler is not None
    interaction = _interaction()
    user = MagicMock()
    user.id = 999
    user.display_name = "Target"
    await handler(interaction, user, "hello there", None)
    interaction.followup.send.assert_awaited_once()
    target.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_message_to_slash_channel(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core._is_admin_user = AsyncMock(return_value=True)
    bot_core._is_moderator_user = AsyncMock(return_value=False)
    target = MagicMock()
    target.id = 999
    target.display_name = "Target"
    target.mention = "<@999>"
    bot_core.bot.fetch_user = AsyncMock(return_value=target)
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "message_to_slash")
    interaction = _interaction()
    guild = MagicMock()
    me = MagicMock()
    channel = MagicMock()
    channel.mention = "#general"
    channel.permissions_for = MagicMock(return_value=MagicMock(send_messages=True))
    channel.send = AsyncMock()
    channel.guild = guild
    channel.__class__ = __import__("discord").TextChannel
    interaction.guild = guild
    guild.me = me
    user = MagicMock()
    user.id = 999
    user.display_name = "Target"
    await handler(interaction, user, "hi", channel)
    channel.send.assert_awaited_once()
