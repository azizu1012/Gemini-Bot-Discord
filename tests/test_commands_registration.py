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
import discord
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
    import discord

    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = user_id
    interaction.user.name = "TestUser"
    interaction.user.display_name = "TestUser"
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    interaction.original_response = AsyncMock(return_value=MagicMock())
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


def _find_health_handler(monkeypatch):
    import src.handlers.discord.commands as cmd_mod

    resolver = MagicMock()
    resolver.is_configured = AsyncMock(return_value=True)
    resolver.get_active_sdk = AsyncMock(return_value="genai")
    resolver.get_endpoint = AsyncMock(return_value={"base_url": "http://x", "api_key": "k"})
    resolver.get_slot_models = AsyncMock(return_value={})
    monkeypatch.setattr(cmd_mod, "get_endpoint_resolver", lambda: resolver)

    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core.config = SimpleNamespace(ADMIN_USER_IDS=[], MODERATOR_USER_IDS=[])
    bot_core.db_repo.init_db = AsyncMock()
    bot_core.db_repo.update_endpoint_check_status = AsyncMock()
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "health_check_slash")
    return handler


@pytest.mark.asyncio
async def test_health_check_slash_configured_ok(monkeypatch):
    handler = _find_health_handler(monkeypatch)
    assert handler is not None
    interaction = _interaction()
    await handler(interaction)
    interaction.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_imagine_history_empty(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core.db_repo.get_generated_images = AsyncMock(return_value=[])
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "imagine_slash")
    assert handler is not None
    action = MagicMock()
    action.value = "history"
    interaction = _interaction()
    await handler(interaction, action, None)
    interaction.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_imagine_no_prompt(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "imagine_slash")
    action = MagicMock()
    action.value = "create"
    interaction = _interaction()
    await handler(interaction, action, None)
    interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_imagine_premium_publishes(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core._is_admin_user = AsyncMock(return_value=True)
    bot_core._is_moderator_user = AsyncMock(return_value=False)
    bot_core.kafka_service.publish = AsyncMock(return_value=True)
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "imagine_slash")
    action = MagicMock()
    action.value = "create"
    interaction = _interaction()
    interaction.id = 555
    interaction.channel_id = 1
    interaction.user.display_name = "Bob"
    await handler(interaction, action, "a cat")
    bot_core.kafka_service.publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_moderator_slash_check_static_admin(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core._is_admin_user = AsyncMock(return_value=True)
    bot_core.config = SimpleNamespace(ADMIN_USER_IDS=["2000"], MODERATOR_USER_IDS=[])
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "moderator_slash")
    interaction = _interaction()
    action = MagicMock()
    action.value = "check"
    user = MagicMock()
    user.id = 2000
    user.display_name = "Bob"
    await handler(interaction, action, user)
    assert "Admin" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_moderator_slash_remove_static(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core._is_admin_user = AsyncMock(return_value=True)
    bot_core.config = SimpleNamespace(ADMIN_USER_IDS=["2000"], MODERATOR_USER_IDS=["3000"])
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "moderator_slash")
    interaction = _interaction()
    action = MagicMock()
    action.value = "remove"
    user = MagicMock()
    user.id = 3000
    user.display_name = "Bob"
    await handler(interaction, action, user)
    assert "tĩnh" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_moderator_slash_remove_dynamic(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core._is_admin_user = AsyncMock(return_value=True)
    bot_core.config = SimpleNamespace(ADMIN_USER_IDS=[], MODERATOR_USER_IDS=[])
    bot_core.db_repo.remove_moderator_user = AsyncMock(return_value=True)
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "moderator_slash")
    interaction = _interaction()
    action = MagicMock()
    action.value = "remove"
    user = MagicMock()
    user.id = 4000
    user.display_name = "Bob"
    await handler(interaction, action, user)
    interaction.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_lock_list_no_locked_rooms(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    room_lock_service = MagicMock()
    room_lock_service.locked_channels = MagicMock(return_value=[])
    bot_core.room_lock_service = room_lock_service
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "lock_list")
    assert handler is not None
    interaction = _interaction()
    interaction.guild = MagicMock()
    await handler(interaction)
    interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_lock_list_with_locked_rooms(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    room_lock_service = MagicMock()
    channel = MagicMock()
    channel.mention = "#lobby"
    rec = MagicMock()
    rec.locked_at.timestamp = MagicMock(return_value=1000000)
    room_lock_service.locked_channels = MagicMock(return_value=[channel])
    room_lock_service.record = MagicMock(return_value=rec)
    bot_core.room_lock_service = room_lock_service
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "lock_list")
    interaction = _interaction()
    interaction.guild = MagicMock()
    await handler(interaction)
    interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_allow_list_empty(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    room_lock_service = MagicMock()
    room_lock_service.whitelist.entries = MagicMock(return_value=[])
    bot_core.room_lock_service = room_lock_service
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "allow_list")
    assert handler is not None
    interaction = _interaction()
    await handler(interaction)
    interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_premium_slash_add_success(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core._is_admin_user = AsyncMock(return_value=True)
    bot_core.db_repo.add_premium_user = AsyncMock(return_value=True)
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
async def test_moderator_slash_check_dynamic(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core._is_admin_user = AsyncMock(return_value=True)
    bot_core.config = SimpleNamespace(ADMIN_USER_IDS=[], MODERATOR_USER_IDS=[])
    bot_core.db_repo.is_admin_user = AsyncMock(return_value=True)
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "moderator_slash")
    interaction = _interaction()
    action = MagicMock()
    action.value = "check"
    user = MagicMock()
    user.id = 5000
    user.display_name = "Bob"
    await handler(interaction, action, user)
    assert "Admin" in interaction.followup.send.call_args[0][0]





@pytest.mark.asyncio
async def test_reset_all_slash(monkeypatch):

    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core._is_admin_user = AsyncMock(return_value=True)
    bot_core.db_repo.clear_all_data_db = AsyncMock()
    bot_core.kafka_service.publish = AsyncMock(return_value=True)
    bot_core.config = SimpleNamespace(ADMIN_USER_IDS=[], MODERATOR_USER_IDS=[], PROJECT_ROOT="")
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "reset_all_slash")
    assert handler is not None
    interaction = _interaction()
    await handler(interaction)
    interaction.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_premium_slash_check_non_premium(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core._is_admin_user = AsyncMock(return_value=False)
    bot_core._is_moderator_user = AsyncMock(return_value=False)
    bot_core.db_repo.is_premium_user = AsyncMock(return_value=False)
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "premium_slash")
    interaction = _interaction()
    action = MagicMock()
    action.value = "check"
    user = MagicMock()
    user.id = 6000
    user.display_name = "Bob"
    await handler(interaction, action, user)
    assert "chưa có Premium" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_global_note_demote_by_hash(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core.db_repo.demote_global_note_by_id_db = AsyncMock(return_value=False)
    bot_core.db_repo.demote_global_fact_hash_db = AsyncMock(return_value=2)
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "global_note_demote_slash")
    interaction = _interaction()
    await handler(interaction, "abc123")
    assert "Demoted 2" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_global_note_demote_no_match(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core.db_repo.demote_global_note_by_id_db = AsyncMock(return_value=False)
    bot_core.db_repo.demote_global_fact_hash_db = AsyncMock(return_value=0)
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "global_note_demote_slash")
    interaction = _interaction()
    await handler(interaction, "xyz")
    assert "Không tìm thấy" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_endpoint_switch_on_choose(monkeypatch):
    import src.handlers.discord.commands as cmd_mod

    captured = {}

    class FakeSDKView:
        def __init__(self, on_choose):
            captured["on_choose"] = on_choose

    monkeypatch.setattr(cmd_mod, "SDKChoiceView", FakeSDKView)

    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core.db_repo.get_llm_endpoints = AsyncMock(return_value={"genai": {}})
    bot_core.db_repo.set_active_sdk = AsyncMock(return_value=True)
    register_slash_commands(bot_core)
    bot_core2, handler = _find_group_handler(monkeypatch, "endpoint", "endpoint_switch")
    bot_core2.db_repo.get_llm_endpoints = AsyncMock(return_value={"genai": {}})
    bot_core2.db_repo.set_active_sdk = AsyncMock(return_value=True)
    interaction = _interaction()
    await handler(interaction)

    on_choose = captured["on_choose"]
    choice_interaction = _interaction()
    await on_choose(choice_interaction, "genai")
    bot_core2.db_repo.set_active_sdk.assert_awaited_once()
    choice_interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_endpoint_switch_on_choose_unconfigured(monkeypatch):
    import src.handlers.discord.commands as cmd_mod

    captured = {}

    class FakeSDKView:
        def __init__(self, on_choose):
            captured["on_choose"] = on_choose

    monkeypatch.setattr(cmd_mod, "SDKChoiceView", FakeSDKView)
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core.db_repo.get_llm_endpoints = AsyncMock(return_value={})
    register_slash_commands(bot_core)
    bot_core2, handler = _find_group_handler(monkeypatch, "endpoint", "endpoint_switch")
    bot_core2.db_repo.get_llm_endpoints = AsyncMock(return_value={})
    interaction = _interaction()
    await handler(interaction)

    on_choose = captured["on_choose"]
    choice_interaction = _interaction()
    await on_choose(choice_interaction, "openai")
    assert "chưa được cấu hình" in choice_interaction.response.send_message.call_args[0][0]


