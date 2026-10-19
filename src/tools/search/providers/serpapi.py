"""SerpAPI Google Search provider."""

from __future__ import annotations

import asyncio
from typing import Dict, List

from src.core.config import logger, SERPAPI_API_KEY
from src.tools.helpers import UrlUtils


async def search_serpapi(query: str, max_results: int = 5, logger_override=None) -> List[Dict[str, str]]:
    log = logger_override or logger
    if not SERPAPI_API_KEY:
        return []
    try:
        import serpapi
    except ImportError:
        log.warning("serpapi package is not installed.")
        return []

    try:
        def _search():
            client = serpapi.Client(api_key=SERPAPI_API_KEY)
            return client.search({
                "q": query,
                "engine": "google",
                "num": max_results,
                "hl": "vi",
            })

        raw = await asyncio.to_thread(_search)
        results = raw.get("organic_results", [])[:max_results]
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
        log.warning(f"SerpAPI search error: {e}")
        return []
