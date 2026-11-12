"""Offline tests for PremiumManager."""
import sys
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, ".")

from src.managers.premium_manager import PremiumManager


def make_mgr():
    mgr = PremiumManager()
    mgr.db = AsyncMock()
    return mgr


@pytest.mark.asyncio
async def test_is_premium_user():
    mgr = make_mgr()
    mgr.db.is_premium_user = AsyncMock(return_value=True)
    assert await mgr.is_premium_user("u1") is True
    mgr.db.is_premium_user.assert_awaited_once_with("u1")


@pytest.mark.asyncio
async def test_is_admin_user_static():
    import src.core.config as config

    mgr = make_mgr()
    old = config.ADMIN_USER_IDS
    config.ADMIN_USER_IDS = ["1000"]
    try:
        assert await mgr.is_admin_user("1000") is True
        mgr.db.is_admin_user.assert_not_called()
    finally:
        config.ADMIN_USER_IDS = old


@pytest.mark.asyncio
async def test_is_admin_user_db():
    mgr = make_mgr()
    mgr.db.is_admin_user = AsyncMock(return_value=True)
    assert await mgr.is_admin_user("9999") is True
    mgr.db.is_admin_user.assert_awaited_once_with("9999")


@pytest.mark.asyncio
async def test_is_moderator_user_static():
    import src.core.config as config

    mgr = make_mgr()
    old = config.MODERATOR_USER_IDS
    config.MODERATOR_USER_IDS = ["2000"]
    try:
        assert await mgr.is_moderator_user("2000") is True
        mgr.db.is_moderator_user.assert_not_called()
    finally:
        config.MODERATOR_USER_IDS = old


@pytest.mark.asyncio
async def test_is_moderator_user_db():
    mgr = make_mgr()
    mgr.db.is_moderator_user = AsyncMock(return_value=False)
    assert await mgr.is_moderator_user("8888") is False


@pytest.mark.asyncio
async def test_add_remove_premium():
    mgr = make_mgr()
    mgr.db.add_premium_user = AsyncMock(return_value=True)
    mgr.db.remove_premium_user = AsyncMock(return_value=True)
    assert await mgr.add_premium_user("u9") is True
    assert await mgr.remove_premium_user("u9") is True
