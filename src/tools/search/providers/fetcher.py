"""Deep read evidence fetcher for web search results with SSRF protection."""

from __future__ import annotations

import asyncio
import urllib.parse
from typing import Optional

import requests
from src.tools.helpers import HtmlParser
from src.tools.search.url_safety import is_safe_url


class PageEvidenceFetcher:
    """Fetches and parses main text content from a web page safely."""

    def __init__(self, deep_read_max_chars: int = 1800):
        self.deep_read_max_chars = deep_read_max_chars

    async def fetch_page_evidence(self, url: str) -> str:
        safe, _ = is_safe_url(url, allow_private=False)
        if not safe:
            return ""

        def _fetch_once(timeout_sec: float) -> str:
            headers = {
                "User-Agent": "Mozilla/5.0 (AzurisBot/1.0)",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.8,vi;q=0.7",
            }
            target_url = url
            response = None
            for _ in range(3):
                safe_hop, _ = is_safe_url(target_url, allow_private=False)
                if not safe_hop:
                    return ""
                response = requests.get(
                    target_url,
                    headers=headers,
                    timeout=timeout_sec,
                    allow_redirects=False,
                )
                if response.is_redirect or response.status_code in (301, 302, 303, 307, 308):
                    loc = response.headers.get("Location", "")
                    target_url = urllib.parse.urljoin(target_url, loc)
                    continue
                break

            if not response or response.status_code != 200 or not response.text:
                return ""
            if not response.encoding:
                response.encoding = response.apparent_encoding or "utf-8"
            parsed = HtmlParser.extract_main_text(response.text)
            if len(parsed) < 120:
                return ""
            return parsed[: self.deep_read_max_chars].strip()

        for attempt in range(2):
            timeout_sec = 3.0 if attempt == 0 else 5.0
            try:
                text = await asyncio.to_thread(_fetch_once, timeout_sec)
                if text:
                    return text
            except Exception:
                continue

        return ""
