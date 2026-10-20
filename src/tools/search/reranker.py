"""SearchReranker composed of domain ranking, consensus scoring, and authority mixins."""

from __future__ import annotations

from typing import Dict, List, Optional
from src.core.config import logger
from src.tools.search.mixins import SearchRankingMixin


class SearchReranker(SearchRankingMixin):
    """OOP Reranker managing scoring, consensus boost, time decay, and domain diversity."""

    def __init__(self, top_results_limit: int = 5, logger_override=None):
        self.top_results_limit = top_results_limit
        self.logger = logger_override or logger

    def dedupe_records(self, records: List[Dict[str, str]]) -> List[Dict[str, str]]:
        seen_urls = set()
        deduped = []
        for rec in records:
            url = (rec.get("normalized_url") or rec.get("url") or "").strip().lower().rstrip("/")
            if not url:
                deduped.append(rec)
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)
            deduped.append(rec)
        return deduped

    def score_record(self, topic: str, query: str, record: Dict[str, str], is_time_sensitive: bool = False) -> float:
        return self._score_record(topic, query, record, is_time_sensitive=is_time_sensitive)

    def is_quality_record(self, topic: str, query: str, record: Dict[str, str]) -> bool:
        return self._is_quality_record(topic, query, record)

    def count_quality_sources(self, records: List[Dict[str, str]], topic: str, query: str = "") -> int:
        return self._count_quality_sources(records, topic, query=query)

    def is_search_result_sufficient(
        self, records: List[Dict[str, str]], topic: str, query: str, required_sources: int, min_chars: int = 220
    ) -> bool:
        return self._is_search_result_sufficient(records, topic, query, required_sources, min_chars=min_chars)

    def dynamic_reputation_score(self, topic: str, query: str, record: Dict[str, str]) -> float:
        return self._dynamic_reputation_score(topic, query, record)

    def domain_diversify_records(self, records: List[Dict[str, str]], limit: int, enforce_diversity: bool = True) -> List[Dict[str, str]]:
        return self._domain_diversify_records(records, limit, enforce_diversity=enforce_diversity)

    def calculate_time_decay_penalty(self, topic: str, pub_date, is_time_sensitive: bool) -> float:
        return self._calculate_time_decay_penalty(topic, pub_date, is_time_sensitive)

    def lightweight_rerank(
        self, topic: str, query: str, records: List[Dict[str, str]], is_time_sensitive: bool = False
    ) -> List[Dict[str, str]]:
        return self._lightweight_rerank(topic, query, records)

    def format_final_search_result(
        self, topic: str, query: str, ranked_records: List[Dict[str, str]], required_sources: int
    ) -> str:
        top = self.domain_diversify_records(ranked_records, self.top_results_limit, enforce_diversity=True)
        if not top:
            return f"### 🔍 [Chủ đề: {topic.upper()}] Kết quả cho '{query}':\n(Không có kết quả phù hợp)"

        parts = [f"### 🔍 [Chủ đề: {topic.upper()}] Kết quả cho '{query}':"]
        for rec in top:
            title = (rec.get("title") or "Không có tiêu đề").strip()
            snippet = (rec.get("snippet") or "").strip()
            url = (rec.get("url") or "#").strip()
            score_val = rec.get("score", "0")
            lines = [f"- **{title}** (Điểm: {score_val})"]
            if snippet:
                lines.append(f"  > {snippet}")
            lines.append(f"  🔗 {url}")
            evidence = rec.get("evidence", "")
            if evidence:
                deep_line = evidence[:600].replace("\n", " ")
                lines.append(f"  📖 {deep_line}")
            parts.append("\n".join(lines))

        quality_count = self.count_quality_sources(top, topic, query)
        parts.append("")
        parts.append(f"Required quality sources: {required_sources} | Quality sources found: {quality_count}")
        if quality_count < required_sources:
            parts.append("⚠️ Chưa đủ nguồn chất lượng theo ngưỡng cho truy vấn này; nên xem kết quả như thông tin tham khảo.")

        return "\n".join(parts)
