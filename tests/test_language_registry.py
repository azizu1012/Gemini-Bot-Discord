"""Offline tests for language topic registry."""
import sys

sys.path.insert(0, ".")

from src.tools.search.languages.registry import (
    build_search_topics,
    detect_query_languages,
    iter_language_topic_keywords,
    language_topic_keywords,
)


def test_language_topic_keywords_unknown():
    assert language_topic_keywords("klingon") == {}


def test_language_topic_keywords_vi():
    topics = language_topic_keywords("vi")
    assert isinstance(topics, dict)
    # at least a general topic with keywords
    assert topics


def test_build_search_topics_has_general():
    merged = build_search_topics()
    assert "general" in merged
    assert "suffixes" in merged["general"]


def test_build_search_topics_merged_keywords():
    merged = build_search_topics()
    # combined dict has a topic structure
    for topic, data in merged.items():
        assert "keywords" in data
        assert "suffixes" in data


def test_detect_query_languages_ja():
    assert "ja" in detect_query_languages("これはテストです")


def test_detect_query_languages_korea():
    assert "korea" in detect_query_languages("안녕하세요")


def test_detect_query_languages_chinese():
    langs = detect_query_languages("你好世界")
    assert "chinese" in langs


def test_detect_query_languages_empty():
    assert detect_query_languages("hello world") == ()


def test_iter_language_topic_keywords():
    items = list(iter_language_topic_keywords(["vi"]))
    # yields (topic, keywords) tuples
    assert items
    assert all(isinstance(t, str) and isinstance(k, tuple) for t, k in items)
