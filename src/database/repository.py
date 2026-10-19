import asyncio
import json
import os
import uuid
from typing import Optional, List, Dict, Any, Tuple

import asyncpg  # type: ignore[reportMissingImports]

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

    @staticmethod
    def _command_count(command_tag: str) -> int:
        try:
            return int(str(command_tag).split()[-1])
        except (IndexError, TypeError, ValueError):
            return 0

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

    # ── LLM endpoints & model slots (endpoint-only refactor) ─────────────

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
