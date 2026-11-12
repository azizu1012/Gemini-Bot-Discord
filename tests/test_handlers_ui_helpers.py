"""Offline tests for handlers/discord/ui.py pure helper functions."""
import sys

sys.path.insert(0, ".")

from src.handlers.discord.ui import (
    _flatten_note_preview,
    _format_note_detail,
    filter_models,
    normalize_models,
    paginate_models,
    total_model_pages,
)


def test_flatten_note_preview_note():
    preview = _flatten_note_preview({"content": "some note content", "note_id": "n1"})
    assert "some note content" in preview


def test_flatten_note_preview_empty():
    # empty note renders a placeholder
    assert _flatten_note_preview({})


def test_format_note_detail():
    detail = _format_note_detail({"content": "hello", "note_id": "n1", "created_at": "2026-01-01"})
    assert "hello" in detail


def test_format_note_detail_empty():
    # empty note produces a stable placeholder
    assert _format_note_detail({})


def test_normalize_models_dedupes():
    raw = [
        {"id": "gemini-1", "display_name": "A"},
        {"id": "gemini-1", "display_name": "A"},  # dup
        {"id": "", "display_name": ""},  # blank
        {"id": "gemini-2", "display_name": "B"},
    ]
    out = normalize_models(raw)
    ids = [m["id"] for m in out]
    assert ids == ["gemini-1", "gemini-2"]


def test_filter_models():
    models = [{"id": "gemini-1"}, {"id": "gpt-4"}, {"id": "claude-3"}]
    out = filter_models(models, "gemini")
    assert len(out) == 1
    assert out[0]["id"] == "gemini-1"


def test_filter_models_no_query():
    models = [{"id": "a"}, {"id": "b"}]
    assert len(filter_models(models, "")) == 2


def test_paginate_models():
    models = [{"id": f"m{i}"} for i in range(10)]
    page1 = paginate_models(models, 0, page_size=4)
    page2 = paginate_models(models, 1, page_size=4)
    assert len(page1) == 4
    assert len(page2) == 4


def test_total_model_pages():
    assert total_model_pages(0, 10) == 1
    assert total_model_pages(10, 10) == 1
    assert total_model_pages(11, 10) == 2
