"""Offline tests for WeatherService."""
import json
import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock

sys.path.insert(0, ".")

from src.tools.builtin.weather import (
    WeatherService,
    _normalize_city_key,
    _parse_timestamp,
)


class NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


def make_service(monkeypatch, tmp_path):
    import src.tools.builtin.weather as w_mod

    w_mod.WEATHER_CACHE_PATH = str(tmp_path / "weather_cache.json")
    svc = WeatherService(logger_override=NullLogger())
    svc.logger = NullLogger()
    return svc, w_mod


def test_normalize_city_key():
    assert _normalize_city_key("  Hanoi ") == "hanoi"
    assert _normalize_city_key("") == ""


def test_parse_timestamp_valid():
    dt = _parse_timestamp("2026-01-01T10:00:00")
    assert dt is not None
    assert dt.tzinfo is None


def test_parse_timestamp_invalid():
    assert _parse_timestamp("not-a-date") is None
    assert _parse_timestamp(None) is None
    assert _parse_timestamp(123) is None


def test_load_cache_restores_valid_entries(monkeypatch, tmp_path):
    svc, w_mod = make_service(monkeypatch, tmp_path)
    cache_file = tmp_path / "weather_cache.json"
    cache_file.write_text(json.dumps({
        "Hanoi": {"timestamp": "2026-01-01T10:00:00", "data": "sunny"},
        "invalid": "not-dict",
    }), encoding="utf-8")
    svc.load_cache()
    assert "hanoi" in svc.weather_cache
    assert "invalid" not in svc.weather_cache


def test_load_cache_missing_file(monkeypatch, tmp_path):
    svc, w_mod = make_service(monkeypatch, tmp_path)
    svc.load_cache()
    assert svc.weather_cache == {}


def test_get_cached_fresh(monkeypatch, tmp_path):
    svc, w_mod = make_service(monkeypatch, tmp_path)
    svc.weather_cache["hanoi"] = {"data": "sunny", "timestamp": datetime.now()}
    assert svc._get_cached("hanoi") == "sunny"


def test_get_cached_stale(monkeypatch, tmp_path):
    svc, w_mod = make_service(monkeypatch, tmp_path)
    svc.weather_cache["hanoi"] = {"data": "sunny", "timestamp": datetime.now() - timedelta(hours=2)}
    assert svc._get_cached("hanoi") is None


def test_get_cached_missing(monkeypatch, tmp_path):
    svc, w_mod = make_service(monkeypatch, tmp_path)
    assert svc._get_cached("nope") is None


def test_store_cache_adds(monkeypatch, tmp_path):
    svc, w_mod = make_service(monkeypatch, tmp_path)
    svc._store_cache("hanoi", "weather info")
    assert svc.weather_cache["hanoi"]["data"] == "weather info"


def test_run_weather_no_city(monkeypatch, tmp_path):
    svc, w_mod = make_service(monkeypatch, tmp_path)
    svc.weather_cache = {}
    w_mod.CITY = ""
    assert "cung cấp tên thành phố" in svc.run_weather("")


def test_run_weather_cache_hit(monkeypatch, tmp_path):
    svc, w_mod = make_service(monkeypatch, tmp_path)
    svc.weather_cache["hanoi"] = {"data": "cached weather", "timestamp": datetime.now()}
    assert svc.run_weather("Hanoi") == "cached weather"


def test_run_weather_no_api_key(monkeypatch, tmp_path):
    svc, w_mod = make_service(monkeypatch, tmp_path)
    w_mod.WEATHER_API_KEY = ""
    assert "WEATHER_API_KEY" in svc.run_weather("Hanoi")


def test_run_weather_success(monkeypatch, tmp_path):
    svc, w_mod = make_service(monkeypatch, tmp_path)
    w_mod.WEATHER_API_KEY = "key"
    response = MagicMock()
    response.status_code = 200
    response.json = MagicMock(return_value={
        "location": {"name": "Hanoi"},
        "current": {"temp_c": 30, "condition": {"text": "Sunny"}, "humidity": 60, "wind_kph": 10},
    })
    monkeypatch.setattr("requests.get", MagicMock(return_value=response))
    result = svc.run_weather("Hanoi")
    assert "Hanoi" in result
    assert "30" in result
    # cached now
    assert "hanoi" in svc.weather_cache


def test_run_weather_not_found(monkeypatch, tmp_path):
    svc, w_mod = make_service(monkeypatch, tmp_path)
    w_mod.WEATHER_API_KEY = "key"
    response = MagicMock()
    response.status_code = 404
    response.json = MagicMock(return_value={"error": {"message": "No matching location"}})
    monkeypatch.setattr("requests.get", MagicMock(return_value=response))
    result = svc.run_weather("Nowhere")
    assert "Không tìm thấy" in result


def test_run_weather_exception(monkeypatch, tmp_path):
    svc, w_mod = make_service(monkeypatch, tmp_path)
    w_mod.WEATHER_API_KEY = "key"
    monkeypatch.setattr("requests.get", MagicMock(side_effect=ConnectionError("no net")))
    result = svc.run_weather("Hanoi")
    assert "Lỗi" in result


def test_load_cache_non_dict_json(monkeypatch, tmp_path):
    svc, w_mod = make_service(monkeypatch, tmp_path)
    cache_file = tmp_path / "weather_cache.json"
    cache_file.write_text("[1, 2, 3]", encoding="utf-8")
    svc.load_cache()
    assert svc.weather_cache == {}


def test_save_cache_oserror(monkeypatch, tmp_path):
    svc, w_mod = make_service(monkeypatch, tmp_path)
    svc.weather_cache["city"] = {"data": "sun", "timestamp": datetime.now()}
    # point to a read-only or invalid dir to trigger OSError
    w_mod.WEATHER_CACHE_PATH = str(tmp_path / "missing_dir" / "sub" / "c.json")
    svc.save_cache()  # handles error without raising


def test_store_cache_lru_eviction(monkeypatch, tmp_path):
    svc, w_mod = make_service(monkeypatch, tmp_path)
    import src.tools.builtin.weather as w_mod_direct
    old_max = w_mod_direct.MAX_CACHE_ENTRIES
    w_mod_direct.MAX_CACHE_ENTRIES = 2
    try:
        svc.weather_cache["c1"] = {"data": "d1", "timestamp": datetime.now() - timedelta(minutes=10)}
        svc.weather_cache["c2"] = {"data": "d2", "timestamp": datetime.now() - timedelta(minutes=5)}
        svc._store_cache("c3", "d3")
        assert len(svc.weather_cache) == 2
        assert "c1" not in svc.weather_cache  # evicted oldest
        assert "c3" in svc.weather_cache
    finally:
        w_mod_direct.MAX_CACHE_ENTRIES = old_max


def test_run_weather_invalid_json_response(monkeypatch, tmp_path):
    svc, w_mod = make_service(monkeypatch, tmp_path)
    w_mod.WEATHER_API_KEY = "key"
    resp = MagicMock()
    resp.status_code = 500
    resp.json = MagicMock(side_effect=ValueError("not json"))
    resp.text = "Internal Server Error"
    monkeypatch.setattr("requests.get", MagicMock(return_value=resp))
    res = svc.run_weather("Hanoi")
    assert "Không tìm thấy" in res
