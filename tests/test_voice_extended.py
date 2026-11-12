"""Extended offline tests for voice services (lock_service, purge, voice_lock, tools_service)."""
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
import tempfile

import discord
import pytest
from unittest.mock import AsyncMock

sys.path.insert(0, ".")

from src.voice.lock_service import RoomLockService, is_member_overwrite
from src.voice.purge import VoicePurgeService
from src.voice.voice_lock import VoiceLockManager
from src.voice.tools_service import RoomToolsService
from src.voice.models import LockOutcome, LockRecord, PurgeReport


class StubLockStore:
    def __init__(self):
        self._records = {}

    def lock(self, channel_id, locked_by=None):
        rec = LockRecord(
            channel_id=channel_id,
            locked_at=datetime.now(timezone.utc),
            locked_by=locked_by,
            enforced_name=None,
        )
        self._records[channel_id] = rec
        return rec

    def unlock(self, channel_id):
        return self._records.pop(channel_id, None)

    def is_locked(self, channel_id):
        return channel_id in self._records

    def get(self, channel_id):
        return self._records.get(channel_id)

    def records(self):
        return list(self._records.values())

    def set_enforced_name(self, channel_id, name):
        if channel_id in self._records:
            self._records[channel_id].enforced_name = name

    def channel_ids(self):
        return set(self._records.keys())


class StubWhitelist:
    def __init__(self):
        self.members = set()

    def ids(self):
        return set(self.members)

    def add(self, uid, name):
        self.members.add(uid)


def _mock_member(uid, name="user", bot=False):
    m = MagicMock(spec=discord.Member)
    m.id = uid
    m.display_name = name
    m.bot = bot
    m.mention = f"<@{uid}>"
    m.name = name
    m.move_to = AsyncMock()
    return m


def _mock_guild(gid=1):
    g = MagicMock(spec=discord.Guild)
    g.id = gid
    g.default_role = MagicMock(spec=discord.Role)
    g.get_member = MagicMock(return_value=None)
    return g


def _mock_channel(cid, guild, members=None):
    ch = MagicMock(spec=discord.VoiceChannel)
    ch.id = cid
    ch.name = f"room-{cid}"
    ch.guild = guild
    ch.members = members or []
    ch.overwrites = {}
    ch.overwrites_for = MagicMock(return_value=MagicMock())
    ch.set_permissions = AsyncMock()
    ch.history = MagicMock()
    ch.edit = AsyncMock()
    return ch


# ---------------- is_member_overwrite ----------------
def test_is_member_overwrite_role_is_false():
    role = MagicMock(spec=discord.Role)
    assert is_member_overwrite(role) is False


def test_is_member_overwrite_member_is_true():
    member = _mock_member(1)
    assert is_member_overwrite(member) is True


# ---------------- RoomLockService basic logic ----------------
def _service(store=None, wl=None, member=None, owner=999):
    store = store or StubLockStore()
    wl = wl or StubWhitelist()

    class _User:
        id = 12345

    bot = MagicMock()
    bot.user = _User()
    bot.get_channel = MagicMock(return_value=None)
    return RoomLockService(store, wl, bot, owner, logger_override=_NullLogger())


class _NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


def test_is_locked_and_record():
    svc = _service()
    assert svc.is_locked(1) is False
    svc.store.lock(1, 999)
    assert svc.is_locked(1) is True
    assert svc.record(1) is not None
    assert svc.record(2) is None


def test_allowed_ids_includes_owner_and_bot():
    svc = _service(owner=999)
    svc.whitelist.add(500, "A")
    ids = svc.allowed_ids()
    assert 999 in ids
    assert 12345 in ids  # bot user
    assert 500 in ids
    assert svc.is_allowed(500) is True
    assert svc.is_allowed(777) is False


def test_prune_missing_channels_removes():
    store = StubLockStore()
    store.lock(101, 999)
    store.lock(102, 999)
    svc = _service(store=store)

    def get_channel(cid):
        # simulate only channel 102 exists
        if cid == 101:
            return None
        g = _mock_guild()
        return _mock_channel(102, g)

    svc.bot.get_channel = get_channel
    removed = svc.prune_missing_channels()
    assert len(removed) == 1
    assert removed[0].channel_id == 101
    assert svc.is_locked(101) is False


