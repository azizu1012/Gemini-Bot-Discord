import asyncio
import io
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Dict, Deque, Any, Optional, List

import discord
from discord import app_commands
from discord.ext import commands

from src.core.config import logger, ADMIN_ID
from src.database.repository import DatabaseRepository
from src.services.memory_service import MemoryService
from src.managers.cleanup_manager import CleanupManager
from src.managers.premium_manager import PremiumManager
from src.tools.tools import ToolsManager
from src.voice.voice_lock import VoiceLockManager


def _flatten_note_preview(note: Dict[str, Any], max_len: int = 80) -> str:
    content = str(note.get("content", "")).replace("\n", " ").strip()
    if len(content) > max_len:
        return content[:max_len - 3] + "..."
    return content or "(empty)"


def _format_note_detail(note: Dict[str, Any]) -> str:
    content = str(note.get("content", ""))
    if len(content) > 1600:
        content = content[:1600] + "\n... (truncated)"
    return (
        f"🧾 **Global note detail**\n"
        f"- id: `{note.get('note_id', '')}`\n"
        f"- owner: `{note.get('user_id', '')}`\n"
        f"- hash: `{note.get('fact_hash', '')}`\n"
        f"- scope: `{note.get('scope', '')}` | type: `{note.get('note_type', '')}`\n"
        f"- importance: `{note.get('importance', 0)}`\n"
        f"- created: `{note.get('created_at', '')}`\n"
        f"- updated: `{note.get('updated_at', '')}`\n\n"
        f"**Nội dung**\n{content}"
    )


class GlobalNoteView(discord.ui.View):
    def __init__(self, notes: List[Dict[str, Any]], page_size: int = 8):
        super().__init__(timeout=240)
        self.notes = list(notes)
        self.page_size = max(1, min(page_size, 25))
        self.page = 0
        self._select: Optional[discord.ui.Select] = None
        self._rebuild_components()

    @property
    def total_pages(self) -> int:
        return max(1, (len(self.notes) + self.page_size - 1) // self.page_size)

    def _current_page_notes(self) -> List[Dict[str, Any]]:
        start = self.page * self.page_size
        end = start + self.page_size
        return self.notes[start:end]

    def summary_text(self) -> str:
        page_notes = self._current_page_notes()
        start = self.page * self.page_size + 1
        lines = [
            f"🌐 **Global notes** — page {self.page + 1}/{self.total_pages} (total {len(self.notes)})",
            "Chọn 1 note trong dropdown để xem chi tiết.",
            "",
        ]
        for idx, note in enumerate(page_notes, start=start):
            owner = str(note.get("user_id", "?"))
            h = str(note.get("fact_hash", ""))
            lines.append(
                f"`{idx:02d}` owner=`{owner}` hash=`{(h[:10] if h else '-')}` · {_flatten_note_preview(note, 70)}"
            )
        return "\n".join(lines)

    def _rebuild_components(self) -> None:
        self.clear_items()

        page_notes = self._current_page_notes()
        options: List[discord.SelectOption] = []
        page_start = self.page * self.page_size + 1
        for idx, note in enumerate(page_notes, start=page_start):
            note_id = str(note.get("note_id", ""))
            owner = str(note.get("user_id", "?"))
            fact_hash = str(note.get("fact_hash", ""))
            label = f"{idx:02d}. {_flatten_note_preview(note, 72)}"
            if len(label) > 100:
                label = label[:97] + "..."
            desc = f"owner={owner} | hash={(fact_hash[:10] if fact_hash else '-') }"
            if len(desc) > 100:
                desc = desc[:100]
            options.append(discord.SelectOption(label=label, description=desc, value=note_id))

        select = discord.ui.Select(
            placeholder="Chọn note để xem chi tiết",
            min_values=1,
            max_values=1,
            options=options,
            disabled=not options,
        )

        async def on_select(select_interaction: discord.Interaction):
            selected_id = select.values[0]
            selected_note = next((n for n in self.notes if str(n.get("note_id", "")) == selected_id), None)
            if not selected_note:
                await select_interaction.response.send_message("Không tìm thấy note đã chọn.", ephemeral=True)
                return
            await select_interaction.response.send_message(_format_note_detail(selected_note), ephemeral=True)

        select.callback = on_select
        self._select = select
        self.add_item(select)

        prev_button = discord.ui.Button(label="◀ Prev", style=discord.ButtonStyle.secondary, disabled=self.page <= 0)
        next_button = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.secondary, disabled=self.page >= self.total_pages - 1)

        async def on_prev(btn_interaction: discord.Interaction):
            if self.page > 0:
                self.page -= 1
                self._rebuild_components()
            await btn_interaction.response.edit_message(content=self.summary_text(), view=self)

        async def on_next(btn_interaction: discord.Interaction):
            if self.page < self.total_pages - 1:
                self.page += 1
                self._rebuild_components()
            await btn_interaction.response.edit_message(content=self.summary_text(), view=self)

        prev_button.callback = on_prev
        next_button.callback = on_next
        self.add_item(prev_button)
        self.add_item(next_button)


