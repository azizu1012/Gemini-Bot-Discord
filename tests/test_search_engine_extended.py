"""Offline tests for SearchEngine — cache/delegation/run paths."""
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, ".")

from src.tools.search.engine import SearchEngine


class NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


def make_engine():
    e = SearchEngine(logger_override=NullLogger())
    return e


# ---------------- delegation methods ----------------
def test_normalize_search_cache_key_delegates():
    e = make_engine()
    e.cache.normalize_cache_key = MagicMock(return_value="key")
    assert e._normalize_search_cache_key("q") == "key"


def test_is_time_sensitive_delegates():
    e = make_engine()
    e.planner.is_time_sensitive_query = MagicMock(return_value=True)
    assert e._is_time_sensitive_query("q") is True


def test_split_multi_intents_delegates():
    e = make_engine()
    e.planner.split_multi_intents = MagicMock(return_value=["a", "b"])
    assert e._split_multi_intents("q") == ["a", "b"]


def test_required_quality_sources_delegates():
    e = make_engine()
    e.planner.required_quality_sources = MagicMock(return_value=2)
    assert e._required_quality_sources("q") == 2


# ---------------- run_search_apis ----------------
@pytest.mark.asyncio
async def test_run_search_apis_empty_query():
    e = make_engine()
    assert await e.run_search_apis("") == ""
    assert await e.run_search_apis("   ") == ""


@pytest.mark.asyncio
async def test_run_search_apis_cached(monkeypatch):
    e = make_engine()
    # cache hit
    e.get_web_search_cache = MagicMock(return_value="cached answer")
    result = await e.run_search_apis("hello")
    assert result == "cached answer"


@pytest.mark.asyncio
async def test_run_search_apis_force_fallback(monkeypatch):
    e = make_engine()
    e._execute_search_pipeline = AsyncMock(return_value="fresh answer")
    result = await e.run_search_apis("[FORCE FALLBACK] hello")
    assert result == "fresh answer"
    e._execute_search_pipeline.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_search_apis_fresh_and_cache(monkeypatch):
    e = make_engine()
    e.get_web_search_cache = MagicMock(return_value=None)
    e.set_web_search_cache = MagicMock()
    e._execute_search_pipeline = AsyncMock(return_value="output")
    result = await e.run_search_apis("normal query")
    assert result == "output"
    e.set_web_search_cache.assert_called_once()


@pytest.mark.asyncio
async def test_run_search_apis_empty_result_sets_cooldown(monkeypatch):
    e = make_engine()
    e.get_web_search_cache = MagicMock(return_value=None)
    e._execute_search_pipeline = AsyncMock(return_value="")
    result = await e.run_search_apis("plain query")
    assert result == ""
    assert len(e.failed_search_cooldowns) == 1


@pytest.mark.asyncio
async def test_run_search_apis_cooldown_hit(monkeypatch):
    import time as _time

    e = make_engine()
    e.get_web_search_cache = MagicMock(return_value=None)
    e._execute_search_pipeline = AsyncMock(return_value="x")
    # precondition: set cooldown for the normalized key
    e.failed_search_cooldowns["general|q"] = _time.time() + 100
    # need normalized key to match — force cache.normalize to identity
    e._normalize_search_cache_key = MagicMock(return_value="general|q")
    result = await e.run_search_apis("q")
    assert "tạm quá tải" in result
    e._execute_search_pipeline.assert_not_awaited()


# ---------------- _fetch_page_evidence ----------------
@pytest.mark.asyncio
async def test_fetch_page_evidence_cached():
    e = make_engine()
    e.cache.get_deep_read = MagicMock(return_value="cached")
    assert await e._fetch_page_evidence("http://x") == "cached"


@pytest.mark.asyncio
async def test_fetch_page_evidence_fetch_and_cache(monkeypatch):
    e = make_engine()
    e.cache.get_deep_read = MagicMock(return_value=None)
    e.cache.set_deep_read = MagicMock()
    e.fetcher.fetch_page_evidence = AsyncMock(return_value="fresh text")
    assert await e._fetch_page_evidence("http://x") == "fresh text"
    e.cache.set_deep_read.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_page_evidence_empty_sets_empty_cache(monkeypatch):
    e = make_engine()
    e.cache.get_deep_read = MagicMock(return_value=None)
    e.cache.set_deep_read = MagicMock()
    e.fetcher.fetch_page_evidence = AsyncMock(return_value="")
    assert await e._fetch_page_evidence("http://x") == ""
    e.cache.set_deep_read.assert_called_once()
