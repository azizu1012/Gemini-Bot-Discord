"""Offline tests for handlers/discord/ui.py View classes (pure logic)."""
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, ".")

from src.handlers.discord.ui import (
    GlobalNoteDemoteView,
    GlobalNoteView,
    ImageHistoryView,
    ModelPickerView,
)


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


def _models(n=30):
    return [{"id": f"model-{i}", "name": f"Model {i}"} for i in range(n)]


@pytest.mark.asyncio
async def test_model_picker_filtered():
    view = ModelPickerView(models=_models(), slot="reasoning")
    assert len(view.filtered) == 30
    view.apply_query("model-1")
    assert len(view.filtered) == 11  # model-1, model-10..19


@pytest.mark.asyncio
async def test_model_picker_pages():
    view = ModelPickerView(models=_models(), slot="final")
    assert view.total_pages == 2  # 30 models / 25 per page
    assert len(view.page_models) == 25


@pytest.mark.asyncio
async def test_model_picker_summary_embed():
    view = ModelPickerView(models=_models(), slot="reasoning")
    embed = view.summary_embed()
    assert embed is not None
    assert "Chọn model" in embed.title


@pytest.mark.asyncio
async def test_global_note_demote_view_empty_summary():
    view = GlobalNoteDemoteView([], db_repo=None)
    assert "Không còn" in view.summary_text()


@pytest.mark.asyncio
async def test_global_note_demote_view_pages():
    notes = _notes(20)
    view = GlobalNoteDemoteView(notes, db_repo=None, page_size=8)
    assert view.total_pages == 3
    assert len(view._current_page_notes()) == 8
    view.page = 2
    assert len(view._current_page_notes()) == 4


@pytest.mark.asyncio
async def test_global_note_demote_view_summary():
    view = GlobalNoteDemoteView(_notes(3), db_repo=None)
    text = view.summary_text()
    assert "Demote global notes" in text
    assert "page 1/1" in text


@pytest.mark.asyncio
async def test_image_history_view_init():
    view = ImageHistoryView([{"prompt": "cat", "image_url": "http://x"}])
    assert len(view.children) == 1


@pytest.mark.asyncio
async def test_image_history_select_callback_url(monkeypatch):
    from unittest.mock import PropertyMock

    view = ImageHistoryView([{"prompt": "cat", "image_url": "http://x/cat.png"}])
    select = view.children[0]
    monkeypatch.setattr(type(select), "values", PropertyMock(return_value=["0"]))
    interaction = MagicMock()
    interaction.response.edit_message = AsyncMock()
    await select.callback(interaction)
    interaction.response.edit_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_image_history_select_callback_local_file(tmp_path, monkeypatch):
    from unittest.mock import PropertyMock

    img = tmp_path / "img.png"
    img.write_bytes(b"pngdata")
    view = ImageHistoryView([{"prompt": "dog", "image_url": str(img)}])
    select = view.children[0]
    monkeypatch.setattr(type(select), "values", PropertyMock(return_value=["0"]))
    interaction = MagicMock()
    interaction.response.edit_message = AsyncMock()
    await select.callback(interaction)
    interaction.response.edit_message.assert_awaited_once()
