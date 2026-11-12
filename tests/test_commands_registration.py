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
