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


def test_delegated_planner_methods():
    e = make_engine()
    e.planner.contains_year = MagicMock(return_value=True)
    e.planner.time_sensitive_timelimit = MagicMock(return_value="d")
    e.planner.transform_temporal_query = MagicMock(return_value=("q2", "d"))
    e.planner.determine_batch_size = MagicMock(return_value=1)
    e.planner.classify_topic = MagicMock(return_value="general")
    assert e._contains_year("2026") is True
    assert e._time_sensitive_timelimit("news") == "d"
    assert e._transform_temporal_query("news") == ("q2", "d")
    assert e._determine_batch_size(["a"]) == 1
    assert e._classify_topic("q") == "general"


def test_delegated_rerank_methods():
    e = make_engine()
    e.reranker.dedupe_records = MagicMock(return_value=[])
    e.reranker.score_record = MagicMock(return_value=1.0)
    e.reranker.is_quality_record = MagicMock(return_value=True)
    e.reranker.count_quality_sources = MagicMock(return_value=2)
    e.reranker.domain_diversify_records = MagicMock(return_value=[])
    e.reranker.lightweight_rerank = MagicMock(return_value=[])
    e.reranker.format_final_search_result = MagicMock(return_value="final")
    assert e._dedupe_records([]) == []
    assert e._score_record("g", "q", {}) == 1.0
    assert e._is_quality_record("g", "q", {}) is True
    assert e._count_quality_sources([], "g", "q") == 2
    assert e._domain_diversify_records([], 3, True) == []
    assert e._lightweight_rerank("g", "q", []) == []
    assert e._format_final_search_result("g", "q", [], 1) == "final"


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


# ---------------- _search_single_intent ----------------
@pytest.mark.asyncio
async def test_search_single_intent_happy_path(monkeypatch):
    e = make_engine()
    rec = {"title": "t", "snippet": "s" * 120, "url": "http://a", "domain": "a.com"}
    e._classify_topic = MagicMock(return_value="general")
    e._transform_temporal_query = MagicMock(return_value=("q", None))
    e._search_duckduckgo_records = AsyncMock(return_value=[rec])
    e._dedupe_records = MagicMock(side_effect=lambda x: x)
    e._required_quality_sources = MagicMock(return_value=1)
    e._is_search_result_sufficient = MagicMock(return_value=True)
    e._run_fallback_search_records = AsyncMock(return_value=[])
    e._score_record = MagicMock(return_value=2.0)
    e._lightweight_rerank = MagicMock(side_effect=lambda t, q, r: r)
    e._fetch_page_evidence = AsyncMock(return_value="evidence")
    e._format_final_search_result = MagicMock(return_value="final")
    e._count_quality_sources = MagicMock(return_value=1)
    e.search_web_mode = "grounded"
    e.search_grounded_top_links = 1

    out = await e._search_single_intent("query")
    assert out == "final"
    e._fetch_page_evidence.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_fallback_search_records_selection(monkeypatch):
    import src.tools.search.engine as eng_mod

    e = make_engine()
    e._search_serpapi_records = AsyncMock(return_value=[{"provider": "serpapi"}])
    e._search_tavily_records = AsyncMock(return_value=[{"provider": "tavily"}])
    e._search_exa_records = AsyncMock(return_value=[{"provider": "exa"}])

    # select 2 fallback providers
    e.fallback_provider_limit = 2
    old_keys = (eng_mod.SERPAPI_API_KEY, eng_mod.TAVILY_API_KEY, eng_mod.EXA_API_KEY)
    eng_mod.SERPAPI_API_KEY = "k1"
    eng_mod.TAVILY_API_KEY = "k2"
    eng_mod.EXA_API_KEY = "k3"
    try:
        merged = await e._run_fallback_search_records("q")
        assert merged
        providers = {r["provider"] for r in merged}
        assert len(providers) == 2  # limited to fallback_provider_limit
    finally:
        eng_mod.SERPAPI_API_KEY, eng_mod.TAVILY_API_KEY, eng_mod.EXA_API_KEY = old_keys


@pytest.mark.asyncio
async def test_run_fallback_search_records_no_keys(monkeypatch):
    import src.tools.search.engine as eng_mod

    e = make_engine()
    old = (eng_mod.SERPAPI_API_KEY, eng_mod.TAVILY_API_KEY, eng_mod.EXA_API_KEY)
    eng_mod.SERPAPI_API_KEY = ""
    eng_mod.TAVILY_API_KEY = ""
    eng_mod.EXA_API_KEY = ""
    try:
        assert await e._run_fallback_search_records("q") == []
    finally:
        eng_mod.SERPAPI_API_KEY, eng_mod.TAVILY_API_KEY, eng_mod.EXA_API_KEY = old


@pytest.mark.asyncio
async def test_search_single_intent_fallback_when_insufficient(monkeypatch):
    e = make_engine()
    e._classify_topic = MagicMock(return_value="general")
    e._transform_temporal_query = MagicMock(return_value=("q", None))
    e._search_duckduckgo_records = AsyncMock(return_value=[])
    e._dedupe_records = MagicMock(side_effect=lambda x: x)
    e._required_quality_sources = MagicMock(return_value=2)
    e._is_search_result_sufficient = MagicMock(return_value=False)
    fallback_rec = {"title": "f", "snippet": "s", "url": "http://f", "domain": "f.com"}
    e._run_fallback_search_records = AsyncMock(return_value=[fallback_rec])
    e._score_record = MagicMock(return_value=1.0)
    e._lightweight_rerank = MagicMock(side_effect=lambda t, q, r: r)
    e._format_final_search_result = MagicMock(return_value="final2")
    e._count_quality_sources = MagicMock(return_value=1)
    e.search_web_mode = "snippet"
    out = await e._search_single_intent("query")
    assert "final2" in out
    e._run_fallback_search_records.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_search_pipeline_multi_intent_with_error():
    e = make_engine()
    e._split_multi_intents = MagicMock(return_value=["intent 1", "intent 2"])
    calls = {"n": 0}

    async def fake_search(intent, fallback):
        calls["n"] += 1
        if calls["n"] == 1:
            return "Result for intent 1"
        raise RuntimeError("intent 2 fail")

    e._search_single_intent = fake_search
    out = await e._execute_search_pipeline("multi query", False)
    assert "Result for intent 1" in out
    assert "Không thể truy xuất dữ liệu" in out


@pytest.mark.asyncio
async def test_run_search_apis_time_sensitive_empty_retries_forced():
    e = make_engine()
    e.get_web_search_cache = MagicMock(return_value=None)
    e._is_time_sensitive_query = MagicMock(return_value=True)

    calls = {"n": 0}
    async def fake_pipeline(query, force_fallback):
        calls["n"] += 1
        if calls["n"] == 1:
            return ""  # first empty
        return "fallback date result"

    e._execute_search_pipeline = fake_pipeline
    out = await e.run_search_apis("tin tức hôm nay")
    assert out == "fallback date result"
    assert calls["n"] == 2
