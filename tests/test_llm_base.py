import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.llm.base import (
    Candidate,
    Content,
    FunctionCall,
    LLMError,
    LLMNotConfiguredError,
    LLMResponse,
    Part,
    SlotModel,
    classify_error,
    extract_status_code,
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


def test_classify_status_code_attribute_wins():
    class HttpError(Exception):
        def __init__(self, message, status_code):
            super().__init__(message)
            self.status_code = status_code

    assert classify_error(HttpError("boom", 403)) == "auth"
    assert classify_error(HttpError("boom", 429)) == "rate_limit"
    assert classify_error(HttpError("boom", 503)) == "unavailable"
    assert classify_error(HttpError("boom", 404)) == "not_found"
    # Mã lỗi xuất hiện nhưng không phải HTTP status → không được coi là not_found.
    assert classify_error(Exception("processed 404 tokens")) == "other"


def test_extract_status_code_ignores_bare_numbers():
    assert extract_status_code(Exception("processed 404 tokens")) is None
    assert extract_status_code(Exception("GenAI endpoint HTTP 403: denied")) == 403


def test_extract_status_code_google_genai_error_shape():
    class GenAIAPIError(Exception):
        """Mô phỏng google.genai.errors.APIError: .code int, .status là enum text."""

        def __init__(self, code, status):
            super().__init__(f"{code} {status}. details")
            self.code = code
            self.status = status

    assert extract_status_code(GenAIAPIError(403, "PERMISSION_DENIED")) == 403
    assert classify_error(GenAIAPIError(429, "RESOURCE_EXHAUSTED")) == "rate_limit"


if __name__ == "__main__":
    test_shapes()
    test_error_classes()
    test_classify()
    test_classify_status_code_attribute_wins()
    test_extract_status_code_ignores_bare_numbers()
    print("ALL PASS")
