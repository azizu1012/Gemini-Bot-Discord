"""Unit tests for modular search engine subpackage."""

import pytest
from src.tools.search.query_planner import QueryPlanner
from src.tools.search.cache import SearchCache
from src.tools.search.reranker import SearchReranker
from src.tools.search.models import SearchRecord
from src.tools.search.engine import SearchEngine


class TestQueryPlanner:
    def test_time_sensitive_detection(self):
        planner = QueryPlanner()
        assert planner.is_time_sensitive_query("tin tức hôm nay") is True
        assert planner.is_time_sensitive_query("giá vàng mới nhất") is True
        assert planner.is_time_sensitive_query("thời tiết hà nội") is True
        assert planner.is_time_sensitive_query("lịch sử việt nam thế kỷ 18") is False

    def test_split_multi_intents(self):
        planner = QueryPlanner(intent_batch_size=3)
        query = "thời tiết hà nội hôm nay. giá vàng 9999 hôm nay. kết quả bóng đá ngoại hạng anh"
        intents = planner.split_multi_intents(query)
        assert len(intents) == 3
        assert "thời tiết hà nội hôm nay" in intents[0]

    def test_classify_topic(self):
        planner = QueryPlanner()
        assert planner.classify_topic("tin tức công nghệ ai mới nhất") == "tech"
        assert planner.classify_topic("game genshin impact banner mới") == "gaming"
        assert planner.classify_topic("nghiên cứu khoa học vũ trụ nasa") == "science"
        assert planner.classify_topic("thuyết tương đối của einstein") == "general"


class TestSearchCache:
    def test_set_and_get_web_search(self):
        cache = SearchCache()
        cache.set_web_search("python tutorial", "some result data")
        assert cache.get_web_search("python tutorial") == "some result data"
        assert cache.get_web_search("non-existent") is None

    def test_deep_read_cache(self):
        cache = SearchCache()
        cache.set_deep_read("https://example.com/article", "sample text content")
        assert cache.get_deep_read("https://example.com/article") == "sample text content"


class TestSearchReranker:
    def test_dedupe_records(self):
        reranker = SearchReranker()
        records = [
            {"title": "Page 1", "url": "https://example.com/page1", "normalized_url": "https://example.com/page1"},
            {"title": "Page 1 Dup", "url": "https://example.com/page1/", "normalized_url": "https://example.com/page1"},
            {"title": "Page 2", "url": "https://example.com/page2", "normalized_url": "https://example.com/page2"},
        ]
        deduped = reranker.dedupe_records(records)
        assert len(deduped) == 2

    def test_domain_diversify(self):
        reranker = SearchReranker()
        records = [
            {"title": "Doc 1", "url": "https://site1.com/a", "domain": "site1.com"},
            {"title": "Doc 2", "url": "https://site1.com/b", "domain": "site1.com"},
            {"title": "Doc 3", "url": "https://site2.com/c", "domain": "site2.com"},
        ]
        diversified = reranker.domain_diversify_records(records, limit=2, enforce_diversity=True)
        assert len(diversified) == 2
        assert diversified[0]["domain"] != diversified[1]["domain"]


class TestSearchEngineFacade:
    def test_instantiation_and_delegation(self):
        engine = SearchEngine()
        assert engine._is_time_sensitive_query("hôm nay") is True
        assert engine.planner is not None
        assert engine.reranker is not None
        assert engine.cache is not None
