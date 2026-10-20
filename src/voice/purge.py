"""Message and reaction purging service for locked voice channels."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Set
import discord
from src.voice.models import PurgeReport

BULK_DELETE_BATCH = 100


class VoicePurgeService:
    """Domain service managing message resolution and purge operations in voice channels."""

    def __init__(self, batch_size: int = BULK_DELETE_BATCH, max_names: int = 15, default_limit: int = 200) -> None:
        self.batch_size = batch_size
        self.max_names = max_names
        self.default_limit = default_limit

    async def resolve_text_channel(self, voice_channel: discord.VoiceChannel) -> Optional[discord.TextChannel]:
        """Find the text chat associated with a voice channel."""
        guild = voice_channel.guild
        text_id = voice_channel.id >> 32

        cached = guild.get_channel(text_id)
        if isinstance(cached, discord.TextChannel):
            return cached

        try:
            fetched = await guild.fetch_channel(text_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None
        return fetched if isinstance(fetched, discord.TextChannel) else None

    async def purge_foreign_messages(
        self,
        channel: discord.VoiceChannel,
        *,
        cutoff: datetime,
        allowed_ids: Set[int],
        bot_user_id: int,
        limit: Optional[int] = None,
        reason: str = "Dọn tin nhắn ngoài allowlist",
        max_names: Optional[int] = None,
    ) -> PurgeReport:
        """Delete messages sent after `cutoff` by users not in `allowed_ids`."""
        target_channel = await self.resolve_text_channel(channel)
        if target_channel is None:
            target_channel = channel  # Fallback to voice channel if it supports history

        effective_limit = limit if limit is not None else self.default_limit
        effective_max_names = max_names if max_names is not None else self.max_names

        report = PurgeReport()
        to_delete: List[discord.Message] = []
        seen_authors: Set[str] = set()

        try:
            async for message in target_channel.history(limit=effective_limit, oldest_first=False):
                report.scanned += 1
                if message.created_at < cutoff:
                    break
                if message.author.id == bot_user_id or message.webhook_id is not None:
                    continue
                if message.author.id not in allowed_ids:
                    report.violations += 1
                    to_delete.append(message)
                    if len(seen_authors) < effective_max_names:
                        seen_authors.add(message.author.display_name)
        except (discord.Forbidden, discord.HTTPException):
            return report

        report.names = sorted(seen_authors)
        if not to_delete:
            return report

        for start in range(0, len(to_delete), self.batch_size):
            batch = to_delete[start : start + self.batch_size]
            try:
                if hasattr(target_channel, "delete_messages") and len(batch) > 1:
                    await target_channel.delete_messages(batch, reason=reason)
                    report.deleted += len(batch)
                else:
                    for msg in batch:
                        try:
                            await msg.delete()
                            report.deleted += 1
                        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                            report.failed += 1
            except (discord.Forbidden, discord.HTTPException):
                report.failed += len(batch)

        return report


# Global default instance and backward-compatible functional facades
voice_purge_service = VoicePurgeService()
resolve_text_channel = voice_purge_service.resolve_text_channel
purge_foreign_messages = voice_purge_service.purge_foreign_messages
