"""Offline tests for FileParserService.parse_attachment / prepare_file_for_indexing."""
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, ".")

from src.services.indexing.parser import FileParserService


class NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


def make_parser():
    p = FileParserService(storage_path="data")
    p.logger = NullLogger()
    return p


@pytest.mark.asyncio
async def test_parse_attachment_download_error():
    p = make_parser()
    p._download_attachment = AsyncMock(return_value=(None, "download failed"))
    result = await p.parse_attachment("http://x", "a.txt")
    assert "download failed" in result["content"]


@pytest.mark.asyncio
async def test_parse_attachment_txt():
    p = make_parser()
    p._download_attachment = AsyncMock(return_value=("/tmp/a.txt", None))
    p._read_text_file = MagicMock(return_value=("hello world", False))
    p._build_security_report = MagicMock(return_value=("hello world", "[SECURITY] clean"))
    result = await p.parse_attachment("http://x", "a.txt")
    assert "hello world" in result["content"]
    assert "FILE TEXT START" in result["content"]


@pytest.mark.asyncio
async def test_parse_attachment_csv():
    p = make_parser()
    p._download_attachment = AsyncMock(return_value=("/tmp/a.csv", None))
    p._read_csv_file = MagicMock(return_value=("a,b", False))
    p._build_security_report = MagicMock(return_value=("a,b", "[SECURITY] clean"))
    result = await p.parse_attachment("http://x", "a.csv")
    assert "a,b" in result["content"]


@pytest.mark.asyncio
async def test_parse_attachment_pdf_missing_library():
    p = make_parser()
    p._download_attachment = AsyncMock(return_value=("/tmp/a.pdf", None))
    import src.services.indexing.parser as parser_mod

    old = parser_mod.pypdf
    parser_mod.pypdf = None
    try:
        result = await p.parse_attachment("http://x", "a.pdf")
        assert "pypdf" in result["content"]
    finally:
        parser_mod.pypdf = old


@pytest.mark.asyncio
async def test_parse_attachment_binary_fallback():
    p = make_parser()
    p._download_attachment = AsyncMock(return_value=("/tmp/a.xyz", None))
    p._read_text_file = MagicMock(return_value=("\x00\x01\x02", False))
    p._looks_binary = MagicMock(return_value=True)
    result = await p.parse_attachment("http://x", "a.xyz")
    assert "không thể đọc" in result["content"]


@pytest.mark.asyncio
async def test_parse_attachment_exception_handled():
    p = make_parser()
    p._download_attachment = AsyncMock(return_value=("/tmp/a.txt", None))
    p._read_text_file = MagicMock(side_effect=RuntimeError("boom"))
    result = await p.parse_attachment("http://x", "a.txt")
    assert "Lỗi" in result["content"] or "không thể" in result["content"]


@pytest.mark.asyncio
async def test_prepare_file_for_indexing_success():
    p = make_parser()
    p._download_attachment = AsyncMock(return_value=("/tmp/a.txt", None))
    p._build_chunk_manifest = MagicMock(return_value=([{"chunk_id": "c1"}], "sec", False))
    result = await p.prepare_file_for_indexing("http://x", "a.txt")
    assert result["file_extension"] == ".txt"
    assert result["chunk_manifest"] == [{"chunk_id": "c1"}]
    assert result["security_report"] == "sec"


@pytest.mark.asyncio
async def test_prepare_file_for_indexing_download_error():
    p = make_parser()
    p._download_attachment = AsyncMock(return_value=(None, "error"))
    result = await p.prepare_file_for_indexing("http://x", "a.txt")
    assert "error" in result["error"]


@pytest.mark.asyncio
async def test_prepare_file_for_indexing_exception():
    p = make_parser()
    p._download_attachment = AsyncMock(return_value=("/tmp/a.txt", None))
    p._build_chunk_manifest = MagicMock(side_effect=RuntimeError("boom"))
    result = await p.prepare_file_for_indexing("http://x", "a.txt")
    assert "chuẩn bị" in result["error"]
