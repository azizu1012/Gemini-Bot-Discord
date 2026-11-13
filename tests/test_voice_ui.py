"""Offline tests for voice role-management UI views (RolePanel & friends)."""
import sys
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

sys.path.insert(0, ".")

from src.voice.ui import RoleDoneView, RolePanel, RolePickerView, RolePositionView, swap_panel


def _mock_guild(role_ids=(1, 2, 3)):
    g = MagicMock(spec=discord.Guild)
    roles = []
    for i, rid in enumerate(role_ids):
        r = MagicMock(spec=discord.Role)
        r.id = rid
        r.name = f"role{rid}"
        r.mention = f"<@&{rid}>"
        r.position = i + 1
        r.is_default = MagicMock(return_value=rid == role_ids[0])
        roles.append(r)
    g.roles = roles
    g.get_role = MagicMock(side_effect=lambda rid: next((r for r in roles if r.id == rid), None))
    me = MagicMock(spec=discord.Member)
    me.top_role = MagicMock(spec=discord.Role)
    me.top_role.mention = "<@&999>"
    g.me = me
    g.edit_role_positions = AsyncMock()
    return g


def _interaction(user_id=1):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock()
    interaction.user.id = user_id
    interaction.response = MagicMock()
    interaction.response.edit_message = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.original_response = AsyncMock(return_value=MagicMock())
    return interaction


# ---------------- RolePanel base ----------------
@pytest.mark.asyncio
async def test_role_panel_init():
    panel = RolePanel(author_id=10)
    assert panel.author_id == 10
    assert panel.detached is False
    assert panel.message is None
    assert panel.embed is not None


@pytest.mark.asyncio
async def test_interaction_check_denies_other_user():
    panel = RolePanel(author_id=10)
    interaction = _interaction(user_id=99)
    assert await panel.interaction_check(interaction) is False
    interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_interaction_check_allows_owner():
    panel = RolePanel(author_id=10)
    interaction = _interaction(user_id=10)
    assert await panel.interaction_check(interaction) is True


@pytest.mark.asyncio
async def test_detach_sets_flag():
    panel = RolePanel(author_id=1)
    panel.detach()
    assert panel.detached is True


@pytest.mark.asyncio
async def test_swap_panel_swaps_and_captures_response():
    old = RolePanel(author_id=1)
    new = RolePanel(author_id=1)
    new.embed = MagicMock()
    interaction = _interaction(user_id=1)
    resp = MagicMock()
    interaction.original_response = AsyncMock(return_value=resp)
    await swap_panel(interaction, old, new)
    assert old.detached is True
    interaction.response.edit_message.assert_awaited_once()
    assert new.message is resp


# ---------------- RolePickerView ----------------
@pytest.mark.asyncio
async def test_role_picker_view_init_refreshes():
    g = _mock_guild()
    view = RolePickerView(g, author_id=1)
    assert view.page == 0
    assert view.total_pages >= 1
    assert view.embed is not None


@pytest.mark.asyncio
async def test_role_picker_turn_page_edits():
    g = _mock_guild()
    view = RolePickerView(g, author_id=1)
    interaction = _interaction(user_id=1)
    await view.turn_page(interaction, 1)
    interaction.response.edit_message.assert_awaited_once()
    # page stays clamped within [0, total_pages-1]
    assert 0 <= view.page < view.total_pages


# ---------------- RolePositionView ----------------
@pytest.mark.asyncio
async def test_role_position_view_init():
    g = _mock_guild()
    role = g.roles[1]
    view = RolePositionView(g, role, author_id=1)
    assert view.role is role
    assert view.total_pages >= 1


@pytest.mark.asyncio
async def test_role_position_turn_page_edits():
    g = _mock_guild()
    role = g.roles[1]
    view = RolePositionView(g, role, author_id=1)
    interaction = _interaction(user_id=1)
    await view.turn_page(interaction, 1)
    interaction.response.edit_message.assert_awaited_once()
    assert 0 <= view.page < view.total_pages


# ---------------- RoleDoneView ----------------
@pytest.mark.asyncio
async def test_role_done_view_init():
    g = _mock_guild()
    view = RoleDoneView(g, role_id=2, old_rank=1, new_rank=3, author_id=1)
    assert view.author_id == 1
    assert view.embed is not None


@pytest.mark.asyncio
async def test_role_panel_on_timeout_success():
    panel = RolePanel(author_id=123)
    panel.detached = False
    panel.message = MagicMock(edit=AsyncMock())
    await panel.on_timeout()
    panel.message.edit.assert_awaited_once()
    assert "hết giờ" in panel.embed.description


@pytest.mark.asyncio
async def test_role_panel_close_button():
    panel = RolePanel(author_id=123)
    interaction = _interaction(user_id=123)
    # child 0 is the close button
    close_btn = panel.children[0]
    await close_btn.callback(interaction)
    assert panel.detached is True
    assert "Panel đã đóng" in panel.embed.description
    interaction.response.edit_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_role_picker_view_buttons():
    g = _mock_guild()
    view = RolePickerView(g, author_id=123)
    interaction = _interaction(user_id=123)
    # child 2 is prev, child 3 is next
    prev_btn = view.children[2]
    next_btn = view.children[3]
    await next_btn.callback(interaction)
    await prev_btn.callback(interaction)


@pytest.mark.asyncio
async def test_role_picker_view_select_callbacks(monkeypatch):
    import src.voice.ui as voice_ui_mod

    g = _mock_guild()
    r = g.roles[0]
    view = RolePickerView(g, author_id=123)
    select_item = view.children[1]
    type(select_item).values = property(lambda self: [str(r.id)])

    interaction = _interaction(user_id=123)
    # immovable role branch
    monkeypatch.setattr(voice_ui_mod, "role_is_movable", lambda g, role: False)
    await select_item.callback(interaction)
    assert "không thể kéo" in interaction.response.send_message.call_args[0][0]

    # movable role branch -> swap_panel
    monkeypatch.setattr(voice_ui_mod, "role_is_movable", lambda g, role: True)
    monkeypatch.setattr(voice_ui_mod, "swap_panel", AsyncMock())
    await select_item.callback(interaction)
    voice_ui_mod.swap_panel.assert_awaited_once()


@pytest.mark.asyncio
async def test_role_position_view_select_and_buttons(monkeypatch):
    import src.voice.ui as voice_ui_mod

    g = _mock_guild()
    r1, r2, r3 = g.roles
    r1.position, r2.position, r3.position = 1, 2, 3

    monkeypatch.setattr(voice_ui_mod, "top_movable_slot", lambda guild: 0)
    monkeypatch.setattr(voice_ui_mod, "role_order", lambda guild: [r1, r2, r3])
    monkeypatch.setattr(voice_ui_mod, "role_rank", lambda guild, r: 1)
    monkeypatch.setattr(voice_ui_mod, "role_is_movable", lambda g, role: True)
    monkeypatch.setattr(voice_ui_mod, "plan_role_move", lambda guild, role, slot: {role.id: slot})
    monkeypatch.setattr(voice_ui_mod, "swap_panel", AsyncMock())

    view = RolePositionView(g, r1, author_id=123)
    assert len(view.children) == 4
    select_item = view.children[1]
    type(select_item).values = property(lambda self: ["1"])

    interaction = _interaction(user_id=123)
    await select_item.callback(interaction)
    g.edit_role_positions.assert_awaited_once()
    voice_ui_mod.swap_panel.assert_awaited_once()

    # prev and next buttons
    prev_btn = view.children[2]
    next_btn = view.children[3]
    await next_btn.callback(interaction)
    await prev_btn.callback(interaction)
