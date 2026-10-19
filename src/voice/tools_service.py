"""RoomToolsService for moving members and editing room attributes."""

from __future__ import annotations

from typing import List, Optional, Tuple
import discord
from src.core.config import logger
from src.voice.lock_service import RoomLockService


class RoomToolsService:
    """Service providing voice room utilities (/move, /move_all, /set_room)."""

    def __init__(self, service: RoomLockService, logger_override=None):
        self.service = service
        self.logger = logger_override or logger

    async def move_member(
        self, member: discord.Member, channel: discord.VoiceChannel, actor: discord.Member
    ) -> Tuple[bool, str]:
        if member.voice is None or member.voice.channel is None:
            return False, f"{member.mention} hiện không ở trong phòng voice nào."
        if channel.guild.id != member.guild.id:
            return False, "Phòng đích không thuộc server này."

        try:
            await member.move_to(channel, reason=f"Chuyển bởi {actor}")
            return True, f"Đã chuyển {member.mention} sang **{channel.name}**."
        except discord.Forbidden:
            return False, f"Không chuyển được {member.mention}: bot thiếu quyền Move Members hoặc role bot không đủ cao."
        except discord.HTTPException as error:
            return False, f"Lỗi khi chuyển: {error}"

    async def move_all(
        self, source_channel: discord.VoiceChannel, target_channel: discord.VoiceChannel, actor: discord.Member
    ) -> Tuple[int, List[str]]:
        targets = [actor]
        targets.extend(
            member for member in source_channel.members if self.service.is_allowed(member.id)
        )

        moved = 0
        failed = []
        seen_ids = set()

        for member in targets:
            if member.id in seen_ids or member.bot:
                continue
            seen_ids.add(member.id)
            try:
                await member.move_to(target_channel, reason=f"Chuyển cả nhóm bởi {actor}")
                moved += 1
            except (discord.Forbidden, discord.HTTPException):
                failed.append(member.display_name)

        return moved, failed

    async def set_room(
        self,
        channel: discord.VoiceChannel,
        name: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Tuple[bool, List[str]]:
        updates = []
        edit_kwargs = {}

        if name and name.strip():
            new_name = name.strip()
            edit_kwargs["name"] = new_name
            updates.append(f"Tên: **{new_name}**")
            # If room is locked, enforce name
            if self.service.is_locked(channel.id):
                self.service.store.set_enforced_name(channel.id, new_name)

        if status and status.strip():
            new_status = status.strip()
            edit_kwargs["status"] = new_status
            updates.append(f"Status: `{new_status}`")

        if not edit_kwargs:
            return False, []

        try:
            await channel.edit(**edit_kwargs, reason="Cập nhật phòng bởi admin/owner")
            return True, updates
        except (discord.Forbidden, discord.HTTPException) as e:
            self.logger.error(f"Error editing channel {channel.id}: {e}")
            return False, [str(e)]
