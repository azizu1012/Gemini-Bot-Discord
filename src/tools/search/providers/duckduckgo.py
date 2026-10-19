"""DuckDuckGo search provider."""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional

try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None

from src.core.config import logger
from src.tools.helpers import UrlUtils


async def search_duckduckgo(
    query: str,
    index: int = 0,
    timelimit: Optional[str] = None,
    query_effective: Optional[str] = None,
    max_results: int = 5,
    logger_override=None,
) -> List[Dict[str, str]]:
    log = logger_override or logger
    if DDGS is None:
        log.warning("DuckDuckGo search library is unavailable.")
        return []

    try:
        def _do_search():
            with DDGS() as ddgs:
                if timelimit:
                    return list(ddgs.text(query, max_results=max_results, timelimit=timelimit))
                return list(ddgs.text(query, max_results=max_results))

        results = await asyncio.to_thread(_do_search)
        items: List[Dict[str, str]] = []
        for item in results[:max_results]:
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
        log.warning(f"[Search Primary] Query: '{query}' | Error: {e}")
        return []
