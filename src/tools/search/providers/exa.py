"""Exa AI neural search provider."""

from __future__ import annotations

import asyncio
from typing import Dict, List

from src.core.config import logger, EXA_API_KEY
from src.tools.helpers import UrlUtils


async def search_exa(query: str, max_results: int = 5, logger_override=None) -> List[Dict[str, str]]:
    log = logger_override or logger
    if not EXA_API_KEY:
        return []
    try:
        import exa_py
    except ImportError:
        log.warning("exa_py package is not installed.")
        return []

    params = {
        "query": query,
        "num_results": max_results,
        "type": "neural"
    }
    try:
        exa = exa_py.Exa(api_key=EXA_API_KEY)
        results = await asyncio.to_thread(exa.search, **params)
        if not results.results:
            return []
        items = []
        for item in results.results[:max_results]:
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
        log.warning(f"Exa search error: {e}")
        return []
