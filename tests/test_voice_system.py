"""Unit tests for voice locking system, atomic stores, purge, and role hierarchy."""

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import pytest

from src.voice.models import LockRecord, LockOutcome, PurgeReport
from src.voice.store import LockStore, WhitelistStore
from src.voice.role_hierarchy import shorten, role_rank
from src.voice.lock_service import RoomLockService


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


class TestRoleHierarchyHelpers:
    def test_shorten_text(self):
        assert shorten("hello world", 20) == "hello world"
        assert shorten("a" * 100, 10).endswith("…")


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