@pytest.mark.asyncio
async def test_endpoint_models_not_configured(monkeypatch):
    import src.handlers.discord.commands as cmd_mod

    resolver = MagicMock()
    resolver.get_active_sdk = AsyncMock(return_value=None)
    monkeypatch.setattr(cmd_mod, "get_endpoint_resolver", lambda: resolver)
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core.config = SimpleNamespace(ADMIN_USER_IDS=[], MODERATOR_USER_IDS=[])
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "endpoint_models")
    if handler is None:
        group = FakeGroup._all.get("endpoint")
        handler = next(f for f in group._cmd.registered if f.__name__ == "endpoint_models")
    interaction = _interaction()
    await handler(interaction)
    interaction.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_moderator_slash_check_dynamic_mod(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core._is_admin_user = AsyncMock(return_value=True)
    bot_core.config = SimpleNamespace(ADMIN_USER_IDS=[], MODERATOR_USER_IDS=[])
    bot_core.db_repo.is_admin_user = AsyncMock(return_value=False)
    bot_core.db_repo.is_moderator_user = AsyncMock(return_value=True)
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "moderator_slash")
    interaction = _interaction()
    action = MagicMock()
    action.value = "check"
    user = MagicMock()
    user.id = 7000
    user.display_name = "Bob"
    await handler(interaction, action, user)
    assert "Moderator" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_reset_chat_slash_do_reset(monkeypatch):
    import src.handlers.discord.commands as cmd_mod

    captured = {}

    class FakeConfirmView:
        def __init__(self, *a, **kw):
            captured["on_confirm"] = kw.get("on_confirm")
            self.message = None

    monkeypatch.setattr(cmd_mod, "ConfirmActionView", FakeConfirmView)
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core.db_repo.clear_user_data_db = AsyncMock()
    bot_core.kafka_service.publish = AsyncMock(return_value=True)
    bot_core.config = SimpleNamespace(ADMIN_USER_IDS=[], MODERATOR_USER_IDS=[])
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "reset_chat_slash")
    assert handler is not None
    interaction = _interaction()
    await handler(interaction)
    on_confirm = captured["on_confirm"]
    btn = _interaction()
    result = await on_confirm(btn)
    assert "xóa toàn bộ" in result
    bot_core.db_repo.clear_user_data_db.assert_awaited_once_with("1000")


