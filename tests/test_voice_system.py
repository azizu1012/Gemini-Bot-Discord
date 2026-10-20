"""Unit tests for voice locking system, atomic stores, purge, and role hierarchy."""

from datetime import datetime, timezone
from pathlib import Path
import tempfile
from unittest.mock import MagicMock
import pytest
import discord

from src.voice.models import LockRecord, LockOutcome, PurgeReport, RoleMovePlan
from src.voice.store import (
    LockStore,
    WhitelistStore,
    LockStoreProtocol,
    WhitelistStoreProtocol,
)
from src.voice.purge import VoicePurgeService, voice_purge_service
from src.voice.role_hierarchy import (
    RoleHierarchyService,
    role_hierarchy_service,
    shorten,
    role_rank,
    plan_role_move,
)
from src.voice.lock_service import RoomLockService


class TestVoiceModels:
    def test_lock_record_serialization(self):
        now = datetime.now(timezone.utc)
        record = LockRecord(
            channel_id=98765,
            locked_at=now,
            locked_by=12345,
            enforced_name="VIP Room",
        )
        data = record.to_json()
        assert data["channel_id"] == 98765
        assert data["locked_by"] == 12345
        assert data["enforced_name"] == "VIP Room"

        reconstructed = LockRecord.from_json(98765, data)
        assert reconstructed.channel_id == 98765
        assert reconstructed.locked_by == 12345
        assert reconstructed.enforced_name == "VIP Room"
        assert reconstructed.locked_at == now

    def test_role_move_plan_value_object(self):
        fake_role = MagicMock(spec=discord.Role)
        fake_role.id = 111
        fake_target = MagicMock(spec=discord.Role)
        fake_target.id = 222

        plan = RoleMovePlan(
            role=fake_role,
            target_slot=2,
            payload={fake_role: 5, fake_target: 4},
        )
        assert plan.has_changes is True
        assert len(plan) == 2
        assert fake_role in plan
        assert plan[fake_role] == 5
        assert list(plan.items()) == [(fake_role, 5), (fake_target, 4)]


class TestStoreProtocols:
    def test_stores_satisfy_protocols(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_store = LockStore(Path(tmpdir) / "locked.json")
            wl_store = WhitelistStore(Path(tmpdir) / "wl.json")

            assert isinstance(lock_store, LockStoreProtocol)
            assert isinstance(wl_store, WhitelistStoreProtocol)


class TestLockStore:
    def test_lock_and_unlock_cycle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "locked_channels.json"
            store = LockStore(file_path)

            assert store.is_locked(123456) is False
            rec = store.lock(123456, locked_by=999)
            assert rec.channel_id == 123456
            assert store.is_locked(123456) is True

            # Persistence check (new instance reads disk)
            store2 = LockStore(file_path)
            assert store2.is_locked(123456) is True
            rec2 = store2.get(123456)
            assert rec2 is not None
            assert rec2.locked_by == 999

            # Unlock
            unlocked = store2.unlock(123456)
            assert unlocked is not None
            assert store2.is_locked(123456) is False


class TestWhitelistStore:
    def test_whitelist_operations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "whitelist.json"
            store = WhitelistStore(file_path)

            assert store.contains(1001) is False
            store.add(1001, "Alice")
            assert store.contains(1001) is True

            # Reload check
            store2 = WhitelistStore(file_path)
            assert store2.contains(1001) is True
            assert 1001 in store2.ids()
            entries = store2.entries()
            assert len(entries) == 1
            assert entries[0] == (1001, "Alice")

            store2.remove(1001)
            assert store2.contains(1001) is False


class TestPurgeReport:
    def test_purge_report_summary(self):
        report = PurgeReport()
        assert not report.has_work
        assert "Không có tin nhắn nào" in report.summary()

        report.violations = 5
        report.deleted = 5
        assert report.has_work
        assert "đã xóa **5** tin nhắn" in report.summary()


class TestVoicePurgeService:
    def test_purge_service_instantiation(self):
        service = VoicePurgeService(batch_size=50, max_names=10, default_limit=150)
        assert service.batch_size == 50
        assert service.max_names == 10
        assert service.default_limit == 150
        assert voice_purge_service is not None


class TestRoleHierarchyService:
    def test_shorten_text(self):
        svc = RoleHierarchyService()
        assert svc.shorten("hello world", 20) == "hello world"
        assert svc.shorten("a" * 100, 10).endswith("…")
        assert shorten("hello world", 20) == "hello world"

    def test_role_order_and_ranking(self):
        svc = RoleHierarchyService()
        guild = MagicMock(spec=discord.Guild)

        r_default = MagicMock(spec=discord.Role)
        r_default.is_default.return_value = True

        r1 = MagicMock(spec=discord.Role)
        r1.id = 1
        r1.position = 10
        r1.is_default.return_value = False

        r2 = MagicMock(spec=discord.Role)
        r2.id = 2
        r2.position = 20
        r2.is_default.return_value = False

        guild.roles = [r_default, r1, r2]

        ordered = svc.get_role_order(guild)
        assert ordered == [r2, r1]
        assert svc.get_rank(guild, r2) == 1
        assert svc.get_rank(guild, r1) == 2
        assert role_rank(guild, r2) == 1

    def test_role_plan_move(self):
        svc = RoleHierarchyService()
        guild = MagicMock(spec=discord.Guild)

        bot_member = MagicMock()
        bot_member.guild_permissions.manage_roles = True
        top_role = MagicMock()
        top_role.id = 99
        top_role.position = 100
        bot_member.top_role = top_role
        guild.me = bot_member

        r1 = MagicMock(spec=discord.Role)
        r1.id = 1
        r1.position = 30
        r1.is_default.return_value = False
        r1.managed = False

        r2 = MagicMock(spec=discord.Role)
        r2.id = 2
        r2.position = 20
        r2.is_default.return_value = False
        r2.managed = False

        guild.roles = [top_role, r1, r2]
        top_role.is_default.return_value = False

        plan = svc.plan_move(guild, r2, slot=1)
        assert isinstance(plan, RoleMovePlan)
        assert plan.role == r2
        assert plan.target_slot == 1


class FakeClient:
    def __init__(self, user_id=888):
        class FakeUser:
            id = user_id
        self.user = FakeUser()

    def get_channel(self, cid):
        return None


class TestRoomLockService:
    def test_allowed_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_store = LockStore(Path(tmpdir) / "locked.json")
            wl_store = WhitelistStore(Path(tmpdir) / "wl.json")
            wl_store.add(111, "Member 1")

            fake_bot = FakeClient(user_id=777)
            service = RoomLockService(
                store=lock_store,
                whitelist=wl_store,
                bot=fake_bot,
                owner_id=999,
            )

            allowed = service.allowed_ids()
            assert 999 in allowed  # owner
            assert 777 in allowed  # bot
            assert 111 in allowed  # whitelist
            assert 222 not in allowed
            assert service.is_allowed(111) is True
            assert service.is_allowed(222) is False
