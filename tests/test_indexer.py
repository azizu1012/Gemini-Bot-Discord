"""Offline tests for indexer (FileIndexService + pure helpers)."""
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, ".")

from src.services.indexing.indexer import (
    FileIndexService,
    build_index_context,
    extract_json_object,
    normalize_intent_text,
    should_use_last_index,
)


class NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


# ---------------- pure helpers ----------------
def test_extract_json_object_plain():
    assert extract_json_object('{"a": 1}') == {"a": 1}


def test_extract_json_object_embedded():
    assert extract_json_object('prefix {"a": 1} suffix') == {"a": 1}


def test_extract_json_object_invalid():
    assert extract_json_object("not json") is None
    assert extract_json_object("") is None
    assert extract_json_object(None) is None


def test_normalize_intent_text():
    assert normalize_intent_text("  Tài Liệu  ") == "tai lieu"
    assert normalize_intent_text("") == ""


def test_should_use_last_index():
    assert should_use_last_index("xem tài liệu đính kèm") is True
    assert should_use_last_index("file đã upload") is True
    assert should_use_last_index("thời tiết hôm nay") is False
    assert should_use_last_index("") is False


# ---------------- build_index_context ----------------
@pytest.mark.asyncio
async def test_build_index_context_uses_similar_chunks():
    db = MagicMock()
    db.search_similar_chunks = AsyncMock(
        return_value=[{
            "chunk_id": "c1",
            "document_id": "d1",
            "content": "hello world",
            "chunk_summary": "summary1",
            "keywords": [],
            "metadata": "{}",
        }]
    )
    parser = MagicMock()
    result = await build_index_context("d1", "q", db_repo=db, file_parser=parser)
    assert "hello world" in result
    assert "summary1" in result


@pytest.mark.asyncio
async def test_build_index_context_fallback_query():
    db = MagicMock()
    db.search_similar_chunks = AsyncMock(return_value=[])
    db.init_db = AsyncMock()
    conn = MagicMock()
    conn.fetch = AsyncMock(
        return_value=[{"chunk_id": "c1", "document_id": "d1", "content": "fallback", "chunk_summary": "s", "keywords": [], "metadata": "{}"}]
    )

    @asynccontextmanager
    async def acquire():
        yield conn

    db.pool = MagicMock()
    db.pool.acquire = acquire
    parser = MagicMock()
    result = await build_index_context("d1", "q", db_repo=db, file_parser=parser)
    assert "fallback" in result


# ---------------- FileIndexService ----------------
def make_service():
    svc = FileIndexService(
        config=MagicMock(),
        db_repo=MagicMock(),
        file_parser=MagicMock(),
        gateway=MagicMock(),
        reasoning_role="r",
        final_role="f",
    )
    svc.logger = NullLogger()
    return svc


def test_set_and_get_latest_index():
    svc = make_service()
    svc.set_latest_index("u1", "d1", "a.pdf")
    info = svc.get_latest_index_for_user("u1")
    assert info["document_id"] == "d1"
    assert info["filename"] == "a.pdf"
    assert svc.get_latest_index_for_user("missing") is None


@pytest.mark.asyncio
async def test_index_chunk_with_reasoning_success():
    svc = make_service()
    response = SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=[SimpleNamespace(text='{"title":"T","summary":"S","keywords":["k"],"risk_flags":[]}')]))]
    )
    svc.gateway.generate = AsyncMock(return_value=response)
    result = await svc.index_chunk_with_reasoning(
        file_name="a.pdf", chunk_id="c1", chunk_source={"path": "x"}, chunk_text="text", security_report="ok", user_id="u1"
    )
    assert result["title"] == "T"
    assert result["summary"] == "S"


@pytest.mark.asyncio
async def test_index_chunk_with_reasoning_empty_candidate():
    svc = make_service()
    svc.gateway.generate = AsyncMock(return_value=SimpleNamespace(candidates=[]))
    result = await svc.index_chunk_with_reasoning(
        file_name="a", chunk_id="c", chunk_source={}, chunk_text="t", security_report="", user_id="u"
    )
    assert result == {}


@pytest.mark.asyncio
async def test_index_chunk_with_reasoning_exception():
    svc = make_service()
    svc.gateway.generate = AsyncMock(side_effect=RuntimeError("llm down"))
    svc.gateway.log_exception = MagicMock()
    result = await svc.index_chunk_with_reasoning(
        file_name="a", chunk_id="c", chunk_source={}, chunk_text="t", security_report="", user_id="u"
    )
    assert result == {}
    svc.gateway.log_exception.assert_called_once()


@pytest.mark.asyncio
async def test_build_file_index_single_chunk():
    svc = make_service()
    svc.db_repo.init_db = AsyncMock()
    svc.file_parser.read_chunk_text = MagicMock(return_value="chunk content")
    svc.index_chunk_with_reasoning = AsyncMock(
        return_value={"title": "T", "summary": "S", "keywords": ["k"], "risk_flags": []}
    )

    conn = MagicMock()
    conn.execute = AsyncMock()

    @asynccontextmanager
    async def acquire():
        yield conn

    svc.db_repo.pool = MagicMock()
    svc.db_repo.pool.acquire = acquire

    result = await svc.build_file_index(
        file_meta={
            "filename": "a.pdf",
            "file_extension": ".pdf",
            "chunk_manifest": [{"chunk_id": "c1", "chunk_path": "/p/c1", "source": {"path": "/p"}}],
            "security_report": "ok",
        },
        document_id="d1",
        user_id="u1",
    )
    assert result["chunk_count"] == 1
    conn.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_build_file_index_skips_missing_chunk_path():
    svc = make_service()
    svc.db_repo.init_db = AsyncMock()
    result = await svc.build_file_index(
        file_meta={
            "filename": "a",
            "chunk_manifest": [{"chunk_id": "c1"}],  # no chunk_path
            "security_report": "",
        },
        document_id="d1",
        user_id="u1",
    )
    assert result["chunk_count"] == 0