@pytest.mark.asyncio
async def test_endpoint_test_not_configured(monkeypatch):
    import src.handlers.discord.commands as cmd_mod

    resolver = MagicMock()
    resolver.get_active_sdk = AsyncMock(return_value=None)
    monkeypatch.setattr(cmd_mod, "get_endpoint_resolver", lambda: resolver)
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core.config = SimpleNamespace(ADMIN_USER_IDS=[], MODERATOR_USER_IDS=[])
    register_slash_commands(bot_core)
    group = FakeGroup._all.get("endpoint")
    handler = next(f for f in group._cmd.registered if f.__name__ == "endpoint_test")
    interaction = _interaction()
    await handler(interaction)
    interaction.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_endpoint_test_success(monkeypatch):
    import src.handlers.discord.commands as cmd_mod

    resolver = MagicMock()
    resolver.get_active_sdk = AsyncMock(return_value="genai")
    resolver.get_endpoint = AsyncMock(return_value={"base_url": "http://x", "api_key": "k"})
    resolver.get_slot_models = AsyncMock(return_value={"reasoning": "m1", "final": "m2", "fallback": None})
    monkeypatch.setattr(cmd_mod, "get_endpoint_resolver", lambda: resolver)

    gw = MagicMock()
    gw.list_models_for = AsyncMock(return_value=[{"id": "m1"}, {"id": "m2"}])
    monkeypatch.setattr(cmd_mod, "get_llm_gateway", lambda: gw)

    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core.config = SimpleNamespace(ADMIN_USER_IDS=[], MODERATOR_USER_IDS=[])
    bot_core.db_repo.update_endpoint_check_status = AsyncMock()
    register_slash_commands(bot_core)
    group = FakeGroup._all.get("endpoint")
    handler = next(f for f in group._cmd.registered if f.__name__ == "endpoint_test")
    interaction = _interaction()
    await handler(interaction)
    interaction.followup.send.assert_awaited_once()
    bot_core.db_repo.update_endpoint_check_status.assert_awaited_once()


