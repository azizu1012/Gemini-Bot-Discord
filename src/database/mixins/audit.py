"""Audit and usage tracking (token usage, search queries, generated images)."""

from __future__ import annotations

from typing import Any, Dict, List


class AuditMixin:
    """Mixin providing audit logging and history retrieval."""

    async def log_usage(
        self,
        user_id: str,
        action_type: str,
        model_name: str = "",
        tokens_used: int = 0,
        metadata: str = "",
    ) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO usage_logs (user_id, action_type, model_name, tokens_used, metadata) VALUES ($1, $2, $3, $4, $5)",
                user_id,
                action_type,
                model_name,
                tokens_used,
                metadata,
            )
        return True

    async def log_web_search(self, user_id: str, query: str, results: str) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO web_history (user_id, query, results) VALUES ($1, $2, $3)",
                user_id,
                query,
                results,
            )
        return True

    async def get_web_history(self, user_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        pool = await self._ensure_pool()
        safe_limit = max(1, min(limit, 100))
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT query, results, timestamp FROM web_history WHERE user_id = $1 ORDER BY timestamp DESC LIMIT $2",
                user_id,
                safe_limit,
            )
        result = []
        for row in rows:
            item = dict(row)
            if item.get("timestamp"):
                item["timestamp"] = item["timestamp"].isoformat()
            result.append(item)
        return result

    async def save_generated_image(self, user_id: str, prompt: str, image_url: str) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO generated_images (user_id, prompt, image_url) VALUES ($1, $2, $3)",
                user_id,
                prompt,
                image_url,
            )
        return True

    async def get_generated_images(self, user_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        pool = await self._ensure_pool()
        safe_limit = max(1, min(limit, 100))
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT prompt, image_url, timestamp FROM generated_images WHERE user_id = $1 ORDER BY timestamp DESC LIMIT $2",
                user_id,
                safe_limit,
            )
        result = []
        for row in rows:
            item = dict(row)
            if item.get("timestamp"):
                item["timestamp"] = item["timestamp"].isoformat()
            result.append(item)
        return result
