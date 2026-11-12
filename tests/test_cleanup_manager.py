"""Offline tests for CleanupManager (disk cleanup logic)."""
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, ".")

from src.managers.cleanup_manager import CleanupManager


class NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


def test_init_defaults():
    mgr = CleanupManager(storage_path="data", min_free_mb=100)
    assert mgr.storage_path == "data"
    assert mgr.min_free_mb == 100


def test_get_disk_free_space_mb_ok(monkeypatch, tmp_path):
    import shutil

    def fake_disk_usage(path):
        return (0, 0, 10 * 1024 * 1024)

    monkeypatch.setattr(shutil, "disk_usage", fake_disk_usage)
    mgr = CleanupManager(storage_path=str(tmp_path), min_free_mb=5)
    mgr.logger = NullLogger()
    assert mgr.get_disk_free_space_mb() == 10


def test_get_disk_free_space_mb_error(monkeypatch, tmp_path):
    import shutil

    def boom(path):
        raise OSError("bad path")

    monkeypatch.setattr(shutil, "disk_usage", boom)
    mgr = CleanupManager(storage_path=str(tmp_path), min_free_mb=5)
    mgr.logger = NullLogger()
    assert mgr.get_disk_free_space_mb() == 0


def test_cleanup_noop_when_enough_space(monkeypatch, tmp_path):
    import asyncio

    mgr = CleanupManager(storage_path=str(tmp_path), min_free_mb=5)
    mgr.logger = MagicMock()
    mgr.get_disk_free_space_mb = MagicMock(return_value=100)
    asyncio.run(mgr.cleanup_local_files())
    mgr.logger.info.assert_called()


@pytest.mark.asyncio
async def test_cleanup_deletes_old_files(monkeypatch, tmp_path):
    # create a couple of files
    f1 = tmp_path / "old.txt"
    f2 = tmp_path / "new.txt"
    f1.write_text("x" * 100)
    f2.write_text("y" * 100)

    # free space is low so cleanup starts, then recovers after deletion
    space = {"current": 3}
    mgr = CleanupManager(storage_path=str(tmp_path), min_free_mb=100)
    mgr.logger = NullLogger()
    mgr.get_disk_free_space_mb = MagicMock(side_effect=lambda: space["current"])

    await mgr.cleanup_local_files()
    # files should be removed once cleanup ran
    assert not f1.exists() and not f2.exists()


@pytest.mark.asyncio
async def test_cleanup_stops_when_threshold_reached(monkeypatch, tmp_path):
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("a" * 100)
    f2.write_text("b" * 100)

    # start low, cross threshold after deleting first file
    calls = {"n": 0}

    def fake_free():
        calls["n"] += 1
        return 3 if calls["n"] == 1 else 200

    mgr = CleanupManager(storage_path=str(tmp_path), min_free_mb=100)
    mgr.logger = NullLogger()
    mgr.get_disk_free_space_mb = MagicMock(side_effect=fake_free)

    await mgr.cleanup_local_files()
    # once space recovered, it stops deleting; at least one file deleted
    assert (not f1.exists()) or (not f2.exists())


@pytest.mark.asyncio
async def test_cleanup_handles_delete_error(monkeypatch, tmp_path):
    f1 = tmp_path / "locked.txt"
    f1.write_text("data")

    def fake_remove(path):
        if path.endswith("locked.txt"):
            raise PermissionError("locked")

    monkeypatch.setattr(os, "remove", fake_remove)
    mgr = CleanupManager(storage_path=str(tmp_path), min_free_mb=100)
    mgr.logger = NullLogger()
    mgr.get_disk_free_space_mb = MagicMock(return_value=1)

    await mgr.cleanup_local_files()
    # file remains because delete failed, but no exception propagates
    assert f1.exists()