@pytest.mark.asyncio
async def test_change_bd_too_long(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core.config = SimpleNamespace(ADMIN_USER_IDS=[], MODERATOR_USER_IDS=[])
    register_slash_commands(bot_core)
    group = FakeGroup._all.get("change")
    assert group is not None
    handler = next(f for f in group._cmd.registered if f.__name__ == "change_bd")
    interaction = _interaction()
    await handler(interaction, "x" * 40, None)
    interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_change_bd_no_permission(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core.config = SimpleNamespace(ADMIN_USER_IDS=[], MODERATOR_USER_IDS=[])
    register_slash_commands(bot_core)
    group = FakeGroup._all.get("change")
    handler = next(f for f in group._cmd.registered if f.__name__ == "change_bd")
    interaction = _interaction()
    interaction.guild = MagicMock()
    me = MagicMock()
    me.guild_permissions.manage_nicknames = False
    interaction.guild.me = me
    await handler(interaction, "newname", None)
    interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_change_bd_success(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core.config = SimpleNamespace(ADMIN_USER_IDS=[], MODERATOR_USER_IDS=[])
    register_slash_commands(bot_core)
    group = FakeGroup._all.get("change")
    handler = next(f for f in group._cmd.registered if f.__name__ == "change_bd")
    interaction = _interaction()
    interaction.guild = MagicMock()
    me = MagicMock()
    me.guild_permissions.manage_nicknames = True
    interaction.guild.me = me
    target = MagicMock(spec=discord.Member)
    target.edit = AsyncMock()
    target.mention = "<@100>"
    await handler(interaction, "newname", target)
    target.edit.assert_awaited_once_with(nick="newname")
    interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_reset_all_slash_do_confirm(monkeypatch):
    import src.handlers.discord.commands as cmd_mod

    captured = {}

    class FakeConfirmView:
        def __init__(self, *a, **kw):
            captured["on_confirm"] = kw.get("on_confirm")
            self.message = None

    monkeypatch.setattr(cmd_mod, "ConfirmActionView", FakeConfirmView)
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core._is_admin_user = AsyncMock(return_value=True)
    bot_core.db_repo.clear_all_data_db = AsyncMock()
    bot_core.kafka_service.publish = AsyncMock(return_value=True)
    bot_core.config = SimpleNamespace(ADMIN_USER_IDS=[], MODERATOR_USER_IDS=[], PROJECT_ROOT="")
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "reset_all_slash")
    assert handler is not None
    interaction = _interaction()
    await handler(interaction)

    on_confirm = captured["on_confirm"]
    res = await on_confirm(_interaction())
    assert "Đã xóa toàn bộ" in res
    bot_core.db_repo.clear_all_data_db.assert_awaited_once()


@pytest.mark.asyncio
async def test_global_notes_with_notes(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core.db_repo.get_global_notes_db = AsyncMock(return_value=[
        {"note_id": "n1", "user_id": "u1", "content": "fact 1", "fact_hash": "h1"}
    ])
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "global_notes_slash")
    interaction = _interaction()
    await handler(interaction, 40)
    interaction.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_lock_room_already_locked(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    room_lock_service = MagicMock()
    room_lock_service.is_locked = MagicMock(return_value=True)
    bot_core.room_lock_service = room_lock_service
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "lock_room")

    interaction = _interaction()
    channel = MagicMock(spec=discord.VoiceChannel)
    channel.id = 101
    channel.name = "Game"
    interaction.guild = MagicMock()
    interaction.user.voice = MagicMock(channel=channel)
    await handler(interaction)
    assert "đang bị khóa rồi" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_lock_room_success(monkeypatch):
    from datetime import datetime, timezone
    from src.voice.models import LockOutcome, LockRecord, PurgeReport

    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    room_lock_service = MagicMock()
    room_lock_service.is_locked = MagicMock(return_value=False)
    rec = LockRecord(101, datetime.now(timezone.utc), 1000)
    outcome = LockOutcome(record=rec, kicked=["Intruder"], purge=PurgeReport(deleted=3), reactions_removed=1)
    room_lock_service.lock = AsyncMock(return_value=outcome)
    bot_core.room_lock_service = room_lock_service
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "lock_room")

    interaction = _interaction()
    channel = MagicMock(spec=discord.VoiceChannel)
    channel.id = 101
    channel.name = "Game"
    interaction.guild = MagicMock()
    interaction.user.voice = MagicMock(channel=channel)
    await handler(interaction)
    interaction.followup.send.assert_awaited_once()
    embed = interaction.followup.send.call_args.kwargs.get("embed")
    assert embed is not None
    assert "Đã khóa" in embed.title


@pytest.mark.asyncio
async def test_unlock_room_success(monkeypatch):
    from datetime import datetime, timezone
    from src.voice.models import LockRecord

    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    room_lock_service = MagicMock()
    room_lock_service.is_locked = MagicMock(return_value=True)
    rec = LockRecord(101, datetime.now(timezone.utc), 1000)
    room_lock_service.unlock = AsyncMock(return_value=rec)
    bot_core.room_lock_service = room_lock_service
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "unlock_room")

    interaction = _interaction()
    channel = MagicMock(spec=discord.VoiceChannel)
    channel.id = 101
    channel.name = "Game"
    interaction.guild = MagicMock()
    interaction.user.voice = MagicMock(channel=channel)
    await handler(interaction)
    embed = interaction.followup.send.call_args.kwargs.get("embed")
    assert embed is not None
    assert "Đã mở khóa" in embed.title


