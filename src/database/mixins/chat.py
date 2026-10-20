"""Chat history and message logging in PostgreSQL."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional


class ChatMixin:
    """Mixin providing chat history storage, queries, and message counts."""

    async def count_user_messages_today_db(self, user_id: str) -> int:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM messages WHERE user_id = $1 AND role = 'user' AND DATE(timestamp) = CURRENT_DATE",
                user_id,
            )
        return int(count or 0)

    async def log_message_db(self, user_id: str, role: str, content: str, message_id: Optional[str] = None) -> None:
        if not message_id:
            message_id = str(uuid.uuid4())
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO messages (message_id, user_id, role, content) VALUES ($1, $2, $3, $4) ON CONFLICT (message_id) DO NOTHING",
                message_id,
                user_id,
                role,
                content,
            )

    async def get_user_history_from_db(self, user_id: str, limit: int = 10) -> List[Dict[str, str]]:
        pool = await self._ensure_pool()
        safe_limit = max(1, min(limit, 100))
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT role, content
                FROM (
                    SELECT role, content, timestamp
                    FROM messages
                    WHERE user_id = $1
                    ORDER BY timestamp DESC
                    LIMIT $2
                ) m
                ORDER BY timestamp ASC
                """,
                user_id,
                safe_limit,
            )
        return [{"role": row["role"], "content": row["content"]} for row in rows]

    async def count_distinct_message_users_db(self) -> int:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            count = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM messages")
        return int(count or 0)

    async def has_other_users_history_db(self, user_id: str) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            val = await conn.fetchval("SELECT 1 FROM messages WHERE user_id != $1 LIMIT 1", user_id)
        return val is not None

    async def search_user_messages_db(
        self, search_query: str, limit: int = 30, exclude_user_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        pool = await self._ensure_pool()
        safe_limit = max(1, min(limit, 100))
        async with pool.acquire() as conn:
            if exclude_user_id:
                rows = await conn.fetch(
                    "SELECT user_id, content, timestamp FROM messages WHERE role = 'user' AND content ILIKE $1 AND user_id != $2 ORDER BY timestamp DESC LIMIT $3",
                    f"%{search_query}%",
                    exclude_user_id,
                    safe_limit,
                )
            else:
                rows = await conn.fetch(
                    "SELECT user_id, content, timestamp FROM messages WHERE role = 'user' AND content ILIKE $1 ORDER BY timestamp DESC LIMIT $2",
                    f"%{search_query}%",
                    safe_limit,
                )
        result = []
        for row in rows:
            item = dict(row)
            if item.get("timestamp"):
                item["timestamp"] = item["timestamp"].isoformat()
            result.append(item)
        return result

    async def clear_user_data_db(self, user_id: str) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM messages WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM user_notes WHERE user_id = $1", user_id)
        return True

    async def clear_all_data_db(self) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("TRUNCATE TABLE messages")
                await conn.execute("TRUNCATE TABLE user_notes")
        return True
