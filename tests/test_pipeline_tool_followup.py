"""Regression: after a tool call, do not send a functionResponse follow-up.

The upstream provider can hold its lite pool slot on native functionResponse
turns and time out with "no free member". The pipeline must defer to the
text-only final synthesis stage instead.
"""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.gemini_pipeline import GeminiPipeline


class FakeConfig:
    REASONING_MAX_API_RETRIES = 1
    REASONING_MAX_LOOPS = 3
    SEARCH_ALLOW_PARTIAL_ANSWER = False
    SEARCH_ENABLE_EXTRA_RETRIEVAL_PASS = False
    MAX_SEARCH_CALLS_PER_TURN = 5
    FINAL_MAX_API_RETRIES = 1
    FINAL_MAX_OUTPUT_TOKENS = 100


class FakeGateway:
    def __init__(self):
        self.calls = 0
        self.last_kwargs = None

    async def generate(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        function_call = SimpleNamespace(name="get_weather", args={"city": "Hanoi"})
        part = SimpleNamespace(function_call=function_call, text=None)
        candidate = SimpleNamespace(content=SimpleNamespace(parts=[part]))
        return SimpleNamespace(candidates=[candidate])


class FakeTools:
    def get_all_tools(self, is_admin=False):
        return []

    async def call_tool(self, function_call, user_id):
        return "Hanoi: 30C, sunny"


def build_pipeline(gateway):
    return GeminiPipeline(
        config=FakeConfig(),
        api_mgr=gateway,
        tools_mgr=FakeTools(),
        identity_builder=lambda privacy_context: "",
        reasoning_role="reasoning",
        final_role="final",
        fallback_role="fallback",
    )


def test_tool_call_defers_to_final_synthesis_without_function_response_followup():
    gateway = FakeGateway()
    pipeline = build_pipeline(gateway)

    reasoning_result, tool_results = asyncio.run(
        pipeline._call_gemini_reasoning_loop(
            [{"role": "user", "parts": [{"text": "Weather in Hanoi?"}]}],
            "test-user",
            {"is_admin": False, "bot_name": "Azuris"},
        )
    )

    assert reasoning_result == "Reasoning completed"
    assert tool_results == "[get_weather] Hanoi: 30C, sunny"
    assert gateway.calls == 1

    sent_parts = [
        part
        for message in gateway.last_kwargs["messages"]
        for part in message.get("parts", [])
    ]
    assert all("function_response" not in part for part in sent_parts)
