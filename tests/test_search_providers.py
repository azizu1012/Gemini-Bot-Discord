"""Offline tests for the web search providers and page evidence fetcher."""
import sys
from unittest.mock import AsyncMock, MagicMock


sys.path.insert(0, ".")

from src.tools.search.providers import duckduckgo as ddg_mod
from src.tools.search.providers import exa as exa_mod
from src.tools.search.providers import serpapi as serp_mod
from src.tools.search.providers import tavily as tav_mod
from src.tools.search.providers.fetcher import PageEvidenceFetcher


class NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


def _await_result(coro):
    import asyncio
    return asyncio.run(coro)


def _sync_to_thread(func, *a, **kw):
    """Return an awaitable wrapping a synchronous call (emulates to_thread)."""
    async def _wrap():
        return func(*a, **kw)
    return _wrap()


# ---------------- DuckDuckGo ----------------
def test_ddg_missing_library(monkeypatch):
    monkeypatch.setattr(ddg_mod, "DDGS", None)
    assert _await_result(ddg_mod.search_duckduckgo("q")) == []


def test_ddg_success(monkeypatch):
    class FakeDDGS:
        def __init__(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def text(self, query, max_results=5, timelimit=None):
            return [
                {"href": "https://example.com/a", "title": "Title A", "body": "snippet A"},
                {"href": "https://facebook.com/x", "title": "FB", "body": "s"},
                {"title": "No URL", "body": "s"},
            ]

    monkeypatch.setattr(ddg_mod, "DDGS", FakeDDGS)

    monkeypatch.setattr(ddg_mod.asyncio, "to_thread", _sync_to_thread)
    items = _await_result(ddg_mod.search_duckduckgo("q", index=1, query_effective="q2"))
    assert len(items) == 1
    assert items[0]["provider"] == "duckduckgo"
    assert items[0]["url"] == "https://example.com/a"
    assert items[0]["query_index"] == "1"
    assert items[0]["query_effective"] == "q2"


def test_ddg_error_returns_empty(monkeypatch):
    class FakeDDGS:
        def __init__(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def text(self, *a, **kw):
            raise RuntimeError("boom")

    monkeypatch.setattr(ddg_mod, "DDGS", FakeDDGS)

    monkeypatch.setattr(ddg_mod.asyncio, "to_thread", _sync_to_thread)
    assert _await_result(ddg_mod.search_duckduckgo("q", logger_override=NullLogger())) == []


# ---------------- Exa ----------------
def test_exa_no_key_returns_empty(monkeypatch):
    monkeypatch.setattr(exa_mod, "EXA_API_KEY", "")
    assert _await_result(exa_mod.search_exa("q")) == []


def test_exa_missing_package(monkeypatch):
    import sys as _sys

    monkeypatch.setattr(exa_mod, "EXA_API_KEY", "abc")
    monkeypatch.setitem(_sys.modules, "exa_py", None)
    assert _await_result(exa_mod.search_exa("q", logger_override=NullLogger())) == []


def test_exa_success(monkeypatch):
    import sys as _sys

    monkeypatch.setattr(exa_mod, "EXA_API_KEY", "abc")

    class FakeResult:
        def __init__(self, results):
            self.results = results

    class FakeExa:
        def __init__(self, **kw):
            self.search = MagicMock(
                return_value=FakeResult([
                    type("R", (), {"url": "https://example.com/e", "title": "E"})()
                ])
            )

    fake_mod = type("M", (), {"Exa": FakeExa})()
    monkeypatch.setitem(_sys.modules, "exa_py", fake_mod)

    monkeypatch.setattr(exa_mod.asyncio, "to_thread", _sync_to_thread)
    items = _await_result(exa_mod.search_exa("q"))
    assert len(items) == 1
    assert items[0]["provider"] == "exa"
    assert items[0]["url"] == "https://example.com/e"


# ---------------- SerpAPI ----------------
def test_serpapi_no_key_returns_empty(monkeypatch):
    monkeypatch.setattr(serp_mod, "SERPAPI_API_KEY", "")
    assert _await_result(serp_mod.search_serpapi("q")) == []


def test_serpapi_success(monkeypatch):
    import sys as _sys

    monkeypatch.setattr(serp_mod, "SERPAPI_API_KEY", "k")

    class FakeClient:
        def __init__(self, **kw):
            pass

        def search(self, params):
            return {
                "organic_results": [
                    {"link": "https://example.com/s", "title": "S", "snippet": "sum"},
                ]
            }

    monkeypatch.setitem(_sys.modules, "serpapi", type("M", (), {"Client": FakeClient})())

    monkeypatch.setattr(serp_mod.asyncio, "to_thread", _sync_to_thread)
    items = _await_result(serp_mod.search_serpapi("q"))
    assert len(items) == 1
    assert items[0]["provider"] == "serpapi"
    assert items[0]["snippet"] == "sum"


# ---------------- Tavily ----------------
def test_tavily_no_key_returns_empty(monkeypatch):
    monkeypatch.setattr(tav_mod, "TAVILY_API_KEY", "")
    assert _await_result(tav_mod.search_tavily("q")) == []


def test_tavily_success(monkeypatch):
    import sys as _sys

    monkeypatch.setattr(tav_mod, "TAVILY_API_KEY", "k")

    class FakeClient:
        def __init__(self, **kw):
            pass

        def search(self, query, max_results):
            return {
                "results": [
                    {"url": "https://example.com/t", "title": "T", "content": "text"},
                ]
            }

    monkeypatch.setitem(_sys.modules, "tavily", type("M", (), {"TavilyClient": FakeClient})())

    monkeypatch.setattr(tav_mod.asyncio, "to_thread", _sync_to_thread)
    items = _await_result(tav_mod.search_tavily("q"))
    assert len(items) == 1
    assert items[0]["provider"] == "tavily"


# ---------------- PageEvidenceFetcher ----------------
def test_fetcher_unsafe_url_returns_empty(monkeypatch):
    fetcher = PageEvidenceFetcher()
    # is_safe_url returns False for private/local
    assert _await_result(fetcher.fetch_page_evidence("http://localhost:5432")) == ""


def test_fetcher_success_fetch(monkeypatch):
    fetcher = PageEvidenceFetcher(deep_read_max_chars=400)

    class FakeResponse:
        status_code = 200
        text = "<html><body><p>" + "main content " * 50 + "</p></body></html>"
        encoding = None
        apparent_encoding = "utf-8"
        headers = {}
        is_redirect = False

    import src.tools.search.providers.fetcher as fetcher_mod

    monkeypatch.setattr(fetcher_mod, "fetch_page_html", AsyncMock(return_value=FakeResponse.text))
    text = _await_result(fetcher.fetch_page_evidence("https://example.com/article"))
    assert "main content" in text


def test_fetcher_parses_shared_fetch_result(monkeypatch):
    fetcher = PageEvidenceFetcher(deep_read_max_chars=400)

    class FinalResponse:
        status_code = 200
        text = "<html><body><p>" + "final text " * 40 + "</p></body></html>"
        encoding = None
        apparent_encoding = "utf-8"
        headers = {}
        is_redirect = False

    import src.tools.search.providers.fetcher as fetcher_mod

    monkeypatch.setattr(fetcher_mod, "fetch_page_html", AsyncMock(return_value=FinalResponse.text))
    text = _await_result(fetcher.fetch_page_evidence("https://example.com/start"))
    assert "final text" in text


def test_serpapi_missing_package(monkeypatch):
    import sys as _sys
    monkeypatch.setattr(serp_mod, "SERPAPI_API_KEY", "k")
    monkeypatch.setitem(_sys.modules, "serpapi", None)
    assert _await_result(serp_mod.search_serpapi("q", logger_override=NullLogger())) == []


def test_serpapi_exception(monkeypatch):
    monkeypatch.setattr(serp_mod, "SERPAPI_API_KEY", "k")
    class FakeClient:
        def __init__(self, **kw): pass
        def search(self, params): raise RuntimeError("serp fail")
    import sys as _sys
    monkeypatch.setitem(_sys.modules, "serpapi", type("M", (), {"Client": FakeClient})())
    monkeypatch.setattr(serp_mod.asyncio, "to_thread", _sync_to_thread)
    assert _await_result(serp_mod.search_serpapi("q", logger_override=NullLogger())) == []


def test_tavily_missing_package(monkeypatch):
    import sys as _sys
    monkeypatch.setattr(tav_mod, "TAVILY_API_KEY", "k")
    monkeypatch.setitem(_sys.modules, "tavily", None)
    assert _await_result(tav_mod.search_tavily("q", logger_override=NullLogger())) == []


def test_tavily_exception(monkeypatch):
    monkeypatch.setattr(tav_mod, "TAVILY_API_KEY", "k")
    class FakeClient:
        def __init__(self, **kw): pass
        def search(self, **kw): raise RuntimeError("tavily fail")
    import sys as _sys
    monkeypatch.setitem(_sys.modules, "tavily", type("M", (), {"TavilyClient": FakeClient})())
    monkeypatch.setattr(tav_mod.asyncio, "to_thread", _sync_to_thread)
    assert _await_result(tav_mod.search_tavily("q", logger_override=NullLogger())) == []


def test_ddg_with_timelimit(monkeypatch):
    class FakeDDGS:
        def __init__(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def text(self, query, max_results=5, timelimit=None):
            return [{"href": "https://example.com/item", "title": "T", "body": "b"}]

    monkeypatch.setattr(ddg_mod, "DDGS", FakeDDGS)
    monkeypatch.setattr(ddg_mod.asyncio, "to_thread", _sync_to_thread)
    items = _await_result(ddg_mod.search_duckduckgo("q", timelimit="d"))
    assert len(items) == 1


def test_exa_empty_results(monkeypatch):
    monkeypatch.setattr(exa_mod, "EXA_API_KEY", "abc")
    class FakeExa:
        def __init__(self, **kw):
            self.search = MagicMock(return_value=type("R", (), {"results": []})())
    import sys as _sys
    monkeypatch.setitem(_sys.modules, "exa_py", type("M", (), {"Exa": FakeExa})())
    monkeypatch.setattr(exa_mod.asyncio, "to_thread", _sync_to_thread)
    assert _await_result(exa_mod.search_exa("q")) == []


def test_exa_exception(monkeypatch):
    monkeypatch.setattr(exa_mod, "EXA_API_KEY", "abc")
    class FakeExa:
        def __init__(self, **kw):
            self.search = MagicMock(side_effect=RuntimeError("exa fail"))
    import sys as _sys
    monkeypatch.setitem(_sys.modules, "exa_py", type("M", (), {"Exa": FakeExa})())
    monkeypatch.setattr(exa_mod.asyncio, "to_thread", _sync_to_thread)
    assert _await_result(exa_mod.search_exa("q", logger_override=NullLogger())) == []
