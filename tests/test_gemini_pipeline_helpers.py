"""Offline tests for GeminiPipeline pure helpers and key async control flows."""
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, ".")

from src.core.gemini_pipeline import (
    GeminiPipeline,
    _append_continuation_text,
    _build_fallback_system_prompt,
    _build_synthesis_messages,
    _candidate_text,
    _clean_response_artifacts,
    _continuation_prompt,
    _extract_image_recognition_result,
    _extract_intent_blocks,
    _finish_reason_text,
    _has_minimum_evidence_block,
    _has_minimum_search_evidence,
    _is_block_sufficient,
    _is_tool_result_sufficient,
    _is_truncated_candidate,
    _long_output_prompt,
    _looks_semantically_incomplete,
    _parse_quality_counts,
    _prepare_user_context_block,
    _prepare_user_input_block,
    _prepare_user_metadata_block,
)


# ---------------- user block helpers ----------------
def test_prepare_user_input_block_short():
    assert "<USER_INPUT>" in _prepare_user_input_block("hello")
    assert "hello" in _prepare_user_input_block("hello")


def test_prepare_user_input_block_truncates():
    text = "x" * 3000
    out = _prepare_user_input_block(text, max_chars=200)
    assert "truncated" in out
    assert len(out) < 400


def test_prepare_user_metadata_block_admin():
    out = _prepare_user_metadata_block({"discord_display_name": "  Alice  ", "is_admin": True})
    assert "Admin" in out
    assert "Alice" in out
    assert "Discord Display Name" in out


def test_prepare_user_metadata_block_unknown():
    out = _prepare_user_metadata_block({})
    assert "Unknown" in out
    assert "Standard User" in out


def test_prepare_user_context_block_combines():
    out = _prepare_user_context_block("hi", {"is_admin": False})
    assert "<USER_METADATA>" in out
    assert "<USER_INPUT>" in out
    assert "hi" in out


# ---------------- intent/evidence parsing ----------------
def test_extract_intent_blocks_empty():
    assert _extract_intent_blocks("") == {}
    assert _extract_intent_blocks(None) == {}


def test_extract_intent_blocks_multi():
    text = "[web_search|intent=weather]\nSunny\n[web_search|intent=news]\nBreaking"
    blocks = _extract_intent_blocks(text)
    assert blocks == {"weather": "Sunny", "news": "Breaking"}


def test_parse_quality_counts_empty():
    assert _parse_quality_counts("") == (None, None)


def test_parse_quality_counts_found():
    assert _parse_quality_counts("required quality sources: 3\nquality sources found: 5") == (3, 5)


def test_is_block_sufficient_true():
    text = "top ranked sources\nrequired quality sources: 2\nquality sources found: 2"
    assert _is_block_sufficient(text) is True


def test_is_block_sufficient_false_insufficient():
    text = "top ranked sources\nrequired quality sources: 3\nquality sources found: 1"
    assert _is_block_sufficient(text) is False


def test_is_block_sufficient_false_no_markers():
    assert _is_block_sufficient("no markers here") is False


def test_has_minimum_evidence_block_found_gt0():
    assert _has_minimum_evidence_block("quality sources found: 2") is True


def test_has_minimum_evidence_block_extra_sources():
    assert _has_minimum_evidence_block("additional corroborating sources:\nfoo") is True


def test_is_tool_result_sufficient_intents():
    text = "[web_search|intent=a]\ntop ranked sources\nrequired quality sources: 1\nquality sources found: 1"
    assert _is_tool_result_sufficient(text) is True


def test_has_minimum_search_evidence_any_intent():
    text = "[web_search|intent=a]\nquality sources found: 2\n[web_search|intent=b]\nno evidence"
    assert _has_minimum_search_evidence(text) is True


# ---------------- semantic/artifact helpers ----------------
def test_looks_semantically_incomplete_short():
    assert _looks_semantically_incomplete("short") is False


def test_looks_semantically_incomplete_unclosed_code():
    assert _looks_semantically_incomplete("some text " * 20 + "```") is True


def test_looks_semantically_incomplete_ends_with_connector():
    assert _looks_semantically_incomplete("some text " * 20 + "và") is True


def test_clean_response_artifacts_removes_thinking():
    out = _clean_response_artifacts("before <THINKING>secret</THINKING> after")
    assert "secret" not in out
    assert "before" in out


