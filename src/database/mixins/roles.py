"""User roles and permissions (admin, moderator, premium)."""

from __future__ import annotations


class RolesMixin:
    """Mixin providing role management operations (Admin, Moderator, Premium)."""

    async def add_premium_user(self, user_id: str) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO premium_users (user_id, added_at) VALUES ($1, CURRENT_TIMESTAMP) ON CONFLICT (user_id) DO NOTHING",
                user_id,
            )
        return True

    async def remove_premium_user(self, user_id: str) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("DELETE FROM premium_users WHERE user_id = $1", user_id)
        return result != "DELETE 0"

    async def is_premium_user(self, user_id: str) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            val = await conn.fetchval("SELECT 1 FROM premium_users WHERE user_id = $1", user_id)
        return val is not None

    async def add_moderator_user(self, user_id: str) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO moderator_users (user_id, added_at) VALUES ($1, CURRENT_TIMESTAMP) ON CONFLICT (user_id) DO NOTHING",
                user_id,
            )
        return True

    async def remove_moderator_user(self, user_id: str) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("DELETE FROM moderator_users WHERE user_id = $1", user_id)
        return result != "DELETE 0"

    async def is_moderator_user(self, user_id: str) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            val = await conn.fetchval("SELECT 1 FROM moderator_users WHERE user_id = $1", user_id)
        return val is not None

    async def add_admin_user(self, user_id: str) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO admin_users (user_id, added_at) VALUES ($1, CURRENT_TIMESTAMP) ON CONFLICT (user_id) DO NOTHING",
                user_id,
            )
        return True

    async def remove_admin_user(self, user_id: str) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("DELETE FROM admin_users WHERE user_id = $1", user_id)
        return result != "DELETE 0"

    async def is_admin_user(self, user_id: str) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            val = await conn.fetchval("SELECT 1 FROM admin_users WHERE user_id = $1", user_id)
        return val is not None
