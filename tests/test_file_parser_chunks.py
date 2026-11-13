"""Offline tests for FileParserService chunking methods."""
import sys

sys.path.insert(0, ".")

from src.services.indexing.parser import FileParserService


class NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


def make_parser(tmp_path):
    p = FileParserService(storage_path=str(tmp_path / "storage"))
    p.logger = NullLogger()
    p.INDEX_CHUNK_CHAR_LIMIT = 200
    return p


def test_chunk_text_file_basic(tmp_path):
    p = make_parser(tmp_path)
    f = tmp_path / "a.txt"
    f.write_text("line one\nline two\nline three", encoding="utf-8")
    state = p._init_security_state()
    manifest, truncated = p._chunk_text_file(str(f), str(tmp_path / "chunks"), state)
    assert manifest
    assert manifest[0]["chunk_id"]
    assert (tmp_path / "chunks" / f"{manifest[0]['chunk_id']}.txt").exists()
    assert truncated in (True, False)


def test_chunk_csv_file_basic(tmp_path):
    p = make_parser(tmp_path)
    f = tmp_path / "a.csv"
    f.write_text("a,b,c\n1,2,3\n4,5,6", encoding="utf-8")
    state = p._init_security_state()
    manifest, truncated = p._chunk_csv_file(str(f), str(tmp_path / "chunks"), state)
    assert manifest
    assert manifest[0]["source"]["row_start"] == 1


def test_chunk_pdf_file_missing_library(tmp_path):
    p = make_parser(tmp_path)
    import src.services.indexing.parser as parser_mod

    old = parser_mod.pypdf
    parser_mod.pypdf = None
    try:
        manifest, truncated = p._chunk_pdf_file("x.pdf", str(tmp_path / "c"), {})
        assert manifest == []
    finally:
        parser_mod.pypdf = old


def test_read_chunk_text_ok(tmp_path):
    p = make_parser(tmp_path)
    f = tmp_path / "c1.txt"
    f.write_text("hello world content", encoding="utf-8")
    assert p.read_chunk_text(str(f)) == "hello world content"


def test_read_chunk_text_truncates(tmp_path):
    p = make_parser(tmp_path)
    f = tmp_path / "c2.txt"
    f.write_text("x" * 500, encoding="utf-8")
    text = p.read_chunk_text(str(f), max_chars=100)
    assert "chunk truncated" in text


def test_read_chunk_text_missing(tmp_path):
    p = make_parser(tmp_path)
    assert p.read_chunk_text(str(tmp_path / "nope.txt")) == ""


def test_finalize_security_report_with_hidden(tmp_path):
    p = make_parser(tmp_path)
    state = p._init_security_state()
    state["hidden_removed"] = 3
    report = p._finalize_security_report(state)
    assert "Hidden/control" in report


def test_chunk_text_file_exceeds_limit(tmp_path):
    p = make_parser(tmp_path)
    p.INDEX_CHUNK_CHAR_LIMIT = 50
    f = tmp_path / "long.txt"
    f.write_text("\n".join(f"line {i} with some content" for i in range(20)), encoding="utf-8")
    state = p._init_security_state()
    manifest, truncated = p._chunk_text_file(str(f), str(tmp_path / "chunks"), state)
    assert len(manifest) >= 2


def test_chunk_csv_file_exceeds_limit(tmp_path):
    p = make_parser(tmp_path)
    p.INDEX_CHUNK_CHAR_LIMIT = 50
    f = tmp_path / "long.csv"
    f.write_text("\n".join(f"col1_{i},col2_{i},col3_{i}" for i in range(20)), encoding="utf-8")
    state = p._init_security_state()
    manifest, truncated = p._chunk_csv_file(str(f), str(tmp_path / "chunks"), state)
    assert len(manifest) >= 2


def test_chunk_pdf_file_with_pages(tmp_path, monkeypatch):
    import src.services.indexing.parser as parser_mod

    class FakePage:
        def __init__(self, text):
            self._text = text

        def extract_text(self):
            return self._text

    class FakeReader:
        def __init__(self, path):
            self.pages = [FakePage("page 1 text line\nanother line"), FakePage("page 2 text content")]

        def get_num_pages(self):
            return 2

    monkeypatch.setattr(parser_mod.pypdf, "PdfReader", FakeReader)
    p = make_parser(tmp_path)
    p.INDEX_CHUNK_CHAR_LIMIT = 20
    state = p._init_security_state()
    manifest, truncated = p._chunk_pdf_file("test.pdf", str(tmp_path / "chunks"), state)
    assert len(manifest) >= 2
