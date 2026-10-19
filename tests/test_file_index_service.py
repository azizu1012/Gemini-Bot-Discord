"""Test FileIndexService đi qua LLMGateway (offline, không cần mạng)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.llm.base import Candidate, Content, LLMError, LLMResponse, Part
from src.services.file_index_service import FileIndexService


class FakeGateway:
    def __init__(self, response_text=None, error=None):
        self.response_text = response_text
        self.error = error
        self.calls = []
        self.logged = []

    async def generate(self, *, role, system_instruction, generation_config, messages, tools=None):
        self.calls.append({"role": role, "messages": messages, "system_instruction": system_instruction})
        if self.error is not None:
            raise self.error
        return LLMResponse([Candidate(Content([Part(text=self.response_text)]))])

    def log_exception(self, **kwargs):
        self.logged.append(kwargs)


def make_service(gateway):
    return FileIndexService(
        config=None,
        db_repo=None,
        file_parser=None,
        gateway=gateway,
        reasoning_role="reasoning",
        final_role="final",
    )


def test_index_chunk_uses_gateway_with_reasoning_role():
    gw = FakeGateway(response_text='{"title": "T", "summary": "S", "keywords": ["k"]}')
    svc = make_service(gw)
    result = asyncio.run(
        svc.index_chunk_with_reasoning(
            file_name="a.txt",
            chunk_id="doc:1",
            chunk_source={"path": "a.txt"},
            chunk_text="nội dung",
            security_report="clean",
            user_id="u1",
        )
    )
    assert result == {"title": "T", "summary": "S", "keywords": ["k"]}
    assert len(gw.calls) == 1
    assert gw.calls[0]["role"] == "reasoning"
    assert gw.calls[0]["messages"][0]["parts"][0]["text"].startswith("FILE_NAME: a.txt")


def test_index_chunk_gateway_error_is_logged_and_returns_empty():
    gw = FakeGateway(error=LLMError("rate_limit", "boom"))
    svc = make_service(gw)
    result = asyncio.run(
        svc.index_chunk_with_reasoning(
            file_name="a.txt",
            chunk_id="doc:1",
            chunk_source={},
            chunk_text="nội dung",
            security_report="",
            user_id="u1",
        )
    )
    assert result == {}
    assert gw.logged[0]["stage"] == "file_index_chunk"
    assert gw.logged[0]["role"] == "reasoning"
    assert gw.logged[0]["user_id"] == "u1"


def test_validate_file_index_uses_final_role():
    gw = FakeGateway(response_text='{"status": "ok", "risk_flags": []}')
    svc = make_service(gw)
    result = asyncio.run(
        svc.validate_file_index(
            {"file_name": "a.txt", "chunks": [{"title": "T", "summary": "S"}], "security_report": ""},
            user_id="u1",
        )
    )
    assert result == {"status": "ok", "risk_flags": []}
    assert gw.calls[0]["role"] == "final"


if __name__ == "__main__":
    test_index_chunk_uses_gateway_with_reasoning_role()
    test_index_chunk_gateway_error_is_logged_and_returns_empty()
    test_validate_file_index_uses_final_role()
    print("ALL PASS")
