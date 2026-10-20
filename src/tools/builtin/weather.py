"""Weather lookup service using WeatherAPI.com."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

import requests
from src.core.config import logger, WEATHER_API_KEY, CITY, WEATHER_CACHE_PATH


class WeatherService:
    """Fetch and cache weather data from WeatherAPI.com."""

    def __init__(self, logger_override=None):
        self.logger = logger_override or logger
        self.weather_cache: Dict[str, Any] = {}
        self.cache_ttl = timedelta(minutes=30)
        self.load_cache()

    def load_cache(self) -> None:
        try:
            with open(WEATHER_CACHE_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for city_name, cached_item in data.items():
                    if 'timestamp' in cached_item and 'data' in cached_item:
                        cached_item['timestamp'] = datetime.fromisoformat(cached_item['timestamp'])
                        self.weather_cache[city_name] = cached_item
        except (FileNotFoundError, json.JSONDecodeError):
            self.weather_cache = {}

    def save_cache(self) -> None:
        try:
            data = {}
            for city_name, cached_item in self.weather_cache.items():
                if 'timestamp' in cached_item and 'data' in cached_item:
                    data[city_name] = {
                        'timestamp': cached_item['timestamp'].isoformat(),
                        'data': cached_item['data'],
                    }
            with open(WEATHER_CACHE_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"Error saving weather cache: {e}")

    def run_weather(self, city: Optional[str] = None) -> str:
        target_city = city or CITY
        if not target_city:
            return "Vui lòng cung cấp tên thành phố."
        target_city = target_city.strip()

        if target_city in self.weather_cache:
            cached_item = self.weather_cache[target_city]
            if datetime.now() - cached_item['timestamp'] < self.cache_ttl:
                return cached_item['data']

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
            data = response.json()
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
                self.weather_cache[target_city] = {'data': weather_info, 'timestamp': datetime.now()}
                self.save_cache()
                return weather_info
            error_message = (data.get("error") or {}).get("message") or data.get("message", "")
            return f"Không tìm thấy thông tin thời tiết cho {target_city}: {error_message}"
        except Exception as e:
            self.logger.error(f"Weather API error: {e}")
            return f"Lỗi khi tra cứu thời tiết: {e}"
