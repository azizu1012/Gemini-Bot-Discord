"""Offline tests for QueryPlanner extended branches."""
import sys
from datetime import datetime

sys.path.insert(0, ".")

from src.tools.search.query_planner import QueryPlanner


def make_planner():
    return QueryPlanner(intent_batch_size=3, min_quality_sources=1, time_sensitive_min_quality_sources=2)


def test_contains_year():
    p = make_planner()
    assert p.contains_year("war in 1945") is True
    assert p.contains_year("2026 season") is True
    assert p.contains_year("no year here") is False
    assert p.contains_year("") is False


def test_is_time_sensitive_query_empty():
    p = make_planner()
    assert p.is_time_sensitive_query("") is False
    assert p.is_time_sensitive_query(None) is False


def test_is_time_sensitive_query_suffix():
    p = make_planner()
    assert p.is_time_sensitive_query("kết quả bóng đá mới nhất") is True
    assert p.is_time_sensitive_query("news update") is True


def test_is_time_sensitive_query_false():
    p = make_planner()
    assert p.is_time_sensitive_query("lịch sử thế kỷ 18") is False


def test_time_sensitive_timelimit_branches():
    p = make_planner()
    assert p.time_sensitive_timelimit("news today") == "d"
    assert p.time_sensitive_timelimit("match yesterday") == "d"
    assert p.time_sensitive_timelimit("news this week") == "w"
    assert p.time_sensitive_timelimit("report this month") == "m"
    assert p.time_sensitive_timelimit("trend this year") == "y"
    assert p.time_sensitive_timelimit("plain query") is None


def test_transform_temporal_query_today():
    p = make_planner()
    query, lim = p.transform_temporal_query("thời tiết hôm nay")
    assert lim == "d"
    assert str(datetime.now().year) in query  # year appended


def test_transform_temporal_query_yesterday():
    p = make_planner()
    query, lim = p.transform_temporal_query("kết quả hôm qua")
    assert lim == "d"
    assert str(datetime.now().year) in query


def test_transform_temporal_query_this_month():
    p = make_planner()
    query, lim = p.transform_temporal_query("báo cáo tháng này")
    assert lim == "m"
    assert str(datetime.now().year) in query


def test_transform_temporal_query_this_year():
    p = make_planner()
    query, lim = p.transform_temporal_query("tổng kết năm nay")
    assert lim == "y"
    assert str(datetime.now().year) in query


def test_transform_temporal_query_plain():
    p = make_planner()
    query, lim = p.transform_temporal_query("cách nấu phở")
    assert query == "cách nấu phở"
    assert lim is None


def test_required_quality_sources_sensitive():
    p = make_planner()
    assert p.required_quality_sources("tin tức hôm nay") == 2
    assert p.required_quality_sources("cách nấu phở") == 1


def test_split_multi_intents_empty():
    p = make_planner()
    assert p.split_multi_intents("") == []
    assert p.split_multi_intents(None) == []


def test_split_multi_intents_multiple():
    p = make_planner()
    # each intent must be >=20 chars to be kept separate
    intents = p.split_multi_intents(
        "lịch sử phát triển của trí tuệ nhân tạo qua các thập kỷ; "
        "so sánh ưu nhược điểm của các mô hình ngôn ngữ lớn khác nhau"
    )
    assert len(intents) == 2


def test_split_multi_intents_single_short():
    p = make_planner()
    assert p.split_multi_intents("chỉ một câu hỏi dài") == ["chỉ một câu hỏi dài"]


def test_determine_batch_size_empty():
    p = make_planner()
    assert p.determine_batch_size([]) == 2


def test_determine_batch_size_non_sensitive():
    p = make_planner()
    assert p.determine_batch_size(["a", "b", "c"]) == 3


def test_determine_batch_size_all_sensitive():
    p = make_planner()
    assert p.determine_batch_size(["tin hôm nay", "giá vàng hôm nay"]) == 1


def test_classify_topic():
    p = make_planner()
    # falls through to _classify_topic (ranking mixin)
    assert isinstance(p.classify_topic("thuyết tương đối"), str)
