import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptography.fernet import Fernet

from src.core.config import logger
from src.core.llm.resolver import (
    EndpointResolver,
    decrypt_api_key,
    encrypt_api_key,
    mask_api_key,
    resolve_model_id,
)


class FakeRepo:
    def __init__(self, endpoints=None, slots=None, active=None):
        self.endpoints = endpoints or {}
        self.slots = slots or {}
        self.active = active

    async def get_llm_endpoints(self):
        return self.endpoints

    async def get_active_sdk(self):
        return self.active

    async def get_llm_model_slots(self, sdk):
        return dict(self.slots.get(sdk, {}))


def test_encrypt_roundtrip():
    key = Fernet.generate_key().decode()
    stored = encrypt_api_key("secret-123", key)
    assert stored.startswith("fernet:")
    assert decrypt_api_key(stored, key) == "secret-123"


def test_plain_fallback_when_no_fernet_key():
    stored = encrypt_api_key("secret-456", "")
    assert stored == "plain:secret-456"
    assert decrypt_api_key(stored, "") == "secret-456"


def test_mask():
    assert mask_api_key("abcdefgh") == "...efgh"
    assert mask_api_key("") == "<chưa cấu hình>"
    assert mask_api_key("abc") == "****"


def test_resolve_model_id_default_rules():
    slots = {"final": "m-final"}
    assert resolve_model_id(slots, "final") == "m-final"
    assert resolve_model_id(slots, "reasoning") == "m-final"
    assert resolve_model_id(slots, "fallback") == "m-final"
    assert resolve_model_id(slots, "vision") == "m-final"

    slots2 = {"final": "m-final", "reasoning": "m-reason", "fallback": "m-fb", "vision": "m-vis"}
    assert resolve_model_id(slots2, "reasoning") == "m-reason"
    assert resolve_model_id(slots2, "fallback") == "m-fb"
    assert resolve_model_id(slots2, "vision") == "m-vis"

    assert resolve_model_id({}, "final") is None


def test_resolver_flow():
    async def run():
        fernet = Fernet.generate_key().decode()
        repo = FakeRepo(
            endpoints={
                "genai": {
                    "sdk": "genai",
                    "base_url": "http://127.0.0.1:58100",
                    "api_key_encrypted": encrypt_api_key("router-key", fernet),
                    "is_active": True,
                }
            },
            slots={"genai": {"final": "gemini-3-flash-preview"}},
            active="genai",
        )
        r = EndpointResolver(config=type("C", (), {"DONATE_ENCRYPTION_KEY": fernet})(), logger=logger, cache_ttl_seconds=0.01)
        r.set_db_repo(repo)

        assert await r.get_active_sdk() == "genai"
        assert await r.is_configured() is True
        ep = await r.get_endpoint("genai")
        assert ep["api_key"] == "router-key"
        assert ep["base_url"] == "http://127.0.0.1:58100"

        sm = await r.resolve_role("vision")
        assert sm.sdk == "genai"
        assert sm.model_id == "gemini-3-flash-preview"

        # Chưa cấu hình
        repo2 = FakeRepo()
        r2 = EndpointResolver(config=type("C", (), {"DONATE_ENCRYPTION_KEY": ""})(), logger=logger)
        r2.set_db_repo(repo2)
        assert await r2.is_configured() is False
        assert await r2.resolve_role("final") is None

    asyncio.run(run())


if __name__ == "__main__":
    test_encrypt_roundtrip()
    test_plain_fallback_when_no_fernet_key()
    test_mask()
    test_resolve_model_id_default_rules()
    test_resolver_flow()
    print("ALL PASS")
