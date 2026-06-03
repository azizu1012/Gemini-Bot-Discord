import time
from typing import Dict, Any, Optional, List


class CacheManager:
    """Manager for caching search, image recognition results, and user chat history."""

    CACHE_TTL_SECONDS = 3600  # 1 hour
    CHAT_CACHE_TTL_SECONDS = 300  # 5 minutes for chat history cache
    MAX_CACHE_SIZE = 1000
    MAX_CHAT_HISTORY_LIMIT = 50  # Max messages kept in RAM for 1 user

    def __init__(self):
        self.web_search_cache: Dict[str, Dict[str, Any]] = {}
        self.image_recognition_cache: Dict[str, Dict[str, Any]] = {}
        self.chat_history_cache: Dict[str, Dict[str, Any]] = {}

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
    
    def get_chat_history(self, user_id: str, limit: int) -> Optional[List[Dict[str, str]]]:
        """Get cached chat history for a user if valid and within TTL."""
        if user_id in self.chat_history_cache:
            cached_item = self.chat_history_cache[user_id]
            if time.time() - cached_item['timestamp'] < self.CHAT_CACHE_TTL_SECONDS:
                # Update timestamp to refresh TTL and LRU status
                cached_item['timestamp'] = time.time()
                history = cached_item['history']
                return history[-limit:]
            else:
                del self.chat_history_cache[user_id]
        return None

    def set_chat_history(self, user_id: str, history: List[Dict[str, str]]) -> None:
        """Save a user's chat history to the cache."""
        if len(self.chat_history_cache) >= self.MAX_CACHE_SIZE:
            # LRU: remove the oldest item
            oldest_key = min(self.chat_history_cache, key=lambda k: self.chat_history_cache[k]['timestamp'])
            del self.chat_history_cache[oldest_key]

        # Only store the last MAX_CHAT_HISTORY_LIMIT messages
        safe_history = list(history[-self.MAX_CHAT_HISTORY_LIMIT:]) if len(history) > self.MAX_CHAT_HISTORY_LIMIT else list(history)
        self.chat_history_cache[user_id] = {
            'history': safe_history,
            'timestamp': time.time()
        }

    def add_chat_message(self, user_id: str, role: str, content: str) -> None:
        """Append a new message to the user's cached chat history if it exists."""
        if user_id in self.chat_history_cache:
            cached_item = self.chat_history_cache[user_id]
            if time.time() - cached_item['timestamp'] < self.CHAT_CACHE_TTL_SECONDS:
                history = cached_item['history']
                history.append({'role': role, 'content': content})

                if len(history) > self.MAX_CHAT_HISTORY_LIMIT:
                    history = history[-self.MAX_CHAT_HISTORY_LIMIT:]

                cached_item['history'] = history
                cached_item['timestamp'] = time.time()
            else:
                del self.chat_history_cache[user_id]

    def invalidate_chat_history(self, user_id: str) -> None:
        """Invalidate the cached chat history for a user."""
        if user_id in self.chat_history_cache:
            del self.chat_history_cache[user_id]

    def clear_all_caches(self) -> None:
        """Clear all caches."""
        self.web_search_cache.clear()
        self.image_recognition_cache.clear()
        self.chat_history_cache.clear()


# Global Singleton pattern
_cache_manager_instance: Optional[CacheManager] = None


def get_cache_manager() -> CacheManager:
    global _cache_manager_instance
    if _cache_manager_instance is None:
        _cache_manager_instance = CacheManager()
    return _cache_manager_instance
