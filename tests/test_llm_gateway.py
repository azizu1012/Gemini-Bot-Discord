import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import logger
from src.core.llm.base import LLMError, LLMNotConfiguredError, LLMResponse, SlotModel
from src.core.llm.gateway import LLMGateway


class FakeResolver:
    def __init__(self, roles, endpoints=None):
        self.roles = roles
        self.endpoints = endpoints or {}

    async def resolve_role(self, role):
        return self.roles.get(role)

    async def get_endpoint(self, sdk):
        return self.endpoints.get(sdk)

    async def get_active_sdk(self):
        return "genai"


class FakeClient:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    async def generate(self, *, model_id, **kw):
        self.calls.append(model_id)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def close(self):
        pass


def make_gateway(roles, results, endpoints=None):
    clients = {}

    def factory(sdk, base_url, api_key):
        clients.setdefault(sdk, FakeClient(results))
        return clients[sdk]

    endpoints = endpoints or {sdk: {"sdk": sdk, "base_url": "u", "api_key": "k", "is_active": True} for sdk in ("genai", "openai")}
    g = LLMGateway(resolver=FakeResolver(roles, endpoints), logger=logger, config=None, client_factory=factory)
    return g, clients


def test_not_configured():
    async def run():
        g = LLMGateway(resolver=FakeResolver({}), logger=logger, config=None, client_factory=lambda *a: None)
        try:
            await g.generate(role="final", system_instruction="", generation_config={}, messages=[])
            assert False, "phải raise LLMNotConfiguredError"
        except LLMNotConfiguredError:
            pass

    asyncio.run(run())


def test_primary_success():
    async def run():
        resp = LLMResponse([])
        roles = {"final": SlotModel("genai", "m1", "final"), "fallback": SlotModel("genai", "m2", "fallback")}
        g, clients = make_gateway(roles, [resp])
        out = await g.generate(role="final", system_instruction="", generation_config={}, messages=[])
        assert out is resp
        assert clients["genai"].calls == ["m1"]

    asyncio.run(run())


def test_fallback_same_provider_on_transient():
    async def run():
        resp = LLMResponse([])
        roles = {"final": SlotModel("genai", "m1", "final"), "fallback": SlotModel("genai", "m2", "fallback")}
        g, clients = make_gateway(roles, [LLMError("rate_limit", "429"), resp])
        out = await g.generate(role="final", system_instruction="", generation_config={}, messages=[])
        assert out is resp
        assert clients["genai"].calls == ["m1", "m2"]

    asyncio.run(run())


def test_no_fallback_for_auth():
    async def run():
        roles = {"final": SlotModel("genai", "m1", "final"), "fallback": SlotModel("genai", "m2", "fallback")}
        g, clients = make_gateway(roles, [LLMError("auth", "401")])
        try:
            await g.generate(role="final", system_instruction="", generation_config={}, messages=[])
            assert False, "phải raise"
        except LLMError as e:
            assert e.kind == "auth"
        assert clients["genai"].calls == ["m1"]

    asyncio.run(run())


def test_fallback_role_does_not_chain():
    async def run():
        roles = {"fallback": SlotModel("genai", "m2", "fallback")}
        g, clients = make_gateway(roles, [LLMError("unavailable", "503")])
        try:
            await g.generate(role="fallback", system_instruction="", generation_config={}, messages=[])
            assert False, "phải raise"
        except LLMError as e:
            assert e.kind == "unavailable"
        assert clients["genai"].calls == ["m2"]

    asyncio.run(run())


def test_fallback_skipped_when_same_model():
    async def run():
        resp = LLMResponse([])
        roles = {"final": SlotModel("genai", "m1", "final"), "fallback": SlotModel("genai", "m1", "fallback")}
        g, clients = make_gateway(roles, [resp])
        await g.generate(role="final", system_instruction="", generation_config={}, messages=[])
        assert clients["genai"].calls == ["m1"]

    asyncio.run(run())


def test_generate_text_extracts():
    async def run():
        from src.core.llm.base import Candidate, Content, Part

        resp = LLMResponse([Candidate(Content([Part(text="kết quả")]))])
        roles = {"final": SlotModel("genai", "m1", "final")}
        g, clients = make_gateway(roles, [resp])
        assert await g.generate_text("tóm tắt", role="final") == "kết quả"

    asyncio.run(run())


if __name__ == "__main__":
    test_not_configured()
    test_primary_success()
    test_fallback_same_provider_on_transient()
    test_no_fallback_for_auth()
    test_fallback_role_does_not_chain()
    test_fallback_skipped_when_same_model()
    test_generate_text_extracts()
    print("ALL PASS")