@pytest.mark.asyncio
async def test_move_member_handler_success(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    room_tools = MagicMock()
    room_tools.move_member = AsyncMock(return_value=(True, "Đã chuyển user"))
    bot_core.room_tools_service = room_tools
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "move_member")

    interaction = _interaction()
    guild = MagicMock()
    target_member = MagicMock(spec=discord.Member)
    target_channel = MagicMock(spec=discord.VoiceChannel)
    guild.get_member = MagicMock(return_value=target_member)
    guild.get_channel = MagicMock(return_value=target_channel)
    interaction.guild = guild

    await handler(interaction, member="500", channel="101")
    room_tools.move_member.assert_awaited_once()
    assert "Đã chuyển" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_move_all_handler_success(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    room_tools = MagicMock()
    room_tools.move_all = AsyncMock(return_value=(3, []))
    bot_core.room_tools_service = room_tools
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "move_all")

    interaction = _interaction()
    guild = MagicMock()
    interaction.guild = guild
    source_channel = MagicMock(spec=discord.VoiceChannel)
    source_channel.id = 200
    interaction.user.voice = MagicMock(channel=source_channel)
    target_channel = MagicMock(spec=discord.VoiceChannel)
    target_channel.id = 300
    target_channel.name = "TargetRoom"

    await handler(interaction, target_channel=target_channel)
    room_tools.move_all.assert_awaited_once()
    assert "Đã chuyển **3** người" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_set_room_handler_show_status(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core.room_tools_service = MagicMock()
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "set_room")

    interaction = _interaction()
    guild = MagicMock()
    interaction.guild = guild
    channel = MagicMock(spec=discord.VoiceChannel)
    channel.id = 200
    channel.name = "MyRoom"
    channel.status = "Playing"
    interaction.user.voice = MagicMock(channel=channel)

    await handler(interaction, name=None, status=None)
    assert "Playing" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_set_room_handler_update_success(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    room_tools = MagicMock()
    room_tools.set_room = AsyncMock(return_value=(True, ["Tên: NewName"]))
    bot_core.room_tools_service = room_tools
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "set_room")

    interaction = _interaction()
    guild = MagicMock()
    interaction.guild = guild
    channel = MagicMock(spec=discord.VoiceChannel)
    channel.id = 200
    interaction.user.voice = MagicMock(channel=channel)

    await handler(interaction, name="NewName", status="Chill")
    room_tools.set_room.assert_awaited_once()
    assert "Đã cập nhật phòng" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_rolerank_command_handler(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core._is_admin_user = AsyncMock(return_value=True)
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "rolerank_command")

    interaction = _interaction()
    guild = MagicMock()
    guild.me = MagicMock()
    guild.me.guild_permissions.manage_roles = True
    guild.roles = []
    interaction.guild = guild

    await handler(interaction)
    interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_donate_slash_success(monkeypatch):
    import cryptography.fernet

    class FakeFernet:
        def __init__(self, key):
            pass

        def decrypt(self, data):
            return b"fake-png-bytes"

    monkeypatch.setattr(cryptography.fernet, "Fernet", FakeFernet)

    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core.config.PROJECT_ROOT = "."
    bot_core.config.DONATE_ENCRYPTION_KEY = "dummy_key_12345"
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "donate_slash")
    assert handler is not None

    interaction = _interaction()
    choice = MagicMock()
    choice.value = "kofi"
    await handler(interaction, choice)
    interaction.followup.send.assert_awaited_once()
    assert interaction.followup.send.call_args.kwargs.get("file") is not None


@pytest.mark.asyncio
async def test_imagine_slash_non_premium_sends_momo_qr(monkeypatch):
    import cryptography.fernet

    class FakeFernet:
        def __init__(self, key):
            pass

        def decrypt(self, data):
            return b"fake-png-bytes"

    monkeypatch.setattr(cryptography.fernet, "Fernet", FakeFernet)

    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core._is_admin_user = AsyncMock(return_value=False)
    bot_core._is_moderator_user = AsyncMock(return_value=False)
    bot_core.db_repo.is_premium_user = AsyncMock(return_value=False)
    bot_core.config.PROJECT_ROOT = "."
    bot_core.config.DONATE_ENCRYPTION_KEY = "dummy_key_12345"
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "imagine_slash")

    interaction = _interaction()
    action = MagicMock()
    action.value = "create"
    await handler(interaction, action, prompt="super cool dog")
    interaction.followup.send.assert_awaited_once()
    assert "Momo" in interaction.followup.send.call_args.kwargs.get("content", "")


