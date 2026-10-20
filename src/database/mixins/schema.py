"""Database schema initialization, DDL definitions, and table migrations."""

from __future__ import annotations


class SchemaMixin:
    """Mixin providing database schema initialization, migration, and vacuuming."""

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
                CREATE TABLE IF NOT EXISTS llm_endpoints (
                    sdk TEXT PRIMARY KEY CHECK (sdk IN ('genai','openai')),
                    base_url TEXT NOT NULL,
                    api_key_encrypted TEXT NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT FALSE,
                    updated_by TEXT,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_check_ok BOOLEAN,
                    last_check_error TEXT,
                    last_checked_at TIMESTAMPTZ
                )
                """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS llm_model_slots (
                    sdk TEXT NOT NULL,
                    slot TEXT NOT NULL CHECK (slot IN ('reasoning','final','fallback','vision')),
                    model_id TEXT,
                    updated_by TEXT,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (sdk, slot)
                )
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

            await conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_user_time ON messages (user_id, timestamp DESC) INCLUDE (role)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_notes_user_scope_active ON user_notes (user_id, scope, is_active)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_notes_fact_hash ON user_notes (fact_hash)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_notes_metadata_gin ON user_notes USING gin (metadata)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_rag_chunks_keywords ON rag_chunks USING GIN (keywords)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_rag_chunks_summary_trgm ON rag_chunks USING GIN (chunk_summary gin_trgm_ops)")

            # Rename bảng của cơ chế key-rotation cũ (giữ dữ liệu để rollback).
            # Idempotent: IF EXISTS bỏ qua khi bảng đã được rename từ lần trước.
            for _old_name, _deprecated_name in (
                ("api_key_pool", "_deprecated_api_key_pool"),
                ("api_key_rate_limits", "_deprecated_api_key_rate_limits"),
                ("custom_api_models", "_deprecated_custom_api_models"),
                ("bot_model_config", "_deprecated_bot_model_config"),
                ("custom_api_provider_config", "_deprecated_custom_api_provider_config"),
            ):
                await conn.execute(f"ALTER TABLE IF EXISTS {_old_name} RENAME TO {_deprecated_name}")

    async def backup_db(self) -> None:
        return None

    async def cleanup_db(self) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute("VACUUM")
