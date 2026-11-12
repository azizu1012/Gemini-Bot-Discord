"""Offline tests for LLMGateway — client caching, generate fallback, helpers."""
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, ".")

from src.core.llm.base import LLMError, LLMNotConfiguredError, LLMUnsupportedError
from src.core.llm.gateway import LLMGateway, _extract_text


class NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


class FakeResolver:
    def __init__(self):
        self.endpoints = {}
        self.roles = {}

    def set_endpoint(self, sdk, base_url, api_key):
        self.endpoints[sdk] = {"base_url": base_url, "api_key": api_key}

    def set_role(self, role, sdk, model_id):
        self.roles[role] = SimpleNamespace(role=role, sdk=sdk, model_id=model_id)

    async def get_endpoint(self, sdk):
        return self.endpoints.get(sdk)

    async def resolve_role(self, role):
        return self.roles.get(role)

    async def get_active_sdk(self):
        return "genai"


def make_gateway():
    resolver = FakeResolver()
    gw = LLMGateway(resolver=resolver, logger=NullLogger(), config=SimpleNamespace(GEMINI_TIMEOUT_MS=60000, SAFETY_SETTINGS=[]))
    return gw, resolver


def test_extract_text_joins_parts():
    response = SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[SimpleNamespace(text="Hello"), SimpleNamespace(text=" world")]))])
    assert _extract_text(response) == "Hello"


def test_extract_text_empty():
    assert _extract_text(SimpleNamespace(candidates=[])) == ""


# ---------------- client factory ----------------
def test_default_client_factory_genai():
    gw, _ = make_gateway()
    gw._default_client_factory = None
    # Need the real factory; re-create
    gw = LLMGateway(resolver=FakeResolver(), logger=NullLogger(), config=SimpleNamespace(GEMINI_TIMEOUT_MS=60000))
    client = gw._default_client_factory("genai", "http://x", "key")
    assert client is not None


def test_default_client_factory_unsupported():
    gw, _ = make_gateway()
    with pytest.raises(LLMUnsupportedError):
        gw._default_client_factory("unknown", "http://x", "k")


# ---------------- _get_client ----------------
@pytest.mark.asyncio
async def test_get_client_creates_and_caches():
    gw, resolver = make_gateway()
    resolver.set_endpoint("genai", "http://x", "key")
    gw._client_factory = MagicMock(return_value=SimpleNamespace())
    c1 = await gw._get_client("genai")
    c2 = await gw._get_client("genai")
    assert c1 is c2
    assert gw._client_factory.call_count == 1


@pytest.mark.asyncio
async def test_get_client_not_configured():
    gw, resolver = make_gateway()
    with pytest.raises(LLMNotConfiguredError):
        await gw._get_client("genai")


# ---------------- generate ----------------
@pytest.mark.asyncio
async def test_generate_success_primary():
    gw, resolver = make_gateway()
    resolver.set_role("final", "genai", "m1")
    resolver.set_endpoint("genai", "http://x", "k")
    client = MagicMock()
    client.generate = AsyncMock(return_value=SimpleNamespace(ok=True))
    gw._client_factory = MagicMock(return_value=client)
    resp = await gw.generate(role="final", system_instruction="", generation_config={}, messages=[])
    assert resp.ok is True
    client.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_fallback_on_transient():
    gw, resolver = make_gateway()
    resolver.set_role("final", "genai", "m1")
    resolver.set_role("fallback", "genai", "m2")
    resolver.set_endpoint("genai", "http://x", "k")

    client = MagicMock()
    # first attempt raises transient, second (fallback attempt) succeeds
    client.generate = AsyncMock(
        side_effect=[LLMError("rate_limit", "busy"), SimpleNamespace(ok=True)]
    )
    gw._client_factory = MagicMock(return_value=client)
    resp = await gw.generate(role="final", system_instruction="", generation_config={}, messages=[])
    assert resp.ok is True
    assert client.generate.await_count == 2


@pytest.mark.asyncio
async def test_generate_raises_on_auth():
    gw, resolver = make_gateway()
    resolver.set_role("final", "genai", "m1")
    resolver.set_endpoint("genai", "http://x", "k")
    client = MagicMock()
    client.generate = AsyncMock(side_effect=LLMError("auth", "invalid key"))
    gw._client_factory = MagicMock(return_value=client)
    with pytest.raises(LLMError):
        await gw.generate(role="final", system_instruction="", generation_config={}, messages=[])