def test_all_locked_channels_filters_voice():
    store = StubLockStore()
    store.lock(201, 999)
    store.lock(202, 999)
    svc = _service(store=store)
    g = _mock_guild()
    ch = _mock_channel(202, g)

    def get_channel(cid):
        if cid == 201:
            return ch  # valid voice
        return None

    svc.bot.get_channel = get_channel
    found = svc.all_locked_channels()
    assert len(found) == 1
    assert found[0].id == 202


def test_locked_channels_filters_by_guild():
    store = StubLockStore()
    store.lock(301, 999)
    svc = _service(store=store)
    g1 = _mock_guild(10)
    g2 = _mock_guild(20)
    svc.bot.get_channel = MagicMock(return_value=_mock_channel(301, g1))
    # channel on guild 10, asking for guild 20 -> empty
    assert svc.locked_channels(g2) == []


# ---------------- lock/unlock/enforce ----------------
@pytest.mark.asyncio
async def test_lock_flow_returns_outcome():
    store = StubLockStore()
    svc = _service(store=store)
    g = _mock_guild()
    ch = _mock_channel(401, g, members=[_mock_member(2, "stranger")])
    ch.overwrites_for = MagicMock(return_value=MagicMock())

    async def fake_enforce(*a, **kw):
        return ["stranger"]

    async def fake_clean(*a, **kw):
        return PurgeReport()

    async def fake_strip(*a, **kw):
        return 2

    svc.enforce = fake_enforce
    svc.clean_messages = fake_clean
    svc.strip_reactions = fake_strip
    svc.apply_permissions = AsyncMock()

    outcome = await svc.lock(ch, 999)
    assert isinstance(outcome, LockOutcome)
    assert outcome.record is not None
    assert outcome.kicked == ["stranger"]
    assert outcome.reactions_removed == 2
    assert svc.is_locked(401)


@pytest.mark.asyncio
async def test_unlock_resets_permissions():
    store = StubLockStore()
    store.lock(501, 999)
    svc = _service(store=store)

    g = _mock_guild()
    base_perms = MagicMock()
    base_perms.connect = False
    base_perms.add_reactions = False
    ch = _mock_channel(501, g)
    ch.overwrites_for = MagicMock(return_value=base_perms)

    member = _mock_member(7)
    member_overwrite = MagicMock(connect=True, add_reactions=True)
    ch.overwrites = {member: member_overwrite}

    rec = await svc.unlock(ch)
    assert rec is not None
    assert svc.is_locked(501) is False
    assert ch.set_permissions.await_count >= 1


# ---------------- enforce ----------------
@pytest.mark.asyncio
async def test_enforce_kicks_non_allowed():
    store = StubLockStore()
    svc = _service(store=store, owner=999)
    svc.whitelist.add(999, "owner")  # owner is allowed anyway
    g = _mock_guild()
    member_ok = _mock_member(999, "owner")
    member_bad = _mock_member(50, "bad")
    ch = _mock_channel(601, g, members=[member_ok, member_bad])
    kicked = await svc.enforce(ch)
    assert kicked == ["bad"]
    member_bad.move_to.assert_called_once()


# ---------------- purge service ----------------
async def _async_iter(items):
    for it in items:
        yield it


