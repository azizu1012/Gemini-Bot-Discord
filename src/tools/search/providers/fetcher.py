"""Deep read evidence fetcher for web search results with SSRF protection."""

from __future__ import annotations

import asyncio
import urllib.parse
from collections.abc import Callable

import aiohttp
from src.tools.helpers import HtmlParser
from src.tools.search.download import read_limited_response
from src.tools.search.url_safety import build_pinned_request, is_safe_url

MAX_PAGE_BYTES = 2 * 1024 * 1024
DOWNLOAD_TOTAL_SECONDS = 8.0


class PageEvidenceFetcher:
    """Fetches and parses main text content from a web page safely."""

    def __init__(self, deep_read_max_chars: int = 1800):
        self.deep_read_max_chars = deep_read_max_chars

    async def fetch_page_evidence(self, url: str) -> str:
        text = await fetch_page_html(url)
        parsed = HtmlParser.extract_main_text(text) if text else ""
        return parsed[: self.deep_read_max_chars].strip() if len(parsed) >= 120 else ""


async def fetch_page_html(url: str, *, text_extractor: Callable[[str], str] = HtmlParser.extract_main_text) -> str:
    try:
        async with asyncio.timeout(DOWNLOAD_TOTAL_SECONDS):
            return await _fetch_with_retries(url, text_extractor)
    except TimeoutError:
        return ""


async def _fetch_with_retries(url: str, text_extractor: Callable[[str], str]) -> str:
    async def _fetch_once(timeout_sec: float) -> str:
        headers = {
            "User-Agent": "Mozilla/5.0 (AzurisBot/1.0)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.8,vi;q=0.7",
            "Accept-Encoding": "gzip, deflate",
        }
        target_url = url
        for _ in range(3):
            safe_hop, pinned_ip = await asyncio.to_thread(
                is_safe_url, target_url, allow_private=False
            )
            if not safe_hop:
                return ""
            request_url, connector = build_pinned_request(target_url, pinned_ip)
            async with aiohttp.ClientSession(
                connector=connector, auto_decompress=False, headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout_sec),
            ) as session:
                async with session.get(request_url, allow_redirects=False) as response:
                    if response.status in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location", "")
                        if not location:
                            return ""
                        target_url = urllib.parse.urljoin(target_url, location)
                        continue
                    if response.status != 200:
                        return ""
                    body = await read_limited_response(response, MAX_PAGE_BYTES)
                    text = body.decode(response.charset or "utf-8", errors="replace")
            return text
        return ""

    for attempt in range(2):
        timeout_sec = 3.0 if attempt == 0 else 5.0
        try:
            text = await _fetch_once(timeout_sec)
            if text and len(text_extractor(text)) >= 120:
                return text
        except Exception:
            continue
    return ""
