"""Offline tests for SearchReranker wrapper methods and formatting."""
import sys
from unittest.mock import MagicMock

sys.path.insert(0, ".")

from src.tools.search.reranker import SearchReranker


class NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


def make_reranker():
    r = SearchReranker(top_results_limit=3, logger_override=NullLogger())
    return r


def test_dedupe_records_removes_dupe_urls():
    r = make_reranker()
    records = [
        {"url": "https://example.com/a"},
        {"url": "https://example.com/a"},
        {"url": "https://example.com/b"},
        {"content": "no url"},  # no url -> kept
    ]
    deduped = r.dedupe_records(records)
    assert len(deduped) == 3


def test_score_record_delegates():
    r = make_reranker()
    r._score_record = MagicMock(return_value=3.5)
    assert r.score_record("general", "q", {"url": "x"}) == 3.5


def test_is_quality_record_delegates():
    r = make_reranker()
    r._is_quality_record = MagicMock(return_value=True)
    assert r.is_quality_record("general", "q", {"url": "x"}) is True


def test_count_quality_sources_delegates():
    r = make_reranker()
    r._count_quality_sources = MagicMock(return_value=2)
    assert r.count_quality_sources([], "general", "q") == 2


def test_is_search_result_sufficient_delegates():
    r = make_reranker()
    r._is_search_result_sufficient = MagicMock(return_value=False)
    assert r.is_search_result_sufficient([], "g", "q", 2) is False


def test_dynamic_reputation_score_delegates():
    r = make_reranker()
    r._dynamic_reputation_score = MagicMock(return_value=1.0)
    assert r.dynamic_reputation_score("g", "q", {}) == 1.0


def test_domain_diversify_delegates():
    r = make_reranker()
    r._domain_diversify_records = MagicMock(return_value=[{"url": "x"}])
    assert r.domain_diversify_records([{"url": "x"}], 3) == [{"url": "x"}]


def test_calculate_time_decay_penalty_delegates():
    r = make_reranker()
    r._calculate_time_decay_penalty = MagicMock(return_value=0.5)
    assert r.calculate_time_decay_penalty("g", None, False) == 0.5


def test_lightweight_rerank_delegates():
    r = make_reranker()
    r._lightweight_rerank = MagicMock(return_value=[{"url": "x"}])
    assert r.lightweight_rerank("g", "q", [{"url": "x"}]) == [{"url": "x"}]


def test_format_final_search_result_empty():
    r = make_reranker()
    r.domain_diversify_records = MagicMock(return_value=[])
    out = r.format_final_search_result("general", "query", [], 2)
    assert "Không có kết quả" in out


def test_format_final_search_result_renders_records():
    r = make_reranker()
    recs = [
        {"title": "Title", "snippet": "Some snippet", "url": "http://x", "score": "0.9",
         "evidence": "evidence text"},
    ]
    r.domain_diversify_records = MagicMock(return_value=recs)
    r.count_quality_sources = MagicMock(return_value=1)
    out = r.format_final_search_result("general", "q", recs, 2)
    assert "Title" in out
    assert "Some snippet" in out
    assert "evidence text" in out
    assert "Chưa đủ nguồn" in out  # quality < required
