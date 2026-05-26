import os
import re
import json
import asyncio
import unicodedata
from datetime import datetime
from typing import Any, Optional, Dict, List, Tuple

from src.core.config import logger, Config
from src.core.prompt_loader import (
    get_file_index_reasoning_prompt,
    get_file_index_validation_prompt,
)
from src.services.file_parser import FileParserService
from src.database.repository import DatabaseRepository


__all__ = ["build_index_context", "FileIndexService", "should_use_last_index"]


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return None


def normalize_intent_text(text: str) -> str:
    lowered = (text or "").lower()
    no_diacritics = "".join(
        ch for ch in unicodedata.normalize("NFD", lowered)
        if unicodedata.category(ch) != "Mn"
    )
    normalized = re.sub(r"[^a-z0-9\s]", " ", no_diacritics)
    return re.sub(r"\s+", " ", normalized).strip()


def should_use_last_index(content: str) -> bool:
    normalized = normalize_intent_text(content)
    if not normalized:
        return False
    triggers = {
        "file", "document", "doc", "pdf", "csv",
        "tai lieu", "tai l", "tai-lieu",
        "trong file", "trong tai lieu",
    }
    return any(trigger in normalized for trigger in triggers)


async def build_index_context(
    document_id: str,
    query: str,
    *,
    db_repo: DatabaseRepository,
    file_parser: FileParserService,
    chunk_limit: int = 3,
    chunk_preview_chars: int = 3800,
) -> str:
    selected = await db_repo.search_similar_chunks(query, limit=chunk_limit)
    selected = [c for c in selected if c.get("document_id") == document_id] if document_id else selected

    if not selected:
        try:
            await db_repo.init_db()
            async with db_repo.pool.acquire() as conn:  # type: ignore[union-attr]
                rows = await conn.fetch(
                    "SELECT chunk_id, document_id, content, chunk_summary, keywords, metadata FROM rag_chunks WHERE document_id = $1 LIMIT $2",
                    document_id,
                    chunk_limit,
                )
                selected = [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error fetching fallback chunks for doc {document_id}: {e}")

    chunk_blocks = []
    for entry in selected:
        chunk_id = entry.get("chunk_id")
        content = entry.get("content", "")
        if not content and entry.get("metadata"):
            try:
                meta = json.loads(entry.get("metadata", "{}"))
                chunk_path = meta.get("chunk_path")
                if chunk_path:
                    content = file_parser.read_chunk_text(chunk_path, max_chars=chunk_preview_chars)
            except Exception:
                pass

        if content:
            if len(content) > chunk_preview_chars:
                content = content[:chunk_preview_chars] + "..."
            chunk_blocks.append(f"[CHUNK {chunk_id}]\n{content}")

    overview_lines = []
    for idx, entry in enumerate(selected[:12], start=1):
        summary = str(entry.get("chunk_summary") or "")
        overview_lines.append(f"{idx}. Chunk {entry.get('chunk_id')} - {summary}")

    overview_text = "\n".join(overview_lines) if overview_lines else "(no index entries)"
    chunks_text = "\n\n".join(chunk_blocks) if chunk_blocks else "(no relevant chunks selected)"

    return (
        f"\n[FILE INDEX]\n"
        f"document_id={document_id} chunks_found={len(selected)}\n"
        f"[INDEX OVERVIEW]\n{overview_text}\n"
        f"[SELECTED CHUNKS]\n{chunks_text}\n"
    )


class FileIndexService:
    INDEX_MAX_OUTPUT_TOKENS = 65000
    INDEX_VALIDATION_MAX_OUTPUT_TOKENS = 1200
    INDEX_QUERY_CHUNK_LIMIT = 3
    INDEX_CHUNK_PREVIEW_CHARS = 3800

    def __init__(
        self,
        *,
        config: Config,
        db_repo: DatabaseRepository,
        file_parser: FileParserService,
        api_generate_fn,
        api_get_key_fn,
        api_commit_key_fn,
        api_throttle_fn,
        api_acquire_quota_fn,
        api_log_exception_fn,
        reasoning_model_alias: str,
        final_model_alias: str,
    ):
        self.config = config
        self.db_repo = db_repo
        self.file_parser = file_parser
        self.logger = logger
        self.latest_index_by_user: Dict[str, Dict[str, str]] = {}

        self._generate = api_generate_fn
        self._get_best_api_key = api_get_key_fn
        self._commit_selected_key = api_commit_key_fn
        self._throttle = api_throttle_fn
        self._acquire_quota = api_acquire_quota_fn
        self._log_exception = api_log_exception_fn
        self._reasoning_alias = reasoning_model_alias
        self._final_alias = final_model_alias

    def set_latest_index(self, user_id: str, document_id: str, filename: str) -> None:
        self.latest_index_by_user[user_id] = {
            "document_id": document_id,
            "filename": filename,
            "updated_at": datetime.now().isoformat(),
        }

    def get_latest_index_for_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        return self.latest_index_by_user.get(user_id)

    async def index_chunk_with_reasoning(
        self,
        *,
        file_name: str,
        chunk_id: str,
        chunk_source: Dict[str, Any],
        chunk_text: str,
        security_report: str,
        user_id: str,
    ) -> Dict[str, Any]:
        current_time_str = datetime.now().strftime("%A, %d/%m/%Y %H:%M")
        time_context = f"Current time: {current_time_str}\n"
        system_instruction = time_context + get_file_index_reasoning_prompt()

        user_payload = (
            f"FILE_NAME: {file_name}\n"
            f"CHUNK_ID: {chunk_id}\n"
            f"CHUNK_SOURCE: {json.dumps(chunk_source, ensure_ascii=False)}\n"
            f"SECURITY_NOTES: {security_report}\n"
            f"CHUNK_TEXT:\n{chunk_text}"
        )

        messages = [{"role": "user", "parts": [{"text": user_payload}]}]
        generation_config = {
            "temperature": 0.2,
            "top_p": 0.9,
            "top_k": 40,
            "max_output_tokens": self.INDEX_MAX_OUTPUT_TOKENS,
        }

        quota_ok = await self._acquire_quota(
            messages,
            generation_config["max_output_tokens"],
            self._reasoning_alias,
            extra_text=system_instruction,
        )
        if not quota_ok:
            return {}

        api_key, model_name, used_model_alias, key_reservation = await self._get_best_api_key(self._reasoning_alias)
        if not api_key or not model_name:
            return {}

        await self._throttle(api_key)
        try:
            response = await self._generate(
                api_key=api_key,
                model_name=model_name,
                system_instruction=system_instruction,
                generation_config=generation_config,
                messages=messages,
            )
            self._commit_selected_key(key_reservation)
            candidate = response.candidates[0] if response.candidates else None
            if not (candidate and candidate.content and candidate.content.parts):
                return {}
            part = candidate.content.parts[0]
            text = (part.text or "").strip() if hasattr(part, "text") else ""
            payload = extract_json_object(text) or {}
            if payload:
                return payload
        except Exception as e:
            self._log_exception(
                stage="file_index_chunk",
                error=e,
                user_id=user_id,
                model_alias=used_model_alias,
                model_name=model_name,
                api_key=api_key,
                attempt=1,
                max_attempts=1,
            )
        return {}

    async def build_file_index(
        self,
        *,
        file_meta: Dict[str, Any],
        document_id: str,
        user_id: str,
    ) -> Dict[str, Any]:
        filename = file_meta.get("filename") or "file"
        chunk_manifest = file_meta.get("chunk_manifest", [])
        security_report = file_meta.get("security_report", "")

        await self.db_repo.init_db()

        index_entries: List[Dict[str, Any]] = []
        for chunk in chunk_manifest:
            manifest_chunk_id = chunk.get("chunk_id")
            chunk_path = chunk.get("chunk_path")
            chunk_source = chunk.get("source", {})
            if not manifest_chunk_id or not chunk_path:
                continue

            chunk_id = f"{document_id}:{manifest_chunk_id}"
            chunk_text = self.file_parser.read_chunk_text(
                chunk_path,
                max_chars=self.INDEX_CHUNK_PREVIEW_CHARS * 2,
            )
            if not chunk_text:
                continue

            entry = await self.index_chunk_with_reasoning(
                file_name=filename,
                chunk_id=chunk_id,
                chunk_source=chunk_source,
                chunk_text=chunk_text,
                security_report=security_report,
                user_id=user_id,
            )

            if not entry:
                entry = {
                    "title": f"Chunk {chunk_id}",
                    "summary": chunk_text[:240].replace("\n", " ").strip(),
                    "keywords": [],
                    "risk_flags": [],
                    "notes": "fallback summary",
                }

            entry["chunk_id"] = chunk_id
            entry["chunk_path"] = chunk_path
            entry["source"] = chunk_source
            index_entries.append(entry)

            try:
                async with self.db_repo.pool.acquire() as conn:  # type: ignore[union-attr]
                    summary = entry.get("summary", "")
                    keywords = entry.get("keywords", [])
                    if not isinstance(keywords, list):
                        keywords = []

                    metadata = json.dumps(
                        {
                            "chunk_path": chunk_path,
                            "source": chunk_source,
                            "title": entry.get("title", ""),
                            "risk_flags": entry.get("risk_flags", []),
                            "notes": entry.get("notes", ""),
                        },
                        ensure_ascii=False,
                    )

                    await conn.execute(
                        """
                        INSERT INTO rag_chunks (chunk_id, document_id, content, chunk_summary, keywords, metadata)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        ON CONFLICT (chunk_id) DO UPDATE
                        SET content = EXCLUDED.content,
                            chunk_summary = EXCLUDED.chunk_summary,
                            keywords = EXCLUDED.keywords,
                            metadata = EXCLUDED.metadata
                        """,
                        chunk_id,
                        document_id,
                        chunk_text,
                        summary,
                        keywords,
                        metadata,
                    )
            except Exception as e:
                self.logger.error(f"Failed to insert chunk {chunk_id} into db: {e}")

        return {
            "document_id": document_id,
            "file_name": filename,
            "file_extension": file_meta.get("file_extension"),
            "user_id": user_id,
            "created_at": datetime.now().isoformat(),
            "chunk_count": len(index_entries),
            "security_report": security_report,
            "truncated": bool(file_meta.get("truncated")),
            "chunks": index_entries,
        }

    async def validate_file_index(self, index_data: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        current_time_str = datetime.now().strftime("%A, %d/%m/%Y %H:%M")
        time_context = f"SYSTEM ALERT: Current Date/Time is {current_time_str}.\n\n"
        system_instruction = time_context + get_file_index_validation_prompt()

        overview_lines = []
        for idx, entry in enumerate(index_data.get("chunks", [])[:30], start=1):
            title = str(entry.get("title") or "")
            summary = str(entry.get("summary") or "")
            overview_lines.append(f"{idx}. {title} - {summary}")
        overview_text = "\n".join(overview_lines) if overview_lines else "(empty)"

        user_payload = (
            f"FILE_NAME: {index_data.get('file_name')}\n"
            f"SECURITY_REPORT:\n{index_data.get('security_report', '')}\n"
            f"INDEX_OVERVIEW:\n{overview_text}\n"
        )

        messages = [{"role": "user", "parts": [{"text": user_payload}]}]
        generation_config = {
            "temperature": 0.2,
            "top_p": 0.9,
            "top_k": 40,
            "max_output_tokens": self.INDEX_VALIDATION_MAX_OUTPUT_TOKENS,
        }

        quota_ok = await self._acquire_quota(
            messages,
            generation_config["max_output_tokens"],
            self._final_alias,
            extra_text=system_instruction,
        )
        if not quota_ok:
            return {"status": "warn", "reason": "quota blocked", "risk_flags": []}

        api_key, model_name, used_model_alias, key_reservation = await self._get_best_api_key(self._final_alias)
        if not api_key or not model_name:
            return {"status": "warn", "reason": "no api key", "risk_flags": []}

        await self._throttle(api_key)
        try:
            response = await self._generate(
                api_key=api_key,
                model_name=model_name,
                system_instruction=system_instruction,
                generation_config=generation_config,
                messages=messages,
            )
            self._commit_selected_key(key_reservation)
            candidate = response.candidates[0] if response.candidates else None
            if not (candidate and candidate.content and candidate.content.parts):
                return {"status": "warn", "reason": "empty validation", "risk_flags": []}
            part = candidate.content.parts[0]
            text = (part.text or "").strip() if hasattr(part, "text") else ""
            payload = extract_json_object(text)
            if payload:
                return payload
        except Exception as e:
            self._log_exception(
                stage="file_index_validate",
                error=e,
                user_id=user_id,
                model_alias=used_model_alias,
                model_name=model_name,
                api_key=api_key,
                attempt=1,
                max_attempts=1,
            )
        return {"status": "warn", "reason": "validation failed", "risk_flags": []}
