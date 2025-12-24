import json
import time
from typing import Dict, Any, Optional

# Cấu hình cache
CACHE_TTL_SECONDS = 3600  # Thời gian sống của cache: 1 giờ
MAX_CACHE_SIZE = 1000    # Số lượng mục tối đa trong cache

# Cache cho web_search
web_search_cache: Dict[str, Dict[str, Any]] = {}

# Cache cho image_recognition
image_recognition_cache: Dict[str, Dict[str, Any]] = {}

def get_web_search_cache(query: str) -> Optional[str]:
    """
    Lấy kết quả web_search từ cache nếu còn hợp lệ.
    """
    if query in web_search_cache:
        cached_item = web_search_cache[query]
        if time.time() - cached_item['timestamp'] < CACHE_TTL_SECONDS:
            return cached_item['data']
        else:
            # Cache hết hạn
            del web_search_cache[query]
    return None

def set_web_search_cache(query: str, data: str) -> None:
    """
    Lưu kết quả web_search vào cache.
    """
    if len(web_search_cache) >= MAX_CACHE_SIZE:
        # Xóa mục cũ nhất nếu cache đầy (có thể cải thiện bằng LRU)
        oldest_key = min(web_search_cache, key=lambda k: web_search_cache[k]['timestamp'])
        del web_search_cache[oldest_key]
    web_search_cache[query] = {'data': data, 'timestamp': time.time()}

def get_image_recognition_cache(image_url: str, question: str) -> Optional[str]:
    """
    Lấy kết quả image_recognition từ cache nếu còn hợp lệ.
    """
    key = f"{image_url}|{question}"
    if key in image_recognition_cache:
        cached_item = image_recognition_cache[key]
        if time.time() - cached_item['timestamp'] < CACHE_TTL_SECONDS:
            return cached_item['data']
        else:
            # Cache hết hạn
            del image_recognition_cache[key]
    return None

def set_image_recognition_cache(image_url: str, question: str, data: str) -> None:
    """
    Lưu kết quả image_recognition vào cache.
    """
    key = f"{image_url}|{question}"
    if len(image_recognition_cache) >= MAX_CACHE_SIZE:
        # Xóa mục cũ nhất nếu cache đầy
        oldest_key = min(image_recognition_cache, key=lambda k: image_recognition_cache[k]['timestamp'])
        del image_recognition_cache[oldest_key]
    image_recognition_cache[key] = {'data': data, 'timestamp': time.time()}

def clear_all_caches() -> None:
    """
    Xóa toàn bộ cache.
    """
    web_search_cache.clear()
    image_recognition_cache.clear()
