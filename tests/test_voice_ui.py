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
