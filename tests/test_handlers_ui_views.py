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


@pytest.mark.asyncio
async def test_model_picker_confirm_without_selection():
    view = ModelPickerView(models=_models(), slot="reasoning")
    # find confirm button (label contains Xác nhận)
    confirm = next(b for b in view.children if "Xác nhận" in getattr(b, "label", ""))
    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()
    await confirm.callback(interaction)
    interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_model_picker_skip():
    view = ModelPickerView(models=_models(), slot="final")
    skip = next(b for b in view.children if "Để trống" in getattr(b, "label", ""))
    interaction = MagicMock()
    interaction.response.edit_message = AsyncMock()
    await skip.callback(interaction)
    assert view.skipped is True
    assert view.confirmed is True


@pytest.mark.asyncio
async def test_global_note_view_callbacks(monkeypatch):
    from unittest.mock import PropertyMock

    notes = _notes(20)
    view = GlobalNoteView(notes, page_size=8)
    select = view.children[0]
    prev_btn = view.children[1]
    next_btn = view.children[2]

    monkeypatch.setattr(type(select), "values", PropertyMock(return_value=["n0"]))
    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()
    await select.callback(interaction)
    interaction.response.send_message.assert_awaited_once()

    # test next page callback
    btn_interaction = MagicMock()
    btn_interaction.response.edit_message = AsyncMock()
    await next_btn.callback(btn_interaction)
    assert view.page == 1

    # test prev page callback
    await prev_btn.callback(btn_interaction)
    assert view.page == 0


@pytest.mark.asyncio
async def test_global_note_demote_view_callbacks(monkeypatch):
    db = MagicMock()
    db.demote_global_note_by_id_db = AsyncMock(return_value=True)
    notes = _notes(10)
    view = GlobalNoteDemoteView(notes, db_repo=db, page_size=5)

    from unittest.mock import PropertyMock
    select = view.children[0]
    monkeypatch.setattr(type(select), "values", PropertyMock(return_value=["n0"]))
    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    interaction.followup.send = AsyncMock()

    await select.callback(interaction)
    db.demote_global_note_by_id_db.assert_awaited_once_with("n0")
    interaction.response.edit_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_confirm_action_view():
    from src.handlers.discord.ui import ConfirmActionView

    confirmed = {"ok": False}

    async def on_confirm(interaction):
        confirmed["ok"] = True
        return "Success message"

    view = ConfirmActionView(
        owner_id=123,
        on_confirm=on_confirm,
        confirm_label="Yes",
        cancel_label="No",
        cancel_text="Cancelled!",
    )

    # interaction check
    intruder = MagicMock()
    intruder.user.id = 999
    intruder.response.send_message = AsyncMock()
    assert await view.interaction_check(intruder) is False

    owner = MagicMock()
    owner.user.id = 123
    assert await view.interaction_check(owner) is True

    # cancel button
    cancel_btn = next(b for b in view.children if getattr(b, "label", "") == "No")
    cancel_intr = MagicMock()
    cancel_intr.response.edit_message = AsyncMock()
    await cancel_btn.callback(cancel_intr)
    assert view.is_finished() is True

    # confirm button
    view2 = ConfirmActionView(owner_id=123, on_confirm=on_confirm)
    confirm_btn = next(b for b in view2.children if getattr(b, "label", "") == "Xác nhận")
    confirm_intr = MagicMock()
    confirm_intr.response.defer = AsyncMock()
    confirm_intr.edit_original_response = AsyncMock()
    await confirm_btn.callback(confirm_intr)
    assert confirmed["ok"] is True

    # on_timeout
    view3 = ConfirmActionView(owner_id=123, on_confirm=on_confirm)
    view3.message = MagicMock()
    view3.message.edit = AsyncMock()
    await view3.on_timeout()
    view3.message.edit.assert_awaited_once()


@pytest.mark.asyncio
async def test_endpoint_config_modal(monkeypatch):
    from src.handlers.discord.ui import EndpointConfigModal

    flow = MagicMock()
    flow.configure = AsyncMock()

    import discord
    def fake_val(self):
        return getattr(self, "_test_val", "")
    monkeypatch.setattr(discord.ui.TextInput, "value", property(fake_val))

    modal = EndpointConfigModal(flow=flow, sdk="genai", default_url="http://x")
    modal.url_input._test_val = ""
    modal.key_input._test_val = ""

    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()
    await modal.on_submit(interaction)
    interaction.response.send_message.assert_awaited_once()
    flow.configure.assert_not_called()

    modal.url_input._test_val = "http://valid.com"
    modal.key_input._test_val = "secret"
    await modal.on_submit(interaction)
    flow.configure.assert_awaited_once_with(interaction, "genai", "http://valid.com", "secret")


@pytest.mark.asyncio
async def test_endpoint_config_flow():
    from src.handlers.discord.ui import EndpointConfigFlow

    gw = MagicMock()
    resolver = MagicMock()
    db = MagicMock()
    cfg = MagicMock()

    flow = EndpointConfigFlow(gateway=gw, resolver=resolver, db_repo=db, config=cfg, admin_user_id="123")

    interaction = MagicMock()
    interaction.followup.send = AsyncMock()
    await flow.start(interaction)
    interaction.followup.send.assert_awaited_once()

    # _on_sdk_choose
    sdk_intr = MagicMock()
    sdk_intr.response.send_modal = AsyncMock()
    await flow._on_sdk_choose(sdk_intr, "genai")
    sdk_intr.response.send_modal.assert_awaited_once()

    # configure with invalid url
    cfg_intr = MagicMock()
    cfg_intr.response.send_message = AsyncMock()
    await flow.configure(cfg_intr, "genai", "invalid://bad", "key")
    assert "Base URL không hợp lệ" in cfg_intr.response.send_message.call_args[0][0]
