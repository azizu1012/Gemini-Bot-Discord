"""Page evidence fetching and deep reading with SSRF protection."""

from __future__ import annotations

from typing import Any, Dict, Tuple

from src.tools.search.providers.fetcher import fetch_page_html


class SearchEvidenceMixin:
    """Provides safe web page fetching and deep evidence extraction."""

    async def _fetch_page_data(self, url: str) -> Tuple[str, Dict[str, Any]]:
        html = await fetch_page_html(url, text_extractor=self._extract_main_text)
        if not html:
            return "", {}
        meta = self._extract_page_metadata(html)
        parsed = self._extract_main_text(html)
        max_chars = getattr(self, "deep_read_max_chars", 1800)
        if len(parsed) < 120:
            return "", {}
        return parsed[:max_chars].strip(), meta

    async def _fetch_page_evidence(self, url: str) -> str:
        text, _ = await self._fetch_page_data(url)
        return text