@pytest.mark.asyncio
async def test_purge_deletes_violations():
    svc = VoicePurgeService(batch_size=50)
    cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)

    msg_old = MagicMock()
    msg_old.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    msg_old.author = MagicMock(id=100)
    msg_old.webhook_id = None

    msg_bot = MagicMock()
    msg_bot.created_at = datetime(2026, 6, 1, tzinfo=timezone.utc)
    msg_bot.author = MagicMock(id=3)
    msg_bot.webhook_id = None

    msg_ok = MagicMock()
    msg_ok.created_at = datetime(2026, 6, 2, tzinfo=timezone.utc)
    msg_ok.author = MagicMock(id=999)
    msg_ok.webhook_id = None

    msg_bad = MagicMock()
    msg_bad.created_at = datetime(2026, 6, 3, tzinfo=timezone.utc)
    msg_bad.author = MagicMock(id=50, display_name="BadGuy")
    msg_bad.webhook_id = None
    msg_bad.delete = AsyncMock()

    channel = MagicMock()
    channel.id = 1 << 32 | 5
    text_channel = MagicMock(spec=discord.TextChannel)
    # history is newest-first; old message at the end triggers the cut-off break
    text_channel.history = MagicMock(return_value=_async_iter([msg_bad, msg_ok, msg_bot, msg_old]))
    text_channel.delete_messages = AsyncMock()
    channel.guild.get_channel = MagicMock(return_value=text_channel)

    report = await svc.purge_foreign_messages(
        channel,
        cutoff=cutoff,
        allowed_ids={999},
        bot_user_id=3,
    )
    assert report.violations == 1
    assert report.deleted == 1
    assert "BadGuy" in report.names
    # single violation -> per-message delete path
    msg_bad.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_purge_handles_forbidden(monkeypatch):
    class _FakeForbidden(Exception):
        pass

    monkeypatch.setattr(discord, "Forbidden", _FakeForbidden)
    svc = VoicePurgeService()

    async def _boom():
        raise _FakeForbidden()

    channel = MagicMock()
    channel.id = 1 << 32 | 6
    channel.history = MagicMock(return_value=_boom())
    channel.guild.get_channel = MagicMock(return_value=MagicMock(spec=discord.TextChannel))

    report = await svc.purge_foreign_messages(
        channel,
        cutoff=datetime.now(timezone.utc),
        allowed_ids={1},
        bot_user_id=2,
    )
    assert report.deleted == 0
    assert report.scanned == 0


@pytest.mark.asyncio
async def test_resolve_text_channel_uses_cache():
    svc = VoicePurgeService()
    g = _mock_guild()
    ch = _mock_channel(1 << 32 | 5, g)
    text = MagicMock(spec=discord.TextChannel)
    g.get_channel = MagicMock(return_value=text)
    result = await svc.resolve_text_channel(ch)
    assert result is text


@pytest.mark.asyncio
async def test_resolve_text_channel_fetch_fallback():
    svc = VoicePurgeService()
    g = _mock_guild()
    ch = _mock_channel(1 << 32 | 7, g)
    g.get_channel = MagicMock(return_value=None)
    text = MagicMock(spec=discord.TextChannel)
    g.fetch_channel = AsyncMock(return_value=text)
    result = await svc.resolve_text_channel(ch)
    assert result is text


@pytest.mark.asyncio
async def test_resolve_text_channel_not_found(monkeypatch):
    class _FakeNotFound(Exception):
        pass

    monkeypatch.setattr(discord, "NotFound", _FakeNotFound)
    svc = VoicePurgeService()
    g = _mock_guild()
    ch = _mock_channel(1 << 32 | 9, g)
    g.get_channel = MagicMock(return_value=None)
    g.fetch_channel = AsyncMock(side_effect=_FakeNotFound())
    result = await svc.resolve_text_channel(ch)
    assert result is None


# ---------------- VoiceLockManager facade ----------------
def test_voice_lock_manager_initializes():
    with tempfile.TemporaryDirectory() as tmp:
        mgr = VoiceLockManager(
            owner_id=999,
            whitelist_file=str(Path(tmp) / "wl.json"),
            locked_channels_file=str(Path(tmp) / "lc.json"),
            enforced_names_file=str(Path(tmp) / "en.json"),
            voice_lock_log_file=str(Path(tmp) / "vl.log"),
        )
        assert mgr.owner_id == 999
        assert mgr.locked_channels == set()
        assert mgr.enforced_names == {}


def test_voice_lock_manager_load_whitelist_defaults():
    with tempfile.TemporaryDirectory() as tmp:
        mgr = VoiceLockManager(999, str(Path(tmp) / "wl.json"),
                               str(Path(tmp) / "lc.json"),
                               str(Path(tmp) / "en.json"),
                               str(Path(tmp) / "vl.log"))
        data = mgr.load_whitelist()
        assert str(999) in data
        mgr.save_whitelist(data)
        data2 = mgr.load_whitelist(force_reload=True)
        assert str(999) in data2


