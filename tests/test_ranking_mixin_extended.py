"""Offline tests for SearchRankingMixin scoring/authority/freshness/rerank."""
import sys
from datetime import datetime

sys.path.insert(0, ".")

from src.tools.search.mixins.ranking import SearchRankingMixin


def make_mixin():
    return SearchRankingMixin()


# ---------------- topic/profile ----------------
def test_detect_query_profile_tech_spec():
    m = make_mixin()
    assert m._detect_query_profile("RFC 9110 specification") == "tech_spec"
    assert m._detect_query_profile("v2.3.0 benchmark") == "tech_spec"


def test_detect_query_profile_realtime():
    m = make_mixin()
    assert m._detect_query_profile("giá vàng hôm nay") == "realtime_news"
    assert m._detect_query_profile("weather today") == "realtime_news"


def test_detect_query_profile_code():
    m = make_mixin()
    assert m._detect_query_profile("how to fix error") == "code_howto"
    assert m._detect_query_profile("cách dùng syntax") == "code_howto"


def test_detect_query_profile_general():
    m = make_mixin()
    assert m._detect_query_profile("lịch sử thế kỷ 18") == "general"


# ---------------- authority score ----------------
def test_domain_authority_score_empty():
    m = make_mixin()
    assert m._domain_authority_score("", "general") == 0.0


def test_domain_authority_score_spam():
    m = make_mixin()
    assert m._domain_authority_score("facebook.com", "general") == -3.0


def test_domain_authority_score_tier1():
    m = make_mixin()
    assert m._domain_authority_score("github.com", "tech_spec") == 2.5
    assert m._domain_authority_score("github.com", "general") == 2.0


def test_domain_authority_score_tier2():
    m = make_mixin()
    assert m._domain_authority_score("theverge.com", "general") == 1.0


def test_domain_authority_score_zero():
    m = make_mixin()
    assert m._domain_authority_score("unknown.com", "general") == 0.0


# ---------------- info density ----------------
def test_information_density_code():
    m = make_mixin()
    assert m._information_density_score("```python def foo()```") >= 0.8


def test_information_density_table():
    m = make_mixin()
    assert m._information_density_score("| a | b |") >= 0.8


def test_information_density_digits():
    m = make_mixin()
    assert m._information_density_score("numbers 12345678 here") >= 0.4


def test_information_density_empty():
    m = make_mixin()
    assert m._information_density_score("") == 0.0


# ---------------- freshness ----------------
def test_coupled_freshness_empty_text():
    m = make_mixin()
    assert m._calculate_coupled_freshness("q", "", None, True) == 0.0


def test_coupled_freshness_fresh_pub_date():
    m = make_mixin()
    now = datetime.now()
    score = m._calculate_coupled_freshness("news today", "the news about today events", now, True)
    assert score > 0


def test_coupled_freshness_no_pub_date():
    m = make_mixin()
    score = m._calculate_coupled_freshness("xyz zzz", "some unrelated text here", None, False)
    assert score >= 0.0


# ---------------- time decay ----------------
def test_time_decay_not_sensitive():
    m = make_mixin()
    assert m._calculate_time_decay_penalty("general", datetime.now(), False) == 0.0


def test_time_decay_no_pub_date():
    m = make_mixin()
    assert m._calculate_time_decay_penalty("general", None, True) == -0.6


def test_time_decay_fresh():
    m = make_mixin()
    assert m._calculate_time_decay_penalty("general", datetime.now(), True) == 0.0


def test_time_decay_old():
    m = make_mixin()
    from datetime import timedelta

    old = datetime.now() - timedelta(days=30)
    penalty = m._calculate_time_decay_penalty("general", old, True)
    assert penalty < 0
    assert penalty >= -1.5


# ---------------- reputation score ----------------
def test_dynamic_reputation_score_basic():
    m = make_mixin()
    rec = {"domain": "example.com", "title": "Python guide", "snippet": "a" * 100, "evidence": "e" * 50}
    score = m._dynamic_reputation_score("general", "python guide", rec)
    assert score >= 0


def test_dynamic_reputation_score_gov_boost():
    m = make_mixin()
    rec = {"domain": "stats.gov", "title": "data", "snippet": "s" * 60, "evidence": ""}
    score = m._dynamic_reputation_score("general", "data", rec)
    assert score > 0


