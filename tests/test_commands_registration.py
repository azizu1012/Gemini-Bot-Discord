"""Offline smoke tests for register_slash_commands wiring and its error handler.

We patch the discord app_commands surface with no-op collectors so the large
command-registration function can run without a live Discord client, exercising
every command definition + the shared error handler.
"""
import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

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
    def __init__(self, *a, **kw):
        self._cmd = FakeCommandDecorator()

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
    bot_core.db_repo = MagicMock()
    bot_core.config = SimpleNamespace(
        ADMIN_USER_IDS=[],
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
