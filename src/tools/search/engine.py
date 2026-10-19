"""SearchEngine coordinator for multi-intent web search."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.core.config import logger, SERPAPI_API_KEY, TAVILY_API_KEY, EXA_API_KEY
from src.tools.search.cache import SearchCache
from src.tools.search.query_planner import QueryPlanner
from src.tools.search.reranker import SearchReranker
from src.tools.search.providers.duckduckgo import search_duckduckgo
from src.tools.search.providers.serpapi import search_serpapi
from src.tools.search.providers.tavily import search_tavily
from src.tools.search.providers.exa import search_exa
from src.tools.search.providers.fetcher import PageEvidenceFetcher


class SearchEngine:
    """Full search pipeline: query planning, providers, ranking, scoring, dedup, and caching."""

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
        self.fallback_provider_limit = fallback_provider_limit
        self.intent_batch_size = intent_batch_size
        self.search_failed_query_cooldown_seconds = search_failed_query_cooldown_seconds
        self.google_search_streams = google_search_streams

        # Submodules
        self.cache = SearchCache(
            semantic_cache_enabled=search_semantic_cache_enabled,
            general_ttl_seconds=search_general_cache_ttl_seconds,
            time_sensitive_ttl_seconds=search_time_sensitive_cache_ttl_seconds,
            empty_evidence_ttl_seconds=search_empty_evidence_cache_ttl_seconds,
        )
        self.planner = QueryPlanner(
            intent_batch_size=intent_batch_size,
            min_quality_sources=min_quality_sources,
            time_sensitive_min_quality_sources=time_sensitive_min_quality_sources,
        )
        self.reranker = SearchReranker(
            top_results_limit=search_top_results_limit,
            logger_override=self.logger,
        )
        self.fetcher = PageEvidenceFetcher(deep_read_max_chars=deep_read_max_chars)

        self.cache_lock = asyncio.Lock()
        self.search_lock = asyncio.Lock()
        self.inflight_search_tasks: Dict[str, asyncio.Task] = {}
        self.failed_search_cooldowns: Dict[str, float] = {}

    # Backward-compatible cache property access
    @property
    def web_search_cache(self):
        return self.cache.web_search_cache

    @property
    def deep_read_cache(self):
        return self.cache.deep_read_cache

    def _normalize_search_cache_key(self, query: str) -> str:
        return self.cache.normalize_cache_key(query)

    def get_web_search_cache(self, query: str):
        return self.cache.get_web_search(query)

    def set_web_search_cache(self, query: str, data: str, time_sensitive: bool = False):
        self.cache.set_web_search(query, data, time_sensitive)

    def _get_deep_read_cache(self, url: str) -> Optional[str]:
        return self.cache.get_deep_read(url)

    def _set_deep_read_cache(self, url: str, text: str, ttl_seconds: int = 7200):
        self.cache.set_deep_read(url, text, ttl_seconds)

    # Delegated query planning methods
    def _is_time_sensitive_query(self, query: str) -> bool:
        return self.planner.is_time_sensitive_query(query)

    def _contains_year(self, query: str) -> bool:
        return self.planner.contains_year(query)

    def _time_sensitive_timelimit(self, query: str) -> Optional[str]:
        return self.planner.time_sensitive_timelimit(query)

    def _transform_temporal_query(self, query: str) -> Tuple[str, Optional[str]]:
        return self.planner.transform_temporal_query(query)

    def _required_quality_sources(self, query: str) -> int:
        return self.planner.required_quality_sources(query)

    def _split_multi_intents(self, query: str) -> List[str]:
        return self.planner.split_multi_intents(query)

    def _determine_batch_size(self, intents: List[str]) -> int:
        return self.planner.determine_batch_size(intents)

    def _classify_topic(self, query: str) -> str:
        return self.planner.classify_topic(query)

    # Delegated reranking & scoring methods
    def _dedupe_records(self, records: List[Dict[str, str]]) -> List[Dict[str, str]]:
        return self.reranker.dedupe_records(records)

    def _score_record(self, topic: str, query: str, record: Dict[str, str]) -> float:
        return self.reranker.score_record(topic, query, record, self._is_time_sensitive_query(query))

    def _is_quality_record(self, topic: str, query: str, record: Dict[str, str]) -> bool:
        return self.reranker.is_quality_record(topic, query, record)

    def _count_quality_sources(self, records: List[Dict[str, str]], topic: str, query: str = "") -> int:
        return self.reranker.count_quality_sources(records, topic, query)

    def _is_search_result_sufficient(self, records: List[Dict[str, str]], topic: str, query: str, required_sources: int, min_chars: int = 220) -> bool:
        return self.reranker.is_search_result_sufficient(records, topic, query, required_sources, min_chars)

    def _domain_diversify_records(self, records: List[Dict[str, str]], limit: int, enforce_diversity: bool) -> List[Dict[str, str]]:
        return self.reranker.domain_diversify_records(records, limit, enforce_diversity)

    def _lightweight_rerank(self, topic: str, query: str, records: List[Dict[str, str]]) -> List[Dict[str, str]]:
        return self.reranker.lightweight_rerank(topic, query, records, self._is_time_sensitive_query(query))

    def _format_final_search_result(self, topic: str, query: str, ranked_records: List[Dict[str, str]], required_sources: int) -> str:
        return self.reranker.format_final_search_result(topic, query, ranked_records, required_sources)

    # Provider calls
    async def _search_duckduckgo_records(self, query: str, index: int = 0, timelimit: Optional[str] = None, query_effective: Optional[str] = None) -> List[Dict[str, str]]:
        return await search_duckduckgo(query, index, timelimit, query_effective, logger_override=self.logger)

    async def _search_serpapi_records(self, query: str) -> List[Dict[str, str]]:
        return await search_serpapi(query, logger_override=self.logger)

    async def _search_tavily_records(self, query: str) -> List[Dict[str, str]]:
        return await search_tavily(query, logger_override=self.logger)

    async def _search_exa_records(self, query: str) -> List[Dict[str, str]]:
        return await search_exa(query, logger_override=self.logger)

    async def _fetch_page_evidence(self, url: str) -> str:
        cached = self.cache.get_deep_read(url)
        if cached is not None:
            return cached
        text = await self.fetcher.fetch_page_evidence(url)
        if text:
            self.cache.set_deep_read(url, text, ttl_seconds=7200)
            return text
        self.cache.set_deep_read(url, "", ttl_seconds=self.cache.empty_evidence_ttl_seconds)
        return ""

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
