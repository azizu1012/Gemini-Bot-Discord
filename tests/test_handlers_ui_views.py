"""Offline tests for handlers/discord/ui.py View classes (pure logic)."""
import sys

import pytest

sys.path.insert(0, ".")

from src.handlers.discord.ui import GlobalNoteView


def _notes(n=10):
    return [{"note_id": f"n{i}", "user_id": "u1", "fact_hash": "abc", "content": f"note {i}"} for i in range(n)]


@pytest.mark.asyncio
async def test_global_note_view_total_pages():
    view = GlobalNoteView(_notes(20), page_size=8)
    assert view.total_pages == 3


@pytest.mark.asyncio
async def test_global_note_view_current_page_notes():
    view = GlobalNoteView(_notes(20), page_size=8)
    assert len(view._current_page_notes()) == 8
    view.page = 2
    assert len(view._current_page_notes()) == 4


@pytest.mark.asyncio
async def test_global_note_view_summary_text():
    view = GlobalNoteView(_notes(5), page_size=8)
    text = view.summary_text()
    assert "Global notes" in text
    assert "page 1/1" in text


@pytest.mark.asyncio
async def test_global_note_view_rebuild_components():
    view = GlobalNoteView(_notes(3))
    view._rebuild_components()
    assert len(view.children) >= 1  # select + prev + next


@pytest.mark.asyncio
async def test_global_note_view_empty_notes():
    view = GlobalNoteView([], page_size=8)
    assert view.total_pages == 1
    assert view._current_page_notes() == []
    view._rebuild_components()  # select disabled but no crash
