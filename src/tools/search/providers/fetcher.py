"""Deep read evidence fetcher for web search results."""

from __future__ import annotations

import asyncio
from typing import Optional

import requests
from src.tools.helpers import HtmlParser


class PageEvidenceFetcher:
    """Fetches and parses main text content from a web page."""

    def __init__(self, deep_read_max_chars: int = 1800):
        self.deep_read_max_chars = deep_read_max_chars

    async def fetch_page_evidence(self, url: str) -> str:
        def _fetch_once(timeout_sec: float) -> str:
            headers = {
                "User-Agent": "Mozilla/5.0 (AzurisBot/1.0)",
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
                    return text
            except Exception:
                continue

        return ""