class GlobalNoteDemoteView(discord.ui.View):
    def __init__(self, notes: List[Dict[str, Any]], db_repo: DatabaseRepository, page_size: int = 8):
        super().__init__(timeout=240)
        self.notes = list(notes)
        self.db_repo = db_repo
        self.page_size = max(1, min(page_size, 25))
        self.page = 0
        self._select: Optional[discord.ui.Select] = None
        self._rebuild_components()

    @property
    def total_pages(self) -> int:
        return max(1, (len(self.notes) + self.page_size - 1) // self.page_size)

    def _current_page_notes(self) -> List[Dict[str, Any]]:
        start = self.page * self.page_size
        end = start + self.page_size
        return self.notes[start:end]

    def summary_text(self) -> str:
        if not self.notes:
            return "✅ Không còn global note nào để demote."
        page_notes = self._current_page_notes()
        start = self.page * self.page_size + 1
        lines = [
            f"🧹 **Demote global notes** — page {self.page + 1}/{self.total_pages} (total {len(self.notes)})",
            "Chọn 1 note trong dropdown để demote.",
            "",
        ]
        for idx, note in enumerate(page_notes, start=start):
            owner = str(note.get("user_id", "?"))
            lines.append(f"`{idx:02d}` owner=`{owner}` · {_flatten_note_preview(note, 70)}")
        return "\n".join(lines)

    def _rebuild_components(self) -> None:
        self.clear_items()

        page_notes = self._current_page_notes()
        options: List[discord.SelectOption] = []
        page_start = self.page * self.page_size + 1
        for idx, note in enumerate(page_notes, start=page_start):
            note_id = str(note.get("note_id", ""))
            owner = str(note.get("user_id", "?"))
            label = f"{idx:02d}. {_flatten_note_preview(note, 72)}"
            if len(label) > 100:
                label = label[:97] + "..."
            desc = f"owner={owner} | id={note_id[:8]}"
            if len(desc) > 100:
                desc = desc[:100]
            options.append(discord.SelectOption(label=label, description=desc, value=note_id))

        select = discord.ui.Select(
            placeholder="Chọn note để demote",
            min_values=1,
            max_values=1,
            options=options,
            disabled=not options,
        )

        async def on_select(select_interaction: discord.Interaction):
            selected_id = select.values[0]
            selected_note = next((n for n in self.notes if str(n.get("note_id", "")) == selected_id), None)
            if not selected_note:
                await select_interaction.response.send_message("Không tìm thấy note đã chọn.", ephemeral=True)
                return

            note_id = str(selected_note.get("note_id", ""))
            fact_hash = str(selected_note.get("fact_hash", ""))
            changed = await self.db_repo.demote_global_note_by_id_db(note_id)
            if not changed:
                await select_interaction.response.send_message("Demote thất bại hoặc note đã không còn global.", ephemeral=True)
                return

            self.notes = [n for n in self.notes if str(n.get("note_id", "")) != note_id]
            if self.page > 0 and self.page >= self.total_pages:
                self.page = self.total_pages - 1
            self._rebuild_components()

            await select_interaction.response.edit_message(content=self.summary_text(), view=self)
            await select_interaction.followup.send(
                f"✅ Đã demote global note `{note_id}`" + (f" (hash `{fact_hash}`)" if fact_hash else ""),
                ephemeral=True,
            )

        select.callback = on_select
        self._select = select
        self.add_item(select)

        prev_button = discord.ui.Button(label="◀ Prev", style=discord.ButtonStyle.secondary, disabled=self.page <= 0 or not self.notes)
        next_button = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.secondary, disabled=self.page >= self.total_pages - 1 or not self.notes)

        async def on_prev(btn_interaction: discord.Interaction):
            if self.page > 0:
                self.page -= 1
                self._rebuild_components()
            await btn_interaction.response.edit_message(content=self.summary_text(), view=self)

        async def on_next(btn_interaction: discord.Interaction):
            if self.page < self.total_pages - 1:
                self.page += 1
                self._rebuild_components()
            await btn_interaction.response.edit_message(content=self.summary_text(), view=self)

        prev_button.callback = on_prev
        next_button.callback = on_next
        self.add_item(prev_button)
        self.add_item(next_button)


