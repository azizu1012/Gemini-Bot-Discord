"""LLM endpoints and model slot configurations in PostgreSQL."""

from __future__ import annotations

from typing import Any, Dict, Optional


class EndpointsMixin:
    """Mixin providing CRUD operations for LLM endpoints and 4 model slots."""

    async def get_llm_endpoints(self) -> Dict[str, Dict[str, Any]]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT sdk, base_url, api_key_encrypted, is_active, updated_by, updated_at,
                       last_check_ok, last_check_error, last_checked_at
                FROM llm_endpoints
                """
            )
        return {row["sdk"]: dict(row) for row in rows}

    async def get_active_sdk(self) -> Optional[str]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT sdk FROM llm_endpoints WHERE is_active = TRUE LIMIT 1")
        return row["sdk"] if row else None

    async def upsert_llm_endpoint(self, sdk: str, base_url: str, api_key_encrypted: str, updated_by: str) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO llm_endpoints (sdk, base_url, api_key_encrypted, is_active, updated_by, updated_at)
                VALUES ($1, $2, $3, FALSE, $4, CURRENT_TIMESTAMP)
                ON CONFLICT (sdk) DO UPDATE SET
                    base_url = EXCLUDED.base_url,
                    api_key_encrypted = EXCLUDED.api_key_encrypted,
                    updated_by = EXCLUDED.updated_by,
                    updated_at = CURRENT_TIMESTAMP
                """,
                sdk,
                base_url,
                api_key_encrypted,
                updated_by,
            )

    async def set_active_sdk(self, sdk: str, updated_by: str) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("UPDATE llm_endpoints SET is_active = FALSE WHERE is_active = TRUE")
                result = await conn.execute(
                    """
                    UPDATE llm_endpoints
                    SET is_active = TRUE, updated_by = $2, updated_at = CURRENT_TIMESTAMP
                    WHERE sdk = $1
                    """,
                    sdk,
                    updated_by,
                )
        return result.endswith(" 1")

    async def save_endpoint_config(
        self,
        sdk: str,
        base_url: str,
        api_key_encrypted: str,
        slots: Dict[str, Optional[str]],
        updated_by: str,
    ) -> bool:
        """Persist endpoint, model slots, and active SDK in one transaction."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO llm_endpoints (sdk, base_url, api_key_encrypted, is_active, updated_by, updated_at)
                    VALUES ($1, $2, $3, FALSE, $4, CURRENT_TIMESTAMP)
                    ON CONFLICT (sdk) DO UPDATE SET
                        base_url = EXCLUDED.base_url,
                        api_key_encrypted = EXCLUDED.api_key_encrypted,
                        updated_by = EXCLUDED.updated_by,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    sdk,
                    base_url,
                    api_key_encrypted,
                    updated_by,
                )
                for slot, model_id in slots.items():
                    await conn.execute(
                        """
                        INSERT INTO llm_model_slots (sdk, slot, model_id, updated_by, updated_at)
                        VALUES ($1, $2, $3, $4, CURRENT_TIMESTAMP)
                        ON CONFLICT (sdk, slot) DO UPDATE SET
                            model_id = EXCLUDED.model_id,
                            updated_by = EXCLUDED.updated_by,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        sdk,
                        slot,
                        model_id,
                        updated_by,
                    )
                await conn.execute("UPDATE llm_endpoints SET is_active = FALSE WHERE is_active = TRUE")
                result = await conn.execute(
                    """
                    UPDATE llm_endpoints
                    SET is_active = TRUE, updated_by = $2, updated_at = CURRENT_TIMESTAMP
                    WHERE sdk = $1
                    """,
                    sdk,
                    updated_by,
                )
                if not result.endswith(" 1"):
                    raise RuntimeError(f"Failed to activate endpoint: {sdk}")
        return True

    async def get_llm_model_slots(self, sdk: str) -> Dict[str, Optional[str]]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT slot, model_id FROM llm_model_slots WHERE sdk = $1", sdk)
        return {row["slot"]: row["model_id"] for row in rows}

    async def upsert_llm_model_slots(self, sdk: str, slots: Dict[str, Optional[str]], updated_by: str) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                for slot, model_id in slots.items():
                    await conn.execute(
                        """
                        INSERT INTO llm_model_slots (sdk, slot, model_id, updated_by, updated_at)
                        VALUES ($1, $2, $3, $4, CURRENT_TIMESTAMP)
                        ON CONFLICT (sdk, slot) DO UPDATE SET
                            model_id = EXCLUDED.model_id,
                            updated_by = EXCLUDED.updated_by,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        sdk,
                        slot,
                        model_id,
                        updated_by,
                    )

    async def update_endpoint_check_status(self, sdk: str, ok: bool, error: Optional[str]) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE llm_endpoints
                SET last_check_ok = $2, last_check_error = $3, last_checked_at = CURRENT_TIMESTAMP
                WHERE sdk = $1
                """,
                sdk,
                ok,
                (error or "")[:500] or None,
            )
