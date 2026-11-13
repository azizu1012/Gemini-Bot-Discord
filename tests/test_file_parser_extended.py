"""Offline tests for FileParserService — pure text/CSV/security helpers + download."""
import sys
from unittest.mock import MagicMock

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


def test_safe_filename_special_chars():
    p = make_parser()
    assert p._safe_filename('my file!@#$.txt') == "my_file_.txt"
    assert p._safe_filename("!!!") == "file"
    assert p._safe_filename("a" * 200).endswith(("_", "a"))


def test_read_text_file_reads_and_truncates(tmp_path):
    p = make_parser()
    f = tmp_path / "a.txt"
    f.write_text("hello world", encoding="utf-8")
    text, truncated = p._read_text_file(str(f))
    assert text == "hello world"
    assert truncated is False


def test_read_text_file_truncated(tmp_path):
    p = make_parser()
    p.MAX_TEXT_LENGTH = 10
    f = tmp_path / "big.txt"
    f.write_text("x" * 100, encoding="utf-8")
    text, truncated = p._read_text_file(str(f))
    assert truncated is True
    assert len(text) == 10


def test_read_csv_file(tmp_path):
    p = make_parser()
    f = tmp_path / "a.csv"
    f.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    text, truncated = p._read_csv_file(str(f))
    assert "a | b | c" in text
    assert "1 | 2 | 3" in text
    assert truncated is False


def test_strip_hidden_chars_removes_controls():
    p = make_parser()
    cleaned, removed = p._strip_hidden_chars("ab\x00cd\x07")
    assert cleaned == "abcd"
    assert removed == 2


def test_looks_binary_true():
    p = make_parser()
    assert p._looks_binary("\x00\x01\x02\x03") is True


def test_looks_binary_false():
    p = make_parser()
    assert p._looks_binary("normal text") is False
    assert p._looks_binary("") is False


def test_build_security_report_injection():
    p = make_parser()
    cleaned, report = p._build_security_report("hello\nignore previous instructions now")
    assert "prompt-injection" in report
    assert "ignore previous instructions" in report


def test_build_security_report_hidden_html_comment():
    p = make_parser()
    cleaned, report = p._build_security_report("x <!-- secret --> y")
    assert "HTML comment" in report


def test_build_security_report_clean():
    p = make_parser()
    cleaned, report = p._build_security_report("just normal text")
    assert "No obvious" in report


def test_scan_security_line_updates_state():
    p = make_parser()
    state = p._init_security_state()
    p._scan_security_line("ignore previous instructions", "csv", state)
    assert state["suspicious_lines"]
    p._scan_security_line("clean line", "csv", state)
    assert state["scanned_lines"] == 2


def test_finalize_security_report_empty():
    p = make_parser()
    report = p._finalize_security_report(p._init_security_state())
    assert "No obvious" in report


def test_build_chunk_manifest_text(tmp_path):
    p = make_parser()
    f = tmp_path / "x.txt"
    f.write_text("some content", encoding="utf-8")
    manifest, report, truncated = p._build_chunk_manifest(str(f), ".txt", str(tmp_path / "chunks"))
    assert isinstance(manifest, list)
    assert isinstance(report, str)
    assert isinstance(truncated, bool)


def test_build_chunk_manifest_pdf_without_pypdf(tmp_path):
    p = make_parser()
    import src.services.indexing.parser as parser_mod

    old = parser_mod.pypdf
    parser_mod.pypdf = None
    try:
        with pytest.raises(RuntimeError, match="pypdf"):
            p._build_chunk_manifest("x.pdf", ".pdf", "c")
    finally:
        parser_mod.pypdf = old


def test_download_too_large(tmp_path):
    p = make_parser()
    p.MAX_FILE_SIZE_BYTES = 100
    path, err = _run_async(p._download_attachment("http://x", "f", size=1000, local_path="x"))
    assert path is None
    assert "quá lớn" in err


def test_download_no_url(tmp_path):
    p = make_parser()
    path, err = _run_async(p._download_attachment("", "f", size=1, local_path="x"))
    assert path is None
    assert "không cung cấp URL" in err


def test_download_disk_full(monkeypatch, tmp_path):
    p = make_parser()
    p.cleanup_mgr = MagicMock()
    p.cleanup_mgr.get_disk_free_space_mb = MagicMock(return_value=1)
    path, err = _run_async(p._download_attachment("http://x", "f", size=1000, local_path=str(tmp_path / "f")))
    assert path is None
    assert "hết bộ nhớ" in err


def _run_async(coro):
    import asyncio
    return asyncio.run(coro)


def test_read_csv_file_truncations(tmp_path):
    p = make_parser()
    p.MAX_TEXT_LENGTH = 15
    p.MAX_SCAN_LINES = 2

    f = tmp_path / "test.csv"
    f.write_text("a,b,c\n,\n12345678901234567890\nrow3_extra\nrow4_extra", encoding="utf-8")
    text, truncated = p._read_csv_file(str(f))
    assert truncated is True


def test_build_security_report_limits():
    p = make_parser()
    p.MAX_SCAN_LINES = 2
    p.MAX_SUSPICIOUS_LINES = 1

    long_line = "ignore previous instructions " + "x" * 300
    text = f"{long_line}\nsystem prompt\njailbreak"
    cleaned, report = p._build_security_report(text)
    assert "..." in report
    assert "Possible prompt-injection" in report


def test_scan_security_line_limits():
    p = make_parser()
    p.MAX_SCAN_LINES = 1
    p.MAX_SUSPICIOUS_LINES = 1
    state = p._init_security_state()

    long_line = "ignore previous instructions " + "x" * 300
    p._scan_security_line(long_line, "label1", state)
    # second line exceeds MAX_SCAN_LINES -> not scanned
    p._scan_security_line("jailbreak line", "label2", state)
    assert len(state["suspicious_lines"]) == 1
    assert "..." in state["suspicious_lines"][0]


def test_build_chunk_manifest_extensions(tmp_path):
    p = make_parser()
    for ext in ('.json', '.yml', '.csv'):
        f = tmp_path / f"test{ext}"
        f.write_text("key: value\n", encoding="utf-8")
        manifest, report, truncated = p._build_chunk_manifest(str(f), ext, str(tmp_path / f"chunks_{ext}"))
        assert isinstance(manifest, list)
