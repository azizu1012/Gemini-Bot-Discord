"""Query planning, temporal analysis, and multi-intent decomposition."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from src.tools.search.mixins.ranking import SearchRankingMixin


class QueryPlanner(SearchRankingMixin):
    """Analyzes search queries, detects time sensitivity, and decomposes multi-intents."""

    def __init__(
        self,
        intent_batch_size: int = 3,
        min_quality_sources: int = 1,
        time_sensitive_min_quality_sources: int = 2,
    ):
        self.intent_batch_size = intent_batch_size
        self.min_quality_sources = min_quality_sources
        self.time_sensitive_min_quality_sources = time_sensitive_min_quality_sources

        self._time_sensitive_rx = re.compile(
            r'\b(?:hôm nay|today|hôm qua|yesterday|vừa qua|just released?|just now|mới ra mắt|'
            r'tin mới|mới nhất|latest|breaking|cập nhật|update|live|trực tiếp|'
            r'mùa này|tuần này|tháng này|năm nay|this week|this month|this year|gần đây|recently|'
            r'vừa xong|mới đây|hôm trước|hôm kia|hiện tại|now|thời sự|thời sự hôm nay|'
            r'thông báo mới|lịch thi đấu|kết quả|giá vàng|tỷ giá|chứng khoán|thời tiết|'
            r'tin tức|news|sự kiện|event|vừa xảy ra)\b',
            re.IGNORECASE,
        )
        self._year_rx = re.compile(r'\b(19\d{2}|20\d{2})\b')
        self._time_sensitive_suffixes = [
            "mới nhất", "latest", "update", "cập nhật", "hôm nay", "today",
            "tuần này", "tháng này", "năm nay", "vừa qua", "mới ra mắt",
            "tin tức", "news", "sự kiện", "event",
        ]

    def is_time_sensitive_query(self, query: str) -> bool:
        if not query:
            return False
        lowered = query.lower().strip()
        if self._time_sensitive_rx.search(lowered):
            return True
        for suffix in self._time_sensitive_suffixes:
            if suffix in lowered:
                return True
        return False

    def contains_year(self, query: str) -> bool:
        return bool(self._year_rx.search(query or ""))

    def time_sensitive_timelimit(self, query: str) -> Optional[str]:
        lowered = query.lower()
        if any(w in lowered for w in ["today", "hôm nay"]):
            return "d"
        if any(w in lowered for w in ["yesterday", "hôm qua"]):
            return "d"
        if any(w in lowered for w in ["this week", "tuần này", "week", "tuần"]):
            return "w"
        if any(w in lowered for w in ["this month", "tháng này", "month", "tháng"]):
            return "m"
        if any(w in lowered for w in ["this year", "năm nay", "year", "năm"]):
            return "y"
        return None

    def transform_temporal_query(self, query: str) -> Tuple[str, Optional[str]]:
        lowered = (query or "").strip().lower()
        now = datetime.now()
        if re.search(r'\b(?:hôm nay|today)\b', lowered):
            return f"{query} {now.strftime('%d %B %Y')}", self.time_sensitive_timelimit(query)
        if re.search(r'\b(?:hôm qua|yesterday)\b', lowered):
            yesterday = now - timedelta(days=1)
            return f"{query} {yesterday.strftime('%d %B %Y')}", self.time_sensitive_timelimit(query)
        if re.search(r'\b(?:tháng này|this month)\b', lowered):
            return f"{query} {now.strftime('%B %Y')}", self.time_sensitive_timelimit(query)
        if re.search(r'\b(?:năm nay|this year)\b', lowered):
            return f"{query} {now.strftime('%Y')}", self.time_sensitive_timelimit(query)
        return query, self.time_sensitive_timelimit(query)

    def required_quality_sources(self, query: str) -> int:
        return self.time_sensitive_min_quality_sources if self.is_time_sensitive_query(query) else self.min_quality_sources

    def split_multi_intents(self, query: str) -> List[str]:
        base = (query or "").strip()
        if not base:
            return []
        parts = re.split(r"\s*(?:\n+|;|\?|\.(?=\s)|,)\s*", base, flags=re.IGNORECASE)
        intents = [p.strip() for p in parts if len(p.strip()) > 2]
        if not intents:
            return [base]
        if len(intents) == 1:
            return intents
        if any(len(intent) < 20 for intent in intents):
            return [base]
        return intents[: self.intent_batch_size]

    def determine_batch_size(self, intents: List[str]) -> int:
        if not intents:
            return 2
        batch = max(2, min(self.intent_batch_size, len(intents)))
        if all(self.is_time_sensitive_query(i) for i in intents):
            batch = min(batch, 1)
        return batch

    def classify_topic(self, query: str) -> str:
        """Classify query topic using multi-lingual script and keyword catalogs."""
        return self._classify_topic(query)