class BotCore:
    """Core bot initialization and event handling."""

    def __init__(self, config):
        self.config = config
        self.logger = logger
        self.db_repo = DatabaseRepository()
        self.memory_service = MemoryService()
        self.cleanup_mgr = CleanupManager()
        self.premium_mgr = PremiumManager()
        self.tools_mgr = ToolsManager()

        self.mention_history: Dict[str, list] = {}
        self.confirmation_pending: Dict[str, Dict[str, Any]] = {}
        self.admin_confirmation_pending: Dict[str, Dict[str, Any]] = {}
        self.user_queue: defaultdict[str, Deque[datetime]] = defaultdict(deque)
        self.processing_users = set()

        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True
        intents.voice_states = True
        intents.members = True
        self.bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

        self.voice_lock_manager: Optional[VoiceLockManager] = self._build_voice_lock_manager()
        self._voice_enforce_task: Optional[asyncio.Task] = None

        self._register_events()
        self._register_commands()

    def _build_voice_lock_manager(self) -> Optional[VoiceLockManager]:
        try:
            owner_id = int(self.config.ADMIN_ID)
        except (TypeError, ValueError):
            self.logger.warning("VOICE LOCK DISABLED: ADMIN_ID is missing or invalid")
            return None

        return VoiceLockManager(
            owner_id=owner_id,
            whitelist_file=self.config.VOICE_WHITELIST_FILE,
            locked_channels_file=self.config.LOCKED_CHANNELS_FILE,
            enforced_names_file=self.config.ENFORCED_NAMES_FILE,
            voice_lock_log_file=self.config.VOICE_LOCK_LOG_FILE,
        )

    async def _voice_channel_autocomplete(self, interaction: discord.Interaction, current: str):
        lm = self.voice_lock_manager
        if not lm or not interaction.guild:
            return []
        channels = []
        for ch in interaction.guild.channels:
            if isinstance(ch, (discord.VoiceChannel, discord.StageChannel)):
                prefix = "🔒 " if ch.id in lm.locked_channels else ""
                name = f"{prefix}{ch.name}"
                if current.lower() in name.lower():
                    channels.append(app_commands.Choice(name=name[:100], value=str(ch.id)))
        return channels[:25]

    async def _member_autocomplete(self, interaction: discord.Interaction, current: str):
        if not interaction.guild:
            return []
        members = []
        for m in interaction.guild.members:
            if not m.bot and current.lower() in m.display_name.lower():
                members.append(app_commands.Choice(name=m.display_name[:100], value=str(m.id)))
        return members[:25]

    async def _voice_lock_enforce_loop(self):
        while not self.bot.is_closed():
            lm = self.voice_lock_manager
            if not lm or not lm.locked_channels:
                await asyncio.sleep(1)
                continue

            bot_user = self.bot.user
            if bot_user is None:
                await asyncio.sleep(1)
                continue

            whitelist = lm.load_whitelist()
            for channel_id in list(lm.locked_channels):
                channel = self.bot.get_channel(channel_id)
                if not isinstance(channel, discord.VoiceChannel):
                    lm.locked_channels.discard(channel_id)
                    lm.save_locked_channels()
                    if channel_id in lm.enforced_names:
                        del lm.enforced_names[channel_id]
                        lm.save_enforced_names()
                    continue

                for member in channel.members:
                    if str(member.id) in whitelist or member.id == lm.owner_id or member.id == bot_user.id:
                        continue
                    try:
                        await member.move_to(None, reason="Auto kicked by lock system")
                        lm.log_action(f"⚡ AUTO-KICK: {member.name} ({member.id}) khỏi {channel.name}")
                    except Exception as e:
                        if "Missing Permissions" not in str(e):
                            lm.log_action(f"⚠️ KICK FAIL: {member.name} khỏi {channel.name}: {e}")

            await asyncio.sleep(1)

    def _register_events(self):
        """Register bot events."""

        @self.bot.event
        async def on_ready():
            try:
                synced = await self.bot.tree.sync()
                self.logger.info(f"Synced {len(synced)} slash commands!")
            except Exception as e:
                self.logger.error(f"Error syncing slash commands: {e}")

            await self.db_repo.init_db()
            self.memory_service.init_json_memory()

            self.logger.info("Running DB cleanup...")
            await self.db_repo.cleanup_db()
            self.logger.info("Running local file cleanup...")
            await self.cleanup_mgr.cleanup_local_files()

            await self.db_repo.backup_db()
            self.logger.info(f'{self.bot.user} is online!')

            if self.voice_lock_manager and not self._voice_enforce_task:
                self._voice_enforce_task = asyncio.create_task(self._voice_lock_enforce_loop())

        @self.bot.event
        async def on_message(message: discord.Message):
            user_id = str(message.author.id)
            if user_id in self.processing_users:
                self.logger.warning(f"User {user_id} already processing, skipping duplicate.")
                return

            try:
                self.processing_users.add(user_id)
            finally:
                if user_id in self.processing_users:
                    self.processing_users.remove(user_id)

        @self.bot.event
        async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
            lm = self.voice_lock_manager
            if not lm or not self.bot.user:
                return

            whitelist = lm.load_whitelist()
            is_whitelisted = (
                str(member.id) in whitelist
                or member.id == lm.owner_id
                or member.id == self.bot.user.id
            )

            if after.channel and after.channel.id in lm.locked_channels and not is_whitelisted:
                try:
                    await member.move_to(None, reason="Instant kick by lock system")
                    lm.log_action(f"🛡️ INSTANT-KICK: {member.name} ({member.id}) vào {after.channel.name}")
                except Exception:
                    pass

            if (
                before.channel
                and before.channel.id in lm.locked_channels
                and before.channel != after.channel
                and after.channel is not None
                and is_whitelisted
                and member.id != lm.owner_id
                and member.id != self.bot.user.id
            ):
                try:
                    was_dragged = False
                    dragger = "Unknown"
                    try:
                        async for entry in member.guild.audit_logs(action=discord.AuditLogAction.member_move, limit=5):
                            if entry.target and getattr(entry.target, "id", None) == member.id:
                                if (discord.utils.utcnow() - entry.created_at).total_seconds() < 5:
                                    was_dragged = True
                                    dragger = getattr(entry.user, "name", "Unknown")
                                    break
                    except discord.Forbidden:
                        pass

                    if was_dragged:
                        await member.move_to(before.channel, reason="Anti-drag protection")
                        lm.log_action(f"⚓ ANTI-DRAG: trả {member.name} về {before.channel.name} (kéo bởi {dragger})")
                except Exception as e:
                    self.logger.warning(f"Anti-drag check failed: {e}")

        @self.bot.event
        async def on_guild_channel_update(before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
            lm = self.voice_lock_manager
            if not lm or not self.bot.user:
                return

            if after.id in lm.ignore_next_updates:
                return
            if not isinstance(after, discord.VoiceChannel) or after.id not in lm.locked_channels:
                return

            is_bot_edit = False
            try:
                async for entry in after.guild.audit_logs(action=discord.AuditLogAction.channel_update, limit=1):
                    if entry.target and entry.target.id == after.id and entry.user and entry.user.id == self.bot.user.id:
                        is_bot_edit = True
                        break
            except discord.Forbidden:
                pass

            if is_bot_edit:
                return

            if after.id in lm.enforced_names and after.name != lm.enforced_names[after.id]:
                try:
                    lm.ignore_next_updates.add(after.id)
                    await after.edit(name=lm.enforced_names[after.id], reason="Anti-edit: keep owner-enforced name")
                    lm.log_action(f"🛡️ ANTI-EDIT: hoàn tác đổi tên room {after.id}")
                except discord.Forbidden:
                    pass
                finally:
                    async def remove_ignore(cid: int):
                        await asyncio.sleep(3)
                        lm.ignore_next_updates.discard(cid)

                    self.bot.loop.create_task(remove_ignore(after.id))

        @self.bot.event
        async def on_command_error(ctx: commands.Context, error: commands.CommandError):
            if isinstance(error, commands.CommandNotFound):
                self.logger.warning(f"Command not found: '{ctx.message.content}' from User: {ctx.author}")
                return
            self.logger.error(f"Command error: {error}")

        _ = (on_ready, on_message, on_voice_state_update, on_guild_channel_update, on_command_error)

    def _register_commands(self):
        """Register slash commands."""

        def is_admin():
            async def predicate(interaction: discord.Interaction) -> bool:
                return str(interaction.user.id) == ADMIN_ID

            return app_commands.check(predicate)

        def get_requester_voice_channel(
            interaction: discord.Interaction,
        ) -> Optional[discord.VoiceChannel | discord.StageChannel]:
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                return None
            voice_state = interaction.user.voice
            if not voice_state:
                return None
            if not isinstance(voice_state.channel, (discord.VoiceChannel, discord.StageChannel)):
                return None
            return voice_state.channel

        @self.bot.tree.command(name="reset-chat", description="Clear your chat history")
        async def reset_chat_slash(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            user_id = str(interaction.user.id)
            self.confirmation_pending[user_id] = {'timestamp': datetime.now(), 'awaiting': True}
            await interaction.followup.send("Clear chat history? Reply **yes** or **y** in 60 seconds! 😳", ephemeral=True)

        @self.bot.tree.command(name="premium", description="Manage premium user status (ADMIN ONLY)")
        @app_commands.describe(
            user="User to check/add/remove",
            action="Action: 'check', 'add', or 'remove'"
        )
        @app_commands.choices(action=[
            app_commands.Choice(name="Check", value="check"),
            app_commands.Choice(name="Add", value="add"),
            app_commands.Choice(name="Remove", value="remove"),
        ])
        @is_admin()
        async def premium_slash(interaction: discord.Interaction, user: discord.User, action: app_commands.Choice[str]):
            try:
                await interaction.response.defer(ephemeral=True)
            except discord.errors.NotFound:
                self.logger.error("Interaction not found for premium command.")
                try:
                    await interaction.user.send("Error processing premium command.")
                except discord.Forbidden:
                    pass
                return

            requester_id = str(interaction.user.id)
            target_user_id = str(user.id)

            if action.value == "check" and requester_id == target_user_id:
                await interaction.followup.send("You are the admin! 🥰", ephemeral=True)
                return

            if action.value == "check":
                if self.premium_mgr.is_premium_user(target_user_id):
                    await interaction.followup.send(f"{user.display_name} is Premium ✨", ephemeral=True)
                else:
                    await interaction.followup.send(f"{user.display_name} is not Premium 😔", ephemeral=True)
            elif action.value == "add":
                if self.premium_mgr.add_premium_user(target_user_id):
                    await interaction.followup.send(f"Added {user.display_name} to Premium 🎉", ephemeral=True)
                else:
                    await interaction.followup.send(f"{user.display_name} already Premium", ephemeral=True)
            elif action.value == "remove":
                if self.premium_mgr.remove_premium_user(target_user_id):
                    await interaction.followup.send(f"Removed {user.display_name} from Premium 💔", ephemeral=True)
                else:
                    await interaction.followup.send(f"{user.display_name} not in Premium list", ephemeral=True)

        @self.bot.tree.command(name="reset-all", description="Clear all DB (ADMIN ONLY)")
        @is_admin()
        async def reset_all_slash(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            admin_id = str(interaction.user.id)
            self.admin_confirmation_pending[admin_id] = {'timestamp': datetime.now(), 'awaiting': True}
            await interaction.followup.send("⚠️ **ADMIN CONFIRM**: Reply **YES RESET** in 60 seconds to clear all DB!", ephemeral=True)

        @self.bot.tree.command(name="global-notes", description="Browse global shared memory notes (ADMIN ONLY)")
        @app_commands.describe(limit="Max notes to load (1-100)")
        @is_admin()
        async def global_notes_slash(interaction: discord.Interaction, limit: app_commands.Range[int, 1, 100] = 40):
            await interaction.response.defer(ephemeral=True)
            notes = await self.db_repo.get_global_notes_db(limit=int(limit))

            if not notes:
                await interaction.followup.send("No global notes found.", ephemeral=True)
                return

            view = GlobalNoteView(notes, page_size=8)
            await interaction.followup.send(content=view.summary_text(), view=view, ephemeral=True)

        @self.bot.tree.command(name="global-note-demote", description="Demote shared note from global (ADMIN ONLY)")
        @app_commands.describe(target="(Optional) note_id hoặc fact_hash để demote nhanh")
        @is_admin()
        async def global_note_demote_slash(interaction: discord.Interaction, target: Optional[str] = None):
            await interaction.response.defer(ephemeral=True)

            token = (target or "").strip()
            if token:
                changed_by_id = False
                if "-" in token:
                    changed_by_id = await self.db_repo.demote_global_note_by_id_db(token)

                changed_by_hash = 0
                if not changed_by_id:
                    changed_by_hash = await self.db_repo.demote_global_fact_hash_db(token)

                if changed_by_id:
                    await interaction.followup.send(f"✅ Demoted global note by id: `{token}`", ephemeral=True)
                    return

                if changed_by_hash > 0:
                    await interaction.followup.send(
                        f"✅ Demoted {changed_by_hash} global notes by fact_hash: `{token}`",
                        ephemeral=True,
                    )
                    return

                await interaction.followup.send("Không tìm thấy global note phù hợp để demote.", ephemeral=True)
                return

            notes = await self.db_repo.get_global_notes_db(limit=100)
            if not notes:
                await interaction.followup.send("No global notes found.", ephemeral=True)
                return

            view = GlobalNoteDemoteView(notes, self.db_repo, page_size=8)
            await interaction.followup.send(content=view.summary_text(), view=view, ephemeral=True)

        @self.bot.tree.command(name="message_to", description="Send message to user (ADMIN ONLY)")
        @app_commands.describe(
            user="Target user",
            message="Message content",
            channel="Optional channel"
        )
        @is_admin()
        async def message_to_slash(interaction: discord.Interaction, user: discord.User, message: str, channel: Optional[discord.TextChannel] = None):
            await interaction.response.defer(ephemeral=True)
            user_id = str(user.id)
            cleaned_message = ' '.join(message.strip().split())

            try:
                target_user = await self.bot.fetch_user(int(user_id))
            except (ValueError, discord.NotFound):
                await interaction.followup.send("Invalid user ID or not found! 😕", ephemeral=True)
                return

            try:
                if channel:
                    if not isinstance(channel, discord.TextChannel):
                        await interaction.followup.send("Channel must be text channel! 😅", ephemeral=True)
                        return
                    if not interaction.guild:
                        await interaction.followup.send("Cannot use channel in DM.", ephemeral=True)
                        return
                    if channel.guild != interaction.guild:
                        await interaction.followup.send("Channel must be in same server! 😢", ephemeral=True)
                        return
                    guild_me = interaction.guild.me
                    if guild_me is None or not channel.permissions_for(guild_me).send_messages:
                        await interaction.followup.send("Bot has no send permission! 😓", ephemeral=True)
                        return
                    await channel.send(f"💌 From admin to {target_user.mention}: {cleaned_message}")
                    await interaction.followup.send(f"Sent to {target_user.display_name} in {channel.mention}! ✨", ephemeral=True)
                else:
                    decorated = f"━━━━━━━━━━━━━━━━━━━━━━\nMessage from admin:\n\n{cleaned_message}\n\n━━━━━━━━━━━━━━━━━━━━━━"
                    if len(decorated) > 1500:
                        decorated = cleaned_message[:1450] + "\n...(truncated)"
                    await target_user.send(decorated)
                    await interaction.followup.send(f"DM sent to {target_user.display_name}! ✨", ephemeral=True)
            except discord.Forbidden:
                await interaction.followup.send(f"Cannot send message to {target_user.display_name}! 😢", ephemeral=True)
            except Exception as e:
                await interaction.followup.send(f"Error sending message! 😓 Error: {str(e)}", ephemeral=True)
                self.logger.error(f"Error sending message to {user_id}: {e}")

        # --- Donate Command ---
        DONATE_PLATFORMS = {
            "kofi": {
                "file": "donate_kofi.png.enc",
                "display_name": "Ko-fi",
                "original_filename": "donate_kofi.png",
                "message": "Cảm ơn bạn đã cân nhắc ủng hộ! Đây là mã QR Ko-fi:",
            },
            "paypal": {
                "file": "donate_paypal.png.enc",
                "display_name": "PayPal",
                "original_filename": "donate_paypal.png",
                "message": "Cảm ơn bạn đã cân nhắc ủng hộ! Đây là mã QR PayPal:",
            },
        }

        @self.bot.tree.command(name="donate", description="Hiện mã QR ủng hộ (Ko-fi hoặc PayPal)")
        @app_commands.describe(platform="Chọn nền tảng ủng hộ (mặc định: Ko-fi)")
        @app_commands.choices(platform=[
            app_commands.Choice(name="Ko-fi (recommended)", value="kofi"),
            app_commands.Choice(name="PayPal", value="paypal"),
        ])
        async def donate_slash(interaction: discord.Interaction, platform: app_commands.Choice[str] = None):
            await interaction.response.defer()

            selected = platform.value if platform else "kofi"
            info = DONATE_PLATFORMS.get(selected)
            if not info:
                await interaction.followup.send("Nền tảng không hợp lệ.", ephemeral=True)
                return

            encrypted_path = Path(self.config.PROJECT_ROOT) / "assets" / "encrypted" / info["file"]
            if not encrypted_path.exists():
                self.logger.error(f"Donate: encrypted file not found: {encrypted_path}")
                await interaction.followup.send("Mã QR hiện không khả dụng. Vui lòng thử lại sau.", ephemeral=True)
                return

            key = self.config.DONATE_ENCRYPTION_KEY
            if not key:
                self.logger.error("Donate: DONATE_ENCRYPTION_KEY not configured")
                await interaction.followup.send("Mã QR hiện không khả dụng. Vui lòng thử lại sau.", ephemeral=True)
                return

            try:
                from cryptography.fernet import Fernet
                fernet = Fernet(key.encode())
                encrypted_data = encrypted_path.read_bytes()
                decrypted_data = fernet.decrypt(encrypted_data)
            except Exception as e:
                self.logger.error(f"Donate: decryption failed: {e}")
                await interaction.followup.send("Không thể tải mã QR. Vui lòng liên hệ admin.", ephemeral=True)
                return

            file_obj = discord.File(
                fp=io.BytesIO(decrypted_data),
                filename=info["original_filename"],
            )

            msg = await interaction.followup.send(
                content=f"**{info['message']}**\n_Tin nhắn này sẽ tự xóa sau 2 phút._",
                file=file_obj,
            )

            async def auto_delete():
                await asyncio.sleep(120)
                try:
                    await msg.delete()
                except (discord.NotFound, discord.Forbidden):
                    pass

            self.bot.loop.create_task(auto_delete())

        _ = (reset_chat_slash, premium_slash, reset_all_slash,
             global_notes_slash, global_note_demote_slash,
             message_to_slash, donate_slash)

        lm = self.voice_lock_manager
        if not lm:
            return

        owner_check = lm.is_owner_check()

        @self.bot.tree.command(name="lock", description="Khóa phòng voice hiện tại và kick người không whitelist")
        @owner_check
        async def lock_room(interaction: discord.Interaction):
            try:
                await interaction.response.defer(ephemeral=True)
            except discord.errors.NotFound:
                return

            channel = get_requester_voice_channel(interaction)
            if channel is None or interaction.guild is None:
                await interaction.followup.send("⚠️ Bạn phải vào phòng voice trước.", ephemeral=True)
                return

            bot_user = self.bot.user
            if bot_user is None:
                await interaction.followup.send("⚠️ Bot chưa sẵn sàng.", ephemeral=True)
                return

            whitelist = lm.load_whitelist()

            default_role = interaction.guild.default_role
            overwrite = channel.overwrites_for(default_role)
            overwrite.connect = False
            await channel.set_permissions(default_role, overwrite=overwrite, reason="Lock room command")

            lm.locked_channels.add(channel.id)
            lm.save_locked_channels()
            lm.log_action(f"🔒 LOCK tại {channel.name} bởi {interaction.user.name}")

            kicked_users: List[str] = []
            for member in channel.members:
                if str(member.id) in whitelist or member.id == lm.owner_id or member.id == bot_user.id:
                    member_overwrite = channel.overwrites_for(member)
                    member_overwrite.connect = True
                    await channel.set_permissions(member, overwrite=member_overwrite)
                    continue
                try:
                    await member.move_to(None, reason="Locked out by owner")
                    kicked_users.append(member.name)
                    lm.log_action(f"🧹 LOCK-KICK: {member.name} ({member.id})")
                except Exception as e:
                    self.logger.warning(f"Kick fail {member.name}: {e}")

            msg = f"🔒 Đã khóa channel **{channel.name}**."
            if kicked_users:
                msg += f"\n👢 Đã kick {len(kicked_users)} người: {', '.join(kicked_users)}"
            await interaction.followup.send(msg, ephemeral=True)

        @self.bot.tree.command(name="unlock", description="Mở khóa phòng voice hiện tại")
        @owner_check
        async def unlock_room(interaction: discord.Interaction):
            try:
                await interaction.response.defer(ephemeral=True)
            except discord.errors.NotFound:
                return

            channel = get_requester_voice_channel(interaction)
            if channel is None or interaction.guild is None:
                await interaction.followup.send("⚠️ Bạn phải vào phòng voice trước.", ephemeral=True)
                return

            default_role = interaction.guild.default_role
            overwrite = channel.overwrites_for(default_role)
            overwrite.connect = None
            await channel.set_permissions(default_role, overwrite=overwrite, reason="Unlock room command")

            lm.locked_channels.discard(channel.id)
            if channel.id in lm.enforced_names:
                del lm.enforced_names[channel.id]
                lm.save_enforced_names()
            lm.save_locked_channels()
            lm.log_action(f"🔓 UNLOCK tại {channel.name} bởi {interaction.user.name}")

            await interaction.followup.send(f"🔓 Đã mở khóa channel **{channel.name}**.", ephemeral=True)

        @self.bot.tree.command(name="move", description="Chuyển một thành viên sang voice channel khác")
        @app_commands.autocomplete(member=self._member_autocomplete, channel=self._voice_channel_autocomplete)
        @owner_check
        async def move_member(interaction: discord.Interaction, member: str, channel: str):
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                return
            try:
                target_member = interaction.guild.get_member(int(member)) if interaction.guild else None
                target_channel = interaction.guild.get_channel(int(channel)) if interaction.guild else None
                if not target_member or not isinstance(target_channel, (discord.VoiceChannel, discord.StageChannel)):
                    raise ValueError("Không tìm thấy member hoặc channel")
                if not target_member.voice:
                    await interaction.followup.send("⚠️ Người đó chưa ở voice.", ephemeral=True)
                    return
                if target_channel.id in lm.locked_channels:
                    await target_channel.set_permissions(target_member, connect=True)
                await target_member.move_to(target_channel)
                await interaction.followup.send(f"✅ Đã chuyển vào {target_channel.name}", ephemeral=True)
            except Exception as e:
                await interaction.followup.send(f"❌ Lỗi: {e}", ephemeral=True)

        @self.bot.tree.command(name="move_all", description="Chuyển owner + whitelist từ phòng hiện tại sang phòng khác")
        @owner_check
        async def move_all(interaction: discord.Interaction, target_channel: discord.VoiceChannel):
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                pass

            source_channel = get_requester_voice_channel(interaction)
            if source_channel is None or interaction.guild is None:
                await interaction.followup.send("⚠️ Bạn đang không ở trong voice.", ephemeral=True)
                return

            if not isinstance(target_channel, discord.VoiceChannel):
                await interaction.followup.send("⚠️ Bạn phải chọn voice channel hợp lệ.", ephemeral=True)
                return

            whitelist = lm.load_whitelist()

            if source_channel.id == target_channel.id:
                await interaction.followup.send("⚠️ Bạn chọn trùng phòng hiện tại.", ephemeral=True)
                return

            moved_count = 0
            for m in source_channel.members:
                if str(m.id) in whitelist or m.id == lm.owner_id:
                    try:
                        await m.move_to(target_channel, reason="Mass move by owner")
                        moved_count += 1
                    except Exception:
                        pass

            if source_channel.id in lm.locked_channels:
                lm.locked_channels.discard(source_channel.id)
                lm.locked_channels.add(target_channel.id)
                lm.save_locked_channels()

                default_role = interaction.guild.default_role
                old_overwrite = source_channel.overwrites_for(default_role)
                old_overwrite.connect = None
                await source_channel.set_permissions(default_role, overwrite=old_overwrite)

                new_overwrite = target_channel.overwrites_for(default_role)
                new_overwrite.connect = False
                await target_channel.set_permissions(default_role, overwrite=new_overwrite)

                lm.log_action(f"✈️ MASS-MOVE + RELOCK tại {target_channel.name}")

            await interaction.followup.send(
                f"✅ Đã chuyển {moved_count} thành viên sang **{target_channel.name}**.",
                ephemeral=True,
            )

        @self.bot.tree.command(name="set_room", description="Đổi tên/trạng thái phòng hiện tại và khóa sửa tên")
        @app_commands.describe(name="Tên mới", status="Trạng thái mới")
        @owner_check
        async def set_room(interaction: discord.Interaction, name: Optional[str] = None, status: Optional[str] = None):
            try:
                await interaction.response.defer(ephemeral=True)
            except discord.errors.NotFound:
                pass

            channel = get_requester_voice_channel(interaction)
            if channel is None:
                await interaction.followup.send("⚠️ Bạn đang không ở trong voice.", ephemeral=True)
                return

            updates = []
            lm.ignore_next_updates.add(channel.id)

            if name:
                try:
                    await channel.edit(name=name, reason="Owner room rename")
                    lm.enforced_names[channel.id] = name
                    lm.save_enforced_names()
                    updates.append(f"Tên phòng: **{name}**")
                except discord.errors.Forbidden:
                    await interaction.followup.send("❌ Bot thiếu quyền Manage Channels để đổi tên.", ephemeral=True)
                    lm.ignore_next_updates.discard(channel.id)
                    return

            if status is not None:
                self.logger.info("VoiceChannel.status edit is not supported in discord.py; skipped status update request.")

            await asyncio.sleep(3)
            lm.ignore_next_updates.discard(channel.id)

            if updates:
                lm.log_action(f"✏️ SET_ROOM: {' | '.join(updates)} ở {channel.id}")
                await interaction.followup.send(
                    "✅ Đã cập nhật và bật chống sửa tên phòng.\n" + "\n".join(f"🔹 {u}" for u in updates),
                    ephemeral=True,
                )
            else:
                await interaction.followup.send("⚠️ Bạn chưa nhập name/status để đổi.", ephemeral=True)

        @self.bot.tree.command(name="add_privet", description="Thêm người vào whitelist để không bị kick khi lock")
        @owner_check
        async def add_privet(interaction: discord.Interaction, member: discord.Member):
            try:
                await interaction.response.defer(ephemeral=True)
            except discord.errors.NotFound:
                pass

            whitelist = lm.load_whitelist()
            user_id_str = str(member.id)
            if user_id_str in whitelist:
                await interaction.followup.send(f"⚠️ **{member.display_name}** đã có trong whitelist.", ephemeral=True)
                return

            whitelist[user_id_str] = {"username": member.name, "id": user_id_str}
            lm.save_whitelist(whitelist)

            owner_channel = get_requester_voice_channel(interaction)
            if owner_channel is not None:
                member_overwrite = owner_channel.overwrites_for(member)
                member_overwrite.connect = True
                await owner_channel.set_permissions(member, overwrite=member_overwrite)

            await interaction.followup.send(
                f"✅ Đã thêm **{member.display_name}** (<@{member.id}>) vào whitelist.",
                ephemeral=True,
            )

        @self.bot.tree.command(name="remove_privet", description="Xóa một người khỏi whitelist")
        @owner_check
        async def remove_privet(interaction: discord.Interaction, member: discord.Member):
            try:
                await interaction.response.defer(ephemeral=True)
            except discord.errors.NotFound:
                pass

            whitelist = lm.load_whitelist()
            user_id_str = str(member.id)

            if user_id_str == str(lm.owner_id):
                await interaction.followup.send("❌ Bạn không thể tự loại khỏi whitelist.", ephemeral=True)
                return

            if user_id_str not in whitelist:
                await interaction.followup.send(f"⚠️ {member.display_name} không có trong whitelist.", ephemeral=True)
                return

            del whitelist[user_id_str]
            lm.save_whitelist(whitelist)

            owner_channel = get_requester_voice_channel(interaction)
            if owner_channel is not None:
                if member in owner_channel.members:
                    await member.move_to(None, reason="Removed from whitelist by owner")

                member_overwrite = owner_channel.overwrites_for(member)
                member_overwrite.connect = None
                await owner_channel.set_permissions(member, overwrite=member_overwrite)

            await interaction.followup.send(
                f"🗑️ Đã xóa **{member.display_name}** (<@{member.id}>) khỏi whitelist.",
                ephemeral=True,
            )

        @self.bot.tree.command(name="list_privet", description="Liệt kê whitelist voice-room")
        @owner_check
        async def list_privet(interaction: discord.Interaction):
            try:
                await interaction.response.defer(ephemeral=True)
            except discord.errors.NotFound:
                pass

            whitelist = lm.load_whitelist()
            if len(whitelist) <= 1:
                await interaction.followup.send("📜 Danh sách trống (ngoài owner).", ephemeral=True)
                return

            lines = ["📜 **Whitelist voice-room:**"]
            for uid, data in whitelist.items():
                if uid == str(lm.owner_id):
                    continue
                username = data.get('username', 'Unknown')
                lines.append(f"🔹 **{username}** - <@{uid}> `(UID: {uid})`")

            await interaction.followup.send("\n".join(lines), ephemeral=True)

        @self.bot.tree.error
        async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
            if isinstance(error, app_commands.CheckFailure):
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ Lệnh này chỉ dành cho owner đã cấu hình.",
                        ephemeral=True,
                    )
                return
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"❌ Đã có lỗi: {error}", ephemeral=True)
                else:
                    await interaction.followup.send(f"❌ Đã có lỗi: {error}", ephemeral=True)
            except Exception:
                pass

        _ = (lock_room, unlock_room, move_member, move_all, set_room,
             add_privet, remove_privet, list_privet, on_app_command_error)

    async def start(self, token: str):
        """Start the bot."""
        async with self.bot:
            await self.bot.start(token)
