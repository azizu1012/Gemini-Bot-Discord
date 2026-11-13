"""Offline tests for SearchCache edge cases."""
import sys
from datetime import datetime, timedelta

sys.path.insert(0, ".")

from src.tools.search.cache import SearchCache


def make_cache():
    return SearchCache(semantic_cache_enabled=True)


def test_normalize_cache_key_mode_split():
    c = make_cache()
    key = c.normalize_cache_key("realtime|news today")
    assert key.startswith("realtime|")


def test_normalize_cache_key_no_mode():
    c = make_cache()
    key = c.normalize_cache_key("  query here ")
    assert key.startswith("general|")


def test_get_web_search_missing():
    c = make_cache()
    assert c.get_web_search("nothing") is None


def test_get_web_search_fresh_expires():
    c = make_cache()
    c.set_web_search("hello", "data")
    assert c.get_web_search("hello") == "data"


def test_get_web_search_expired():
    c = make_cache()
    c.set_web_search("hello", "data")
    c.web_search_cache[c.normalize_cache_key("hello")]["expires_at"] = datetime.now() - timedelta(minutes=1)
    assert c.get_web_search("hello") is None


def test_set_web_search_stores_time_sensitive_ttl():
    c = make_cache()
    c.set_web_search("q", "data", time_sensitive=True)
    item = c.web_search_cache[c.normalize_cache_key("q")]
    assert item["time_sensitive"] is True
    assert item["ttl_seconds"] == c.time_sensitive_ttl_seconds


def test_get_deep_read_missing():
    c = make_cache()
    assert c.get_deep_read("http://x") is None


def test_get_deep_read_fresh():
    c = make_cache()
    c.set_deep_read("http://x", "content")
    assert c.get_deep_read("http://x") == "content"


def test_get_deep_read_expired():
    c = make_cache()
    c.set_deep_read("http://x", "content", ttl_seconds=1)
    c.deep_read_cache["http://x"]["timestamp"] = datetime.now() - timedelta(seconds=100)
    assert c.get_deep_read("http://x") is None


def test_set_deep_read_min_ttl():
    c = make_cache()
    c.set_deep_read("http://a", "x", ttl_seconds=10)
    assert c.deep_read_cache["http://a"]["ttl_seconds"] == 60


def test_get_web_search_no_expires_at_fresh():
    c = make_cache()
    c.web_search_cache[c.normalize_cache_key("q")] = {
        "data": "fresh_data",
        "timestamp": datetime.now() - timedelta(hours=1),
        "expires_at": None,
    }
    assert c.get_web_search("q") == "fresh_data"


def test_get_web_search_no_expires_at_stale():
    c = make_cache()
    c.web_search_cache[c.normalize_cache_key("q")] = {
        "data": "stale_data",
        "timestamp": datetime.now() - timedelta(hours=10),
        "expires_at": None,
    }
    assert c.get_web_search("q") is None
    assert c.normalize_cache_key("q") not in c.web_search_cache
