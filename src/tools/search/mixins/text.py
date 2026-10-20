"""Text utilities, Vietnamese normalization, HTML metadata, and main text extraction."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import dateparser

from src.tools.search.mixins.data import SearchDataMixin

_VIETNAMESE_FOLD = str.maketrans({"đ": "d", "Đ": "d"})


class SearchTextMixin(SearchDataMixin):
    """Provides HTML parsing, date extraction, and multilingual text matching utilities."""

    def _extract_date(self, text: str) -> Optional[datetime]:
        if not text:
            return None
        try:
            return dateparser.parse(text, languages=["vi", "en"])
        except Exception:
            return None

    def _parse_soup(self, html_text: str) -> BeautifulSoup:
        try:
            return BeautifulSoup(html_text, "lxml")
        except Exception:
            return BeautifulSoup(html_text, "html.parser")

    def _extract_page_metadata(self, html_text: str) -> Dict[str, Any]:
        """Extract verified published date and author from HTML meta/json-ld/time tags."""
        result: Dict[str, Any] = {
            "published_date": None,
            "date_str": "",
            "relative_age": "",
            "author": "",
            "has_verified_date": False,
        }
        if not html_text:
            return result

        try:
            soup = self._parse_soup(html_text)
            raw_date = None

            # 1. Meta tags
            meta_date_keys = [
                {"property": "article:published_time"},
                {"property": "og:published_time"},
                {"name": "pubdate"},
                {"name": "publishdate"},
                {"name": "date"},
                {"name": "dc.date"},
                {"name": "parsely-pub-date"},
            ]
            for selector in meta_date_keys:
                tag = soup.find("meta", selector)
                if tag and tag.get("content"):
                    raw_date = tag["content"].strip()
                    break

            # 2. Schema.org JSON-LD
            if not raw_date:
                for script in soup.find_all("script", type="application/ld+json"):
                    if not script.string:
                        continue
                    try:
                        data = json.loads(script.string)
                        items = data if isinstance(data, list) else [data]
                        for item in items:
                            if isinstance(item, dict):
                                d = item.get("datePublished") or item.get("dateCreated") or item.get("dateModified")
                                if d:
                                    raw_date = str(d).strip()
                                    break
                        if raw_date:
                            break
                    except Exception:
                        continue

            # 3. HTML5 <time datetime="...">
            if not raw_date:
                time_tag = soup.find("time")
                if time_tag:
                    raw_date = time_tag.get("datetime") or time_tag.get_text().strip()

            if raw_date:
                parsed = self._extract_date(raw_date)
                if parsed:
                    result["published_date"] = parsed
                    result["has_verified_date"] = True
                    result["date_str"] = parsed.strftime("%d/%m/%Y")
                    parsed_naive = parsed.replace(tzinfo=None) if getattr(parsed, "tzinfo", None) is not None else parsed
                    days = (datetime.now() - parsed_naive).days
                    if days <= 0:
                        result["relative_age"] = "hôm nay"
                    elif days == 1:
                        result["relative_age"] = "hôm qua"
                    elif days < 30:
                        result["relative_age"] = f"{days} ngày trước"
                    elif days < 365:
                        months = max(1, days // 30)
                        result["relative_age"] = f"{months} tháng trước"
                    else:
                        years = max(1, days // 365)
                        result["relative_age"] = f"{years} năm trước"
        except Exception:
            pass

        return result

    def _extract_main_text(self, html_text: str) -> str:
        soup = self._parse_soup(html_text)

        # Decompose unneeded tags
        for tag in soup(["script", "style", "noscript", "svg", "form", "button", "header", "footer", "nav", "aside", "iframe"]):
            tag.decompose()

        # Decompose noise blocks
        noise_patterns = re.compile(
            r"(toc|table-of-contents|author-bio|author-profile|newsletter|subscribe|share-buttons|related-posts|comments|cta|sidebar|advertisement|cookie-banner)",
            re.IGNORECASE,
        )
        for noise_el in soup.find_all(True, attrs={"class": noise_patterns}):
            noise_el.decompose()
        for noise_el in soup.find_all(True, attrs={"id": noise_patterns}):
            noise_el.decompose()

        content = soup.find("article") or soup.find("main") or soup.body
        if not content:
            return ""

        # Format code blocks
        for pre in content.find_all("pre"):
            code_tag = pre.find("code")
            lang = ""
            if code_tag and code_tag.get("class"):
                for cls in code_tag.get("class", []):
                    if cls.startswith(("language-", "lang-")):
                        lang = cls.split("-", 1)[1]
                        break
            code_text = pre.get_text().strip()
            pre.replace_with(f"\n\n```{lang}\n{code_text}\n```\n\n")

        # Headings, tables, lists, paragraphs
        for h in content.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            level = int(h.name[1]) if len(h.name) > 1 and h.name[1].isdigit() else 2
            prefix = "#" * level
            h.replace_with(f"\n\n{prefix} {h.get_text().strip()}\n")

        for tr in content.find_all("tr"):
            cells = [td.get_text().strip() for td in tr.find_all(["td", "th"])]
            if cells:
                tr.replace_with("\n| " + " | ".join(cells) + " |\n")

        for li in content.find_all("li"):
            li.replace_with(f"\n- {li.get_text().strip()}")

        for p in content.find_all("p"):
            p.replace_with(f"\n\n{p.get_text().strip()}\n")

        raw_text = content.get_text()
        raw_text = re.sub(
            r"\b(cookie policy|accept cookies|subscribe|advertisement|all rights reserved)\b",
            " ",
            raw_text,
            flags=re.IGNORECASE,
        )

        lines = []
        in_code = False
        for line in raw_text.splitlines():
            if line.strip().startswith("```"):
                in_code = not in_code
                lines.append(line.strip())
                continue
            if in_code:
                lines.append(line)
            else:
                cleaned = re.sub(r"[ \t]+", " ", line).strip()
                if cleaned:
                    lines.append(cleaned)
                elif not lines or lines[-1] != "":
                    lines.append("")

        return "\n".join(lines).strip()

    def _extract_query_highlight(self, text: str, query: str, max_chars: int = 2500) -> str:
        """Extract the most relevant excerpt window centered around query keyword density."""
        if len(text) <= max_chars:
            return text.strip()

        tokens = [t.lower() for t in re.findall(r"\w+", query) if len(t) > 2]
        if not tokens:
            return text[:max_chars].strip()

        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not paragraphs:
            return text[:max_chars].strip()

        scores = [sum(1 for t in tokens if t in p.lower()) for p in paragraphs]
        best_idx = max(range(len(scores)), key=lambda idx: scores[idx])

        if scores[best_idx] == 0:
            return text[:max_chars].strip()

        start, end = best_idx, best_idx + 1
        curr_len = len(paragraphs[best_idx])

        while curr_len < max_chars:
            expanded = False
            if start > 0:
                prev_len = len(paragraphs[start - 1]) + 2
                if curr_len + prev_len <= max_chars:
                    start -= 1
                    curr_len += prev_len
                    expanded = True
            if end < len(paragraphs):
                next_len = len(paragraphs[end]) + 2
                if curr_len + next_len <= max_chars:
                    end += 1
                    curr_len += next_len
                    expanded = True
            if not expanded:
                break

        selected_paragraphs = paragraphs[start:end]
        highlight = "\n\n".join(selected_paragraphs)

        if highlight.count("```") % 2 != 0:
            highlight += "\n```"

        prefix = "... " if start > 0 else ""
        suffix = " ..." if end < len(paragraphs) else ""
        return prefix + highlight + suffix

    def _normalize_domain(self, url: str) -> str:
        try:
            host = (urlparse(url).netloc or "").lower().strip()
            if host.startswith("www."):
                host = host[4:]
            return host
        except Exception:
            return ""

    def _organization_domain(self, domain: str) -> str:
        d = (domain or "").strip().lower()
        if not d:
            return ""
        labels = [x for x in d.split(".") if x]
        if len(labels) < 2:
            return d

        if len(labels) >= 3 and ".".join(labels[-2:]) in {"com.vn", "gov.vn", "org.vn", "edu.vn", "net.vn"}:
            return ".".join(labels[-3:])

        return ".".join(labels[-2:])

    def _normalize_query_tokens(self, text: str) -> List[str]:
        normalized = (text or "").lower().translate(_VIETNAMESE_FOLD)
        normalized = unicodedata.normalize("NFKD", normalized)
        normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
        return [t for t in normalized.split() if len(t) > 2]

    def _normalize_text_for_match(self, text: str) -> str:
        normalized = (text or "").lower().translate(_VIETNAMESE_FOLD)
        normalized = unicodedata.normalize("NFKD", normalized)
        normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
        return re.sub(r"\s+", " ", normalized).strip()

    def _contains_phrase(self, tokens: List[str], phrase: str) -> bool:
        parts = phrase.split()
        span = len(parts)
        if not span or span > len(tokens):
            return False
        for i in range(len(tokens) - span + 1):
            if tokens[i : i + span] == parts:
                return True
        return False

    def _query_overlap_count(self, query: str, text: str) -> int:
        q_tokens = set(self._normalize_query_tokens(query))
        if not q_tokens:
            return 0
        t_tokens = set(self._normalize_query_tokens(text))
        return len(q_tokens.intersection(t_tokens))

    def _query_coverage_score(self, query: str, text: str) -> float:
        q_tokens = self._normalize_query_tokens(query)
        if not q_tokens:
            return 0.0

        normalized_text = self._normalize_text_for_match(text)
        text_tokens = set(normalized_text.split())
        unique_query_tokens = list(dict.fromkeys(q_tokens))

        token_hits = sum(1 for token in unique_query_tokens if token in text_tokens)
        token_ratio = token_hits / len(unique_query_tokens)

        score = 0.0
        if token_ratio >= 0.9:
            score += 1.45
        elif token_ratio >= 0.75:
            score += 1.1
        elif token_ratio >= 0.55:
            score += 0.8
        elif token_ratio >= 0.35:
            score += 0.45
        elif token_ratio > 0:
            score += 0.2

        return round(score, 3)