# ---------------- score_record ----------------
def test_score_record_spam_negative():
    m = make_mixin()
    rec = {"domain": "facebook.com", "title": "x", "snippet": ""}
    assert m._score_record("general", "q", rec) == -1.0


def test_score_record_normal():
    m = make_mixin()
    rec = {"domain": "github.com", "title": "How to install python", "snippet": "step by step " * 20, "evidence": "e" * 10, "provider": "duckduckgo"}
    score = m._score_record("tech_spec", "how to install python", rec, is_time_sensitive=False)
    assert score > 0


# ---------------- rerank + diversify ----------------
def test_lightweight_rerank_empty():
    m = make_mixin()
    assert m._lightweight_rerank("g", "q", []) == []


def test_lightweight_rerank_sorts():
    m = make_mixin()
    records = [
        {"title": "a", "snippet": "x", "score": "1.0", "domain": "a.com"},
        {"title": "b", "snippet": "y", "score": "3.0", "domain": "b.com"},
    ]
    out = m._lightweight_rerank("g", "q", records)
    assert out[0]["score"] >= out[1]["score"]


def test_domain_diversify_records():
    m = make_mixin()
    records = [
        {"domain": "a.com", "title": "1"},
        {"domain": "a.com", "title": "2"},
        {"domain": "b.com", "title": "3"},
    ]
    out = m._domain_diversify_records(records, 2)
    assert len(out) == 2  # a.com deduped (a.com, b.com)


def test_domain_diversify_no_enforce():
    m = make_mixin()
    records = [{"domain": "a.com", "title": "1"}, {"domain": "a.com", "title": "2"}]
    out = m._domain_diversify_records(records, 5, enforce_diversity=False)
    assert len(out) == 2


# ---------------- quality ----------------
def test_is_quality_record_spam_false():
    m = make_mixin()
    rec = {"domain": "pinterest.com", "title": "", "snippet": ""}
    assert m._is_quality_record("general", "q", rec) is False


def test_count_quality_sources():
    m = make_mixin()
    m._is_quality_record = lambda t, q, r: r.get("quality", False)
    records = [{"quality": True}, {"quality": False}, {"quality": True}]
    assert m._count_quality_sources(records, "g", "q") == 2


def test_is_search_result_sufficient():
    m = make_mixin()
    m._count_quality_sources = lambda *a, **k: 2
    records = [{"snippet": "s" * 300, "title": "t" * 50}]
    assert m._is_search_result_sufficient(records, "g", "q", 2, min_chars=220) is True
    assert m._is_search_result_sufficient(records, "g", "q", 3, min_chars=220) is False


def test_time_decay_grace_windows_by_topic():
    from datetime import timedelta
    m = make_mixin()
    now = datetime.now()

    # future date -> 0.0
    future = now + timedelta(days=2)
    assert m._calculate_time_decay_penalty("general", future, True) == 0.0

    # gaming: 21 days grace -> 10 days old has 0 penalty
    assert m._calculate_time_decay_penalty("gaming", now - timedelta(days=10), True) == 0.0
    # gaming: 30 days old has penalty
    assert m._calculate_time_decay_penalty("gaming", now - timedelta(days=30), True) < 0.0

    # finance: 3 days grace
    assert m._calculate_time_decay_penalty("finance", now - timedelta(days=2), True) == 0.0
    assert m._calculate_time_decay_penalty("finance", now - timedelta(days=5), True) < 0.0

    # movies_tv: 14 days grace
    assert m._calculate_time_decay_penalty("movies_tv", now - timedelta(days=10), True) == 0.0
    assert m._calculate_time_decay_penalty("movies_tv", now - timedelta(days=20), True) < 0.0

    # weather: 1 day grace
    assert m._calculate_time_decay_penalty("weather", now - timedelta(days=0.5), True) == 0.0
    assert m._calculate_time_decay_penalty("weather", now - timedelta(days=2), True) < 0.0


def test_coupled_freshness_pub_date_ranges():
    from datetime import timedelta
    m = make_mixin()
    now = datetime.now()

    # <= 30 days
    s_30 = m._calculate_coupled_freshness("news", "text", now - timedelta(days=20), True)
    assert s_30 >= 0.6

    # <= 90 days
    s_90 = m._calculate_coupled_freshness("news", "text", now - timedelta(days=60), True)
    assert s_90 >= 0.3
