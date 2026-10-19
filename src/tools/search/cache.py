"""Cache management for search queries and deep-read evidence."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from src.tools.constants import MAX_CACHE_SIZE
from src.tools.helpers import TextProcessor


class SearchCache:
    """In-memory cache for web search results and deep-read page content."""

    def __init__(
        self,
        semantic_cache_enabled: bool = True,
        general_ttl_seconds: int = 21600,
        time_sensitive_ttl_seconds: int = 1800,
        empty_evidence_ttl_seconds: int = 600,
    ):
        self.semantic_cache_enabled = semantic_cache_enabled
        self.general_ttl_seconds = general_ttl_seconds
        self.time_sensitive_ttl_seconds = time_sensitive_ttl_seconds
        self.empty_evidence_ttl_seconds = empty_evidence_ttl_seconds

        self.web_search_cache: Dict[str, Any] = {}
        self.deep_read_cache: Dict[str, Any] = {}

    def normalize_cache_key(self, query: str) -> str:
        normalized = (query or "").strip().lower()
        normalized = re.sub(r"\s+", " ", normalized)
        normalized = re.sub(r"\s*\|\s*", "|", normalized)
        mode = "general"
        payload = normalized
        if "|" in normalized:
            maybe_mode, maybe_payload = normalized.split("|", 1)
            mode = maybe_mode or "general"
            payload = maybe_payload or ""
        if self.semantic_cache_enabled:
            canonical_payload = TextProcessor.canonicalize_search_query(payload)
            if canonical_payload:
                payload = canonical_payload
        return f"{mode}|{payload}"

    def get_web_search(self, query: str) -> Optional[str]:
        key = self.normalize_cache_key(query)
        if key in self.web_search_cache:
            cached_item = self.web_search_cache[key]
            expires_at = cached_item.get("expires_at")
            if isinstance(expires_at, datetime):
                if datetime.now() <= expires_at:
                    return cached_item.get("data")
                del self.web_search_cache[key]
                return None
            if datetime.now() - cached_item.get("timestamp", datetime.min) < timedelta(hours=6):
                return cached_item.get("data")
            del self.web_search_cache[key]
        return None

    def set_web_search(self, query: str, data: str, time_sensitive: bool = False) -> None:
        key = self.normalize_cache_key(query)
        if len(self.web_search_cache) >= MAX_CACHE_SIZE:
            oldest_key = min(self.web_search_cache, key=lambda k: self.web_search_cache[k]["timestamp"])
            del self.web_search_cache[oldest_key]
        now = datetime.now()
        ttl_seconds = self.time_sensitive_ttl_seconds if time_sensitive else self.general_ttl_seconds
        self.web_search_cache[key] = {
            "data": data,
            "timestamp": now,
            "expires_at": now + timedelta(seconds=ttl_seconds),
            "ttl_seconds": ttl_seconds,
            "time_sensitive": time_sensitive,
        }

    def get_deep_read(self, url: str) -> Optional[str]:
        item = self.deep_read_cache.get(url)
        if not item:
            return None
        ttl_seconds = int(item.get("ttl_seconds", 7200))
        if datetime.now() - item["timestamp"] > timedelta(seconds=ttl_seconds):
            del self.deep_read_cache[url]
            return None
        return item.get("text", "")

    def set_deep_read(self, url: str, text: str, ttl_seconds: int = 7200) -> None:
        self.deep_read_cache[url] = {
            "text": text,
            "timestamp": datetime.now(),
            "ttl_seconds": max(60, ttl_seconds),
        }
