"""Page evidence fetching and deep reading with SSRF protection."""

from __future__ import annotations

import asyncio
import urllib.parse
from typing import Any, Dict, Tuple

import requests

from src.tools.search.url_safety import build_pinned_request, is_safe_url


class SearchEvidenceMixin:
    """Provides safe web page fetching and deep evidence extraction."""

    async def _fetch_page_data(self, url: str) -> Tuple[str, Dict[str, Any]]:
        safe, _ = await asyncio.to_thread(is_safe_url, url, allow_private=False)
        if not safe:
            return "", {}

        async def _fetch_once(timeout_sec: float) -> Tuple[str, Dict[str, Any]]:
            headers = {
                "User-Agent": "Mozilla/5.0 (AzurisBot/1.0)",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.8,vi;q=0.7",
            }
            target_url = url
            response = None
            for _ in range(3):
                safe_hop, pinned_ip = await asyncio.to_thread(
                    is_safe_url, target_url, allow_private=False
                )
                if not safe_hop:
                    return "", {}
                dial_url, pinned_headers = build_pinned_request(target_url, pinned_ip)
                response = await asyncio.to_thread(
                    requests.get,
                    dial_url,
                    headers={**headers, **pinned_headers},
                    timeout=timeout_sec,
                    allow_redirects=False,
                )
                if response.is_redirect or response.status_code in (301, 302, 303, 307, 308):
                    loc = response.headers.get("Location", "")
                    target_url = urllib.parse.urljoin(target_url, loc)
                    continue
                break

            if not response or response.status_code != 200 or not response.text:
                return "", {}
            if not response.encoding:
                response.encoding = response.apparent_encoding or "utf-8"

            meta = self._extract_page_metadata(response.text)
            parsed = self._extract_main_text(response.text)
            max_chars = getattr(self, "deep_read_max_chars", 1800)
            if len(parsed) < 120:
                return "", meta
            return parsed[:max_chars].strip(), meta

        for timeout_sec in (3.0, 5.0):
            try:
                text, meta = await _fetch_once(timeout_sec)
                if text:
                    return text, meta
            except Exception:
                continue

        return "", {}

    async def _fetch_page_evidence(self, url: str) -> str:
        text, _ = await self._fetch_page_data(url)
        return text