def test_clean_response_artifacts_removes_tool_code():
    out = _clean_response_artifacts("x <tool_code>web_search(query='a')</tool_code> y")
    assert "web_search" not in out


def test_extract_image_recognition_result_simple():
    text = "[image_recognition]\nA cat"
    assert _extract_image_recognition_result(text) == "A cat"


def test_extract_image_recognition_result_empty():
    assert _extract_image_recognition_result("") == ""
    assert _extract_image_recognition_result("no image result") == ""


# ---------------- candidate helpers ----------------
def _part(text=None, function_call=None):
    return SimpleNamespace(text=text, function_call=function_call)


def _candidate(parts, finish="STOP"):
    finish_obj = SimpleNamespace(name=finish)
    return SimpleNamespace(
        content=SimpleNamespace(parts=parts),
        finish_reason=finish_obj,
    )


def test_candidate_text_joins_parts():
    cand = _candidate([_part("Hello "), _part("world")])
    assert _candidate_text(cand) == "Hello world"


def test_candidate_text_returns_empty_when_no_text():
    cand = _candidate([_part(None)])
    assert _candidate_text(cand) == ""


def test_finish_reason_text_name():
    cand = _candidate([_part("x")], finish="MAX_TOKENS")
    assert _finish_reason_text(cand) == "max_tokens"


def test_is_truncated_candidate_max_tokens():
    cand = _candidate([_part("x")], finish="MAX_TOKENS")
    assert _is_truncated_candidate(cand) is True


def test_is_truncated_candidate_stop():
    cand = _candidate([_part("x")], finish="STOP")
    assert _is_truncated_candidate(cand) is False


def test_is_truncated_candidate_no_reason():
    cand = SimpleNamespace(finish_reason=None, content=SimpleNamespace(parts=[_part("x")]))
    assert _is_truncated_candidate(cand) is False


# ---------------- continuation helpers ----------------
def test_append_continuation_text_no_current():
    assert _append_continuation_text("", "incoming") == "incoming"


def test_append_continuation_text_no_incoming():
    assert _append_continuation_text("current", "") == "current"


def test_append_continuation_text_overlaps():
    # overlap detection only runs when the overlap length is >=80
    tail = "shared" * 25  # 125 chars
    long_a = "x" * 200 + tail
    long_b = tail + "y" * 200
    assert _append_continuation_text(long_a, long_b) == "x" * 200 + tail + "y" * 200


def test_append_continuation_text_fallback_join():
    out = _append_continuation_text("aaaa", "bbbb")
    assert out == "aaaa\n\nbbbb"


def test_continuation_prompt_contains_tail():
    out = _continuation_prompt("some accumulated text", 2, 5)
    assert "[CONTINUATION REQUEST]" in out
    assert "2/5" in out


def test_long_output_prompt_extends_base():
    out = _long_output_prompt("BASE")
    assert out.startswith("BASE")
    assert "[LONG OUTPUT MODE]" in out


# ---------------- synthesis messages ----------------
def test_build_synthesis_messages_no_images():
    msgs = [{"role": "user", "parts": [{"text": "hi"}]}]
    out = _build_synthesis_messages(msgs, "PROMPT", include_images=False)
    assert len(out) == 1
    assert out[0]["role"] == "user"
    assert out[0]["parts"][0]["text"] == "PROMPT"


def test_build_synthesis_messages_preserves_inline_image():
    msgs = [
        {"role": "assistant", "parts": [{"text": "x"}]},
        {"role": "user", "parts": [{"text": "hi"}, {"inline_data": {"data": b"img"}}]},
    ]
    out = _build_synthesis_messages(msgs, "P", include_images=True)
    # last user message's inline image is hoisted into the synthesis prompt parts
    assert len(out[0]["parts"]) == 2
    assert out[0]["parts"][1]["inline_data"]["data"] == b"img"


def test_build_fallback_system_prompt_substitutes():
    out = _build_fallback_system_prompt("hello", "reasoning", "tools")
    assert "hello" in out
    assert "reasoning" in out
    assert "tools" in out


