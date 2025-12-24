import time
from typing import Dict, Any, Optional


class CacheManager:
    """Manager for caching search and image recognition results."""
    
    CACHE_TTL_SECONDS = 3600  # 1 hour
    MAX_CACHE_SIZE = 1000
    
    def __init__(self):
        self.web_search_cache: Dict[str, Dict[str, Any]] = {}
        self.image_recognition_cache: Dict[str, Dict[str, Any]] = {}
    
    def get_web_search_cache(self, query: str) -> Optional[str]:
        """Get cached web search result if valid."""
        if query in self.web_search_cache:
            cached_item = self.web_search_cache[query]
            if time.time() - cached_item['timestamp'] < self.CACHE_TTL_SECONDS:
                return cached_item['data']
            else:
                del self.web_search_cache[query]
        return None
    
    def set_web_search_cache(self, query: str, data: str) -> None:
        """Save web search result to cache."""
        if len(self.web_search_cache) >= self.MAX_CACHE_SIZE:
            oldest_key = min(self.web_search_cache, key=lambda k: self.web_search_cache[k]['timestamp'])
            del self.web_search_cache[oldest_key]
        self.web_search_cache[query] = {'data': data, 'timestamp': time.time()}
    
    def get_image_recognition_cache(self, image_url: str, question: str) -> Optional[str]:
        """Get cached image recognition result if valid."""
        key = f"{image_url}|{question}"
        if key in self.image_recognition_cache:
            cached_item = self.image_recognition_cache[key]
            if time.time() - cached_item['timestamp'] < self.CACHE_TTL_SECONDS:
                return cached_item['data']
            else:
                del self.image_recognition_cache[key]
        return None
    
    def set_image_recognition_cache(self, image_url: str, question: str, data: str) -> None:
        """Save image recognition result to cache."""
        key = f"{image_url}|{question}"
        if len(self.image_recognition_cache) >= self.MAX_CACHE_SIZE:
            oldest_key = min(self.image_recognition_cache, key=lambda k: self.image_recognition_cache[k]['timestamp'])
            del self.image_recognition_cache[oldest_key]
        self.image_recognition_cache[key] = {'data': data, 'timestamp': time.time()}
    
    def clear_all_caches(self) -> None:
        """Clear all caches."""
        self.web_search_cache.clear()
        self.image_recognition_cache.clear()
