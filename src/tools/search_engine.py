import asyncio
import json
import os
import re
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Set, Tuple

import requests
from bs4 import BeautifulSoup
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

from src.core.config import logger, SERPAPI_API_KEY, TAVILY_API_KEY, EXA_API_KEY
from src.tools.helpers import (
    HtmlParser,
    DateParser,
    TextProcessor,
    UrlUtils,
)
from src.tools.constants import SEARCH_TOPICS, MAX_CACHE_SIZE


class SearchEngine:
    """Full search pipeline: providers, ranking, scoring, dedup, evidence, topic classification."""

    def __init__(
        self,
        logger_override=None,
        search_web_mode: str = "grounded",
        search_grounded_top_links: int = 3,
        search_top_results_limit: int = 5,
        deep_read_top_links: int = 2,
        deep_read_max_chars: int = 1800,
        search_semantic_cache_enabled: bool = True,
        search_general_cache_ttl_seconds: int = 21600,
        search_time_sensitive_cache_ttl_seconds: int = 1800,
        search_failed_query_cooldown_seconds: int = 15,
        search_empty_evidence_cache_ttl_seconds: int = 600,
        fallback_provider_limit: int = 2,
        intent_batch_size: int = 3,
        min_quality_sources: int = 1,
        time_sensitive_min_quality_sources: int = 2,
        exa_use_autoprompt: bool = False,
        google_search_streams: int = 1,
    ):
        self.logger = logger_override or logger
        self.search_web_mode = search_web_mode
        self.search_grounded_top_links = search_grounded_top_links
        self.search_top_results_limit = search_top_results_limit
        self.deep_read_top_links = deep_read_top_links
        self.deep_read_max_chars = deep_read_max_chars
        self.search_semantic_cache_enabled = search_semantic_cache_enabled
        self.search_general_cache_ttl_seconds = search_general_cache_ttl_seconds
        self.search_time_sensitive_cache_ttl_seconds = search_time_sensitive_cache_ttl_seconds
        self.search_failed_query_cooldown_seconds = search_failed_query_cooldown_seconds
        self.search_empty_evidence_cache_ttl_seconds = search_empty_evidence_cache_ttl_seconds
        self.fallback_provider_limit = fallback_provider_limit
        self.intent_batch_size = intent_batch_size
        self.min_quality_sources = min_quality_sources
        self.time_sensitive_min_quality_sources = time_sensitive_min_quality_sources
        self.exa_use_autoprompt = exa_use_autoprompt
        self.google_search_streams = google_search_streams

        self.web_search_cache: Dict[str, Any] = {}
        self.deep_read_cache: Dict[str, Any] = {}
        self.cache_lock = asyncio.Lock()
        self.search_lock = asyncio.Lock()
        self.inflight_search_tasks: Dict[str, asyncio.Task] = {}
        self.failed_search_cooldowns: Dict[str, float] = {}

        self._time_sensitive_rx = re.compile(
            r'\b(?:hôm nay|today|hôm qua|yesterday|vừa qua|just released?|just now|mới ra mắt|'
            r'latest|mới nhất|hiện tại|current|now|cập nhật|có mặt|đã ra|vừa|mới|gần đây|'
            r'recent(?:ly)?|breaking|just|this (?:week|month|year)|today|tonight|now)\b',
            re.IGNORECASE
        )
        self._year_rx = re.compile(r'\b(20\d{2})\b')
        self._time_sensitive_suffixes = [
            "latest", "mới nhất", "hôm nay", "today", "this week", "this month",
            "current", "hiện tại", "just", "breaking", "update",
        ]

    # ── Cache ──────────────────────────────────────────────

    def _normalize_search_cache_key(self, query: str) -> str:
        normalized = (query or "").strip().lower()
        normalized = re.sub(r"\s+", " ", normalized)
        normalized = re.sub(r"\s*\|\s*", "|", normalized)
        mode = "general"
        payload = normalized
        if "|" in normalized:
            maybe_mode, maybe_payload = normalized.split("|", 1)
            mode = maybe_mode or "general"
            payload = maybe_payload or ""
        if self.search_semantic_cache_enabled:
            canonical_payload = TextProcessor.canonicalize_search_query(payload)
            if canonical_payload:
                payload = canonical_payload
        return f"{mode}|{payload}"

    def get_web_search_cache(self, query: str):
        key = self._normalize_search_cache_key(query)
        if key in self.web_search_cache:
            cached_item = self.web_search_cache[key]
            expires_at = cached_item.get("expires_at")
            if isinstance(expires_at, datetime):
                if datetime.now() <= expires_at:
                    return cached_item.get("data")
                del self.web_search_cache[key]
                return None
            if datetime.now() - cached_item['timestamp'] < timedelta(hours=6):
                return cached_item['data']
            del self.web_search_cache[key]
        return None

    def set_web_search_cache(self, query: str, data: str, time_sensitive: bool = False):
        key = self._normalize_search_cache_key(query)
        if len(self.web_search_cache) >= MAX_CACHE_SIZE:
            oldest_key = min(self.web_search_cache, key=lambda k: self.web_search_cache[k]['timestamp'])
            del self.web_search_cache[oldest_key]
        now = datetime.now()
        ttl_seconds = self.search_time_sensitive_cache_ttl_seconds if time_sensitive else self.search_general_cache_ttl_seconds
        self.web_search_cache[key] = {
            'data': data,
            'timestamp': now,
            'expires_at': now + timedelta(seconds=ttl_seconds),
            'ttl_seconds': ttl_seconds,
            'time_sensitive': time_sensitive,
        }

    def _get_deep_read_cache(self, url: str) -> Optional[str]:
        item = self.deep_read_cache.get(url)
        if not item:
            return None
        ttl_seconds = int(item.get("ttl_seconds", 7200))
        if datetime.now() - item["timestamp"] > timedelta(seconds=ttl_seconds):
            del self.deep_read_cache[url]
            return None
        return item.get("text", "")

    def _set_deep_read_cache(self, url: str, text: str, ttl_seconds: int = 7200):
        self.deep_read_cache[url] = {
            "text": text,
            "timestamp": datetime.now(),
            "ttl_seconds": max(60, ttl_seconds),
        }

    # ── Query utilities ────────────────────────────────────

    def _is_time_sensitive_query(self, query: str) -> bool:
        if not query:
            return False
        lowered = query.lower().strip()
        if self._time_sensitive_rx.search(lowered):
            return True
        for suffix in self._time_sensitive_suffixes:
            if suffix in lowered:
                return True
        return False

    def _contains_year(self, query: str) -> bool:
        return bool(self._year_rx.search(query or ""))

    def _time_sensitive_timelimit(self, query: str) -> Optional[str]:
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

    def _transform_temporal_query(self, query: str) -> Tuple[str, Optional[str]]:
        lowered = (query or "").strip().lower()
        now = datetime.now()
        if re.search(r'\b(?:hôm nay|today)\b', lowered):
            return f"{query} {now.strftime('%d %B %Y')}", self._time_sensitive_timelimit(query)
        if re.search(r'\b(?:hôm qua|yesterday)\b', lowered):
            yesterday = now - timedelta(days=1)
            return f"{query} {yesterday.strftime('%d %B %Y')}", self._time_sensitive_timelimit(query)
        if re.search(r'\b(?:tháng này|this month)\b', lowered):
            return f"{query} {now.strftime('%B %Y')}", self._time_sensitive_timelimit(query)
        if re.search(r'\b(?:năm nay|this year)\b', lowered):
            return f"{query} {now.strftime('%Y')}", self._time_sensitive_timelimit(query)
        return query, self._time_sensitive_timelimit(query)

    def _required_quality_sources(self, query: str) -> int:
        return self.time_sensitive_min_quality_sources if self._is_time_sensitive_query(query) else self.min_quality_sources

    def _split_multi_intents(self, query: str) -> List[str]:
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
        return intents[:self.intent_batch_size]

    def _determine_batch_size(self, intents: List[str]) -> int:
        if not intents:
            return 2
        batch = max(2, min(self.intent_batch_size, len(intents)))
        if all(self._is_time_sensitive_query(i) for i in intents):
            batch = min(batch, 1)
        return batch

    def _query_contains_suffix_intent(self, query: str, suffix: str) -> bool:
        if not query or not suffix:
            return False
        lowered = query.lower().strip()
        lower_suffix = suffix.lower().strip()
        if lower_suffix in lowered:
            return True
        for prefix in ["tìm", "search", "tra", "thông tin"]:
            combined = f"{prefix} {lower_suffix}".strip()
            if combined in lowered:
                return True
        return False

    def _build_secondary_query(self, q1: str, suffixes: List[str]) -> str:
        if not suffixes:
            return q1
        chosen_suffix = suffixes[0]
        return f"{q1} {chosen_suffix}".strip()

    # ── Topic ──────────────────────────────────────────────

    def _classify_topic(self, query: str) -> str:
        lowered = (query or "").strip().lower()
        for topic, config in SEARCH_TOPICS.items():
            if topic == "general":
                continue
            for keyword in config.get("keywords", []):
                if keyword in lowered:
                    return topic
        return "general"

    # ── Providers ──────────────────────────────────────────

    async def _search_duckduckgo_records(
        self, query: str, index: int = 0,
        timelimit: Optional[str] = None,
        query_effective: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        if DDGS is None:
            self.logger.warning("DuckDuckGo search library is unavailable.")
            return []

        start_ts = datetime.now().timestamp()
        try:
            def _do_search():
                with DDGS() as ddgs:
                    if timelimit:
                        return list(ddgs.text(query, max_results=5, timelimit=timelimit))
                    return list(ddgs.text(query, max_results=5))

            results = await asyncio.to_thread(_do_search)
            items: List[Dict[str, str]] = []
            for item in results[:5]:
                url_raw = item.get("href") or item.get("url") or ""
                normalized_url = UrlUtils.normalize_url(url_raw)
                if not normalized_url or UrlUtils.is_blocked_domain(normalized_url):
                    continue
                snippet = (item.get("body") or "").strip()
                items.append({
                    "provider": "duckduckgo",
                    "title": item.get("title") or "Không có tiêu đề",
                    "snippet": snippet,
                    "url": normalized_url,
                    "normalized_url": normalized_url,
                    "domain": UrlUtils.normalize_domain(normalized_url),
                    "query": query,
                    "query_effective": query_effective or query,
                    "query_index": str(index),
                })
            return items
        except Exception as e:
            self.logger.warning(f"[Search Primary] Query: '{query}' | Error: {e}")
            return []

    async def _search_serpapi_records(self, query: str) -> List[Dict[str, str]]:
        if not SERPAPI_API_KEY:
            return []
        import serpapi
        start_ts = datetime.now().timestamp()
        try:
            def _search():
                client = serpapi.Client(api_key=SERPAPI_API_KEY)
                return client.search({
                    "q": query,
                    "engine": "google",
                    "num": 5,
                    "hl": "vi",
                })
            raw = await asyncio.to_thread(_search)
            results = raw.get("organic_results", [])[:5]
            items = []
            for item in results:
                url = UrlUtils.normalize_url(item.get("link") or "")
                if not url or UrlUtils.is_blocked_domain(url):
                    continue
                items.append({
                    "provider": "serpapi",
                    "title": item.get("title") or "Không có tiêu đề",
                    "snippet": (item.get("snippet") or "").strip(),
                    "url": url,
                    "normalized_url": url,
                    "domain": UrlUtils.normalize_domain(url),
                    "query": query,
                    "query_effective": query,
                    "query_index": "0",
                })
            return items
        except Exception as e:
            self.logger.warning(f"SerpAPI search error: {e}")
            return []

    async def _search_tavily_records(self, query: str) -> List[Dict[str, str]]:
        if not TAVILY_API_KEY:
            return []
        from tavily import TavilyClient
        start_ts = datetime.now().timestamp()
        try:
            def _search():
                client = TavilyClient(api_key=TAVILY_API_KEY)
                return client.search(query=query, max_results=5)
            raw = await asyncio.to_thread(_search)
            results = raw.get("results", [])[:5]
            items = []
            for item in results:
                url = UrlUtils.normalize_url(item.get("url") or "")
                if not url or UrlUtils.is_blocked_domain(url):
                    continue
                items.append({
                    "provider": "tavily",
                    "title": item.get("title") or "Không có tiêu đề",
                    "snippet": (item.get("content") or "").strip(),
                    "url": url,
                    "normalized_url": url,
                    "domain": UrlUtils.normalize_domain(url),
                    "query": query,
                    "query_effective": query,
                    "query_index": "0",
                })
            return items
        except Exception as e:
            self.logger.warning(f"Tavily search error: {e}")
            return []

    async def _search_exa_records(self, query: str) -> List[Dict[str, str]]:
        if not EXA_API_KEY:
            return []
        import exa_py
        start_ts = datetime.now().timestamp()
        params = {
            "query": query,
            "num_results": 5,
            "type": "neural"
        }
        try:
            exa = exa_py.Exa(api_key=EXA_API_KEY)
            results = await asyncio.to_thread(exa.search, **params)
            if not results.results:
                return []
            items = []
            for item in results.results[:5]:
                url = UrlUtils.normalize_url(item.url or "")
                if not url or UrlUtils.is_blocked_domain(url):
                    continue
                items.append({
                    "provider": "exa",
                    "title": item.title or "Không có tiêu đề",
                    "snippet": "",
                    "url": url,
                    "normalized_url": url,
                    "domain": UrlUtils.normalize_domain(url),
                    "query": query,
                    "query_effective": query,
                    "query_index": "0",
                })
            return items
        except TypeError:
            try:
                exa = exa_py.Exa(api_key=EXA_API_KEY)
                results = await asyncio.to_thread(exa.search, **params)
                if not results.results:
                    return []
                items = []
                for item in results.results[:5]:
                    url = UrlUtils.normalize_url(item.url or "")
                    if not url or UrlUtils.is_blocked_domain(url):
                        continue
                    items.append({
                        "provider": "exa",
                        "title": item.title or "Không có tiêu đề",
                        "snippet": "",
                        "url": url,
                        "normalized_url": url,
                        "domain": UrlUtils.normalize_domain(url),
                        "query": query,
                        "query_effective": query,
                        "query_index": "0",
                    })
                return items
            except Exception as e:
                self.logger.warning(f"Exa search error: {e}")
                return []
        except Exception as e:
            self.logger.warning(f"Exa search error: {e}")
            return []

    async def _run_fallback_search_records(self, query: str) -> List[Dict[str, str]]:
        provider_funcs: List[Tuple[str, Any]] = []
        if SERPAPI_API_KEY:
            provider_funcs.append(("serpapi", self._search_serpapi_records))
        if TAVILY_API_KEY:
            provider_funcs.append(("tavily", self._search_tavily_records))
        if EXA_API_KEY:
            provider_funcs.append(("exa", self._search_exa_records))

        if not provider_funcs:
            return []

        selected = provider_funcs[:self.fallback_provider_limit]
        names = [name for name, _ in selected]
        self.logger.info(f"Running fallback providers: {', '.join(names)}")

        tasks = [func(query) for _, func in selected]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        merged: List[Dict[str, str]] = []
        success_count = 0

        for (name, _), result in zip(selected, results):
            if isinstance(result, BaseException):
                self.logger.warning(f"Fallback {name} error: {result}")
                continue
            if result:
                success_count += 1
                merged.extend(result)
                self.logger.info(f"Fallback {name} success for query '{query[:60]}'")
            else:
                self.logger.warning(f"Fallback {name} empty.")

        self.logger.info(f"AB_METRIC search_fallback providers={len(selected)} success={1 if success_count else 0} results={success_count}")
        return merged

    # ── Evidence (Deep Read) ─────────────────────────────

    async def _fetch_page_evidence(self, url: str) -> str:
        cached = self._get_deep_read_cache(url)
        if cached is not None:
            return cached

        def _fetch_once(timeout_sec: float) -> str:
            headers = {
                "User-Agent": "Mozilla/5.0 (ChadGibitiBot/1.0)",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.8,vi;q=0.7",
            }
            response = requests.get(url, headers=headers, timeout=timeout_sec)
            if response.status_code != 200 or not response.text:
                return ""
            if not response.encoding:
                response.encoding = response.apparent_encoding or "utf-8"
            parsed = HtmlParser.extract_main_text(response.text)
            if len(parsed) < 120:
                return ""
            return parsed[:self.deep_read_max_chars].strip()

        for attempt in range(2):
            timeout_sec = 3.0 if attempt == 0 else 5.0
            try:
                text = await asyncio.to_thread(_fetch_once, timeout_sec)
                if text:
                    self._set_deep_read_cache(url, text, ttl_seconds=7200)
                    return text
            except Exception:
                continue

        self._set_deep_read_cache(url, "", ttl_seconds=self.search_empty_evidence_cache_ttl_seconds)
        return ""

    # ── Dedup & Quality ─────────────────────────────────

    def _dedupe_records(self, records: List[Dict[str, str]]) -> List[Dict[str, str]]:
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

    def _count_quality_sources(self, records: List[Dict[str, str]], topic: str, query: str = "") -> int:
        return sum(1 for r in records if self._is_quality_record(topic, query, r))

    def _is_search_result_sufficient(self, records: List[Dict[str, str]], topic: str, query: str, required_sources: int, min_chars: int = 220) -> bool:
        quality_count = self._count_quality_sources(records, topic, query)
        total_chars = sum(len(r.get("snippet", "")) + len(r.get("title", "")) for r in records)
        return quality_count >= required_sources and total_chars >= min_chars

    # ── Scoring & Ranking ───────────────────────────────

    def _score_record(self, topic: str, query: str, record: Dict[str, str]) -> float:
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
        is_time_sensitive = self._is_time_sensitive_query(query)
        if pub_date and is_time_sensitive:
            days_ago = (datetime.now() - pub_date).days
            if days_ago <= 1:
                score += 1.0
            elif days_ago <= 7:
                score += 0.6
            elif days_ago <= 30:
                score += 0.3

        freshness_bonus = -0.05
        if is_time_sensitive and not pub_date and not self._contains_year(combined_text):
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

    def _is_quality_record(self, topic: str, query: str, record: Dict[str, str]) -> bool:
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

    def _dynamic_reputation_score(self, topic: str, query: str, record: Dict[str, str]) -> float:
        domain = (record.get("domain") or "").lower()
        snippet = (record.get("snippet") or "").strip().lower()

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

    def _domain_diversify_records(self, records: List[Dict[str, str]], limit: int, enforce_diversity: bool) -> List[Dict[str, str]]:
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

    def _lightweight_rerank(self, topic: str, query: str, records: List[Dict[str, str]]) -> List[Dict[str, str]]:
        scored = []
        for rec in records:
            base_score = float(rec.get("score", 0))
            rep_score = self._dynamic_reputation_score(topic, query, rec)
            is_time_sensitive = self._is_time_sensitive_query(query)
            pub_date = DateParser.extract_date(
                (rec.get("snippet") or "") + " " + (rec.get("title") or "")
            )
            decay = self._calculate_time_decay_penalty(topic, pub_date, is_time_sensitive)
            total = base_score + rep_score + decay
            scored.append((total, rec))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [rec for _, rec in scored]

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
        except Exception as e:
            self.logger.warning(f"Error calculating time decay penalty: {e}")
            return 0.0

    def _format_source_line(self, rec: Dict[str, str]) -> str:
        title = (rec.get("title") or "Liên kết").strip()
        url = (rec.get("url") or "#").strip()
        return f"- **{title}**: {url}"

    # ── Format Output ──────────────────────────────────

    def _format_final_search_result(self, topic: str, query: str, ranked_records: List[Dict[str, str]], required_sources: int) -> str:
        top = self._domain_diversify_records(ranked_records, self.search_top_results_limit, enforce_diversity=True)
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

        quality_count = self._count_quality_sources(top, topic, query)
        parts.append("")
        parts.append(f"Required quality sources: {required_sources} | Quality sources found: {quality_count}")
        if quality_count < required_sources:
            parts.append("⚠️ Chưa đủ nguồn chất lượng theo ngưỡng cho truy vấn này; nên xem kết quả như thông tin tham khảo.")

        return "\n".join(parts)

    # ── Main Pipeline ──────────────────────────────────

    async def _search_single_intent(self, q_sub: str, force_fallback: bool = False) -> str:
        selected_topic = self._classify_topic(q_sub)
        q1 = q_sub.strip()
        self.logger.info(f"Classified: {selected_topic.upper()}. Searching for: '{q_sub}'")
        transformed_query, timelimit = self._transform_temporal_query(q1)
        primary_queries = [transformed_query or q1]

        primary_tasks = [
            asyncio.create_task(self._search_duckduckgo_records(p_query, idx, timelimit=timelimit, query_effective=transformed_query))
            for idx, p_query in enumerate(primary_queries)
        ]
        primary_results = await asyncio.gather(*primary_tasks, return_exceptions=True)

        records: List[Dict[str, str]] = []
        for result in primary_results:
            if isinstance(result, BaseException):
                continue
            records.extend(result)

        records = self._dedupe_records(records)
        required_sources = self._required_quality_sources(q_sub)
        has_enough = self._is_search_result_sufficient(records, selected_topic, q_sub, required_sources)

        should_fallback = force_fallback or not has_enough
        if should_fallback:
            fallback_records = await self._run_fallback_search_records(q_sub)
            records.extend(fallback_records)
            records = self._dedupe_records(records)

        scored = []
        for rec in records:
            rec["score"] = str(self._score_record(selected_topic, q_sub, rec))
            scored.append(rec)

        ranked = self._lightweight_rerank(selected_topic, q_sub, scored)

        if self.search_web_mode == "grounded":
            top_records = ranked[:self.search_grounded_top_links]
            if top_records:
                evidence_results = await asyncio.gather(
                    *(self._fetch_page_evidence(rec.get("url", "")) for rec in top_records),
                    return_exceptions=True,
                )
                for rec, evidence in zip(top_records, evidence_results):
                    rec["evidence"] = evidence if isinstance(evidence, str) else ""

        final = self._format_final_search_result(selected_topic, q_sub, ranked, required_sources)
        quality_count = self._count_quality_sources(ranked, selected_topic, q_sub)

        if quality_count < required_sources:
            final += "\n\n⚠️ Chưa đủ nguồn chất lượng theo ngưỡng cho truy vấn này; nên xem kết quả như thông tin tham khảo."
        return final

    async def _execute_search_pipeline(self, clean_query: str, force_fallback: bool) -> str:
        intents = self._split_multi_intents(clean_query)
        if not intents:
            return ""
        if len(intents) > 1:
            self.logger.info(f"Subquery fanout enabled. Running {len(intents)} search intents fully in parallel.")

        tasks = [self._search_single_intent(intent, force_fallback) for intent in intents]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        final_sections = []
        for intent, res in zip(intents, results):
            if isinstance(res, Exception):
                self.logger.error(f"Search intent error for '{intent[:60]}': {res}")
                final_sections.append(f"### 🔍 [Chủ đề: GENERAL] Kết quả cho '{intent}':\n(Không thể truy xuất dữ liệu cho intent này.)")
            elif res:
                final_sections.append(res)

        return "\n\n".join(final_sections).strip() if final_sections else ""

    async def run_search_apis(self, query: str, mode: str = "general"):
        raw_query = query or ""
        force_fallback = "[FORCE FALLBACK]" in raw_query.upper()
        clean_query = raw_query.replace("[FORCE FALLBACK]", "").strip()
        if not clean_query:
            return ""

        cache_key = f"{mode}|{clean_query}"
        normalized_key = self._normalize_search_cache_key(cache_key)
        time_sensitive = self._is_time_sensitive_query(clean_query)
        bypass_cache = time_sensitive and not force_fallback

        inflight_task: Optional[asyncio.Task] = None
        async with self.cache_lock:
            cached_result = None if (force_fallback or bypass_cache) else self.get_web_search_cache(cache_key)
            if not cached_result:
                inflight_task = self.inflight_search_tasks.get(normalized_key)

        if cached_result:
            self.logger.info(f"Web search result from cache for query: {clean_query[:50]}...")
            return cached_result

        if inflight_task:
            self.logger.info(f"Web search joined inflight task for key={normalized_key[:80]}")
            return await inflight_task

        if not force_fallback and not time_sensitive and self.search_failed_query_cooldown_seconds > 0:
            async with self.cache_lock:
                cooldown_until = self.failed_search_cooldowns.get(normalized_key, 0)
            if cooldown_until > time.time():
                self.logger.info(f"Search cooldown active for key={normalized_key[:80]}")
                return "⚠️ Nguồn tìm kiếm đang tạm quá tải, vui lòng thử lại sau ít giây."

        task = asyncio.create_task(self._execute_search_pipeline(clean_query, force_fallback))
        async with self.cache_lock:
            self.inflight_search_tasks[normalized_key] = task

        try:
            output = await task
            if not output and time_sensitive and not force_fallback:
                absolute_date = datetime.now().strftime("%d %B %Y")
                forced_query = f"{clean_query} ngay {absolute_date}"
                self.logger.info(
                    f"Time-sensitive query produced empty result. Retrying forced fallback query='{forced_query[:80]}'."
                )
                output = await self._execute_search_pipeline(forced_query, True)

            if output:
                async with self.cache_lock:
                    if not bypass_cache:
                        self.set_web_search_cache(cache_key, output, time_sensitive=time_sensitive)
                    self.failed_search_cooldowns.pop(normalized_key, None)
                if bypass_cache:
                    self.logger.info(f"Completed fresh search for time-sensitive query='{clean_query[:60]}'.")
                else:
                    self.logger.info(f"Completed search for query='{clean_query[:60]}' and cached.")
                return output

            if not time_sensitive and self.search_failed_query_cooldown_seconds > 0:
                async with self.cache_lock:
                    self.failed_search_cooldowns[normalized_key] = time.time() + self.search_failed_query_cooldown_seconds
                self.logger.info(f"Search failed, cooldown set for key={normalized_key[:60]}")
            return ""
        except Exception as e:
            self.logger.error(f"Search pipeline error: {e}")
            async with self.cache_lock:
                self.inflight_search_tasks.pop(normalized_key, None)
            return ""
