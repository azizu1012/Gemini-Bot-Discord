import asyncio
import json
import time
from typing import Any, Dict, Optional

import requests

from src.core.config import logger, WEATHER_API_KEY, CITY, WEATHER_CACHE_PATH
from src.tools.helpers import CityNameHelper


class WeatherService:
    """Fetch and cache weather data from OpenWeatherMap API."""

    CACHE_TTL_SECONDS = 3600

    def __init__(self):
        self.logger = logger
        self.weather_lock = asyncio.Lock()

    def _normalize_city(self, city_query: str):
        return CityNameHelper.normalize(city_query)

    async def get_weather(self, city_query: Optional[str] = None):
        import json
        async with self.weather_lock:
            if city_query is None:
                city_query = CITY or "Ho Chi Minh City"
            city_en, city_vi = self._normalize_city(city_query)

            cache_path = WEATHER_CACHE_PATH.replace(".json", f"_{city_en.replace(' ', '_').lower()}.json")

            def _write_cache_sync(payload: Dict[str, Any]) -> None:
                try:
                    with open(cache_path, "w", encoding="utf-8") as f:
                        json.dump(payload, f, ensure_ascii=False, indent=2)
                except Exception as e:
                    self.logger.warning(f"Weather cache write failed: {e}")

            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                cached_time = cached.get("timestamp", 0)
                if time.time() - cached_time < self.CACHE_TTL_SECONDS:
                    return cached.get("data", {})
            except (FileNotFoundError, json.JSONDecodeError, Exception):
                pass

            if not WEATHER_API_KEY:
                return {"error": f"Chưa cấu hình WEATHER_API_KEY cho thời tiết.", "city": city_en}

            def _fetch_weather_sync() -> Dict[str, Any]:
                try:
                    resp = requests.get(
                        f"https://api.openweathermap.org/data/2.5/weather",
                        params={
                            "q": city_en,
                            "appid": WEATHER_API_KEY,
                            "units": "metric",
                            "lang": "vi",
                        },
                        timeout=10,
                    )
                    if resp.status_code == 200:
                        raw = resp.json()
                        main = raw.get("main", {})
                        weather_desc = raw.get("weather", [{}])[0].get("description", "Không rõ")
                        wind = raw.get("wind", {})
                        return {
                            "city": city_en,
                            "city_vi": city_vi,
                            "temperature": main.get("temp"),
                            "feels_like": main.get("feels_like"),
                            "humidity": main.get("humidity"),
                            "description": weather_desc,
                            "wind_speed": wind.get("speed"),
                            "country": raw.get("sys", {}).get("country", ""),
                        }
                    elif resp.status_code == 404:
                        return {"error": f"Không tìm thấy thành phố '{city_en}'.", "city": city_en}
                    else:
                        return {"error": f"Lỗi API thời tiết (HTTP {resp.status_code})", "city": city_en}
                except requests.RequestException as e:
                    return {"error": f"Lỗi kết nối OpenWeatherMap: {e}", "city": city_en}

            data = await asyncio.to_thread(_fetch_weather_sync)
            if "error" not in data:
                await asyncio.to_thread(_write_cache_sync, {"timestamp": time.time(), "data": data})
            return data
