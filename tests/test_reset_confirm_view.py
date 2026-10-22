"""Tests for ConfirmActionView used by /reset-chat and /reset-all."""

import asyncio
from typing import Optional
from unittest.mock import AsyncMock

import discord
import pytest

from src.handlers.discord.ui import ConfirmActionView


class FakeUser:
    def __init__(self, user_id: int):
        self.id = user_id


class FakeResponse:
    def __init__(self):
        self.deferred = False
        self.messages: list[str] = []
        self.edited_content: Optional[str] = None
        self.view = None

    async def defer(self):
        self.deferred = True

    async def send_message(self, content: str, ephemeral: bool = False):
        self.messages.append(content)

    async def edit_message(self, content: str, view=None):
        self.edited_content = content
        self.view = view


class FakeInteraction:
    def __init__(self, user_id: int):
        self.user = FakeUser(user_id)
        self.response = FakeResponse()
        self.edited_original: Optional[str] = None
        self.view = None

    async def edit_original_response(self, content: str, view=None):
        self.edited_original = content
        self.view = view


@pytest.mark.asyncio
async def test_confirm_action_view_owner_confirms():
    confirmed = False

    async def _on_confirm(interaction: discord.Interaction) -> str:
        nonlocal confirmed
        confirmed = True
        return "Thành công!"

    view = ConfirmActionView(
        owner_id=123,
        on_confirm=_on_confirm,
        confirm_label="Đồng ý",
        cancel_label="Bỏ qua",
    )

    interaction = FakeInteraction(user_id=123)
    # Check interaction permission
    allowed = await view.interaction_check(interaction)  # type: ignore[arg-type]
    assert allowed is True

    # Click confirm button
    await view.confirm_button.callback(interaction)  # type: ignore[arg-type]
    assert confirmed is True
    assert interaction.response.deferred is True
    assert interaction.edited_original == "Thành công!"


@pytest.mark.asyncio
async def test_confirm_action_view_owner_cancels():
    confirmed = False

    async def _on_confirm(interaction: discord.Interaction) -> str:
        nonlocal confirmed
        confirmed = True
        return "Thành công!"

    view = ConfirmActionView(
        owner_id=123,
        on_confirm=_on_confirm,
        cancel_text="Đã hủy thao tác.",
    )

    interaction = FakeInteraction(user_id=123)
    allowed = await view.interaction_check(interaction)  # type: ignore[arg-type]
    assert allowed is True

    # Click cancel button
    await view.cancel_button.callback(interaction)  # type: ignore[arg-type]
    assert confirmed is False
    assert interaction.response.edited_content == "Đã hủy thao tác."


@pytest.mark.asyncio
async def test_confirm_action_view_non_owner_blocked():
    view = ConfirmActionView(
        owner_id=123,
        on_confirm=AsyncMock(),
    )

    intruder = FakeInteraction(user_id=999)
    allowed = await view.interaction_check(intruder)  # type: ignore[arg-type]
    assert allowed is False
    assert len(intruder.response.messages) == 1
    assert "Chỉ người gọi lệnh" in intruder.response.messages[0]


@pytest.mark.asyncio
async def test_confirm_action_view_timeout_edits_message():
    view = ConfirmActionView(
        owner_id=123,
        on_confirm=AsyncMock(),
    )

    fake_msg = AsyncMock()
    view.message = fake_msg

    await view.on_timeout()
    fake_msg.edit.assert_awaited_once()
    args, kwargs = fake_msg.edit.call_args
    assert "hết thời gian" in kwargs["content"].lower()
    assert kwargs["view"] is None