def test_voice_lock_manager_log_action():
    with tempfile.TemporaryDirectory() as tmp:
        logfile = Path(tmp) / "sub" / "vl.log"
        mgr = VoiceLockManager(999, str(Path(tmp) / "wl.json"),
                               str(Path(tmp) / "lc.json"),
                               str(Path(tmp) / "en.json"),
                               str(logfile))
        mgr.log_action("hello")
        assert logfile.exists()
        assert "hello" in logfile.read_text(encoding="utf-8")


def test_voice_lock_manager_owner_check(monkeypatch):
    import src.voice.voice_lock as vl

    captured = {}

    def fake_check(predicate):
        captured["predicate"] = predicate
        return lambda f: f

    monkeypatch.setattr(vl.app_commands, "check", fake_check)

    with tempfile.TemporaryDirectory() as tmp:
        mgr = VoiceLockManager(999, str(Path(tmp) / "wl.json"),
                               str(Path(tmp) / "lc.json"),
                               str(Path(tmp) / "en.json"),
                               str(Path(tmp) / "vl.log"))
        decorator = mgr.is_owner_check()
        assert decorator is not None
        assert "predicate" in captured

        predicate = captured["predicate"]

        class _Interaction:
            def __init__(self, uid):
                self.user = type("U", (), {"id": uid})()

        import asyncio
        import inspect

        assert inspect.iscoroutinefunction(predicate)
        assert asyncio.run(predicate(_Interaction(999))) is True
        assert asyncio.run(predicate(_Interaction(1))) is False


# ---------------- RoomToolsService ----------------
def _tools_service(store=None, wl=None, owner=999):
    svc = _service(store=store, wl=wl, owner=owner)
    return RoomToolsService(svc, logger_override=_NullLogger())


@pytest.mark.asyncio
async def test_move_member_no_voice():
    svc = _tools_service()
    member = _mock_member(1)
    member.voice = None
    ch = _mock_channel(1, _mock_guild())
    ok, msg = await svc.move_member(member, ch, member)
    assert ok is False
    assert "không ở trong phòng" in msg


@pytest.mark.asyncio
async def test_move_member_different_guild():
    svc = _tools_service()
    member = _mock_member(1)
    member.voice = MagicMock(channel=MagicMock())
    ch = _mock_channel(1, _mock_guild(2))
    member.guild = _mock_guild(1)
    ok, _ = await svc.move_member(member, ch, member)
    assert ok is False


@pytest.mark.asyncio
async def test_move_member_success():
    svc = _tools_service()
    member = _mock_member(1)
    member.voice = MagicMock(channel=MagicMock())
    g = _mock_guild(1)
    ch = _mock_channel(1, g)
    member.guild = g
    ok, msg = await svc.move_member(member, ch, member)
    assert ok is True
    member.move_to.assert_awaited_once()


@pytest.mark.asyncio
async def test_move_all_skips_duplicates_and_bots():
    svc = _tools_service()
    actor = _mock_member(9, "actor")
    member_a = _mock_member(1, "A")
    member_b = _mock_member(2, "B", bot=True)
    # allow actor and member_a
    svc.service.whitelist.add(9, "actor")
    svc.service.whitelist.add(1, "A")
    source = MagicMock()
    source.id = 100
    source.members = [actor, member_a, member_b]
    source.guild = _mock_guild()
    # mock is_allowed to trust our whitelist instead of the default service copy
    svc.service.allowed_ids = MagicMock(return_value={9, 1})
    target = MagicMock()
    target.guild = source.guild
    moved, failed = await svc.move_all(source, target, actor)
    assert moved == 2  # actor + A; bot skipped
    assert failed == []


@pytest.mark.asyncio
async def test_set_room_updates_name_and_status():
    svc = _tools_service()
    ch = MagicMock()
    ch.id = 1
    ch.edit = AsyncMock()

    store = StubLockStore()
    svc.service.store = store
    store.lock(1, 999)

    ok, updates = await svc.set_room(ch, name="  New Room  ", status="busy")
    assert ok is True
    assert any("New Room" in u for u in updates)
    assert any("busy" in u for u in updates)
    ch.edit.assert_awaited_once()
    # enforced name recorded because room is locked
    assert store.get(1).enforced_name == "New Room"


@pytest.mark.asyncio
async def test_set_room_no_args_returns_false():
    svc = _tools_service()
    ch = MagicMock()
    ok, updates = await svc.set_room(ch)
    assert ok is False
    assert updates == []
