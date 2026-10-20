import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.llm.base import (
    Candidate,
    Content,
    FinishReason,
    FunctionCall,
    LLMError,
    LLMNotConfiguredError,
    LLMResponse,
    Part,
    SlotModel,
    classify_error,
    SLOTS,
)


def test_shapes():
    part = Part(text="xin chào")
    resp = LLMResponse([Candidate(Content([part]))])
    assert resp.candidates[0].content.parts[0].text == "xin chào"
    assert resp.candidates[0].finish_reason.name == "STOP"

    fc = FunctionCall(name="web_search", args={"query": "abc"}, id="call_1")
    p2 = Part(function_call=fc)
    assert p2.function_call.name == "web_search"
    assert p2.text is None

    sm = SlotModel(sdk="genai", model_id="gemini-3-flash-preview", role="final")
    assert (sm.sdk, sm.model_id, sm.role) == ("genai", "gemini-3-flash-preview", "final")
    assert SLOTS == ("reasoning", "final", "fallback")


def test_error_classes():
    e = LLMNotConfiguredError()
    assert e.kind == "not_configured"
    e2 = LLMError("auth", "401 unauthorized", status_code=401)
    assert e2.status_code == 401


def test_classify():
    cases = [
        (LLMNotConfiguredError(), "not_configured"),
        (LLMError("rate_limit", "x"), "rate_limit"),
        (Exception("429 Too Many Requests"), "rate_limit"),
        (Exception("ResourceExhausted: quota exceeded"), "rate_limit"),
        (Exception("401 Unauthorized: API key not valid"), "auth"),
        (Exception("403 PERMISSION_DENIED"), "auth"),
        (Exception("503 Service Unavailable"), "unavailable"),
        (Exception("500 Internal Server Error"), "unavailable"),
        (Exception("Connection reset by peer"), "connection"),
        (Exception("model not found"), "not_found"),
        (Exception("some random failure"), "other"),
    ]
    for err, expected in cases:
        got = classify_error(err)
        assert got == expected, f"{err!r}: got {got}, expected {expected}"


if __name__ == "__main__":
    test_shapes()
    test_error_classes()
    test_classify()
    print("ALL PASS")
