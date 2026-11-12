"""Offline tests for src/tools/helpers.py utility classes."""
import sys

sys.path.insert(0, ".")

from src.tools.helpers import (
    CityNameHelper,
    DateParser,
    HtmlParser,
    TextProcessor,
    UrlUtils,
)


# ---------------- HtmlParser ----------------
def test_extract_main_text_article():
    html = "<html><body><nav>menu</nav><article><p>Hello world content.</p></article></body></html>"
    text = HtmlParser.extract_main_text(html)
    assert "Hello world" in text
    assert "menu" not in text


def test_extract_main_text_empty():
    assert HtmlParser.extract_main_text("") == ""


def test_extract_main_text_no_content():
    assert HtmlParser.extract_main_text("<html></html>") == ""


# ---------------- DateParser ----------------
def test_extract_date_empty():
    assert DateParser.extract_date("") is None
    assert DateParser.extract_date(None) is None


def test_extract_date_valid():
    d = DateParser.extract_date("2026-11-12")
    assert d is not None


# ---------------- TextProcessor ----------------
def test_remove_diacritics():
    assert TextProcessor.remove_diacritics("Việt Nam") == "Viet Nam"
    assert TextProcessor.remove_diacritics("") == ""


def test_canonicalize_search_query_basic():
    q = TextProcessor.canonicalize_search_query("  Thời tiết Hà Nội  ")
    assert q == "ha noi thoi tiet"


def test_canonicalize_search_query_empty():
    assert TextProcessor.canonicalize_search_query("") == ""
    assert TextProcessor.canonicalize_search_query("!!!") == ""


def test_canonicalize_search_query_alias():
    q = TextProcessor.canonicalize_search_query("tin tức mới nhất")
    assert "latest" in q


def test_normalize_text_for_match():
    assert TextProcessor.normalize_text_for_match("  Xin chào  Việt Nam  ") == "xin chao viet nam"


def test_normalize_query_tokens():
    tokens = TextProcessor.normalize_query_tokens("Thời tiết Hà Nội")
    assert "thoi" in tokens


def test_query_overlap_count():
    assert TextProcessor.query_overlap_count("hello world", "world hello x") == 2
    assert TextProcessor.query_overlap_count("", "x") == 0


def test_query_coverage_score():
    assert TextProcessor.query_coverage_score("hello world", "hello world here") == 1.0
    assert TextProcessor.query_coverage_score("", "x") == 0.0
    assert TextProcessor.query_coverage_score("zzz", "") == 0.0


# ---------------- UrlUtils ----------------
def test_normalize_domain():
    assert UrlUtils.normalize_domain("https://www.example.com/path") == "example.com"
    assert UrlUtils.normalize_domain("http://Sub.EXAMPLE.com") == "sub.example.com"
    assert UrlUtils.normalize_domain("") == ""


def test_organization_domain():
    assert UrlUtils.organization_domain("blog.example.com") == "example.com"
    assert UrlUtils.organization_domain("example") == "example"


def test_normalize_url():
    assert UrlUtils.normalize_url("example.com/path/") == "https://example.com/path"
    assert UrlUtils.normalize_url("//example.com") == "https://example.com"
    assert UrlUtils.normalize_url("") == ""


def test_is_blocked_domain():
    assert UrlUtils.is_blocked_domain("https://facebook.com/x") is True
    assert UrlUtils.is_blocked_domain("https://github.com") is False


# ---------------- CityNameHelper ----------------
def test_city_normalize_known():
    city, title = CityNameHelper.normalize("Hà Nội")
    # map contains a normalized city key; title is non-empty
    assert city
    assert title


def test_city_normalize_unknown():
    city, title = CityNameHelper.normalize("Somewhere")
    assert city == "Somewhere"
    assert title == "Somewhere"


def test_city_normalize_empty():
    city, title = CityNameHelper.normalize("")
    assert city == ""


def test_guess_mime_type():
    assert CityNameHelper.guess_mime_type("x.png") == "image/png"
    assert CityNameHelper.guess_mime_type("x.gif") == "image/gif"
    assert CityNameHelper.guess_mime_type("x.webp") == "image/webp"
    assert CityNameHelper.guess_mime_type("x.jpg") == "image/jpeg"
