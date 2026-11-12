"""Offline tests for search text mixin helpers and evidence fetching."""
import sys


sys.path.insert(0, ".")

from src.tools.search.mixins.text import SearchTextMixin
from src.tools.search.mixins.evidence import SearchEvidenceMixin


class T(SearchTextMixin):
    pass


class E(SearchEvidenceMixin, SearchTextMixin):
    deep_read_max_chars = 1800


def _await(coro):
    import asyncio
    return asyncio.run(coro)


# ---------------- _extract_date ----------------
def test_extract_date_none():
    assert T()._extract_date("") is None
    assert T()._extract_date(None) is None


def test_extract_date_valid():
    d = T()._extract_date("2026-11-12")
    assert d is not None
    assert d.year == 2026


# ---------------- _parse_soup ----------------
def test_parse_soup_returns_soup():
    soup = T()._parse_soup("<html><body><p>hi</p></body></html>")
    assert soup is not None
    assert soup.get_text().strip() == "hi"


# ---------------- _extract_page_metadata ----------------
def test_extract_page_metadata_empty():
    r = T()._extract_page_metadata("")
    assert r["has_verified_date"] is False


def test_extract_page_metadata_from_meta():
    html = '<meta property="article:published_time" content="2026-11-12T10:00:00Z">'
    r = T()._extract_page_metadata(html)
    assert r["has_verified_date"] is True
    assert r["date_str"] == "12/11/2026"


def test_extract_page_metadata_jsonld():
    html = '<script type="application/ld+json">{"datePublished":"2026-11-12"}</script>'
    r = T()._extract_page_metadata(html)
    assert r["has_verified_date"] is True


def test_extract_page_metadata_time_tag():
    html = '<time datetime="2026-11-12">Nov 12</time>'
    r = T()._extract_page_metadata(html)
    assert r["has_verified_date"] is True


# ---------------- _extract_main_text ----------------
def test_extract_main_text_strips_noise():
    html = """
    <html><body>
      <nav>menu</nav>
      <article><h2>Title</h2><p>Hello world content here.</p></article>
    </body></html>
    """
    text = T()._extract_main_text(html)
    assert "Title" in text
    assert "Hello world" in text
    assert "menu" not in text


def test_extract_main_text_paragraphs():
    html = "<html><body><article><p>Para one</p><p>Para two</p></article></body></html>"
    text = T()._extract_main_text(html)
    assert "Para one" in text


# ---------------- _extract_query_highlight ----------------
def test_query_highlight_short_text():
    assert T()._extract_query_highlight("short", "q") == "short"


def test_query_highlight_selects_relevant_paragraph():
    text = ("\n\n".join(["irrelevant " * 50, "matching " * 50, "other " * 50]))
    hl = T()._extract_query_highlight(text, "matching")
    assert "matching" in hl


# ---------------- domain helpers ----------------
def test_normalize_domain():
    assert T()._normalize_domain("https://www.example.com/path") == "example.com"
    assert T()._normalize_domain("") == ""


def test_organization_domain():
    assert T()._organization_domain("www.example.com") == "example.com"
    assert T()._organization_domain("blog.example.com.vn") == "example.com.vn"
    assert T()._organization_domain("") == ""


# ---------------- token helpers ----------------
def test_normalize_query_tokens_diacritics():
    tokens = T()._normalize_query_tokens("Thời tiết Hà Nội")
    assert all("đ" not in t for t in tokens)
    assert any("thoi" in t for t in tokens)


def test_normalize_text_for_match():
    assert T()._normalize_text_for_match("  Xin chào  Việt Nam  ") == "xin chao viet nam"


def test_contains_phrase():
    assert T()._contains_phrase(["a", "b", "c"], "b c") is True
    assert T()._contains_phrase(["a", "b"], "b c") is False


def test_query_overlap_count():
    assert T()._query_overlap_count("hello world", "world hello x") == 2
    assert T()._query_overlap_count("", "x") == 0


def test_query_coverage_score_full():
    score = T()._query_coverage_score("hello world", "hello world here")
    assert score > 1.0


def test_query_coverage_score_none():
    assert T()._query_coverage_score("", "x") == 0.0
    assert T()._query_coverage_score("zzz", "aaa") == 0.0


def test_query_coverage_score_high_ratio():
    score = T()._query_coverage_score("alpha beta gamma delta", "alpha beta gamma delta extra")
    assert score >= 1.0


def test_query_coverage_score_partial():
    # some tokens hit -> small positive score
    score = T()._query_coverage_score("alpha beta gamma delta", "alpha something else")
    assert score > 0


def test_query_highlight_unclosed_code_fence():
    text = ("paragraph one content " * 30) + "\n\n```python\nprint(1)\n" + ("more " * 30)
    hl = T()._extract_query_highlight(text, "one", max_chars=500)
    assert hl.count("```") % 2 == 0  # balanced


def test_query_highlight_no_tokens():
    text = "x" * 2000
    hl = T()._extract_query_highlight(text, "!!", max_chars=100)
    assert len(hl) <= 100


# ---------------- evidence mixin ----------------
def test_fetch_page_data_unsafe_url():
    owner = E()
    text, meta = _await(owner._fetch_page_data("http://localhost:5432"))
    assert text == ""
    assert meta == {}


def test_fetch_page_data_success(monkeypatch):
    owner = E()

    class FakeResponse:
        status_code = 200
        text = "<html><body><article><p>" + "main content " * 50 + "</p></article></body></html>"
        encoding = None
        apparent_encoding = "utf-8"
        headers = {}
        is_redirect = False

    def fake_get(url, headers, timeout, allow_redirects):
        return FakeResponse()

    import src.tools.search.mixins.evidence as ev_mod

    monkeypatch.setattr(ev_mod.requests, "get", fake_get)
    text, meta = _await(owner._fetch_page_data("https://example.com/article"))
    assert "main content" in text


def test_fetch_page_data_keeps_metadata(monkeypatch):
    owner = E()

    class FakeResponse:
        status_code = 200
        text = '<html><head><meta property="article:published_time" content="2026-11-12T10:00:00Z"></head><body><article><p>' + "main content " * 50 + "</p></article></body></html>"
        encoding = None
        apparent_encoding = "utf-8"
        headers = {}
        is_redirect = False

    def fake_get(url, headers, timeout, allow_redirects):
        return FakeResponse()

    import src.tools.search.mixins.evidence as ev_mod

    monkeypatch.setattr(ev_mod.requests, "get", fake_get)
    text, meta = _await(owner._fetch_page_data("https://example.com/article"))
    assert "main content" in text
    assert meta["has_verified_date"] is True


def test_fetch_page_evidence_returns_text(monkeypatch):
    owner = E()

    class FakeResponse:
        status_code = 200
        text = "<html><body><article><p>" + "evidence " * 60 + "</p></article></body></html>"
        encoding = None
        apparent_encoding = "utf-8"
        headers = {}
        is_redirect = False

    import src.tools.search.mixins.evidence as ev_mod

    monkeypatch.setattr(ev_mod.requests, "get", lambda *a, **kw: FakeResponse())
    text = _await(owner._fetch_page_evidence("https://example.com/e"))
    assert "evidence" in text
