"""User notes, facts memory, and RAG chunks storage."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


class NotesMixin:
    """Mixin providing long-term memory operations (personal notes, global facts, RAG chunks)."""

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
