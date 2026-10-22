"""Unit tests for modular search engine subpackage with SSRF safety and consensus reranking."""

import pytest
from datetime import datetime, timezone
from src.tools.search.query_planner import QueryPlanner
from src.tools.search.cache import SearchCache
from src.tools.search.reranker import SearchReranker
from src.tools.search.models import SearchRecord
from src.tools.search.engine import SearchEngine
from src.tools.search.url_safety import is_safe_url


class TestUrlSafety:
    def test_block_internal_hosts(self):
        safe, err = is_safe_url("http://localhost:5432")
        assert safe is False
        assert "not allowed" in err

        safe, err = is_safe_url("http://127.0.0.1:6379")
        assert safe is False
        assert "not allowed" in err

        safe, err = is_safe_url("http://192.168.1.1/admin")
        assert safe is False
        assert "not allowed" in err

        safe, err = is_safe_url("http://10.0.0.1/status")
        assert safe is False
        assert "not allowed" in err

        safe, err = is_safe_url("http://169.254.169.254/latest/meta-data/")
        assert safe is False
        assert "not allowed" in err

    def test_block_invalid_schemes(self):
        safe, err = is_safe_url("ftp://example.com/file")
        assert safe is False
        assert "scheme" in err.lower()

        safe, err = is_safe_url("file:///etc/passwd")
        assert safe is False

    def test_allow_safe_urls(self):
        safe, _ = is_safe_url("https://github.com/azizu1012/Gemini-Bot-Discord")
        assert safe is True

        safe, _ = is_safe_url("https://api.example.com/data")
        assert safe is True


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

    def test_spam_seo_penalized(self):
        reranker = SearchReranker()
        spam_rec = {
            "title": "Best AI tools 2026",
            "snippet": "Check out tokencalc.dev for everything",
            "domain": "tokencalc.dev",
            "url": "https://tokencalc.dev/ai",
        }
        score = reranker.score_record("tech", "best ai tools", spam_rec)
        assert score == -1.0
        assert reranker.is_quality_record("tech", "best ai tools", spam_rec) is False

    def test_authority_domain_boost(self):
        reranker = SearchReranker()
        auth_rec = {
            "title": "Python 3.13 Documentation",
            "snippet": "Official documentation for Python release features",
            "domain": "docs.python.org",
            "url": "https://docs.python.org/3.13/",
        }
        score = reranker.score_record("tech", "python documentation", auth_rec)
        assert score > 0.5
        assert reranker.is_quality_record("tech", "python documentation", auth_rec) is True

    def test_cross_source_consensus_boost(self):
        reranker = SearchReranker()
        # Source 1 and Source 2 share consensus facts
        records = [
            {
                "title": "SpaceX Starship orbital launch test",
                "snippet": "Starship completed orbital insertion successfully with Super Heavy booster recovery.",
                "domain": "reuters.com",
                "url": "https://reuters.com/starship",
                "score": "1.0",
            },
            {
                "title": "Starship orbital flight update",
                "snippet": "Super Heavy booster successfully completed orbital flight test milestones.",
                "domain": "nasaspaceflight.com",
                "url": "https://nasaspaceflight.com/starship",
                "score": "1.0",
            },
            {
                "title": "Random cooking recipe",
                "snippet": "Delicious homemade pasta with tomato sauce.",
                "domain": "cooking.com",
                "url": "https://cooking.com/pasta",
                "score": "1.0",
            },
        ]
        reranked = reranker.lightweight_rerank("tech", "starship orbital launch", records)
        # First two records should have higher score than third due to consensus boost
        assert float(reranked[0]["score"]) > float(reranked[2]["score"])


class TestSearchEngineFacade:
    def test_instantiation_and_delegation(self):
        engine = SearchEngine()
        assert engine._is_time_sensitive_query("hôm nay") is True
        assert engine.planner is not None
        assert engine.reranker is not None
        assert engine.cache is not None

    def test_time_sensitive_inflight_task_is_released(self):
        import asyncio

        async def scenario():
            engine = SearchEngine()
            calls = []

            async def fake_pipeline(query, force_fallback):
                calls.append(query)
                return f"result-{len(calls)}"

            engine._execute_search_pipeline = fake_pipeline
            query = "tin tức hôm nay"
            first = await engine.run_search_apis(query)
            second = await engine.run_search_apis(query)
            return calls, first, second, dict(engine.inflight_search_tasks)

        calls, first, second, inflight = asyncio.run(scenario())
        # Truy vấn time-sensitive phải chạy lại thay vì join task cũ đã hoàn tất.
        assert len(calls) == 2
        assert first == "result-1"
        assert second == "result-2"
        assert inflight == {}
