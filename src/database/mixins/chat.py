"""Chat history and message logging in PostgreSQL."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Sequence


class ChatMixin:
    """Mixin providing chat history storage, queries, and message counts."""

    async def count_user_messages_today_db(self, user_id: str) -> int:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            # Mốc "hôm nay" cố định theo UTC để khớp giới hạn DM/ngày reset 00:00 UTC.
            # Không bọc hàm quanh cột "timestamp" để planner vẫn dùng được index
            # idx_messages_user_time (user_id, timestamp DESC) cho range scan.
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM messages WHERE user_id = $1 AND role = 'user' "
                "AND \"timestamp\" >= date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'",
                user_id,
            )
        return int(count or 0)

    async def log_message_db(
        self, user_id: str, role: str, content: str, message_id: Optional[str] = None
    ) -> bool:
        """Ghi một dòng lịch sử chat. Trả về False nếu dòng đã tồn tại.

        ``message_id`` do caller truyền vào phải ổn định qua các lần thử lại thì
        ``ON CONFLICT`` mới chống được ghi trùng; không truyền thì hàm tự sinh
        UUID và mỗi lần gọi là một dòng mới.
        """
        if not message_id:
            message_id = str(uuid.uuid4())
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            status = await conn.execute(
                "INSERT INTO messages (message_id, user_id, role, content) VALUES ($1, $2, $3, $4) ON CONFLICT (message_id) DO NOTHING",
                message_id,
                user_id,
                role,
                content,
            )
        # asyncpg trả "INSERT 0 1" khi chèn được, "INSERT 0 0" khi bị conflict.
        return str(status).endswith(" 1")

    async def get_user_history_from_db(
        self,
        user_id: str,
        limit: int = 10,
        exclude_message_ids: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, str]]:
        pool = await self._ensure_pool()
        safe_limit = max(1, min(limit, 100))
        excluded = [str(mid) for mid in (exclude_message_ids or []) if mid]
        async with pool.acquire() as conn:
            if excluded:
                # Dùng khi xử lý lại một tin đã được ghi ở lần thử trước: loại
                # đúng các dòng của turn hiện tại để câu hỏi không bị lặp trong
                # prompt. message_id là khoá chính nên phép lọc này rẻ.
                rows = await conn.fetch(
                    """
                    SELECT role, content
                    FROM (
                        SELECT role, content, timestamp
                        FROM messages
                        WHERE user_id = $1 AND message_id <> ALL($3::text[])
                        ORDER BY timestamp DESC
                        LIMIT $2
                    ) m
                    ORDER BY timestamp ASC
                    """,
                    user_id,
                    safe_limit,
                    excluded,
                )
            else:
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
                # Chunk nội dung file user đã upload cũng là dữ liệu của user.
                await conn.execute("DELETE FROM rag_chunks WHERE user_id = $1", user_id)
        return True

    async def clear_all_data_db(self) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("TRUNCATE TABLE messages")
                await conn.execute("TRUNCATE TABLE user_notes")
                await conn.execute("TRUNCATE TABLE rag_chunks")
        return True
