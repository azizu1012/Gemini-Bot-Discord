import asyncio
import json
import os
import uuid
from typing import Optional, List, Dict, Any, Tuple

import asyncpg

from src.core.config import logger


class DatabaseRepository:
    """Direct asyncpg repository for all database operations."""

    def __init__(self, db_url: str = os.getenv("DATABASE_URL", "postgresql://localhost:5432/azuris")):
        self.db_url = db_url
        self.logger = logger
        self.pool: Optional[asyncpg.Pool] = None
        self._init_lock = asyncio.Lock()
        self._schema_ready = False

    async def init_db(self) -> None:
        if self.pool is not None and self._schema_ready:
            return

        async with self._init_lock:
            if self.pool is None:
                async def init_connection(conn):
                    # Register JSON/JSONB codecs for automatic python dict <-> postgres jsonb translation
                    await conn.set_type_codec(
                        "json",
                        encoder=json.dumps,
                        decoder=json.loads,
                        schema="pg_catalog"
                    )
                    await conn.set_type_codec(
                        "jsonb",
                        encoder=json.dumps,
                        decoder=json.loads,
                        schema="pg_catalog"
                    )

                self.pool = await asyncpg.create_pool(
                    dsn=self.db_url,
                    min_size=2,
                    max_size=10,
                    max_inactive_connection_lifetime=300.0,
                    command_timeout=60.0,
                    ssl=False,
                    init=init_connection,
                )
            if not self._schema_ready:
                await self._initialize_schema()
                self._schema_ready = True

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None
            self._schema_ready = False

    async def _ensure_pool(self) -> asyncpg.Pool:
        await self.init_db()
        if self.pool is None:
            raise RuntimeError("Database pool is not initialized")
        return self.pool

    @staticmethod
    def _collect_env_keys() -> List[Tuple[str, str]]:
        keys: List[Tuple[str, str]] = []
        seen = set()
        for env_name, env_value in sorted(os.environ.items()):
            upper_name = env_name.upper()
            key = (env_value or "").strip()
            if not key or key in seen:
                continue
            if upper_name.startswith("GEMINI_API_KEY_") and "TOMTAT" not in upper_name:
                seen.add(key)
                keys.append((key, "gemini"))
            elif upper_name == "OPENAI_API_KEY" or key.startswith("sk-"):
                seen.add(key)
                keys.append((key, "openai"))
        return keys

    async def _initialize_schema(self) -> None:
        if self.pool is None:
            raise RuntimeError("Database pool is not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_processing_states (
                    user_id TEXT PRIMARY KEY,
                    is_busy BOOLEAN NOT NULL DEFAULT FALSE,
                    current_stage TEXT NOT NULL DEFAULT '',
                    last_updated TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_notes (
                    note_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ,
                    scope TEXT NOT NULL DEFAULT 'user',
                    importance INTEGER NOT NULL DEFAULT 0,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    note_type TEXT NOT NULL DEFAULT 'personal_preference',
                    fact_hash TEXT NOT NULL DEFAULT ''
                )
                """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS premium_users (
                    user_id TEXT PRIMARY KEY,
                    added_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS moderator_users (
                    user_id TEXT PRIMARY KEY,
                    added_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_users (
                    user_id TEXT PRIMARY KEY,
                    added_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_logs (
                    id BIGSERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    model_name TEXT NOT NULL DEFAULT '',
                    tokens_used INTEGER NOT NULL DEFAULT 0,
                    metadata TEXT NOT NULL DEFAULT '',
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS web_history (
                    id BIGSERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    query TEXT NOT NULL,
                    results TEXT NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS generated_images (
                    id BIGSERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    image_url TEXT NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rag_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    chunk_summary TEXT NOT NULL,
                    keywords TEXT[] NOT NULL DEFAULT '{}',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS api_key_pool (
                    key_id BIGSERIAL PRIMARY KEY,
                    api_key TEXT NOT NULL UNIQUE,
                    provider TEXT NOT NULL DEFAULT 'gemini',
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    cooldown_until TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS api_key_rate_limits (
                    key_id BIGINT PRIMARY KEY REFERENCES api_key_pool(key_id) ON DELETE CASCADE,
                    requests_used INTEGER NOT NULL DEFAULT 0,
                    last_reset TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS custom_api_models (
                    provider TEXT NOT NULL DEFAULT 'openai',
                    model_id TEXT NOT NULL,
                    display_name TEXT NOT NULL DEFAULT '',
                    is_alive BOOLEAN NOT NULL DEFAULT TRUE,
                    last_seen_at TIMESTAMPTZ,
                    last_checked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_error TEXT NOT NULL DEFAULT '',
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    PRIMARY KEY (provider, model_id)
                )
                """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_model_config (
                    config_key TEXT PRIMARY KEY DEFAULT 'global',
                    reasoning_model_id TEXT,
                    final_model_id TEXT,
                    image_generator_model_id TEXT,
                    updated_by TEXT NOT NULL DEFAULT '',
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS custom_api_provider_config (
                    provider TEXT PRIMARY KEY DEFAULT 'openai',
                    endpoint_base_url TEXT NOT NULL DEFAULT '',
                    normalized_base_url TEXT NOT NULL DEFAULT '',
                    endpoint_preset TEXT NOT NULL DEFAULT 'manual',
                    active_key_id BIGINT REFERENCES api_key_pool(key_id) ON DELETE SET NULL,
                    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    last_scan_ok BOOLEAN NOT NULL DEFAULT FALSE,
                    last_scan_error TEXT NOT NULL DEFAULT '',
                    updated_by TEXT NOT NULL DEFAULT '',
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # Evolve schema to add columns if missing
            await conn.execute(
                """
                ALTER TABLE api_key_pool ADD COLUMN IF NOT EXISTS cooldown_until TIMESTAMPTZ
                """
            )
            await conn.execute(
                """
                ALTER TABLE custom_api_provider_config
                ADD COLUMN IF NOT EXISTS endpoint_preset TEXT NOT NULL DEFAULT 'manual'
                """
            )

            # Migrate user_notes.metadata column to JSONB if it's currently TEXT
            await conn.execute(
                """
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_name = 'user_notes'
                          AND column_name = 'metadata'
                          AND data_type = 'text'
                    ) THEN
                        ALTER TABLE user_notes ALTER COLUMN metadata DROP DEFAULT;
                        ALTER TABLE user_notes ALTER COLUMN metadata TYPE jsonb USING metadata::jsonb;
                        ALTER TABLE user_notes ALTER COLUMN metadata SET DEFAULT '{}'::jsonb;
                    END IF;
                END $$;
                """
            )

            await conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_user_time ON messages (user_id, timestamp DESC)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_notes_user_scope_active ON user_notes (user_id, scope, is_active)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_notes_fact_hash ON user_notes (fact_hash)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_notes_metadata_gin ON user_notes USING gin (metadata)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_rag_chunks_keywords ON rag_chunks USING GIN (keywords)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_rag_chunks_summary_trgm ON rag_chunks USING GIN (chunk_summary gin_trgm_ops)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_custom_api_models_alive ON custom_api_models (provider, is_alive, model_id)")

            await self.sync_env_api_keys(conn=conn)

    @staticmethod
    def _command_count(command_tag: str) -> int:
        try:
            return int(str(command_tag).split()[-1])
        except (IndexError, TypeError, ValueError):
            return 0

    async def sync_env_api_keys(self, conn: Optional[asyncpg.Connection] = None) -> Dict[str, int]:
        env_keys = self._collect_env_keys()
        openai_keys = [key for key, provider in env_keys if provider == "openai"]

        async def run(target_conn) -> Dict[str, int]:
            provider_config = await target_conn.fetchrow(
                """
                SELECT active_key_id
                FROM custom_api_provider_config
                WHERE provider = 'openai'
                  AND active_key_id IS NOT NULL
                """
            )
            db_managed_openai = provider_config is not None
            active_key_id = provider_config["active_key_id"] if provider_config else None

            upserted = 0
            for key, provider in env_keys:
                if provider == "openai" and db_managed_openai:
                    await target_conn.execute(
                        """
                        INSERT INTO api_key_pool (api_key, provider, is_active)
                        VALUES ($1, $2, FALSE)
                        ON CONFLICT (api_key) DO UPDATE
                        SET provider = EXCLUDED.provider
                        """,
                        key,
                        provider,
                    )
                else:
                    await target_conn.execute(
                        """
                        INSERT INTO api_key_pool (api_key, provider, is_active)
                        VALUES ($1, $2, TRUE)
                        ON CONFLICT (api_key) DO UPDATE
                        SET provider = EXCLUDED.provider,
                            is_active = TRUE,
                            cooldown_until = NULL
                        """,
                        key,
                        provider,
                    )
                upserted += 1

            await target_conn.execute(
                """
                INSERT INTO api_key_rate_limits (key_id, requests_used, last_reset)
                SELECT p.key_id, 0, CURRENT_TIMESTAMP
                FROM api_key_pool p
                ON CONFLICT (key_id) DO NOTHING
                """
            )

            if db_managed_openai and active_key_id is not None:
                await target_conn.execute(
                    """
                    UPDATE api_key_pool
                    SET is_active = TRUE,
                        cooldown_until = NULL
                    WHERE key_id = $1
                    """,
                    active_key_id,
                )

            deactivated = 0
            if openai_keys and not db_managed_openai:
                result = await target_conn.execute(
                    """
                    UPDATE api_key_pool
                    SET is_active = FALSE,
                        cooldown_until = NULL
                    WHERE provider = 'openai'
                      AND api_key <> ALL($1::text[])
                      AND is_active = TRUE
                    """,
                    openai_keys,
                )
                deactivated = self._command_count(result)
            return {"upserted": upserted, "openai_deactivated": deactivated}

        if conn is not None:
            return await run(conn)

        pool = await self._ensure_pool()
        async with pool.acquire() as owned_conn:
            return await run(owned_conn)

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

    async def backup_db(self) -> None:
        return None

    async def cleanup_db(self) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute("VACUUM")

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

    async def get_all_keys_from_pool(self) -> List[Dict[str, Any]]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT key_id, api_key, provider, is_active, cooldown_until FROM api_key_pool"
            )
        return [dict(r) for r in rows]

    async def upsert_custom_api_models(
        self,
        provider: str,
        models: List[Any],
        checked_at: Optional[Any] = None,
        error: str = "",
    ) -> Dict[str, int]:
        from datetime import datetime, timezone

        checked_at = checked_at or datetime.now(timezone.utc)
        normalized: List[Dict[str, Any]] = []
        seen = set()
        for item in models:
            if isinstance(item, dict):
                model_id = str(item.get("id") or item.get("model") or item.get("name") or "").strip()
                display_name = str(item.get("display_name") or item.get("name") or model_id).strip()
                metadata = dict(item)
            else:
                model_id = str(item or "").strip()
                display_name = model_id
                metadata = {}
            if not model_id or model_id in seen:
                continue
            seen.add(model_id)
            normalized.append({
                "model_id": model_id,
                "display_name": display_name or model_id,
                "metadata": metadata,
            })

        if not normalized:
            return {"upserted": 0}

        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                for model in normalized:
                    await conn.execute(
                        """
                        INSERT INTO custom_api_models (
                            provider, model_id, display_name, is_alive,
                            last_seen_at, last_checked_at, last_error, metadata
                        )
                        VALUES ($1, $2, $3, TRUE, $4, $4, $5, $6)
                        ON CONFLICT (provider, model_id) DO UPDATE
                        SET display_name = EXCLUDED.display_name,
                            is_alive = TRUE,
                            last_seen_at = EXCLUDED.last_seen_at,
                            last_checked_at = EXCLUDED.last_checked_at,
                            last_error = '',
                            metadata = EXCLUDED.metadata
                        """,
                        provider,
                        model["model_id"],
                        model["display_name"],
                        checked_at,
                        error,
                        model["metadata"],
                    )
        return {"upserted": len(normalized)}

    async def mark_missing_custom_api_models_dead(
        self,
        provider: str,
        seen_model_ids: List[str],
        checked_at: Optional[Any] = None,
        error: str = "missing_from_provider_scan",
    ) -> List[str]:
        from datetime import datetime, timezone

        checked_at = checked_at or datetime.now(timezone.utc)
        seen = [str(model_id).strip() for model_id in seen_model_ids if str(model_id).strip()]
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            if seen:
                rows = await conn.fetch(
                    """
                    UPDATE custom_api_models
                    SET is_alive = FALSE,
                        last_checked_at = $2,
                        last_error = $3
                    WHERE provider = $1
                      AND is_alive = TRUE
                      AND model_id <> ALL($4::text[])
                    RETURNING model_id
                    """,
                    provider,
                    checked_at,
                    error,
                    seen,
                )
            else:
                rows = await conn.fetch(
                    """
                    UPDATE custom_api_models
                    SET is_alive = FALSE,
                        last_checked_at = $2,
                        last_error = $3
                    WHERE provider = $1
                      AND is_alive = TRUE
                    RETURNING model_id
                    """,
                    provider,
                    checked_at,
                    error,
                )
        return [str(row["model_id"]) for row in rows]

    async def get_alive_custom_api_models(self, provider: str = "openai") -> List[Dict[str, Any]]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT provider, model_id, display_name, is_alive, last_seen_at,
                       last_checked_at, last_error, metadata
                FROM custom_api_models
                WHERE provider = $1 AND is_alive = TRUE
                ORDER BY display_name ASC, model_id ASC
                """,
                provider,
            )
        return [dict(row) for row in rows]

    async def get_custom_api_model(self, provider: str, model_id: str) -> Optional[Dict[str, Any]]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT provider, model_id, display_name, is_alive, last_seen_at,
                       last_checked_at, last_error, metadata
                FROM custom_api_models
                WHERE provider = $1 AND model_id = $2
                """,
                provider,
                model_id,
            )
        return dict(row) if row else None

    async def get_bot_model_config(self) -> Dict[str, Any]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT config_key, reasoning_model_id, final_model_id,
                       image_generator_model_id, updated_by, updated_at
                FROM bot_model_config
                WHERE config_key = 'global'
                """
            )
        if row:
            return dict(row)
        return {
            "config_key": "global",
            "reasoning_model_id": None,
            "final_model_id": None,
            "image_generator_model_id": None,
            "updated_by": "",
            "updated_at": None,
        }

    async def set_bot_model_config(
        self,
        reasoning_model_id: Optional[str],
        final_model_id: Optional[str],
        image_generator_model_id: Optional[str],
        updated_by: str,
    ) -> Dict[str, Any]:
        def clean(value: Optional[str]) -> Optional[str]:
            cleaned = str(value or "").strip()
            return cleaned or None

        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO bot_model_config (
                    config_key, reasoning_model_id, final_model_id,
                    image_generator_model_id, updated_by, updated_at
                )
                VALUES ('global', $1, $2, $3, $4, CURRENT_TIMESTAMP)
                ON CONFLICT (config_key) DO UPDATE
                SET reasoning_model_id = EXCLUDED.reasoning_model_id,
                    final_model_id = EXCLUDED.final_model_id,
                    image_generator_model_id = EXCLUDED.image_generator_model_id,
                    updated_by = EXCLUDED.updated_by,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING config_key, reasoning_model_id, final_model_id,
                          image_generator_model_id, updated_by, updated_at
                """,
                clean(reasoning_model_id),
                clean(final_model_id),
                clean(image_generator_model_id),
                str(updated_by or ""),
            )
        return dict(row) if row else await self.get_bot_model_config()

    async def get_custom_provider_config(self, provider: str = "openai") -> Optional[Dict[str, Any]]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT provider, endpoint_base_url, normalized_base_url, endpoint_preset, active_key_id,
                       is_enabled, last_scan_ok, last_scan_error, updated_by, updated_at
                FROM custom_api_provider_config
                WHERE provider = $1
                """,
                provider,
            )
        return dict(row) if row else None

    async def set_custom_provider_config(
        self,
        provider: str,
        endpoint_base_url: str,
        normalized_base_url: str,
        active_key_id: Optional[int],
        is_enabled: bool,
        last_scan_ok: bool,
        last_scan_error: str,
        updated_by: str,
        endpoint_preset: str = "manual",
    ) -> Dict[str, Any]:
        pool = await self._ensure_pool()
        clean_preset = str(endpoint_preset or "manual").strip().lower()
        if clean_preset not in {"manual", "lm_studio", "ollama"}:
            clean_preset = "manual"
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO custom_api_provider_config (
                    provider, endpoint_base_url, normalized_base_url, endpoint_preset, active_key_id,
                    is_enabled, last_scan_ok, last_scan_error, updated_by, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, CURRENT_TIMESTAMP)
                ON CONFLICT (provider) DO UPDATE
                SET endpoint_base_url = EXCLUDED.endpoint_base_url,
                    normalized_base_url = EXCLUDED.normalized_base_url,
                    endpoint_preset = EXCLUDED.endpoint_preset,
                    active_key_id = EXCLUDED.active_key_id,
                    is_enabled = EXCLUDED.is_enabled,
                    last_scan_ok = EXCLUDED.last_scan_ok,
                    last_scan_error = EXCLUDED.last_scan_error,
                    updated_by = EXCLUDED.updated_by,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING provider, endpoint_base_url, normalized_base_url, endpoint_preset, active_key_id,
                          is_enabled, last_scan_ok, last_scan_error, updated_by, updated_at
                """,
                provider,
                str(endpoint_base_url or "").strip(),
                str(normalized_base_url or "").strip(),
                clean_preset,
                active_key_id,
                bool(is_enabled),
                bool(last_scan_ok),
                str(last_scan_error or "")[:500],
                str(updated_by or ""),
            )
        return dict(row)

    async def set_custom_provider_enabled(self, provider: str, enabled: bool, updated_by: str) -> Optional[Dict[str, Any]]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE custom_api_provider_config
                SET is_enabled = $2,
                    updated_by = $3,
                    updated_at = CURRENT_TIMESTAMP
                WHERE provider = $1
                RETURNING provider, endpoint_base_url, normalized_base_url, endpoint_preset, active_key_id,
                          is_enabled, last_scan_ok, last_scan_error, updated_by, updated_at
                """,
                provider,
                bool(enabled),
                str(updated_by or ""),
            )
        return dict(row) if row else None

    async def update_custom_provider_scan_status(
        self,
        provider: str,
        last_scan_ok: bool,
        last_scan_error: str = "",
    ) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE custom_api_provider_config
                SET last_scan_ok = $2,
                    last_scan_error = $3,
                    updated_at = CURRENT_TIMESTAMP
                WHERE provider = $1
                """,
                provider,
                bool(last_scan_ok),
                str(last_scan_error or "")[:500],
            )

    async def upsert_provider_api_key(self, api_key: str, provider: str = "openai") -> Dict[str, Any]:
        key = str(api_key or "").strip()
        if not key:
            raise ValueError("API key không được để trống.")
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    INSERT INTO api_key_pool (api_key, provider, is_active, cooldown_until)
                    VALUES ($1, $2, TRUE, NULL)
                    ON CONFLICT (api_key) DO UPDATE
                    SET provider = EXCLUDED.provider,
                        is_active = TRUE,
                        cooldown_until = NULL
                    RETURNING key_id, api_key, provider, is_active, cooldown_until
                    """,
                    key,
                    provider,
                )
                await conn.execute(
                    """
                    INSERT INTO api_key_rate_limits (key_id, requests_used, last_reset)
                    VALUES ($1, 0, CURRENT_TIMESTAMP)
                    ON CONFLICT (key_id) DO NOTHING
                    """,
                    row["key_id"],
                )
        return dict(row)

    async def deactivate_other_provider_keys(self, provider: str = "openai", keep_key_id: Optional[int] = None) -> int:
        if keep_key_id is None:
            return 0
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE api_key_pool
                SET is_active = FALSE,
                    cooldown_until = NULL
                WHERE provider = $1
                  AND key_id <> $2
                  AND is_active = TRUE
                """,
                provider,
                keep_key_id,
            )
        return self._command_count(result)

    async def log_usage(self, user_id: str, action_type: str, model_name: str = "", tokens_used: int = 0, metadata: str = "") -> bool:
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

    async def get_web_history(self, user_id: str, limit: int = 5) -> list:
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

    async def get_generated_images(self, user_id: str, limit: int = 5) -> list:
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

    async def search_user_messages_db(self, search_query: str, limit: int = 30, exclude_user_id: Optional[str] = None) -> List[Dict[str, Any]]:
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

    async def add_user_note_db(
        self,
        user_id: str,
        note_id: str,
        content: str,
        metadata: Dict[str, Any],
        scope: str = "user",
        importance: int = 0,
        note_type: str = "personal_preference",
        fact_hash: str = "",
    ) -> bool:
        pool = await self._ensure_pool()

        # Đảm bảo metadata là dict/list hoặc giải mã nếu là chuỗi để tương thích codec jsonb của asyncpg
        if isinstance(metadata, str):
            try:
                metadata_val = json.loads(metadata)
            except Exception:
                metadata_val = {}
        elif isinstance(metadata, (dict, list)):
            metadata_val = metadata
        else:
            metadata_val = {}

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO user_notes
                (user_id, note_id, content, metadata, created_at, updated_at, scope, importance, is_active, note_type, fact_hash)
                VALUES ($1, $2, $3, $4, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, $5, $6, 1, $7, $8)
                """,
                user_id,
                note_id,
                content,
                metadata_val,
                scope,
                importance,
                note_type,
                fact_hash,
            )
        return True

    async def get_file_note_by_filename_db(self, user_id: str, filename: str) -> Optional[Dict[str, Any]]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT note_id, content, metadata, created_at
                FROM user_notes
                WHERE user_id = $1 AND metadata->>'filename' = $2
                LIMIT 1
                """,
                user_id,
                filename,
            )
        if row:
            item = dict(row)
            if item.get("created_at"):
                item["created_at"] = item["created_at"].isoformat()
            if isinstance(item["metadata"], str):
                try:
                    item["metadata"] = json.loads(item["metadata"])
                except Exception:
                    item["metadata"] = {}
            return item
        return None

    async def update_user_note_db(self, note_id: str, content: str, metadata: dict) -> bool:
        pool = await self._ensure_pool()
        if isinstance(metadata, str):
            try:
                metadata_val = json.loads(metadata)
            except Exception:
                metadata_val = {}
        elif isinstance(metadata, (dict, list)):
            metadata_val = metadata
        else:
            metadata_val = {}

        async with pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE user_notes SET content = $1, metadata = $2, updated_at = CURRENT_TIMESTAMP WHERE note_id = $3",
                content,
                metadata_val,
                note_id,
            )
        return result != "UPDATE 0"

    async def delete_user_note_db(self, note_id: str, user_id: str) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM user_notes WHERE note_id = $1 AND user_id = $2",
                note_id,
                user_id,
            )
        return result != "DELETE 0"

    async def get_user_notes_db(
        self,
        user_id: str,
        search_query: Optional[str] = None,
        include_global: bool = False,
        limit: int = 20,
        note_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        pool = await self._ensure_pool()
        safe_limit = max(1, min(limit, 100))

        query_args: List[Any] = []
        idx = 1
        sql = "SELECT note_id, content, metadata, created_at, updated_at, scope, importance, note_type, fact_hash FROM user_notes WHERE is_active = 1 "

        if include_global:
            sql += f"AND (user_id = ${idx} OR scope = 'global') "
        else:
            sql += f"AND user_id = ${idx} "
        query_args.append(user_id)
        idx += 1

        if note_type:
            sql += f"AND note_type = ${idx} "
            query_args.append(note_type)
            idx += 1

        if search_query:
            sql += f"AND (content ILIKE ${idx} OR metadata->>'filename' ILIKE ${idx} OR metadata->>'source' ILIKE ${idx}) "
            query_args.append(f"%{search_query}%")
            idx += 1

        sql += f"ORDER BY importance DESC, COALESCE(updated_at, created_at) DESC LIMIT ${idx}"
        query_args.append(safe_limit)

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *query_args)

        notes = []
        for row in rows:
            item = dict(row)
            if item.get("created_at"):
                item["created_at"] = item["created_at"].isoformat()
            if item.get("updated_at"):
                item["updated_at"] = item["updated_at"].isoformat()
            notes.append(item)
        return notes

    async def count_distinct_users_by_fact_hash_db(self, fact_hash: str) -> int:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(DISTINCT user_id) FROM user_notes WHERE is_active = 1 AND note_type = 'global_knowledge' AND fact_hash = $1",
                fact_hash,
            )
        return int(count or 0)

    async def promote_fact_hash_to_global_db(self, fact_hash: str) -> int:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE user_notes SET scope = 'global', updated_at = CURRENT_TIMESTAMP WHERE is_active = 1 AND note_type = 'global_knowledge' AND fact_hash = $1",
                fact_hash,
            )
        return int(result.split()[-1]) if result.startswith("UPDATE") else 0

    async def get_global_notes_db(self, limit: int = 20) -> List[Dict[str, Any]]:
        pool = await self._ensure_pool()
        safe_limit = max(1, min(limit, 100))
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT note_id, user_id, content, created_at, updated_at, scope, importance, note_type, fact_hash
                FROM user_notes
                WHERE is_active = 1 AND scope = 'global'
                ORDER BY COALESCE(updated_at, created_at) DESC
                LIMIT $1
                """,
                safe_limit,
            )
        notes = []
        for row in rows:
            item = dict(row)
            if item.get("created_at"):
                item["created_at"] = item["created_at"].isoformat()
            if item.get("updated_at"):
                item["updated_at"] = item["updated_at"].isoformat()
            notes.append(item)
        return notes

    async def demote_global_note_by_id_db(self, note_id: str) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE user_notes SET scope = 'user', updated_at = CURRENT_TIMESTAMP WHERE note_id = $1 AND scope = 'global'",
                note_id,
            )
        return result != "UPDATE 0"

    async def demote_global_fact_hash_db(self, fact_hash: str) -> int:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE user_notes SET scope = 'candidate_global', updated_at = CURRENT_TIMESTAMP WHERE is_active = 1 AND scope = 'global' AND fact_hash = $1",
                fact_hash,
            )
        return int(result.split()[-1]) if result.startswith("UPDATE") else 0

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

    async def search_similar_chunks(self, search_text: str, limit: int = 5) -> List[Dict[str, Any]]:
        pool = await self._ensure_pool()
        safe_limit = max(1, min(limit, 50))
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT chunk_id, document_id, content, chunk_summary, keywords, metadata, created_at,
                       (chunk_summary <-> $1) AS summary_distance
                FROM rag_chunks
                WHERE chunk_summary % $1 OR $2::text[] && keywords
                ORDER BY summary_distance ASC
                LIMIT $3
                """,
                search_text,
                [search_text],
                safe_limit,
            )
        result = []
        for row in rows:
            item = dict(row)
            if item.get("created_at"):
                item["created_at"] = item["created_at"].isoformat()
            result.append(item)
        return result

    @staticmethod
    def _provider_rpm_limit(provider: str) -> int:
        if provider == "openai":
            raw_limit = os.getenv("CUSTOM_API_DEFAULT_RPM", "1000000")
        else:
            raw_limit = os.getenv("GEMINI_DB_KEY_RPM", "15")
        try:
            return max(1, int(raw_limit))
        except (TypeError, ValueError):
            return 1000000 if provider == "openai" else 15

    async def get_next_available_key(
        self,
        provider: str = "gemini",
        rpm_limit: Optional[int] = None,
        key_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        effective_rpm = max(1, int(rpm_limit or self._provider_rpm_limit(provider)))
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                WITH selected_key AS (
                    SELECT p.api_key, p.key_id
                    FROM api_key_pool p
                    JOIN api_key_rate_limits r ON p.key_id = r.key_id
                    WHERE p.is_active = TRUE
                      AND p.provider = $1
                      AND ($3::bigint IS NULL OR p.key_id = $3)
                      AND (p.cooldown_until IS NULL OR p.cooldown_until < CURRENT_TIMESTAMP)
                      AND (r.last_reset < NOW() - INTERVAL '1 minute' OR r.requests_used < $2)
                    ORDER BY r.requests_used ASC, r.last_reset ASC, p.key_id ASC
                    FOR UPDATE OF r SKIP LOCKED
                    LIMIT 1
                )
                UPDATE api_key_rate_limits
                SET requests_used = CASE WHEN last_reset < NOW() - INTERVAL '1 minute' THEN 1 ELSE requests_used + 1 END,
                    last_reset = CASE WHEN last_reset < NOW() - INTERVAL '1 minute' THEN NOW() ELSE last_reset END
                FROM selected_key
                WHERE api_key_rate_limits.key_id = selected_key.key_id
                RETURNING selected_key.key_id, selected_key.api_key
                """,
                provider,
                effective_rpm,
                key_id,
            )
        return dict(row) if row else None

    async def cooldown_key_db(self, api_key: str, wait_time_seconds: float) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE api_key_pool
                SET cooldown_until = CURRENT_TIMESTAMP + $2 * INTERVAL '1 second'
                WHERE api_key = $1
                """,
                api_key,
                wait_time_seconds,
            )

    async def exhaust_key_db(self, api_key: str) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE api_key_pool
                SET is_active = FALSE,
                    cooldown_until = NULL
                WHERE api_key = $1
                """,
                api_key,
            )
