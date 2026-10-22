"""Weather lookup service using WeatherAPI.com."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import requests
from src.core.config import logger, WEATHER_API_KEY, CITY, WEATHER_CACHE_PATH

MAX_CACHE_ENTRIES = 128


def _normalize_city_key(city: str) -> str:
    """Chuẩn hóa khóa cache để 'Hanoi', 'hanoi ', ' HANOI' dùng chung một entry."""
    return " ".join((city or "").split()).casefold()


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    # Luôn dùng giờ naive để TTL so sánh ổn định giữa các lần ghi/đọc.
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


class WeatherService:
    """Fetch and cache weather data from WeatherAPI.com."""

    def __init__(self, logger_override=None):
        self.logger = logger_override or logger
        self.weather_cache: Dict[str, Dict[str, Any]] = {}
        self.cache_ttl = timedelta(minutes=30)
        self._cache_lock = threading.Lock()
        self.load_cache()

    def load_cache(self) -> None:
        try:
            with open(WEATHER_CACHE_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except FileNotFoundError:
            self.weather_cache = {}
            return
        except (OSError, ValueError, TypeError) as exc:
            self.logger.warning(f"Bỏ qua weather cache không đọc được: {exc}")
            self.weather_cache = {}
            return

        if not isinstance(data, dict):
            self.weather_cache = {}
            return

        restored: Dict[str, Dict[str, Any]] = {}
        for city_name, cached_item in data.items():
            if not isinstance(cached_item, dict):
                continue
            payload = cached_item.get('data')
            timestamp = _parse_timestamp(cached_item.get('timestamp'))
            key = _normalize_city_key(str(city_name))
            if not key or not isinstance(payload, str) or timestamp is None:
                continue
            restored[key] = {'data': payload, 'timestamp': timestamp}
        self.weather_cache = restored

    def save_cache(self) -> None:
        with self._cache_lock:
            data = {
                city_name: {
                    'timestamp': cached_item['timestamp'].isoformat(),
                    'data': cached_item['data'],
                }
                for city_name, cached_item in self.weather_cache.items()
            }
        try:
            with open(WEATHER_CACHE_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            self.logger.error(f"Error saving weather cache: {e}")

    def _get_cached(self, cache_key: str) -> Optional[str]:
        with self._cache_lock:
            cached_item = self.weather_cache.get(cache_key)
            if not cached_item:
                return None
            age = datetime.now() - cached_item['timestamp']
            if -self.cache_ttl < age < self.cache_ttl:
                return cached_item['data']
            return None

    def _store_cache(self, cache_key: str, weather_info: str) -> None:
        with self._cache_lock:
            if (
                cache_key not in self.weather_cache
                and len(self.weather_cache) >= MAX_CACHE_ENTRIES
            ):
                oldest_key = min(
                    self.weather_cache,
                    key=lambda key: self.weather_cache[key]['timestamp'],
                )
                del self.weather_cache[oldest_key]
            self.weather_cache[cache_key] = {
                'data': weather_info,
                'timestamp': datetime.now(),
            }
        self.save_cache()

    def run_weather(self, city: Optional[str] = None) -> str:
        target_city = str(city or CITY or "").strip()
        if not target_city:
            return "Vui lòng cung cấp tên thành phố."

        cache_key = _normalize_city_key(target_city)
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        if not WEATHER_API_KEY:
            return "Chưa cấu hình WEATHER_API_KEY."

        url = "https://api.weatherapi.com/v1/current.json"
        params = {
            "key": WEATHER_API_KEY,
            "q": target_city,
            "aqi": "no",
            "lang": "vi",
        }
        try:
            response = requests.get(url, params=params, timeout=10)
            try:
                data = response.json()
            except ValueError:
                data = {}
            if response.status_code == 200:
                current = data.get("current") or {}
                temp = current.get("temp_c")
                desc = (current.get("condition") or {}).get("text") or "không rõ"
                humidity = current.get("humidity")
                wind_kph = current.get("wind_kph")
                location_name = (data.get("location") or {}).get("name") or target_city
                weather_info = (
                    f"Thời tiết tại {location_name}: {desc}, nhiệt độ {temp}°C, "
                    f"độ ẩm {humidity}%, gió {wind_kph} km/h."
                )
                self._store_cache(cache_key, weather_info)
                return weather_info
            error_message = (data.get("error") or {}).get("message") or data.get("message", "")
            return f"Không tìm thấy thông tin thời tiết cho {target_city}: {error_message}"
        except Exception as e:
            self.logger.error(f"Weather API error: {e}")
            return f"Lỗi khi tra cứu thời tiết: {e}"
