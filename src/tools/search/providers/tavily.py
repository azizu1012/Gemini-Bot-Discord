"""Tavily search provider."""

from __future__ import annotations

import asyncio
from typing import Dict, List

from src.core.config import logger, TAVILY_API_KEY
from src.tools.helpers import UrlUtils


async def search_tavily(query: str, max_results: int = 5, logger_override=None) -> List[Dict[str, str]]:
    log = logger_override or logger
    if not TAVILY_API_KEY:
        return []
    try:
        from tavily import TavilyClient
    except ImportError:
        log.warning("tavily package is not installed.")
        return []

    try:
        def _search():
            client = TavilyClient(api_key=TAVILY_API_KEY)
            return client.search(query=query, max_results=max_results)

        raw = await asyncio.to_thread(_search)
        results = raw.get("results", [])[:max_results]
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
        log.warning(f"Tavily search error: {e}")
        return []