@pytest.mark.asyncio
async def test_premium_slash_buy_already_premium(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core._is_admin_user = AsyncMock(return_value=False)
    bot_core._is_moderator_user = AsyncMock(return_value=True)
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "premium_slash")

    interaction = _interaction()
    action = MagicMock()
    action.value = "buy"
    await handler(interaction, action, None)
    assert "đã có quyền" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_premium_slash_buy_success(monkeypatch):
    import cryptography.fernet

    class FakeFernet:
        def __init__(self, key):
            pass

        def decrypt(self, data):
            return b"fake-png-bytes"

    monkeypatch.setattr(cryptography.fernet, "Fernet", FakeFernet)

    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core._is_admin_user = AsyncMock(return_value=False)
    bot_core._is_moderator_user = AsyncMock(return_value=False)
    bot_core.db_repo.is_premium_user = AsyncMock(return_value=False)
    bot_core.config.PROJECT_ROOT = "."
    bot_core.config.DONATE_ENCRYPTION_KEY = "dummy_key_12345"
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "premium_slash")

    interaction = _interaction()
    action = MagicMock()
    action.value = "buy"
    await handler(interaction, action, None)
    interaction.followup.send.assert_awaited_once()
    assert interaction.followup.send.call_args.kwargs.get("file") is not None


@pytest.mark.asyncio
async def test_ping_command_sends_pong(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "ping")
    assert handler is not None
    interaction = _interaction()
    await handler(interaction)
    interaction.response.send_message.assert_awaited_once()
    assert "Bot đang hoạt động" in interaction.response.send_message.call_args[0][0]


@pytest.mark.asyncio
async def test_endpoint_config_calls_flow(monkeypatch):
    import src.handlers.discord.commands as cmd_mod

    flow_mock = MagicMock()
    flow_mock.start = AsyncMock()
    monkeypatch.setattr(cmd_mod, "EndpointConfigFlow", lambda **kw: flow_mock)

    bot_core, handler = _find_group_handler(monkeypatch, "endpoint", "endpoint_config")
    interaction = _interaction()
    await handler(interaction)
    interaction.response.defer.assert_awaited_once()
    flow_mock.start.assert_awaited_once_with(interaction)


@pytest.mark.asyncio
async def test_endpoint_view_with_details(monkeypatch):
    bot_core, handler = _find_group_handler(monkeypatch, "endpoint", "endpoint_view")
    bot_core.db_repo.get_llm_endpoints = AsyncMock(return_value={
        "genai": {
            "base_url": "http://g", "updated_at": "now", "updated_by": "adm",
            "last_checked_at": "yesterday", "last_check_ok": False, "last_check_error": "timeout",
        },
        "openai": {
            "base_url": "http://o", "updated_at": "now", "updated_by": "adm",
            "last_checked_at": None,
        }
    })
    bot_core.db_repo.get_active_sdk = AsyncMock(return_value="genai")
    bot_core.db_repo.get_llm_model_slots = AsyncMock(return_value={"reasoning": "m1"})

    interaction = _interaction()
    await handler(interaction)
    interaction.followup.send.assert_awaited_once()
    embed = interaction.followup.send.call_args.kwargs.get("embed")
    assert embed is not None


@pytest.mark.asyncio
async def test_endpoint_models_empty_list(monkeypatch):
    import src.handlers.discord.commands as cmd_mod

    resolver = MagicMock()
    resolver.get_active_sdk = AsyncMock(return_value="genai")
    resolver.get_endpoint = AsyncMock(return_value={"base_url": "http://x", "api_key": "k"})
    monkeypatch.setattr(cmd_mod, "get_endpoint_resolver", lambda: resolver)

    gw = MagicMock()
    gw.list_models_for = AsyncMock(return_value=[])  # empty
    monkeypatch.setattr(cmd_mod, "get_llm_gateway", lambda: gw)

    bot_core, handler = _find_group_handler(monkeypatch, "endpoint", "endpoint_models")
    interaction = _interaction()
    await handler(interaction)
    assert "danh sách model rỗng" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_endpoint_models_fetch_error(monkeypatch):
    import src.handlers.discord.commands as cmd_mod

    resolver = MagicMock()
    resolver.get_active_sdk = AsyncMock(return_value="genai")
    resolver.get_endpoint = AsyncMock(return_value={"base_url": "http://x", "api_key": "k"})
    monkeypatch.setattr(cmd_mod, "get_endpoint_resolver", lambda: resolver)

    gw = MagicMock()
    gw.list_models_for = AsyncMock(side_effect=RuntimeError("models error"))
    monkeypatch.setattr(cmd_mod, "get_llm_gateway", lambda: gw)

    bot_core, handler = _find_group_handler(monkeypatch, "endpoint", "endpoint_models")
    interaction = _interaction()
    await handler(interaction)
    assert "Không lấy được danh sách model" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_global_note_demote_no_target_shows_view(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core.db_repo.get_global_notes_db = AsyncMock(return_value=[
        {"note_id": "n1", "user_id": "u1", "content": "note 1", "fact_hash": "h1"}
    ])
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "global_note_demote_slash")
    interaction = _interaction()
    await handler(interaction, target=None)
    interaction.followup.send.assert_awaited_once()
    assert interaction.followup.send.call_args.kwargs.get("view") is not None


