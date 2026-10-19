"""Unit tests for system managers (CacheManager, CleanupManager, PremiumManager)."""

import os
import tempfile
import time
import pytest
from src.managers.cache_manager import CacheManager, get_cache_manager
from src.managers.cleanup_manager import CleanupManager
from src.managers.premium_manager import PremiumManager


class TestCacheManager:
    def test_singleton_instance(self):
        cm1 = get_cache_manager()
        cm2 = get_cache_manager()
        assert cm1 is cm2

    def test_chat_history_cache_and_lru(self):
        cm = CacheManager()
        user_id = "user_test_1"
        history = [
            {"role": "user", "content": "hello"},
            {"role": "model", "content": "hi there"},
        ]
        cm.set_chat_history(user_id, history)
        cached = cm.get_chat_history(user_id, limit=2)
        assert cached == history

        cm.add_chat_message(user_id, "user", "how are you?")
        updated = cm.get_chat_history(user_id, limit=10)
        assert len(updated) == 3

        cm.invalidate_chat_history(user_id)
        assert cm.get_chat_history(user_id, limit=10) is None

    def test_search_and_image_cache(self):
        cm = CacheManager()
        cm.set_web_search_cache("python test", "result 123")
        assert cm.get_web_search_cache("python test") == "result 123"

        cm.set_image_recognition_cache("https://img.png", "what is this?", "a cat")
        assert cm.get_image_recognition_cache("https://img.png", "what is this?") == "a cat"

        cm.clear_all_caches()
        assert cm.get_web_search_cache("python test") is None
        assert cm.get_image_recognition_cache("https://img.png", "what is this?") is None


class TestCleanupManager:
    def test_disk_space_check_and_safe_cleanup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = CleanupManager(storage_path=tmpdir, min_free_mb=100)
            free_mb = mgr.get_disk_free_space_mb()
            assert isinstance(free_mb, int)
            assert free_mb >= 0


class FakeDbRepo:
    def __init__(self):
        self.admins = set()
        self.mods = set()
        self.premiums = set()

    async def is_premium_user(self, uid):
        return uid in self.premiums

    async def is_admin_user(self, uid):
        return uid in self.admins

    async def is_moderator_user(self, uid):
        return uid in self.mods

    async def add_premium_user(self, uid):
        self.premiums.add(uid)
        return True

    async def remove_premium_user(self, uid):
        self.premiums.discard(uid)
        return True


class TestPremiumManager:
    @pytest.mark.asyncio
    async def test_roles_and_premium_toggle(self):
        pm = PremiumManager.__new__(PremiumManager)
        fake_db = FakeDbRepo()
        pm.db = fake_db

        assert await pm.is_premium_user("u100") is False
        assert await pm.add_premium_user("u100") is True
        assert await pm.is_premium_user("u100") is True
        assert await pm.remove_premium_user("u100") is True
        assert await pm.is_premium_user("u100") is False
