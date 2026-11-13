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


def test_extract_main_text_code_and_table():
    html = """
    <html><body><article>
      <pre><code class="language-python">print(1)</code></pre>
      <table><tr><td>A</td><td>B</td></tr></table>
      <ul><li>item one</li></ul>
    </article></body></html>
    """
    text = T()._extract_main_text(html)
    assert "print(1)" in text
    assert "A | B" in text
    assert "item one" in text


def test_extract_main_text_noise_removed():
    html = """
    <html><body><article>
      <div class="comments">spam comments</div>
      <div class="advertisement">buy now</div>
      <p>real content</p>
    </article></body></html>
    """
    text = T()._extract_main_text(html)
    assert "real content" in text
    assert "spam" not in text
    assert "buy now" not in text


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


def test_query_highlight_expands_paragraphs():
    # multiple paragraphs with matching keyword -> window expands to max_chars
    text = "\n\n".join(["matching paragraph " * 20] + ["other " * 20] * 10)
    hl = T()._extract_query_highlight(text, "matching", max_chars=600)
    assert "matching" in hl
    assert len(hl) <= 600


def test_query_highlight_no_matching_paragraph():
    text = "\n\n".join(["alpha " * 30, "beta " * 30, "gamma " * 30])
    hl = T()._extract_query_highlight(text, "zzz", max_chars=500)
    assert hl  # returns first max_chars slice


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


def test_extract_page_metadata_relative_ages():
    from datetime import datetime, timedelta

    t = T()
    now = datetime.now()

    # 1. yesterday
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    html1 = f'<meta property="article:published_time" content="{yesterday}">'
    assert t._extract_page_metadata(html1)["relative_age"] == "hôm qua"

    # 2. 10 days ago
    days_10 = (now - timedelta(days=10)).strftime("%Y-%m-%d")
    html2 = f'<meta property="article:published_time" content="{days_10}">'
    assert "ngày trước" in t._extract_page_metadata(html2)["relative_age"]

    # 3. 60 days ago -> months
    days_60 = (now - timedelta(days=60)).strftime("%Y-%m-%d")
    html3 = f'<meta property="article:published_time" content="{days_60}">'
    assert "tháng trước" in t._extract_page_metadata(html3)["relative_age"]

    # 4. 400 days ago -> years
    days_400 = (now - timedelta(days=400)).strftime("%Y-%m-%d")
    html4 = f'<meta property="article:published_time" content="{days_400}">'
    assert "năm trước" in t._extract_page_metadata(html4)["relative_age"]


def test_organization_domain_vietnamese_suffix():
    t = T()
    assert t._organization_domain("news.company.com.vn") == "company.com.vn"
    assert t._organization_domain("sub.portal.gov.vn") == "portal.gov.vn"


def test_query_coverage_score_all_ratios():
    t = T()
    # 4 tokens query
    q = "apple banana orange grape"

    # ratio >= 0.75 (3 hits out of 4)
    s_75 = t._query_coverage_score(q, "apple banana orange other")
    assert s_75 == 1.1

    # ratio >= 0.55 (2 hits out of 4 -> 0.5 < 0.55, need 3 hits out of 5)
    q5 = "alpha beta gamma delta epsilon"
    s_60 = t._query_coverage_score(q5, "alpha beta gamma other other2")
    assert s_60 == 0.8

    # ratio >= 0.35 (2 hits out of 5 = 0.40 >= 0.35)
    s_40 = t._query_coverage_score(q5, "alpha beta other other2 other3")
    assert s_40 == 0.45

    # ratio > 0 (1 hit out of 5 = 0.20 < 0.35)
    s_20 = t._query_coverage_score(q5, "alpha other other2 other3 other4")
    assert s_20 == 0.2


def test_fetch_page_data_redirect(monkeypatch):
    owner = E()

    class RedirectResp:
        status_code = 302
        is_redirect = True
        headers = {"Location": "http://example.com/target"}
        text = ""

    class FinalResp:
        status_code = 200
        is_redirect = False
        headers = {}
        encoding = "utf-8"
        text = "<html><body><article><p>" + "evidence text " * 30 + "</p></article></body></html>"

    calls = {"n": 0}
    def fake_get(url, **kw):
        calls["n"] += 1
        return RedirectResp() if calls["n"] == 1 else FinalResp()

    import src.tools.search.mixins.evidence as ev_mod
    monkeypatch.setattr(ev_mod.requests, "get", fake_get)
    text, meta = _await(owner._fetch_page_data("http://example.com/start"))
    assert "evidence text" in text


def test_fetch_page_data_non_200(monkeypatch):
    owner = E()
    class ErrResp:
        status_code = 404
        is_redirect = False
        text = "Not found"
        headers = {}
    import src.tools.search.mixins.evidence as ev_mod
    monkeypatch.setattr(ev_mod.requests, "get", lambda *a, **kw: ErrResp())
    text, meta = _await(owner._fetch_page_data("http://example.com/notfound"))
    assert text == ""


def test_fetch_page_data_short_text_returns_meta_only(monkeypatch):
    owner = E()
    class ShortResp:
        status_code = 200
        is_redirect = False
        headers = {}
        encoding = "utf-8"
        text = '<html><head><meta name="date" content="2026-01-01"></head><body><p>short</p></body></html>'
    import src.tools.search.mixins.evidence as ev_mod
    monkeypatch.setattr(ev_mod.requests, "get", lambda *a, **kw: ShortResp())
    text, meta = _await(owner._fetch_page_data("http://example.com/short"))
    assert text == ""
    assert meta == {}
