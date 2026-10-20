"""User processing state management and atomic locks in PostgreSQL."""

from __future__ import annotations

from typing import Optional


class StateMixin:
    """Mixin for managing user processing states to prevent concurrent request collisions."""

    async def set_user_processing_state(self, user_id: str, stage: str) -> Optional[str]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO user_processing_states (user_id, is_busy, current_stage, last_updated)
                VALUES ($1, TRUE, $2, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id) DO UPDATE
                SET is_busy = TRUE,
                    current_stage = $2,
                    last_updated = CURRENT_TIMESTAMP
                WHERE user_processing_states.is_busy = FALSE
                   OR user_processing_states.last_updated < CURRENT_TIMESTAMP - INTERVAL '5 minutes'
                RETURNING current_stage
                """,
                user_id,
                stage,
            )
            if row:
                return None
            current = await conn.fetchval(
                "SELECT current_stage FROM user_processing_states WHERE user_id = $1",
                user_id,
            )
            return current or "đang bận"

    async def clear_user_processing_state(self, user_id: str) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE user_processing_states
                SET is_busy = FALSE, current_stage = '', last_updated = CURRENT_TIMESTAMP
                WHERE user_id = $1
                """,
                user_id,
            )
