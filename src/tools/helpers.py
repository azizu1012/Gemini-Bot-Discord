import re
import unicodedata
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import dateparser

from src.tools.constants import (
    SEARCH_CACHE_PHRASE_ALIASES,
    SEARCH_CACHE_TOKEN_ALIASES,
    SEARCH_CACHE_STOPWORDS,
    CITY_NAME_MAP,
)


class HtmlParser:
    """Extract main text content from HTML using BeautifulSoup/lxml."""

    @staticmethod
    def extract_main_text(html_text: str) -> str:
        soup = BeautifulSoup(html_text, 'lxml')
        for tag in soup(["script", "style", "noscript", "svg", "form", "button", "header", "footer", "nav", "aside"]):
            tag.decompose()
        content = soup.find("article") or soup.find("main") or soup.body
        if not content:
            return ""
        text = content.get_text(separator=' ')
        text = re.sub(r"\b(cookie policy|accept cookies|subscribe|advertisement|all rights reserved)\b", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+", " ", text).strip()
        return text


class DateParser:
    """Parse date strings using dateparser library."""

    @staticmethod
    def extract_date(text: str) -> Optional[datetime]:
        if not text:
            return None
        try:
            return dateparser.parse(text, languages=['vi', 'en'])
        except Exception:
            return None


class TextProcessor:
    """Text normalization and matching utilities."""

    @staticmethod
    def remove_diacritics(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text or "")
        return "".join(ch for ch in normalized if not unicodedata.combining(ch))

    @staticmethod
    def canonicalize_search_query(query: str) -> str:
        lowered = (query or "").strip().lower()
        lowered = lowered.replace("[force fallback]", " ")
        lowered = TextProcessor.remove_diacritics(lowered)

        for src, dst in SEARCH_CACHE_PHRASE_ALIASES:
            lowered = re.sub(rf"\b{re.escape(src)}\b", dst, lowered)

        lowered = re.sub(r"[^a-z0-9_\s]", " ", lowered)
        lowered = re.sub(r"\s+", " ", lowered).strip()
        if not lowered:
            return ""

        tokens = []
        for token in lowered.split(" "):
            normalized_token = SEARCH_CACHE_TOKEN_ALIASES.get(token, token)
            if not normalized_token or normalized_token in SEARCH_CACHE_STOPWORDS:
                continue
            if len(normalized_token) <= 1:
                continue
            tokens.append(normalized_token)

        if not tokens:
            return lowered
        canonical_tokens = sorted(set(tokens))
        return " ".join(canonical_tokens[:32])

    @staticmethod
    def normalize_text_for_match(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", (text or "").lower())
        normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
        return re.sub(r"\s+", " ", normalized).strip()

    @staticmethod
    def normalize_query_tokens(text: str) -> List[str]:
        normalized = unicodedata.normalize("NFKD", (text or "").lower())
        normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
        tokens = [t for t in normalized.split() if len(t) > 2]
        return tokens

    @staticmethod
    def query_overlap_count(query: str, text: str) -> int:
        q_tokens = set(TextProcessor.normalize_query_tokens(query))
        if not q_tokens:
            return 0
        t_tokens = set(TextProcessor.normalize_query_tokens(text))
        return len(q_tokens.intersection(t_tokens))

    @staticmethod
    def query_coverage_score(query: str, text: str) -> float:
        q_tokens = TextProcessor.normalize_query_tokens(query)
        if not q_tokens:
            return 0.0
        t_tokens = TextProcessor.normalize_query_tokens(text)
        if not t_tokens:
            return 0.0
        overlap = len(set(q_tokens).intersection(set(t_tokens)))
        return round(overlap / len(q_tokens), 3)


class UrlUtils:
    """URL and domain normalization utilities."""

    @staticmethod
    def normalize_domain(url: str) -> str:
        try:
            parsed = urlparse(url)
            domain = parsed.netloc or parsed.path.split("/")[0]
            return domain.lower().replace("www.", "").strip()
        except Exception:
            return (url or "").lower().replace("www.", "").strip()

    @staticmethod
    def organization_domain(domain: str) -> str:
        parts = domain.strip().split(".")
        if len(parts) >= 2:
            return ".".join(parts[-2:])
        return domain

    @staticmethod
    def normalize_url(url: str) -> str:
        if not url:
            return ""
        normalized = url.strip()
        if normalized.startswith("//"):
            normalized = "https:" + normalized
        if not normalized.startswith(("http://", "https://")):
            normalized = "https://" + normalized
        normalized = normalized.rstrip("/")
        return normalized

    @staticmethod
    def is_blocked_domain(url: str) -> bool:
        blocked_domains = {
            "pinterest.com", "pinterest.ca", "facebook.com", "instagram.com",
            "tiktok.com", "reddit.com", "x.com", "twitter.com",
        }
        domain = UrlUtils.normalize_domain(url)
        return domain in blocked_domains


class CityNameHelper:
    """City name normalization for weather lookups."""

    @staticmethod
    def normalize(city_query: str) -> Tuple[str, str]:
        city_key = (city_query or "").strip().lower()
        city_key = TextProcessor.remove_diacritics(city_key)
        for k, v in CITY_NAME_MAP.items():
            if k in city_key:
                return v
        return (city_query, city_query.title())

    @staticmethod
    def guess_mime_type(image_url: str) -> str:
        lower = image_url.lower()
        if ".png" in lower:
            return "image/png"
        if ".gif" in lower:
            return "image/gif"
        if ".webp" in lower:
            return "image/webp"
        return "image/jpeg"
