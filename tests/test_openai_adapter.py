import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import logger
from src.core.llm.base import FunctionCall, Part
from src.core.llm.openai_client import (
    DEFAULT_OPENAI_BASE_URL,
    OpenAIClient,
    normalize_schema,
    to_json_schema,
    tools_to_openai,
)


def make_client():
    return OpenAIClient(base_url="http://127.0.0.1:58100/v1", api_key="router-key", logger=logger)


def test_default_constant():
    assert DEFAULT_OPENAI_BASE_URL == "https://api.openai.com/v1"


def test_convert_system_and_text():
    c = make_client()
    msgs = c.convert_messages("SYS", [{"role": "user", "parts": [{"text": "hello"}]}])
    assert msgs[0] == {"role": "system", "content": "SYS"}
    assert msgs[1] == {"role": "user", "content": "hello"}


def test_convert_model_role_to_assistant():
    c = make_client()
    msgs = c.convert_messages(None, [{"role": "model", "parts": [{"text": "câu trả lời"}]}])
    assert msgs[0]["role"] == "assistant"
    assert msgs[0]["content"] == "câu trả lời"


def test_convert_image_bytes_to_data_url():
    c = make_client()
    msg = {"role": "user", "parts": [{"text": "xem ảnh"}, {"inline_data": {"data": b"\x89PNG", "mime_type": "image/png"}}]}
    msgs = c.convert_messages(None, [msg])
    content = msgs[0]["content"]
    assert content[0] == {"type": "text", "text": "xem ảnh"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_convert_function_call_and_response_id_matching():
    c = make_client()
    msgs = c.convert_messages(None, [
        {"role": "model", "parts": [{"function_call": {"name": "web_search", "args": {"query": "a"}}}]},
        {"role": "user", "parts": [{"function_response": {"name": "web_search", "response": {"content": "kết quả A"}}}]},
        {"role": "model", "parts": [{"function_call": {"name": "web_search", "args": {"query": "b"}}}]},
        {"role": "user", "parts": [{"function_response": {"name": "web_search", "response": {"content": "kết quả B"}}}]},
    ])
    assert msgs[0]["role"] == "assistant"
    call_a = msgs[0]["tool_calls"][0]
    assert call_a["function"]["name"] == "web_search"
    assert msgs[1]["role"] == "tool" and msgs[1]["tool_call_id"] == call_a["id"]
    assert msgs[1]["content"] == "kết quả A"
    call_b = msgs[2]["tool_calls"][0]
    assert msgs[3]["tool_call_id"] == call_b["id"]
    assert call_a["id"] != call_b["id"]


def test_convert_part_objects():
    c = make_client()
    parts = [
        Part(text="xin chào"),
        Part(function_call=FunctionCall(name="get_weather", args={"city": "Hà Nội"}, id="call_obj_1")),
    ]
    msgs = c.convert_messages(None, [{"role": "model", "parts": parts}])
    assert msgs[0]["content"] == "xin chào"
    assert msgs[0]["tool_calls"][0]["id"] == "call_obj_1"
    assert msgs[0]["tool_calls"][0]["function"]["arguments"] == '{"city": "Hà Nội"}'


def test_tools_conversion():
    class FakeDecl:
        def __init__(self, name, description, parameters):
            self.name = name
            self.description = description
            self.parameters = parameters

    class FakeTool:
        def __init__(self, decls):
            self.function_declarations = decls

    tool = FakeTool([FakeDecl("web_search", "tìm kiếm", {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]})])
    out = tools_to_openai([tool])
    assert out[0]["type"] == "function"
    assert out[0]["function"]["name"] == "web_search"
    assert out[0]["function"]["parameters"]["properties"]["query"]["type"] == "string"


def test_schema_normalization():
    assert normalize_schema({"type": "OBJECT", "properties": {"a": {"type": "STRING"}}}) == {
        "type": "object",
        "properties": {"a": {"type": "string"}},
    }
    assert to_json_schema(None) == {"type": "object", "properties": {}}


def test_emulate_response_text_and_tool_calls():
    c = make_client()
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="đang nghĩ",
                    tool_calls=[
                        SimpleNamespace(
                            id="call_9",
                            function=SimpleNamespace(name="calculator", arguments='{"expression": "1+1"}'),
                        )
                    ],
                ),
                finish_reason="tool_calls",
            )
        ]
    )
    resp = c.emulate_response(completion)
    parts = resp.candidates[0].content.parts
    assert parts[0].text == "đang nghĩ"
    fc = parts[1].function_call
    assert fc.name == "calculator"
    assert fc.args == {"expression": "1+1"}
    assert fc.id == "call_9"
    assert resp.candidates[0].finish_reason.name == "STOP"


def test_emulate_response_length_finish():
    c = make_client()
    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="abc", tool_calls=None), finish_reason="length")]
    )
    resp = c.emulate_response(completion)
    assert resp.candidates[0].finish_reason.name == "MAX_TOKENS"


if __name__ == "__main__":
    test_default_constant()
    test_convert_system_and_text()
    test_convert_model_role_to_assistant()
    test_convert_image_bytes_to_data_url()
    test_convert_function_call_and_response_id_matching()
    test_convert_part_objects()
    test_tools_conversion()
    test_schema_normalization()
    test_emulate_response_text_and_tool_calls()
    test_emulate_response_length_finish()
    print("ALL PASS")
