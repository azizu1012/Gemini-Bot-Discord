"""Search data definitions: authority domains, spam lists, phrase aliases, and topic dictionaries."""

from __future__ import annotations

from typing import Dict, List, Set, Tuple
from src.tools.search.languages.registry import build_search_topics


class SearchDataMixin:
    """Provides topic vocabulary, authority tiers, aliases, and stopwords."""

    CACHE_TTL_SECONDS = 3600
    MAX_CACHE_SIZE = 1000
    MAX_TEXT_LENGTH = 10000

    SEARCH_TOPICS: Dict[str, Dict[str, List[str]]] = build_search_topics()

    SEARCH_CACHE_STOPWORDS: Set[str] = {
        "the", "a", "an", "of", "for", "to", "and", "or", "in", "on", "at", "is", "are", "be",
        "toi", "la", "va", "cua", "cho", "ve", "trong", "tai", "duoc", "khong", "nao", "gi", "bao", "khi",
        "news", "information", "thong", "tin", "xem", "hoi", "giup",
    }

    SEARCH_CACHE_PHRASE_ALIASES: List[Tuple[str, str]] = [
        ("moi nhat", "latest"),
        ("hien tai", "current"),
        ("cap nhat", "update"),
        ("khi nao", "when"),
        ("bao gio", "when"),
        ("ket thuc", "end"),
        ("thoi gian", "schedule"),
        ("lich", "schedule"),
    ]

    SEARCH_CACHE_TOKEN_ALIASES: Dict[str, str] = {
        "hsr": "honkai_star_rail",
        "starrail": "honkai_star_rail",
        "banner": "banner",
        "latest": "latest",
        "current": "current",
        "update": "update",
        "patch": "patch",
        "schedule": "schedule",
    }

    # Tier 1: Highest authority technical & institutional domains
    TIER1_AUTHORITY_DOMAINS: Set[str] = {
        "github.com", "gitlab.com", "arxiv.org", "ietf.org", "w3.org",
        "modelcontextprotocol.io", "python.org", "rust-lang.org", "go.dev", "golang.org",
        "pypi.org", "npmjs.com", "crates.io", "huggingface.co",
        "google.com", "deepmind.google", "blog.google", "ai.google.dev", "cloud.google.com",
        "anthropic.com", "openai.com", "microsoft.com", "apple.com", "meta.com", "aws.amazon.com",
        "developer.mozilla.org", "docs.python.org", "fastapi.tiangolo.com",
    }

    TIER1_AUTHORITY_PATTERNS: Tuple[str, ...] = (
        "docs.", "api.", "developer.", "spec.", "specification.",
        ".gov", ".edu", ".ac.", "gov.vn", "edu.vn"
    )

    # Tier 2: Reputable news and tech media
    TIER2_REPUTABLE_DOMAINS: Set[str] = {
        "theverge.com", "arstechnica.com", "techcrunch.com", "reuters.com", "bloomberg.com",
        "wired.com", "stackoverflow.com", "stackexchange.com", "wikipedia.org", "zdnet.com",
        "tomshardware.com", "anandtech.com", "venturebeat.com", "infoworld.com", "apnews.com",
        "bbc.com", "bbc.co.uk", "nature.com", "science.org",
    }

    # Tier 4: Known AI SEO spam sites to penalize or reject
    TIER4_SPAM_SEO_DOMAINS: Set[str] = {
        "tokencalc.dev", "whichllm.io", "projedefteri.com", "hackaigc.com", "shattered.io",
        "prompeteer.ai", "lorka.ai", "distk.in", "pinterest.com", "facebook.com",
        "instagram.com", "tiktok.com",
    }
