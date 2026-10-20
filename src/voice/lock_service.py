"""RoomLockService managing voice locking, enforcement, and permission restoration."""

from __future__ import annotations

import time
from typing import Iterator, List, Optional, Set

import discord
from src.core.config import logger
from src.voice.models import LockOutcome, LockRecord, PurgeReport
from src.voice.purge import VoicePurgeService, voice_purge_service
from src.voice.store import LockStoreProtocol, WhitelistStoreProtocol


def is_member_overwrite(target: object) -> bool:
    return not isinstance(target, (discord.Role, discord.abc.GuildChannel))


class RoomLockService:
    """Core domain service for voice channel locking and security enforcement."""

    def __init__(
        self,
        store: LockStoreProtocol,
        whitelist: WhitelistStoreProtocol,
        bot: discord.Client,
        owner_id: int,
        purge_service: Optional[VoicePurgeService] = None,
        logger_override=None,
    ) -> None:
        self.store = store
        self.whitelist = whitelist
        self.bot = bot
        self.owner_id = owner_id
        self.purge_service = purge_service or voice_purge_service
        self.logger = logger_override or logger

    def is_locked(self, channel_id: int) -> bool:
        return self.store.is_locked(channel_id)

    def record(self, channel_id: int) -> Optional[LockRecord]:
        return self.store.get(channel_id)

    def allowed_ids(self) -> Set[int]:
        ids = self.whitelist.ids()
        ids.add(self.owner_id)
        if self.bot.user is not None:
            ids.add(self.bot.user.id)
        return ids

    def is_allowed(self, member_id: int) -> bool:
        return member_id in self.allowed_ids()

    def locked_channels(self, guild: discord.Guild) -> List[discord.VoiceChannel]:
        return [c for c in self.all_locked_channels() if c.guild.id == guild.id]

    def all_locked_channels(self) -> List[discord.VoiceChannel]:
        found = []
        for record in self.store.records():
            channel = self.bot.get_channel(record.channel_id)
            if isinstance(channel, discord.VoiceChannel):
                found.append(channel)
        return found

    def prune_missing_channels(self) -> List[LockRecord]:
        removed = []
        for record in list(self.store.records()):
            if self.bot.get_channel(record.channel_id) is None:
                self.store.unlock(record.channel_id)
                removed.append(record)
        return removed

    async def lock(self, channel: discord.VoiceChannel, actor_id: Optional[int]) -> LockOutcome:
        record = self.store.lock(channel.id, actor_id)
        await self.apply_permissions(channel)
        kicked = await self.enforce(channel, reason=f"Đã khóa phòng {channel.name}")
        purge = await self.clean_messages(channel, record)
        reactions = await self.strip_reactions(channel)
        outcome = LockOutcome(record=record, kicked=kicked, purge=purge, reactions_removed=reactions)
        return outcome

    async def unlock(self, channel: discord.VoiceChannel) -> Optional[LockRecord]:
        record = self.store.unlock(channel.id)

        base = channel.overwrites_for(channel.guild.default_role)
        base.connect = None
        base.add_reactions = None
        try:
            await channel.set_permissions(channel.guild.default_role, overwrite=base, reason=f"Mở khóa {channel.name}")
        except (discord.Forbidden, discord.HTTPException) as e:
            self.logger.warning(f"Error resetting default role permissions on unlock: {e}")

        for target, overwrite in list(channel.overwrites.items()):
            if overwrite.connect is not True or overwrite.add_reactions is not True:
                continue
            if not is_member_overwrite(target):
                continue
            overwrite.connect = None
            overwrite.add_reactions = None
            try:
                await channel.set_permissions(target, overwrite=overwrite, reason=f"Mở khóa {channel.name}")
            except (discord.Forbidden, discord.HTTPException):
                pass

        return record

    async def apply_permissions(self, channel: discord.VoiceChannel) -> None:
        base = channel.overwrites_for(channel.guild.default_role)
        base.connect = False
        base.add_reactions = False
        await channel.set_permissions(channel.guild.default_role, overwrite=base, reason=f"Khóa phòng {channel.name}")

        for member in self._allowed_members(channel.guild):
            overwrite = channel.overwrites_for(member)
            overwrite.connect = True
            overwrite.add_reactions = True
            try:
                await channel.set_permissions(member, overwrite=overwrite, reason=f"Mở quyền cho {member.display_name}")
            except (discord.Forbidden, discord.HTTPException):
                pass

    def _allowed_members(self, guild: discord.Guild) -> List[discord.Member]:
        members = []
        for uid in self.allowed_ids():
            member = guild.get_member(uid)
            if member is not None:
                members.append(member)
        return members

    async def enforce(self, channel: discord.VoiceChannel, reason: str = "Phòng đã khóa") -> List[str]:
        kicked = []
        allowed = self.allowed_ids()
        for member in list(channel.members):
            if member.id in allowed:
                continue
            try:
                await member.move_to(None, reason=reason)
                kicked.append(member.display_name)
            except (discord.Forbidden, discord.HTTPException):
                pass
        return kicked

    async def clean_messages(self, channel: discord.VoiceChannel, record: LockRecord) -> PurgeReport:
        return await self.purge_service.purge_foreign_messages(
            channel,
            cutoff=record.locked_at,
            allowed_ids=self.allowed_ids(),
            bot_user_id=self.bot.user.id if self.bot.user else 0,
            limit=200,
        )

    async def strip_reactions(self, channel: discord.VoiceChannel) -> int:
        removed = 0
        allowed = self.allowed_ids()
        try:
            async for message in channel.history(limit=50):
                for reaction in list(message.reactions):
                    try:
                        async for user in reaction.users():
                            if user.id not in allowed:
                                await reaction.remove(user)
                                removed += 1
                    except (discord.Forbidden, discord.HTTPException):
                        continue
        except (discord.Forbidden, discord.HTTPException):
            pass
        return removed

    async def grant_access(self, member: discord.Member) -> int:
        granted = 0
        for channel in self.locked_channels(member.guild):
            overwrite = channel.overwrites_for(member)
            overwrite.connect = True
            overwrite.add_reactions = True
            try:
                await channel.set_permissions(member, overwrite=overwrite, reason="Cấp quyền allowlist")
                granted += 1
            except (discord.Forbidden, discord.HTTPException):
                pass
        return granted

    async def revoke_access(self, member: discord.Member) -> int:
        touched = 0
        for channel in self.locked_channels(member.guild):
            overwrite = channel.overwrites_for(member)
            overwrite.connect = None
            overwrite.add_reactions = None
            try:
                await channel.set_permissions(member, overwrite=overwrite, reason="Thu hồi quyền allowlist")
                touched += 1
            except (discord.Forbidden, discord.HTTPException):
                pass
            if member in channel.members:
                try:
                    await member.move_to(None, reason="Bị loại khỏi allowlist")
                except (discord.Forbidden, discord.HTTPException):
                    pass
        return touched

    async def ensure_locked(self, channel: discord.VoiceChannel) -> bool:
        base = channel.overwrites_for(channel.guild.default_role)
        if base.connect is not False or base.add_reactions is not False:
            base.connect = False
            base.add_reactions = False
            try:
                await channel.set_permissions(
                    channel.guild.default_role,
                    overwrite=base,
                    reason="Bảo vệ phòng khóa",
                )
                return True
            except (discord.Forbidden, discord.HTTPException):
                pass
        return False
