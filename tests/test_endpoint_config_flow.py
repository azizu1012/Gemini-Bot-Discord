"""Regression test cho /endpoint config flow (modal interaction phải defer trước network)."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.handlers.discord.ui import EndpointConfigFlow


class FakeResponse:
    def __init__(self):
        self.deferred = False
        self.defer_kwargs = {}
        self.messages = []

    async def defer(self, **kwargs):
        self.deferred = True
        self.defer_kwargs = kwargs

    async def send_message(self, content=None, **kwargs):
        self.messages.append(content)


class FakeMessage:
    async def edit(self, **kwargs):
        return None


class FakeFollowup:
    def __init__(self):
        self.messages = []

    async def send(self, content=None, **kwargs):
        self.messages.append(content)
        return FakeMessage()


class FakeInteraction:
    def __init__(self):
        self.response = FakeResponse()
        self.followup = FakeFollowup()


class FakeGateway:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.list_calls = 0
        self.interaction = None

    async def list_models_for(self, *, sdk, base_url, api_key):
        self.list_calls += 1
        # Interaction phải được defer trước khi gọi network, nếu không Discord
        # sẽ hết hạn interaction sau 3 giây và mọi followup.send sẽ thất bại.
        assert self.interaction is None or self.interaction.response.deferred is True
        if self.fail:
            raise RuntimeError("router unreachable")
        return [{"id": "gemini-flash", "display_name": "Gemini Flash"}]


class FakeResolver:
    def __init__(self):
        self.invalidated = False

    def invalidate(self):
        self.invalidated = True


class FakeRepo:
    def __init__(self):
        self.endpoint = None
        self.slots = None
        self.active = None

    async def save_endpoint_config(self, sdk, base_url, encrypted, slots, updated_by):
        self.endpoint = (sdk, base_url, encrypted, updated_by)
        self.slots = (sdk, slots, updated_by)
        self.active = sdk
        return True


class FakeConfig:
    DONATE_ENCRYPTION_KEY = ""
    ALLOW_PLAINTEXT_ENDPOINT_KEYS = True


class StrictEncryptionConfig(FakeConfig):
    ALLOW_PLAINTEXT_ENDPOINT_KEYS = False


def _make_flow(gateway, repo, config=None):
    flow = EndpointConfigFlow(
        gateway=gateway,
        resolver=FakeResolver(),
        db_repo=repo,
        config=config or FakeConfig(),
        admin_user_id="123",
    )

    async def fake_pickers(interaction, models):
        return {"reasoning": "gemini-flash", "final": "gemini-flash", "fallback": None, "vision": None}

    flow.run_slot_pickers = fake_pickers  # type: ignore[assignment]
    return flow


def test_modal_defers_before_listing_models():
    interaction = FakeInteraction()
    gateway = FakeGateway()
    gateway.interaction = interaction
    repo = FakeRepo()
    flow = _make_flow(gateway, repo)

    asyncio.run(flow.configure(interaction, "openai", "http://127.0.0.1:58100", "sk-test"))

    assert interaction.response.deferred is True
    assert interaction.response.defer_kwargs.get("ephemeral") is True
    assert gateway.list_calls == 1
    assert repo.endpoint is not None
    assert repo.endpoint[0] == "openai"
    assert repo.endpoint[1] == "http://127.0.0.1:58100/v1"
    assert repo.active == "openai"


def test_modal_error_after_defer_uses_followup():
    interaction = FakeInteraction()
    gateway = FakeGateway(fail=True)
    gateway.interaction = interaction
    repo = FakeRepo()
    flow = _make_flow(gateway, repo)

    asyncio.run(flow.configure(interaction, "openai", "127.0.0.1:58100", "bad-key"))

    assert interaction.response.deferred is True
    assert interaction.response.messages == []
    assert len(interaction.followup.messages) == 1
    assert "Không kết nối" in interaction.followup.messages[0]
    assert "router unreachable" not in interaction.followup.messages[0]
    assert repo.endpoint is None


def test_invalid_url_answers_without_defer():
    interaction = FakeInteraction()
    gateway = FakeGateway()
    gateway.interaction = interaction
    repo = FakeRepo()
    flow = _make_flow(gateway, repo)

    asyncio.run(flow.configure(interaction, "openai", "://bad-url", "key"))

    assert interaction.response.deferred is False
    assert gateway.list_calls == 0
    assert len(interaction.response.messages) == 1
    assert "không hợp lệ" in interaction.response.messages[0].lower()


def test_refuses_plaintext_key_without_encryption_key():
    interaction = FakeInteraction()
    gateway = FakeGateway()
    gateway.interaction = interaction
    repo = FakeRepo()
    flow = _make_flow(gateway, repo, config=StrictEncryptionConfig())

    asyncio.run(flow.configure(interaction, "openai", "http://127.0.0.1:58100", "sk-test"))

    assert interaction.response.deferred is False
    assert gateway.list_calls == 0
    assert repo.endpoint is None
    assert len(interaction.response.messages) == 1
    assert "DONATE_ENCRYPTION_KEY" in interaction.response.messages[0]


if __name__ == "__main__":
    test_modal_defers_before_listing_models()
    test_modal_error_after_defer_uses_followup()
    test_invalid_url_answers_without_defer()
    print("ok")