@pytest.mark.asyncio
async def test_generate_all_fail_raises_last():
    gw, resolver = make_gateway()
    resolver.set_role("final", "genai", "m1")
    resolver.set_role("fallback", "genai", "m2")
    resolver.set_endpoint("genai", "http://x", "k")
    gw._client_factory = MagicMock(return_value=MagicMock())
    gw._client_factory.return_value.generate = AsyncMock(side_effect=LLMError("connection", "down"))
    with pytest.raises(LLMError):
        await gw.generate(role="final", system_instruction="", generation_config={}, messages=[])


@pytest.mark.asyncio
async def test_generate_not_configured():
    gw, resolver = make_gateway()
    with pytest.raises(LLMNotConfiguredError):
        await gw.generate(role="final", system_instruction="", generation_config={}, messages=[])


# ---------------- list_models_for ----------------
@pytest.mark.asyncio
async def test_list_models_for():
    gw, _ = make_gateway()
    client = MagicMock()
    client.list_models = AsyncMock(return_value=["a", "b"])
    client.close = AsyncMock()
    gw._client_factory = MagicMock(return_value=client)
    assert await gw.list_models_for(sdk="genai", base_url="http://x", api_key="k") == ["a", "b"]
    client.close.assert_awaited_once()


# ---------------- generate_text / vision ----------------
@pytest.mark.asyncio
async def test_generate_text_returns_extracted():
    gw, resolver = make_gateway()
    resolver.set_role("final", "genai", "m1")
    resolver.set_endpoint("genai", "http://x", "k")
    client = MagicMock()
    client.generate = AsyncMock(return_value=SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[SimpleNamespace(text="answer")]))]))
    gw._client_factory = MagicMock(return_value=client)
    assert await gw.generate_text("prompt") == "answer"


@pytest.mark.asyncio
async def test_generate_vision():
    gw, resolver = make_gateway()
    resolver.set_role("final", "genai", "m1")
    resolver.set_endpoint("genai", "http://x", "k")
    client = MagicMock()
    client.generate = AsyncMock(return_value=SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[SimpleNamespace(text="a cat")]))]))
    gw._client_factory = MagicMock(return_value=client)
    assert await gw.generate_vision(b"img", "image/png", "what") == "a cat"


# ---------------- get_raw_genai_client ----------------
@pytest.mark.asyncio
async def test_get_raw_genai_client():
    gw, resolver = make_gateway()
    resolver.set_endpoint("genai", "http://x", "k")
    client = MagicMock()
    client.raw_client = MagicMock()
    gw._client_factory = MagicMock(return_value=client)
    assert await gw.get_raw_genai_client() is client.raw_client


@pytest.mark.asyncio
async def test_get_raw_genai_client_unsupported():
    gw, resolver = make_gateway()
    resolver.endpoints = {}
    resolver.set_endpoint("genai", "http://x", "k")

    # force active sdk to openai
    async def fake_active():
        return "openai"

    resolver.get_active_sdk = fake_active
    with pytest.raises(LLMUnsupportedError):
        await gw.get_raw_genai_client()


# ---------------- misc ----------------
def test_log_exception():
    gw, _ = make_gateway()
    gw.log_exception(stage="s", error=ValueError("boom"), user_id="u", role="r", attempt=1, max_attempts=3)
    # no exception


def test_static_error_helpers():
    assert LLMGateway._is_connection_error(ConnectionError()) is True
    assert LLMGateway._is_rate_limit_error("rate limit hit") is True


@pytest.mark.asyncio
async def test_close_closes_clients():
    gw, _ = make_gateway()
    c1 = MagicMock()
    c1.close = AsyncMock()
    c2 = MagicMock()
    c2.close = AsyncMock()
    gw._clients[("g", "u", "k")] = c1
    gw._clients[("o", "u", "k")] = c2
    await gw.close()
    c1.close.assert_awaited_once()
    c2.close.assert_awaited_once()
    assert gw._clients == {}