# ---------------- async pipeline flows ----------------
class FakeConfig:
    REASONING_MAX_API_RETRIES = 1
    REASONING_MAX_LOOPS = 1
    SEARCH_ALLOW_PARTIAL_ANSWER = False
    SEARCH_ENABLE_EXTRA_RETRIEVAL_PASS = False
    MAX_SEARCH_CALLS_PER_TURN = 5
    FINAL_MAX_API_RETRIES = 1
    FINAL_MAX_OUTPUT_TOKENS = 100
    FALLBACK_MAX_API_RETRIES = 1
    FALLBACK_MAX_OUTPUT_TOKENS = 100
    FINAL_CONTINUATION_MAX_CALLS = 3


class FakeGateway:
    def __init__(self, response_candidates):
        self.call_candidates = response_candidates
        self.calls = 0
        self.last_kwargs = None

    async def generate(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        cand = self.call_candidates()
        return SimpleNamespace(candidates=[cand] if cand else [])

    def _is_invalid_key_error(self, s):
        return "invalid key" in str(s)

    def _is_rate_limit_error(self, s):
        return "rate limit" in str(s)

    def _is_unavailable_error(self, s):
        return "unavailable" in str(s)

    def _is_connection_error(self, s):
        return "connection" in str(s)

    def log_exception(self, **kw):
        pass


class FakeTools:
    def __init__(self):
        self.calls = []

    def get_all_tools(self, is_admin=False):
        return []

    async def call_tool(self, fc, user_id):
        self.calls.append((fc.name, user_id))
        return "tool_result"


def make_pipeline(gateway, tools=None, config=None):
    return GeminiPipeline(
        config=config or FakeConfig(),
        api_mgr=gateway,
        tools_mgr=tools or FakeTools(),
        identity_builder=lambda privacy_context: "",
        reasoning_role="reasoning",
        final_role="final",
        fallback_role="fallback",
    )


def _step_candidate(text="final answer", finish="STOP", function_call=None):
    parts = []
    if function_call:
        parts.append(_part(text=None, function_call=function_call))
    if text:
        parts.append(_part(text))
    return _candidate(parts, finish=finish)


@pytest.mark.asyncio
async def test_call_gemini_api_image_result_short_circuits():
    gateway = FakeGateway(lambda: _step_candidate(text=None, function_call=SimpleNamespace(name="image_recognition", args={})))
    tools = FakeTools()

    # reasoning loop returns image result tool
    async def fake_call_tool(fc, user_id):
        return "[image_recognition]\nA cat"

    tools.call_tool = fake_call_tool
    pipeline = make_pipeline(gateway, tools)
    # image recognition tool in reasoning -> but tools_mgr must be called
    result = await pipeline.call_gemini_api(
        [{"role": "user", "parts": [{"text": "what is this?"}]}],
        "u1",
        {"is_admin": False, "bot_name": "Azuris"},
    )
    assert "A cat" in result


@pytest.mark.asyncio
async def test_final_synthesis_return_text():
    gateway = FakeGateway(lambda: _step_candidate(text="final answer", finish="STOP"))
    pipeline = make_pipeline(gateway)
    result = await pipeline._call_gemini_final(
        [{"role": "user", "parts": [{"text": "hi"}]}],
        "reasoning",
        "",
        "u1",
        {"is_admin": False},
    )
    assert result == "final answer"


@pytest.mark.asyncio
async def test_final_truncated_calls_continuation():
    # first call returns truncated candidate, continuation returns text
    state = {"n": 0}

    def next_candidate():
        state["n"] += 1
        if state["n"] == 1:
            return _step_candidate(text="partial ", finish="MAX_TOKENS")
        return _step_candidate(text="continued", finish="STOP")

    gateway = FakeGateway(next_candidate)
    pipeline = make_pipeline(gateway)
    result = await pipeline._call_gemini_final(
        [{"role": "user", "parts": [{"text": "hi"}]}],
        "reasoning",
        "",
        "u1",
        {"is_admin": False},
    )
    assert "partial" in result
    assert "continued" in result


@pytest.mark.asyncio
async def test_fallback_lite_returns_error_on_retry_exhausted():
    # gateway always raises connection error -> fallback also ends in user-facing error
    class ErrGateway(FakeGateway):
        async def generate(self, **kwargs):
            raise ConnectionError("connection failed")

        def _is_connection_error(self, s):
            return True

        def _is_invalid_key_error(self, s):
            return False

        def _is_rate_limit_error(self, s):
            return False

    pipeline = make_pipeline(ErrGateway(None))
    result = await pipeline._call_gemini_final(
        [{"role": "user", "parts": [{"text": "hi"}]}],
        "reasoning",
        "",
        "u1",
        {"is_admin": False},
    )
    assert "thử lại" in result


@pytest.mark.asyncio
async def test_reasoning_loop_text_result():
    gateway = FakeGateway(lambda: _step_candidate(text="reasoned", finish="STOP"))
    tools = FakeTools()
    pipeline = make_pipeline(gateway, tools)
    result, tool_results = await pipeline._call_gemini_reasoning_loop(
        [{"role": "user", "parts": [{"text": "hi"}]}],
        "u1",
        {"is_admin": False},
    )
    assert result == "reasoned"


@pytest.mark.asyncio
async def test_reasoning_loop_function_call_collects():
    fc = SimpleNamespace(name="calculate", args={"equation": "6*7"}, id="1")
    gateway = FakeGateway(lambda: _step_candidate(text=None, finish="STOP", function_call=fc))
    tools = FakeTools()
    pipeline = make_pipeline(gateway, tools)
    result, tool_results = await pipeline._call_gemini_reasoning_loop(
        [{"role": "user", "parts": [{"text": "calc"}]}],
        "u1",
        {"is_admin": False},
    )
    assert result == "Reasoning completed"
    assert "[calculate]" in tool_results
    assert tools.calls[0][0] == "calculate"


@pytest.mark.asyncio
async def test_continue_final_output_handles_rate_limit_then_success():
    state = {"n": 0}

    class RLGateway(FakeGateway):
        async def generate(self, **kwargs):
            state["n"] += 1
            if state["n"] == 1:
                raise Exception("rate limit hit")
            return SimpleNamespace(candidates=[_step_candidate(text="continued", finish="STOP")])

        def _is_rate_limit_error(self, s):
            return "rate limit" in str(s)

        def _is_unavailable_error(self, s):
            return False

        def _is_invalid_key_error(self, s):
            return False

        def _is_connection_error(self, s):
            return False

    pipeline = make_pipeline(RLGateway(None))
    result = await pipeline._continue_final_output(
        accumulated_text="partial",
        system_instruction="sys",
        generation_config={},
        slot_role="final",
        user_id="u1",
        stage="final_flash",
    )
    assert result == "partial\n\ncontinued"


@pytest.mark.asyncio
async def test_continue_final_output_stops_on_invalid_key():
    class KeyGateway(FakeGateway):
        async def generate(self, **kwargs):
            raise Exception("invalid key abc")

        def _is_invalid_key_error(self, s):
            return "invalid key" in str(s)

        def _is_rate_limit_error(self, s):
            return False

        def _is_connection_error(self, s):
            return False

    pipeline = make_pipeline(KeyGateway(None))
    result = await pipeline._continue_final_output(
        accumulated_text="partial",
        system_instruction="sys",
        generation_config={},
        slot_role="final",
        user_id="u1",
        stage="final_flash",
    )
    assert result == "partial"


@pytest.mark.asyncio
async def test_fallback_lite_success_returns_text():
    gateway = FakeGateway(lambda: _step_candidate(text="lite answer", finish="STOP"))
    pipeline = make_pipeline(gateway)
    result = await pipeline._fallback_lite_as_flash(
        [{"role": "user", "parts": [{"text": "hi"}]}],
        "reasoning",
        "",
        "u1",
        {"is_admin": False},
    )
    assert result == "lite answer"


@pytest.mark.asyncio
async def test_fallback_lite_truncated_continuation():
    state = {"n": 0}

    def next_candidate():
        state["n"] += 1
        if state["n"] == 1:
            return _step_candidate(text="partial ", finish="MAX_TOKENS")
        return _step_candidate(text="continued", finish="STOP")

    pipeline = make_pipeline(FakeGateway(next_candidate))
    result = await pipeline._fallback_lite_as_flash(
        [{"role": "user", "parts": [{"text": "hi"}]}],
        "reasoning",
        "",
        "u1",
        {"is_admin": False},
    )
    assert "partial" in result
    assert "continued" in result


@pytest.mark.asyncio
async def test_fallback_lite_invalid_key_returns_user_error():
    class KeyGateway(FakeGateway):
        async def generate(self, **kwargs):
            raise Exception("invalid key abc")

        def _is_invalid_key_error(self, s):
            return "invalid key" in str(s)

        def _is_rate_limit_error(self, s):
            return False

        def _is_connection_error(self, s):
            return False

    pipeline = make_pipeline(KeyGateway(None))
    result = await pipeline._fallback_lite_as_flash(
        [{"role": "user", "parts": [{"text": "hi"}]}],
        "reasoning",
        "",
        "u1",
        {"is_admin": False},
    )
    assert "thử lại" in result


@pytest.mark.asyncio
async def test_final_rate_limit_fallback_to_lite():
    state = {"n": 0}

    class RLGateway(FakeGateway):
        async def generate(self, **kwargs):
            state["n"] += 1
            if state["n"] <= 1:
                raise Exception("rate limit hit")
            return SimpleNamespace(candidates=[_step_candidate(text="lite answer", finish="STOP")])

        def _is_rate_limit_error(self, s):
            return "rate limit" in str(s)

        def _is_unavailable_error(self, s):
            return False

        def _is_invalid_key_error(self, s):
            return False

        def _is_connection_error(self, s):
            return False

        def log_exception(self, **kw):
            pass

    pipeline = make_pipeline(RLGateway(None))
    result = await pipeline._call_gemini_final(
        [{"role": "user", "parts": [{"text": "hi"}]}],
        "reasoning",
        "",
        "u1",
        {"is_admin": False},
    )
    assert "lite answer" in result


@pytest.mark.asyncio
async def test_final_invalid_key_breaks_to_fallback():
    class KeyGateway(FakeGateway):
        async def generate(self, **kwargs):
            raise Exception("invalid key abc")

        def _is_invalid_key_error(self, s):
            return "invalid key" in str(s)

        def _is_rate_limit_error(self, s):
            return False

        def _is_connection_error(self, s):
            return False

        def log_exception(self, **kw):
            pass

    pipeline = make_pipeline(KeyGateway(None))
    result = await pipeline._call_gemini_final(
        [{"role": "user", "parts": [{"text": "hi"}]}],
        "reasoning",
        "",
        "u1",
        {"is_admin": False},
    )
    assert "thử lại" in result


@pytest.mark.asyncio
async def test_final_connection_error_retries_then_empty_candidate():
    state = {"n": 0}

    class ConnGateway(FakeGateway):
        async def generate(self, **kwargs):
            state["n"] += 1
            if state["n"] <= 1:
                raise ConnectionError("connection reset")
            return SimpleNamespace(candidates=[])

        def _is_connection_error(self, s):
            return True

        def _is_invalid_key_error(self, s):
            return False

        def _is_rate_limit_error(self, s):
            return False

        def log_exception(self, **kw):
            pass

    pipeline = make_pipeline(ConnGateway(None))
    result = await pipeline._call_gemini_final(
        [{"role": "user", "parts": [{"text": "hi"}]}],
        "reasoning",
        "",
        "u1",
        {"is_admin": False},
    )
    assert "thử lại" in result


@pytest.mark.asyncio
async def test_call_gemini_api_extra_retrieval_pass():
    class ExtraConfig(FakeConfig):
        SEARCH_ENABLE_EXTRA_RETRIEVAL_PASS = True
        SEARCH_ALLOW_PARTIAL_ANSWER = False

    # reasoning loop returns insufficient evidence, then retry pass, then final
    state = {"calls": 0}

    class FlowGateway(FakeGateway):
        async def generate(self, **kwargs):
            state["calls"] += 1
            if state["calls"] <= 2:
                return SimpleNamespace(candidates=[_step_candidate(text=None, function_call=SimpleNamespace(name="web_search", args={"query": "q"}))])
            return SimpleNamespace(candidates=[_step_candidate(text="final answer", finish="STOP")])

        def _is_invalid_key_error(self, s):
            return False

        def _is_rate_limit_error(self, s):
            return False

        def _is_connection_error(self, s):
            return False

        def log_exception(self, **kw):
            pass

    tools = FakeTools()

    async def fake_call_tool(fc, user_id):
        return "top ranked sources\nrequired quality sources: 2\nquality sources found: 1"

    tools.call_tool = fake_call_tool
    pipeline = make_pipeline(FlowGateway(None), tools, ExtraConfig())
    result = await pipeline.call_gemini_api(
        [{"role": "user", "parts": [{"text": "search this"}]}],
        "u1",
        {"is_admin": False},
    )
    assert result == "final answer"
    assert state["calls"] >= 3
