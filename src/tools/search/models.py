"""Data models for search engine pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class SearchRecord:
    provider: str
    title: str
    url: str
    normalized_url: str
    domain: str
    snippet: str = ""
    evidence: str = ""
    score: float = 0.0
    query: str = ""
    query_effective: str = ""
    query_index: str = "0"

    def to_dict(self) -> Dict[str, str]:
        return {
            "provider": self.provider,
            "title": self.title,
            "snippet": self.snippet,
            "url": self.url,
            "normalized_url": self.normalized_url,
            "domain": self.domain,
            "score": str(self.score),
            "evidence": self.evidence,
            "query": self.query,
            "query_effective": self.query_effective,
            "query_index": self.query_index,
        }