@pytest.mark.asyncio
async def test_premium_slash_add_no_user(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core._is_admin_user = AsyncMock(return_value=True)
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "premium_slash")
    action = MagicMock(value="add")
    interaction = _interaction()
    await handler(interaction, action, user=None)
    assert "chọn người dùng" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_premium_slash_check_moderator_and_premium(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core._is_admin_user = AsyncMock(return_value=False)
    bot_core._is_moderator_user = AsyncMock(return_value=True)
    bot_core.db_repo.is_premium_user = AsyncMock(return_value=False)
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "premium_slash")
    action = MagicMock(value="check")
    user = MagicMock(id=88, display_name="ModUser")
    interaction = _interaction()
    await handler(interaction, action, user=user)
    assert "Moderator" in interaction.followup.send.call_args[0][0]

    # test check premium
    bot_core._is_moderator_user = AsyncMock(return_value=False)
    bot_core.db_repo.is_premium_user = AsyncMock(return_value=True)
    await handler(interaction, action, user=user)
    assert "Premium" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_moderator_slash_add_already_admin_or_mod(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core._is_admin_user = AsyncMock(return_value=True)
    bot_core.config = SimpleNamespace(ADMIN_USER_IDS=["99"], MODERATOR_USER_IDS=["88"])
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "moderator_slash")
    action = MagicMock(value="add")
    user_admin = MagicMock(id=99, display_name="AdminMan")
    user_mod = MagicMock(id=88, display_name="ModMan")
    interaction = _interaction()

    await handler(interaction, action, user=user_admin)
    assert "đã là Admin" in interaction.followup.send.call_args[0][0]

    await handler(interaction, action, user=user_mod)
    assert "đã là Moderator" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_moderator_slash_remove_not_dynamic(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core._is_admin_user = AsyncMock(return_value=True)
    bot_core.config = SimpleNamespace(ADMIN_USER_IDS=[], MODERATOR_USER_IDS=[])
    bot_core.db_repo.remove_moderator_user = AsyncMock(return_value=False)
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "moderator_slash")
    action = MagicMock(value="remove")
    user = MagicMock(id=55, display_name="Normal")
    interaction = _interaction()
    await handler(interaction, action, user=user)
    assert "không phải Moderator động" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_moderator_slash_check_static_mod_and_normal(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core._is_admin_user = AsyncMock(return_value=True)
    bot_core.config = SimpleNamespace(ADMIN_USER_IDS=[], MODERATOR_USER_IDS=["44"])
    bot_core.db_repo.is_admin_user = AsyncMock(return_value=False)
    bot_core.db_repo.is_moderator_user = AsyncMock(return_value=False)
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "moderator_slash")
    action = MagicMock(value="check")
    user_mod = MagicMock(id=44, display_name="ModStatic")
    user_norm = MagicMock(id=33, display_name="Norm")
    interaction = _interaction()

    await handler(interaction, action, user=user_mod)
    assert "tĩnh" in interaction.followup.send.call_args[0][0]

    await handler(interaction, action, user=user_norm)
    assert "người dùng bình thường" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_message_to_slash_moderator_rules(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    # caller is moderator, not admin
    bot_core._is_admin_user = AsyncMock(return_value=False)
    bot_core._is_moderator_user = AsyncMock(return_value=True)
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "message_to_slash")
    user = MagicMock(id=77, display_name="U")
    interaction = _interaction()

    # 1. No channel -> error
    await handler(interaction, user=user, message="hi", channel=None)
    assert "không được quyền gửi DM" in interaction.followup.send.call_args[0][0]

    # 2. Channel from different guild -> error
    channel = MagicMock(spec=discord.TextChannel)
    channel.guild = MagicMock()
    interaction.guild = MagicMock()
    await handler(interaction, user=user, message="hi", channel=channel)
    assert "chỉ được phép gửi tin nhắn trong server" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_message_to_slash_channel_permission_error(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core._is_admin_user = AsyncMock(return_value=True)
    bot_core._is_moderator_user = AsyncMock(return_value=False)
    bot_core.bot.fetch_user = AsyncMock(return_value=MagicMock(id=77, mention="<@77>", display_name="U"))
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "message_to_slash")

    interaction = _interaction()
    guild = MagicMock()
    me = MagicMock()
    interaction.guild = guild
    guild.me = me

    # channel not text channel
    voice_ch = MagicMock(spec=discord.VoiceChannel)
    voice_ch.guild = guild
    await handler(interaction, user=MagicMock(id=77), message="msg", channel=voice_ch)
    assert "must be text channel" in interaction.followup.send.call_args[0][0]

    # bot lacks send permission in channel
    text_ch = MagicMock(spec=discord.TextChannel)
    text_ch.guild = guild
    text_ch.permissions_for = MagicMock(return_value=MagicMock(send_messages=False))
    await handler(interaction, user=MagicMock(id=77), message="msg", channel=text_ch)
    assert "no send permission" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_set_room_no_tools(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core.room_tools_service = None
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "set_room")
    interaction = _interaction()
    await handler(interaction)
    assert "chưa sẵn sàng" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_set_room_not_in_voice(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "set_room")
    interaction = _interaction()
    interaction.guild = MagicMock()
    interaction.user.voice = None
    await handler(interaction)
    assert "không ở trong voice" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_set_room_update_failed(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core.room_tools_service.set_room = AsyncMock(return_value=(False, ["fail reason"]))
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "set_room")
    ch = MagicMock(spec=discord.VoiceChannel)
    ch.id = 1
    interaction = _interaction()
    interaction.guild = MagicMock()
    interaction.user.voice = MagicMock(channel=ch)
    await handler(interaction, name="New")
    assert "thất bại" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_move_member_no_tools(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core.room_tools_service = None
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "move_member")
    interaction = _interaction()
    await handler(interaction, "1", "2")
    assert "chưa sẵn sàng" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_move_member_not_found(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "move_member")
    interaction = _interaction()
    guild = MagicMock()
    guild.get_member = MagicMock(return_value=None)
    interaction.guild = guild
    await handler(interaction, "1", "2")
    assert "Không tìm thấy" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_move_all_no_tools(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core.room_tools_service = None
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "move_all")
    interaction = _interaction()
    await handler(interaction, target_channel=MagicMock())
    assert "chưa sẵn sàng" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_move_all_not_in_voice(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "move_all")
    interaction = _interaction()
    interaction.guild = MagicMock()
    interaction.user.voice = None
    await handler(interaction, target_channel=MagicMock())
    assert "không ở trong voice" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_move_all_same_channel(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    register_slash_commands(bot_core)
    handler = _find_registered(tree, "move_all")
    ch = MagicMock(spec=discord.VoiceChannel)
    ch.id = 100
    interaction = _interaction()
    interaction.guild = MagicMock()
    interaction.user.voice = MagicMock(channel=ch)
    await handler(interaction, target_channel=ch)
    assert "trùng phòng" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_aliases_work(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    room_lock = MagicMock()
    room_lock.whitelist = MagicMock()
    room_lock.whitelist.entries = MagicMock(return_value=[])
    bot_core.room_lock_service = room_lock
    register_slash_commands(bot_core)

    add_privet = _find_registered(tree, "add_privet")
    list_privet = _find_registered(tree, "list_privet")
    assert add_privet is not None
    assert list_privet is not None

    interaction = _interaction()
    await list_privet(interaction)
    interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_change_bd_error_branches(monkeypatch):
    _install_app_commands_mocks(monkeypatch)
    bot_core, tree = _make_bot_core()
    bot_core.config = SimpleNamespace(ADMIN_USER_IDS=[], MODERATOR_USER_IDS=[])
    register_slash_commands(bot_core)
    group = FakeGroup._all.get("change")
    handler = next(f for f in group._cmd.registered if f.__name__ == "change_bd")

    # 1. Target is not a Member (e.g. User object in DM)
    interaction = _interaction()
    guild = MagicMock()
    me = MagicMock()
    me.guild_permissions.manage_nicknames = True
    guild.me = me
    interaction.guild = guild
    user_target = MagicMock(spec=discord.User)  # User, not Member
    await handler(interaction, "nick", user_target)
    assert "Chỉ có thể đổi biệt danh" in interaction.response.send_message.call_args[0][0]

    # 2. Forbidden exception during edit
    interaction = _interaction()
    interaction.guild = guild
    member_target = MagicMock(spec=discord.Member)
    member_target.edit = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "forbidden"))
    await handler(interaction, "nick", member_target)
    assert "thiếu quyền" in interaction.response.send_message.call_args[0][0]
