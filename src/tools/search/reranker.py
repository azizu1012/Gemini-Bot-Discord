"""Scoring, deduplication, time decay penalty, and domain diversification."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List, Optional, Set

from src.core.config import logger
from src.tools.constants import SEARCH_TOPICS
from src.tools.helpers import DateParser, UrlUtils


class SearchReranker:
    """Scores and reranks search records, applies domain diversity and decay penalty."""

    def __init__(self, top_results_limit: int = 5, logger_override=None):
        self.top_results_limit = top_results_limit
        self.logger = logger_override or logger
        self._year_rx = re.compile(r'\b(19\d{2}|20\d{2})\b')

    def dedupe_records(self, records: List[Dict[str, str]]) -> List[Dict[str, str]]:
        seen_urls: Set[str] = set()
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
        score = 0.0
        snippet = (record.get("snippet") or "").strip().lower()
        title = (record.get("title") or "").strip().lower()
        domain = (record.get("domain") or "").lower()
        combined_text = f"{title} {snippet}"

        query_lower = query.lower().strip()
        query_terms = [t for t in query_lower.split() if len(t) > 2]

        title_overlap = sum(1 for t in query_terms if t in title)
        snippet_overlap = sum(1 for t in query_terms if t in snippet)
        score += title_overlap * 0.30
        score += snippet_overlap * 0.20

        if any(t in title for t in query_terms):
            score += 0.50

        freshness_bonus = 0.20
        pub_date = DateParser.extract_date(snippet + " " + title)
        if pub_date and is_time_sensitive:
            days_ago = (datetime.now() - pub_date).days
            if days_ago <= 1:
                score += 1.0
            elif days_ago <= 7:
                score += 0.6
            elif days_ago <= 30:
                score += 0.3

        freshness_bonus = -0.05
        if is_time_sensitive and not pub_date and not bool(self._year_rx.search(combined_text)):
            score -= 0.3

        topic_lower = topic.lower()
        topic_keywords = set(SEARCH_TOPICS.get(topic_lower, {}).get("keywords", []))
        if topic_keywords:
            topic_match = sum(1 for kw in topic_keywords if kw in combined_text)
            score += topic_match * 0.10

        snippet_len = len(snippet)
        if snippet_len < 20:
            score -= 0.30
        elif snippet_len < 40:
            score -= 0.10

        if domain:
            if any(d in domain for d in ["wiki", "wikipedia"]):
                score += 0.15
            if any(d in domain for d in [".gov", ".edu"]):
                score += 0.20

        score += freshness_bonus
        return round(max(-0.5, min(3.0, score)), 3)

    def is_quality_record(self, topic: str, query: str, record: Dict[str, str]) -> bool:
        snippet = (record.get("snippet") or "").strip().lower()
        title = (record.get("title") or "").strip().lower()
        domain = (record.get("domain") or "").lower()
        combined = f"{title} {snippet}"
        query_terms = [t for t in query.lower().strip().split() if len(t) > 2]

        if not query_terms:
            return len(snippet) >= 40

        if not any(t in combined for t in query_terms):
            return False
        if len(snippet) < 30:
            return False
        if any(d in domain for d in ["pinterest", "facebook", "instagram", "tiktok"]):
            return False
        return True

    def count_quality_sources(self, records: List[Dict[str, str]], topic: str, query: str = "") -> int:
        return sum(1 for r in records if self.is_quality_record(topic, query, r))

    def is_search_result_sufficient(
        self, records: List[Dict[str, str]], topic: str, query: str, required_sources: int, min_chars: int = 220
    ) -> bool:
        quality_count = self.count_quality_sources(records, topic, query)
        total_chars = sum(len(r.get("snippet", "")) + len(r.get("title", "")) for r in records)
        return quality_count >= required_sources and total_chars >= min_chars

    def dynamic_reputation_score(self, topic: str, query: str, record: Dict[str, str]) -> float:
        domain = (record.get("domain") or "").lower()

        high_reputation = {
            "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "nytimes.com",
            "wsj.com", "bloomberg.com", "npr.org", "theguardian.com",
            "nature.com", "science.org", "sciencedaily.com",
            "who.int", "cdc.gov", "nih.gov",
            "wikipedia.org", "britannica.com",
        }
        medium_reputation = {
            "forbes.com", "cnn.com", "washingtonpost.com", "economist.com",
            "techcrunch.com", "theverge.com", "wired.com", "arstechnica.com",
            "ign.com", "gamespot.com", "polygon.com",
            "imdb.com", "rottentomatoes.com",
            "github.com", "stackoverflow.com",
            "medium.com", "substack.com",
        }

        if domain in high_reputation:
            return 0.30
        if domain in medium_reputation:
            return 0.15

        if re.search(r'https?://(?!www\.)', domain):
            return -0.05
        return 0.0

    def domain_diversify_records(self, records: List[Dict[str, str]], limit: int, enforce_diversity: bool = True) -> List[Dict[str, str]]:
        if not enforce_diversity:
            return records[:limit]
        seen_org_domains: Set[str] = set()
        diversified = []
        for rec in records:
            domain = rec.get("domain", "")
            org_domain = UrlUtils.organization_domain(domain)
            if org_domain in seen_org_domains:
                continue
            seen_org_domains.add(org_domain)
            diversified.append(rec)
            if len(diversified) >= limit:
                break
        if len(diversified) < limit:
            for rec in records:
                if rec not in diversified:
                    diversified.append(rec)
                    if len(diversified) >= limit:
                        break
        return diversified[:limit]

    def calculate_time_decay_penalty(self, topic: str, pub_date: Optional[datetime], is_time_sensitive: bool) -> float:
        if not is_time_sensitive:
            return 0.0
        try:
            if not pub_date:
                return -0.6
            now = datetime.now()
            delta = now - pub_date
            D = delta.days + (delta.seconds / 86400.0)
            if D < 0:
                return 0.0
            grace_window = 7.0
            if topic == "gaming":
                grace_window = 21.0
            elif topic in {"finance", "tech"}:
                grace_window = 3.0
            elif topic in {"movies_tv", "anime_manga"}:
                grace_window = 14.0
            elif topic == "weather":
                grace_window = 1.0
            excess_days = max(0.0, D - grace_window)
            decay_penalty = -0.1 * excess_days
            return round(max(-1.5, decay_penalty), 3)
        except Exception as e:
            self.logger.warning(f"Error calculating time decay penalty: {e}")
            return 0.0

    def lightweight_rerank(self, topic: str, query: str, records: List[Dict[str, str]], is_time_sensitive: bool = False) -> List[Dict[str, str]]:
        scored = []
        for rec in records:
            base_score = float(rec.get("score", 0))
            rep_score = self.dynamic_reputation_score(topic, query, rec)
            pub_date = DateParser.extract_date(
                (rec.get("snippet") or "") + " " + (rec.get("title") or "")
            )
            decay = self.calculate_time_decay_penalty(topic, pub_date, is_time_sensitive)
            total = base_score + rep_score + decay
            scored.append((total, rec))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [rec for _, rec in scored]

    def format_final_search_result(self, topic: str, query: str, ranked_records: List[Dict[str, str]], required_sources: int) -> str:
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
