"""Ranking, scoring, domain authority, consensus verification, and time-decay algorithms."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from src.tools.helpers import UrlUtils
from src.tools.search.languages.registry import detect_query_languages, iter_language_topic_keywords
from src.tools.search.mixins.text import SearchTextMixin


class SearchRankingMixin(SearchTextMixin):
    """Provides topic classification, coupled freshness, authority ranking, and cross-source consensus."""

    def _classify_topic(self, query: str) -> str:
        raw_query = (query or "").strip().lower()

        # 1. CJK and other non-Latin scripts check
        script_topic_scores: Dict[str, int] = {}
        for topic, keywords in iter_language_topic_keywords(detect_query_languages(raw_query)):
            score = sum(1 for keyword in keywords if keyword.lower() in raw_query)
            if score:
                script_topic_scores[topic] = script_topic_scores.get(topic, 0) + score

        if script_topic_scores:
            return max(script_topic_scores, key=script_topic_scores.get)

        # 2. Latin / Vietnamese accent-insensitive matching
        tokens = self._normalize_text_for_match(query).split()
        generic_tokens = {
            self._normalize_text_for_match(token)
            for token in ("update", "news", "latest", "new", "information", "tin tức", "thông tin")
        }

        best_topic = "general"
        best_score = 0
        for topic, data in self.SEARCH_TOPICS.items():
            if topic == "general":
                continue

            score = 0
            for keyword in data["keywords"]:
                kw = self._normalize_text_for_match(keyword)
                if not kw or kw in generic_tokens:
                    continue
                if self._contains_phrase(tokens, kw):
                    score += 1

            if score > best_score:
                best_score = score
                best_topic = topic

        return best_topic

    def _detect_query_profile(self, query: str) -> str:
        q = (query or "").lower()
        if re.search(r"\b(v\d|\d+\.\d+|\d{4}-\d{2}-\d{2}|benchmark|spec|specification|protocol|rfc|changelog|release notes|model card)\b", q):
            return "tech_spec"
        if any(w in q for w in ["giá", "price", "hôm nay", "today", "vừa qua", "mới nhất", "breaking", "bão", "weather", "ron95", "xăng"]):
            return "realtime_news"
        if any(w in q for w in ["how to", "làm sao", "cách dùng", "example", "syntax", "error", "exception", "cú pháp", "fix bug"]):
            return "code_howto"
        return "general"

    def _domain_authority_score(self, domain: str, profile: str) -> float:
        d = (domain or "").strip().lower()
        if not d:
            return 0.0

        # Tier 4 SEO / Aggregator Spam penalty
        if d in self.TIER4_SPAM_SEO_DOMAINS or any(spam in d for spam in ["tokencalc", "whichllm", "projedefteri", "hackaigc", "shattered", "prompeteer", "lorka.ai", "distk.in"]):
            return -3.0

        # Tier 1 Primary Authority bonus
        is_tier1 = d in self.TIER1_AUTHORITY_DOMAINS or any(d.startswith(pat) or pat in d for pat in self.TIER1_AUTHORITY_PATTERNS)
        if is_tier1:
            return 2.5 if profile in ("tech_spec", "code_howto") else 2.0

        # Tier 2 Reputable Media
        if d in self.TIER2_REPUTABLE_DOMAINS:
            return 1.0

        return 0.0

    def _information_density_score(self, text: str) -> float:
        """Measure technical information density (code, tables, numbers, specs)."""
        if not text:
            return 0.0
        score = 0.0
        if "```" in text or re.search(r"\b(def |class |import |async def |curl |pip install )\b", text):
            score += 0.8
        if re.search(r"\|.+\|.+\|", text):
            score += 0.8
        digits = sum(1 for ch in text if ch.isdigit())
        if digits >= 8:
            score += 0.4
        return score

    def _calculate_coupled_freshness(self, query: str, text: str, pub_date: Optional[datetime], is_time_sensitive: bool) -> float:
        """Calculate freshness score coupled with query terms in the same local sentence window."""
        if not text:
            return 0.0

        q_tokens = [t.lower() for t in re.findall(r"\w+", query) if len(t) > 2]
        if not q_tokens:
            return 0.0

        current_year = str(datetime.now().year)
        prev_year = str(datetime.now().year - 1)
        freshness_markers = ["mới nhất", "cập nhật", "hôm nay", "vừa qua", "mới đây", "ngày trước", "giờ trước", "latest", "update", "yesterday", "ago"]

        sentences = re.split(r"[.\n!?]+", text.lower())
        best_coupled_score = 0.0

        for s in sentences:
            s_clean = s.strip()
            if not s_clean:
                continue
            hits = sum(1 for t in q_tokens if t in s_clean)
            if hits < 2 and len(q_tokens) >= 2:
                continue
            if hits < 1:
                continue

            has_curr_year = current_year in s_clean
            has_prev_year = prev_year in s_clean
            has_fresh_marker = any(m in s_clean for m in freshness_markers)

            s_boost = 0.0
            if has_curr_year:
                s_boost += 1.2
            elif has_prev_year:
                s_boost += 0.5

            if has_fresh_marker:
                s_boost += 0.4

            match_ratio = hits / len(q_tokens)
            coupled_val = s_boost * match_ratio
            if coupled_val > best_coupled_score:
                best_coupled_score = coupled_val

        if pub_date:
            pub_naive = pub_date.replace(tzinfo=None) if getattr(pub_date, "tzinfo", None) is not None else pub_date
            days = max(0.0, (datetime.now() - pub_naive).total_seconds() / 86400.0)
            if days <= 7:
                best_coupled_score += 1.0
            elif days <= 30:
                best_coupled_score += 0.6
            elif days <= 90:
                best_coupled_score += 0.3

        return round(best_coupled_score, 3)

    def _calculate_time_decay_penalty(self, topic: str, pub_date: Optional[datetime], is_time_sensitive: bool) -> float:
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
        except Exception:
            return 0.0

    def _dynamic_reputation_score(self, topic: str, query: str, record: Dict[str, str]) -> float:
        domain = (record.get("domain") or "").strip().lower()
        title = record.get("title") or ""
        snippet = record.get("snippet") or ""
        evidence = record.get("evidence") or ""

        score = 0.0
        score += self._query_coverage_score(query, f"{title} {snippet}")
        if evidence:
            score += 0.75 * self._query_coverage_score(query, f"{title} {evidence}")

        overlap_snippet = self._query_overlap_count(query, f"{title} {snippet}")
        if overlap_snippet >= 4:
            score += 1.0
        elif overlap_snippet == 3:
            score += 0.75
        elif overlap_snippet == 2:
            score += 0.5
        elif overlap_snippet == 1:
            score += 0.2

        if evidence:
            overlap_evidence = self._query_overlap_count(query, f"{title} {evidence}")
            if overlap_evidence >= 3:
                score += 0.75
            elif overlap_evidence == 2:
                score += 0.45
            elif overlap_evidence == 1:
                score += 0.2

        snippet_len = len(snippet.strip())
        if snippet_len >= 80:
            score += 0.3
        if snippet_len >= 140:
            score += 0.25

        evidence_len = len(evidence.strip())
        if evidence_len >= 180:
            score += 0.75

        if any(tag in domain for tag in [".gov", ".edu", ".ac.", ".int", "gov.vn", "edu.vn"]):
            score += 0.35

        title_match = any(token for token in re.findall(r"\w+", query.lower()) if len(token) > 3 and token in title.lower())
        if title_match:
            score += 0.35

        return score

    def _score_record(self, topic: str, query: str, record: Dict[str, str], is_time_sensitive: bool = False) -> float:
        domain = (record.get("domain") or "").strip().lower()
        if domain in self.TIER4_SPAM_SEO_DOMAINS or any(spam in domain for spam in self.TIER4_SPAM_SEO_DOMAINS):
            return -1.0

        profile = self._detect_query_profile(query)
        title = (record.get("title") or "").lower()
        snippet = (record.get("snippet") or "").lower()
        evidence = (record.get("evidence") or "").lower()
        full_text = f"{title} {snippet} {evidence}"

        score = self._dynamic_reputation_score(topic, query, record)
        score += self._domain_authority_score(domain, profile)
        score += self._information_density_score(full_text)

        pub_date = record.get("published_date") or self._extract_date(snippet[:40]) or self._extract_date(title[:40])
        score += self._calculate_coupled_freshness(query, full_text, pub_date, is_time_sensitive)

        if any(token for token in re.findall(r"\w+", query.lower()) if len(token) > 3 and token in f"{title} {snippet}"):
            score += 1.1

        provider = (record.get("provider") or "").lower()
        if provider == "duckduckgo":
            score += 0.4

        if len(snippet) > 120:
            score += 0.35

        return round(score, 3)

    def _lightweight_rerank(self, topic: str, query: str, records: List[Dict[str, str]]) -> List[Dict[str, str]]:
        if not records:
            return []

        # 1. Extract tokens per record for cross-source consensus
        record_tokens = []
        for rec in records:
            text = f"{rec.get('title', '')} {rec.get('snippet', '')}".lower()
            tokens = set(self._normalize_query_tokens(text))
            record_tokens.append(tokens)

        # 2. Consensus cross-scoring: count how many independent records agree on facts
        consensus_scores = [0.0] * len(records)
        for i in range(len(records)):
            for j in range(len(records)):
                if i != j:
                    overlap = len(record_tokens[i].intersection(record_tokens[j]))
                    if overlap > 3:
                        consensus_scores[i] += min(1.0, overlap * 0.1)

        domain_counts: Dict[str, int] = {}
        reranked = []

        for idx, rec in enumerate(records):
            base_score = float(rec.get("score", "0"))
            c_boost = min(1.5, consensus_scores[idx] * 0.2)

            domain = (rec.get("domain") or "").strip().lower()
            org_domain = self._organization_domain(domain) or domain
            d_penalty = 0.0
            if org_domain:
                domain_counts[org_domain] = domain_counts.get(org_domain, 0) + 1
                if domain_counts[org_domain] > 1:
                    d_penalty = -0.5 * (domain_counts[org_domain] - 1)

            final_score = base_score + c_boost + d_penalty
            rec["score"] = str(round(final_score, 3))
            reranked.append(rec)

        reranked.sort(key=lambda r: float(r.get("score", 0)), reverse=True)
        return reranked

    def _domain_diversify_records(self, records: List[Dict[str, str]], limit: int, enforce_diversity: bool = True) -> List[Dict[str, str]]:
        if not enforce_diversity:
            return records[:limit]
        seen_org_domains: Set[str] = set()
        diversified = []
        for rec in records:
            domain = rec.get("domain", "")
            org_domain = self._organization_domain(domain)
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

    def _is_quality_record(self, topic: str, query: str, record: Dict[str, str]) -> bool:
        domain = (record.get("domain") or "").strip().lower()
        if domain in self.TIER4_SPAM_SEO_DOMAINS:
            return False

        dynamic_score = self._dynamic_reputation_score(topic, query, record)
        threshold = 2.25
        if len((record.get("evidence") or "").strip()) >= 160:
            threshold -= 0.2
        if len((record.get("snippet") or "").strip()) >= 120:
            threshold -= 0.1

        return dynamic_score >= threshold

    def _count_quality_sources(self, records: List[Dict[str, str]], topic: str, query: str = "") -> int:
        return sum(1 for r in records if self._is_quality_record(topic, query, r))

    def _is_search_result_sufficient(
        self, records: List[Dict[str, str]], topic: str, query: str, required_sources: int, min_chars: int = 220
    ) -> bool:
        quality_count = self._count_quality_sources(records, topic, query)
        total_chars = sum(len(r.get("snippet", "")) + len(r.get("title", "")) for r in records)
        return quality_count >= required_sources and total_chars >= min_chars
