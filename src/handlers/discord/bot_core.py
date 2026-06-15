import asyncio
import io
import json
import os
import random
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.core.config import Config, logger
from src.database.repository import DatabaseRepository
from src.managers.cleanup_manager import CleanupManager
from src.services.health_checker import get_health_checker
from src.services.redis_service import RedisStreamService
from src.voice.voice_lock import VoiceLockManager

# Import Slash Commands Registration
from src.handlers.discord.commands import register_slash_commands


class BotCore:
    """Core bot initialization and event handling for Redis Streams-based architecture."""

    def __init__(self, config: Config):
        self.config = config
        self.logger = logger
        self.db_repo = DatabaseRepository(self.config.DATABASE_URL)
        self.cleanup_mgr = CleanupManager()
        self.health_checker = get_health_checker()
        self.health_checker.db_repo = self.db_repo
        self.health_checker.router.set_db_repo(self.db_repo)

        self.confirmation_pending: Dict[str, Dict[str, Any]] = {}
        self.admin_confirmation_pending: Dict[str, Dict[str, Any]] = {}

        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True
        intents.voice_states = True
        intents.members = True

        self.bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
        self.kafka_service = RedisStreamService(redis_url=self.config.REDIS_URL, client_id="bot-core")
        self.active_interactions: Dict[str, discord.Interaction] = {}
        self.active_typing_tasks: Dict[str, asyncio.Task] = {}
        self._outgoing_queues: Dict[str, asyncio.Queue] = {}
        self._outgoing_senders: Dict[str, asyncio.Task] = {}
        self._delivery_state: Dict[str, Dict[str, Any]] = {}
        self._consume_task: Optional[asyncio.Task] = None
        self._active_user_locks: Dict[str, float] = {}

        # Khởi tạo Redis client tùy chọn cho cơ chế Centralized Lock khi scale ngang
        self._redis_client = None
        import os
        redis_url = os.getenv("REDIS_URL")
        if redis_url:
            try:
                import redis.asyncio as aioredis
                self._redis_client = aioredis.from_url(redis_url, decode_responses=True)
                self.logger.info("Redis detected! Centralized Lock mode is ENABLED for BotCore.")
            except Exception as e:
                self.logger.warning(f"Failed to initialize Redis client: {e}. Falling back to Local RAM Lock.")

        self.voice_lock_manager: Optional[VoiceLockManager] = self._build_voice_lock_manager()
        self._voice_enforce_task: Optional[asyncio.Task] = None

        self._register_slash_commands()
        self._register_events()

    def _update_env_var(self, key: str, value: str):
        """Cập nhật biến môi trường trong tệp .env và cập nhật os.environ"""
        from dotenv import set_key
        env_path = self.config.PROJECT_ROOT / ".env"
        try:
            set_key(str(env_path), key, value)
            os.environ[key] = value
            self.logger.info(f"Updated env var {key} in {env_path}")
        except Exception as e:
            self.logger.error(f"Failed to update env var {key}: {e}")

    async def _is_admin_user(self, user_id: str) -> bool:
        if str(user_id) in self.config.ADMIN_USER_IDS:
            return True
        return await self.db_repo.is_admin_user(str(user_id))

    async def _is_moderator_user(self, user_id: str) -> bool:
        if str(user_id) in self.config.MODERATOR_USER_IDS:
            return True
        return await self.db_repo.is_moderator_user(str(user_id))

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

    async def _resolve_user_display_name(self, user_id: int, channel: Optional[discord.abc.GuildChannel]) -> str:
        if channel and getattr(channel, "guild", None):
            guild = channel.guild
            member = guild.get_member(user_id)
            if member is None:
                try:
                    member = await guild.fetch_member(user_id)
                except Exception:
                    member = None
            if member is not None:
                return member.display_name

        user = self.bot.get_user(user_id)
        if user is None:
            try:
                user = await self.bot.fetch_user(user_id)
            except Exception:
                user = None
        if user is not None:
            return getattr(user, "display_name", None) or user.name

        return f"User {user_id}"

    async def _sanitize_mentions(
        self,
        content: Optional[str],
        channel: Optional[discord.abc.GuildChannel],
        allow_user_mentions: Optional[List[str]] = None,
    ) -> Optional[str]:
        if not content:
            return content

        allow_set = {str(uid) for uid in (allow_user_mentions or []) if str(uid)}

        content = content.replace("@everyone", "everyone").replace("@here", "here")

        role_ids = set(re.findall(r"<@&(\d+)>", content))
        channel_ids = set(re.findall(r"<#(\d+)>", content))
        user_ids = set(re.findall(r"<@!?(\d+)>", content))

        role_map: Dict[str, str] = {}
        if channel and getattr(channel, "guild", None):
            guild = channel.guild
            for rid in role_ids:
                role = guild.get_role(int(rid))
                role_map[rid] = role.name if role else f"role {rid}"
            for cid in channel_ids:
                ch = guild.get_channel(int(cid))
                channel_name = f"#{ch.name}" if ch else f"channel {cid}"
                role_map[cid] = channel_name
        else:
            for rid in role_ids:
                role_map[rid] = f"role {rid}"
            for cid in channel_ids:
                role_map[cid] = f"channel {cid}"

        user_map: Dict[str, str] = {}
        for uid in user_ids:
            if uid in allow_set:
                continue
            user_map[uid] = await self._resolve_user_display_name(int(uid), channel)

        def replace_user(match: re.Match) -> str:
            uid = match.group(1)
            if uid in allow_set:
                return f"<@{uid}>"
            return user_map.get(uid, f"User {uid}")

        def replace_role(match: re.Match) -> str:
            rid = match.group(1)
            return role_map.get(rid, f"role {rid}")

        def replace_channel(match: re.Match) -> str:
            cid = match.group(1)
            return role_map.get(cid, f"channel {cid}")

        content = re.sub(r"<@!?(\d+)>", replace_user, content)
        content = re.sub(r"<@&(\d+)>", replace_role, content)
        content = re.sub(r"<#(\d+)>", replace_channel, content)
        return content

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

    async def _handle_confirmation_message(self, message: discord.Message) -> bool:
        user_id = str(message.author.id)
        content = (message.content or "").strip()
        now = datetime.now()

        if user_id in self.confirmation_pending:
            state = self.confirmation_pending.get(user_id, {})
            if now - state.get("timestamp", now) > timedelta(seconds=60):
                self.confirmation_pending.pop(user_id, None)
                await message.reply("⏳ Hết thời gian xác nhận. Hãy gọi lại /reset-chat nếu cần.", mention_author=False)
                return True

            # Chỉ nuốt tin nhắn nếu là phản hồi yes/no/y/n/có/không rõ ràng
            valid_yes = {"yes", "y", "co", "có"}
            valid_no = {"no", "n", "khong", "không"}
            normalized_content = content.lower()

            if normalized_content in valid_yes:
                self.confirmation_pending.pop(user_id, None)
                await self.db_repo.clear_user_data_db(user_id)
                try:
                    await self.kafka_service.publish(
                        "discord-incoming",
                        payload={"type": "invalidate_cache", "user_id": user_id},
                        key=user_id
                    )
                except Exception as pub_err:
                    self.logger.error(f"Failed to publish invalidate_cache for user {user_id}: {pub_err}")
                await message.reply("✅ Đã xóa lịch sử chat của bạn.", mention_author=False)
                return True
            elif normalized_content in valid_no:
                self.confirmation_pending.pop(user_id, None)
                await message.reply("❌ Đã hủy yêu cầu reset chat.", mention_author=False)
                return True
            else:
                # Không phải là yes/no hợp lệ, hủy trạng thái pending nhưng không nuốt tin nhắn
                self.confirmation_pending.pop(user_id, None)
                return False

        if user_id in self.admin_confirmation_pending:
            state = self.admin_confirmation_pending.get(user_id, {})
            if now - state.get("timestamp", now) > timedelta(seconds=60):
                self.admin_confirmation_pending.pop(user_id, None)
                await message.reply("⏳ Hết thời gian xác nhận. Hãy gọi lại /reset-all nếu cần.", mention_author=False)
                return True

            # Chỉ nuốt nếu là "yes reset" hoặc phản hồi hủy rõ ràng "no"/"cancel"
            normalized_content = content.strip().lower()
            valid_cancel = {"no", "n", "cancel", "huy", "hủy", "khong", "không"}

            if normalized_content == "yes reset":
                self.admin_confirmation_pending.pop(user_id, None)
                if not await self._is_admin_user(user_id):
                    await message.reply("❌ Bạn không có quyền admin để xác nhận reset.", mention_author=False)
                    return True

                await self.db_repo.clear_all_data_db()
                try:
                    await self.kafka_service.publish(
                        "discord-incoming",
                        payload={"type": "invalidate_all_cache"},
                        key="all"
                    )
                except Exception as pub_err:
                    self.logger.error(f"Failed to publish invalidate_all_cache: {pub_err}")
                await message.reply("✅ Đã xóa toàn bộ dữ liệu hệ thống.", mention_author=False)
                return True
            elif normalized_content in valid_cancel:
                self.admin_confirmation_pending.pop(user_id, None)
                await message.reply("❌ Đã hủy yêu cầu reset toàn bộ dữ liệu.", mention_author=False)
                return True
            else:
                # Không phải là xác nhận hợp lệ hoặc từ chối, hủy trạng thái pending nhưng không nuốt tin nhắn
                self.admin_confirmation_pending.pop(user_id, None)
                return False

        return False

    def _build_attachment_payload(
        self,
        attachment: discord.Attachment,
        *,
        source: str,
        source_message_id: str,
    ) -> Dict[str, Any]:
        return {
            "id": str(attachment.id),
            "url": attachment.url,
            "proxy_url": attachment.proxy_url,
            "filename": attachment.filename,
            "size": attachment.size,
            "content_type": attachment.content_type,
            "source": source,
            "source_message_id": source_message_id,
        }

    async def _resolve_referenced_message(self, message: discord.Message) -> Optional[discord.Message]:
        reference = message.reference
        if not reference or not reference.message_id:
            return None

        resolved = getattr(reference, "resolved", None)
        if isinstance(resolved, discord.Message):
            return resolved

        channel = message.channel
        reference_channel_id = getattr(reference, "channel_id", None)
        if reference_channel_id and int(reference_channel_id) != message.channel.id:
            resolved_channel = self.bot.get_channel(int(reference_channel_id))
            if resolved_channel is not None and hasattr(resolved_channel, "fetch_message"):
                channel = resolved_channel

        try:
            return await channel.fetch_message(reference.message_id)
        except (discord.NotFound, discord.Forbidden):
            return None
        except Exception as e:
            self.logger.warning(f"Failed to fetch referenced message {reference.message_id}: {e}")
            return None

    async def _collect_message_attachments(self, message: discord.Message) -> List[Dict[str, Any]]:
        attachments: List[Dict[str, Any]] = []
        seen_ids = set()

        for attachment in message.attachments:
            attachments.append(
                self._build_attachment_payload(
                    attachment,
                    source="current_message",
                    source_message_id=str(message.id),
                )
            )
            seen_ids.add(str(attachment.id))

        referenced_message = await self._resolve_referenced_message(message)
        if referenced_message:
            for attachment in referenced_message.attachments:
                attachment_id = str(attachment.id)
                if attachment_id in seen_ids:
                    continue
                attachments.append(
                    self._build_attachment_payload(
                        attachment,
                        source="referenced_message",
                        source_message_id=str(referenced_message.id),
                    )
                )
                seen_ids.add(attachment_id)

        return attachments

    async def setup_redis(self):
        try:
            await self.kafka_service.start_producer()
            await self.kafka_service.start_consumer("discord-outgoing", group_id="azuris_bot_dispatcher_group")
            self._consume_task = asyncio.create_task(self.consume_outgoing_loop())
        except Exception as e:
            self.logger.error(f"Failed to start BotCore Redis services: {e}")
            raise

    async def consume_outgoing_loop(self):
        self.logger.info("BotCore Redis consumer loop started. Listening for outgoing replies...")
        consumer = self.kafka_service.consumers.get("discord-outgoing")
        if not consumer:
            self.logger.error("Consumer for 'discord-outgoing' not found in RedisStreamService")
            return

        try:
            async for msg in consumer:
                payload = msg.value
                asyncio.create_task(self.handle_outgoing_payload(payload))
        except asyncio.CancelledError:
            self.logger.info("BotCore Redis consumer loop cancelled")
        except Exception as e:
            self.logger.error(f"Error in BotCore Redis consumer loop: {e}")

    async def handle_outgoing_payload(self, payload: dict):
        action = payload.get("action")
        channel_id_str = payload.get("channel_id")
        user_id = payload.get("user_id") or "unknown"
        self.logger.info(f"[REDIS-RECV] BotCore consumed outgoing event | Action: {action} | User: {user_id} | MsgID/IntID: {payload.get('reference_message_id') or payload.get('interaction_id')}")

        if not action:
            return

        if action in ("reply", "reply_batch"):
            queue = self._get_outgoing_queue(user_id)
            await queue.put(payload)
            self._ensure_sender_task(user_id)
            return

        try:
            if action == "typing" and channel_id_str:
                channel_id = int(channel_id_str)
                channel = self.bot.get_channel(channel_id)
                if not channel:
                    channel = await self.bot.fetch_channel(channel_id)
                if channel and bool(payload.get("typing")):
                    await self.bot.http.send_typing(channel.id)
                if channel and not bool(payload.get("typing")):
                    self._cancel_typing_task(user_id)

            elif action == "slash_reply":
                interaction_id = payload.get("interaction_id")
                content = payload.get("content")
                ephemeral = bool(payload.get("ephemeral", False))
                files = []
                embed = None

                base64_data = payload.get("file_base64")
                if base64_data:
                    import base64
                    import io
                    filename = payload.get("file_name", "file.png")
                    file_bytes = base64.b64decode(base64_data)
                    files.append(discord.File(io.BytesIO(file_bytes), filename=filename))

                    if filename.endswith(('.png', '.jpg', '.jpeg', '.webp')):
                        embed = discord.Embed(title=payload.get("embed_title", "🖼️ Kết quả"), color=discord.Color.blue())
                        embed.set_image(url=f"attachment://{filename}")
                        if payload.get("embed_footer"):
                            embed.set_footer(text=payload.get("embed_footer"))

                interaction = self.active_interactions.pop(interaction_id, None)
                if interaction:
                    self.logger.info(f"Delivering slash_reply for interaction {interaction_id} to user {interaction.user.id}")
                    content = await self._sanitize_mentions(content, interaction.channel, payload.get("allow_user_mentions") or [])
                    if files:
                        await interaction.followup.send(content=content, embed=embed, files=files, ephemeral=ephemeral)
                    else:
                        await interaction.followup.send(content=content, ephemeral=ephemeral)
                    self._cancel_typing_task(str(interaction.user.id))
                else:
                    self.logger.warning(f"Could not find active interaction for ID {interaction_id}")

        except Exception as e:
            self.logger.error(f"Failed to handle outgoing Redis payload: {e}")

    def _get_outgoing_queue(self, user_id: str) -> asyncio.Queue:
        queue = self._outgoing_queues.get(user_id)
        if queue is None:
            queue = asyncio.Queue()
            self._outgoing_queues[user_id] = queue
        return queue

    def _ensure_sender_task(self, user_id: str) -> None:
        task = self._outgoing_senders.get(user_id)
        if task and not task.done():
            return
        self._outgoing_senders[user_id] = asyncio.create_task(self._outgoing_sender_loop(user_id))

    def _cancel_typing_task(self, user_id: str) -> None:
        task = self.active_typing_tasks.pop(user_id, None)
        if task:
            self.logger.info(f"Cancelling active typing task for user {user_id}")
            task.cancel()
        self._active_user_locks.pop(user_id, None)
        if self._redis_client:
            asyncio.create_task(self._redis_client.delete(f"lock:user:{user_id}"))

    async def _outgoing_sender_loop(self, user_id: str) -> None:
        queue = self._outgoing_queues.get(user_id)
        if queue is None:
            return
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    if queue.empty():
                        break
                    continue

                try:
                    await self._process_outgoing_payload(payload)
                finally:
                    queue.task_done()
        finally:
            if queue.empty():
                self._outgoing_queues.pop(user_id, None)
                self._outgoing_senders.pop(user_id, None)

    async def _process_outgoing_payload(self, payload: dict) -> None:
        action = payload.get("action")
        if not action:
            return

        if action == "reply_batch":
            await self._process_reply_batch(payload)
            return

        if action == "reply":
            await self._process_reply(payload)
            return

    async def _process_reply(self, payload: dict) -> None:
        channel_id_str = payload.get("channel_id")
        user_id = payload.get("user_id") or "unknown"
        if not channel_id_str:
            return

        channel_id = int(channel_id_str)
        channel = self.bot.get_channel(channel_id)
        if not channel:
            channel = await self.bot.fetch_channel(channel_id)
        if not channel:
            return

        content = payload.get("content")
        allow_user_mentions = payload.get("allow_user_mentions") or []
        content = await self._sanitize_mentions(content, channel, allow_user_mentions)
        ref_id_str = payload.get("reference_message_id")

        reference = None
        if ref_id_str:
            reference = discord.MessageReference(
                message_id=int(ref_id_str),
                channel_id=channel_id,
                fail_if_not_exists=False,
            )

        sent_message = await self._send_message_with_retry(
            channel,
            content=content,
            reference=reference,
            mention_author=False,
            label="reply",
        )
        if sent_message:
            self._cancel_typing_task(user_id)

    async def _process_reply_batch(self, payload: dict) -> None:
        channel_id_str = payload.get("channel_id")
        user_id = payload.get("user_id") or "unknown"
        if not channel_id_str:
            return

        channel_id = int(channel_id_str)
        channel = self.bot.get_channel(channel_id)
        if not channel:
            channel = await self.bot.fetch_channel(channel_id)
        if not channel:
            return

        reply_group_id = str(payload.get("reply_group_id") or payload.get("reference_message_id") or "unknown")
        allow_user_mentions = payload.get("allow_user_mentions") or []
        mode_hint = str(payload.get("mode_hint") or "").strip().lower()

        chunk_items = payload.get("chunk_items") or []
        chunks = payload.get("chunks") or []

        items: List[Dict[str, Any]] = []
        if isinstance(chunk_items, list) and chunk_items:
            for item in chunk_items:
                if not isinstance(item, dict):
                    continue
                items.append({
                    "index": int(item.get("index", len(items))),
                    "content": item.get("content"),
                })
        else:
            items = [{"index": idx, "content": chunk} for idx, chunk in enumerate(chunks)]

        if not items:
            return

        items.sort(key=lambda x: x.get("index", 0))
        chunk_total = int(payload.get("chunk_total") or len(items))

        state = self._delivery_state.setdefault(
            reply_group_id,
            {"sent": set(), "last_index": -1, "created_at": datetime.utcnow()},
        )
        sent_set = state.get("sent", set())
        start_index = int(state.get("last_index", -1)) + 1

        ref_id_str = payload.get("reference_message_id")
        reference = None
        if ref_id_str:
            reference = discord.MessageReference(
                message_id=int(ref_id_str),
                channel_id=channel_id,
                fail_if_not_exists=False,
            )

        for item in items:
            idx = int(item.get("index", 0))
            if idx < start_index or idx in sent_set:
                continue
            content = item.get("content")
            content = await self._sanitize_mentions(content, channel, allow_user_mentions)
            sent_ok = False
            if idx == 0 and chunk_total == 1 and mode_hint == "edit_then_batch":
                placeholder = "..."
                sent_message = await self._send_message_with_retry(
                    channel,
                    content=placeholder,
                    reference=reference,
                    mention_author=False,
                    label="reply_batch_placeholder",
                )
                if sent_message:
                    edited = await self._edit_message_with_retry(
                        sent_message,
                        content=content,
                        label="reply_batch_edit",
                    )
                    if edited:
                        sent_ok = True
                    else:
                        fallback = await self._send_message_with_retry(
                            channel,
                            content=content,
                            reference=None,
                            mention_author=False,
                            label="reply_batch_edit_fallback",
                        )
                        sent_ok = fallback is not None
            else:
                sent_message = await self._send_message_with_retry(
                    channel,
                    content=content,
                    reference=reference if idx == 0 else None,
                    mention_author=False,
                    label="reply_batch",
                )
                sent_ok = sent_message is not None

            if not sent_ok:
                break

            if idx == 0:
                self._cancel_typing_task(user_id)

            sent_set.add(idx)
            state["last_index"] = idx

        if int(state.get("last_index", -1)) >= chunk_total - 1:
            self._delivery_state.pop(reply_group_id, None)

    async def _send_message_with_retry(
        self,
        channel: discord.abc.Messageable,
        *,
        content: Optional[str],
        reference: Optional[discord.MessageReference],
        mention_author: bool,
        label: str,
        max_attempts: int = 3,
        base_delay: float = 0.35,
    ) -> Optional[discord.Message]:
        async def _do_send():
            return await channel.send(content=content, reference=reference, mention_author=mention_author)

        try:
            return await self._run_with_retry(_do_send, label, max_attempts, base_delay)
        except Exception as e:
            self.logger.error(f"Failed to {label}: {e}")
            return None

    async def _edit_message_with_retry(
        self,
        message: discord.Message,
        *,
        content: Optional[str],
        label: str,
        max_attempts: int = 3,
        base_delay: float = 0.35,
    ) -> bool:
        async def _do_edit():
            await message.edit(content=content)
            return True

        try:
            await self._run_with_retry(_do_edit, label, max_attempts, base_delay)
            return True
        except Exception as e:
            self.logger.error(f"Failed to {label}: {e}")
            return False

    async def _run_with_retry(
        self,
        coro_factory,
        label: str,
        max_attempts: int,
        base_delay: float,
    ):
        last_exc: Optional[Exception] = None
        for attempt in range(1, max_attempts + 1):
            try:
                return await coro_factory()
            except discord.HTTPException as e:
                last_exc = e
                status = getattr(e, "status", None)
                if status == 429:
                    retry_after = getattr(e, "retry_after", None)
                    if retry_after is None:
                        headers = getattr(getattr(e, "response", None), "headers", {}) or {}
                        retry_after = float(headers.get("Retry-After", "1"))
                    await asyncio.sleep(max(0.2, float(retry_after or 1.0)))
                    continue
                if status and 500 <= status < 600:
                    await asyncio.sleep(base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.25))
                    continue
                break
            except (asyncio.TimeoutError, OSError, discord.DiscordException) as e:
                last_exc = e
                await asyncio.sleep(base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.25))

        if last_exc:
            raise last_exc
        return None

    async def shutdown(self):
        if self._consume_task and not self._consume_task.done():
            self._consume_task.cancel()
            try:
                await self._consume_task
            except asyncio.CancelledError:
                pass

        await self.kafka_service.stop()

        try:
            await self.db_repo.close()
        except Exception as e:
            self.logger.warning(f"Failed to close DB pool cleanly: {e}")

    def _register_slash_commands(self):
        # Đăng ký Slash Commands từ commands.py
        register_slash_commands(self)

    def _register_events(self):
        @self.bot.event
        async def on_ready():
            self.logger.info(f"Bot logged in as {self.bot.user.name} (ID: {self.bot.user.id})")

            await self.db_repo.init_db()
            try:
                await self.setup_redis()
            except Exception as e:
                self.logger.error(f"Failed to start Redis producer: {e}")

            try:
                synced = await self.bot.tree.sync()
                self.logger.info(f"Slash commands synced: {len(synced)}")
            except Exception as e:
                self.logger.error(f"Failed to sync slash commands: {e}")

            try:
                self.logger.info("Running DB cleanup...")
                await self.db_repo.cleanup_db()
            except Exception as e:
                self.logger.warning(f"DB cleanup failed: {e}")

            try:
                self.logger.info("Running local file cleanup...")
                await self.cleanup_mgr.cleanup_local_files()
            except Exception as e:
                self.logger.warning(f"Local cleanup failed: {e}")

            try:
                await self.db_repo.backup_db()
            except Exception as e:
                self.logger.warning(f"DB backup failed: {e}")

            if self.health_checker:
                try:
                    admin_user = await self.bot.fetch_user(int(self.config.ADMIN_ID)) if self.config.ADMIN_ID else None
                    self.health_checker.start_background_check(admin_user)
                    self.logger.info("Health Checker background task started.")
                except Exception as e:
                    self.logger.error(f"Failed to start health checker: {e}")

            if self.voice_lock_manager and not self._voice_enforce_task:
                self._voice_enforce_task = asyncio.create_task(self._voice_lock_enforce_loop())

            self.logger.info(f"{self.bot.user} is online and ready!")

        @self.bot.event
        async def on_message(message: discord.Message):
            if message.author.bot:
                return

            if await self._handle_confirmation_message(message):
                return

            user_id = str(message.author.id)
            is_dm = isinstance(message.channel, discord.DMChannel)
            is_mentioned = self.bot.user in message.mentions

            if not is_dm and not is_mentioned:
                return

            import time
            now = time.time()

            # Chế độ Centralized Lock bằng Redis nếu có cấu hình REDIS_URL
            redis_lock_ok = False
            if self._redis_client:
                try:
                    lock_key = f"lock:user:{user_id}"
                    # SET lock_key "busy" NX EX 20 (Chỉ set nếu chưa có, tự hết hạn sau 20s)
                    acquired = await self._redis_client.set(lock_key, "busy", nx=True, ex=20)
                    if not acquired:
                        busy_text = "Đợi chút nha, mình đang bận xử lý câu hỏi trước của bạn. Nhắn chen ngang cũng bị trừ tin nhắn đó nha! ⏳"
                        await message.reply(busy_text, mention_author=False)
                        return
                    redis_lock_ok = True
                except Exception as e:
                    self.logger.error(f"Redis lock error: {e}. Falling back to Local RAM Lock.")

            # Chế độ Fallback / Local RAM Lock (Mặc định khi không dùng Redis)
            if not redis_lock_ok:
                # Dọn dẹp RAM locks cũ quá 20 giây (Timeout an toàn chống khóa oan khi Worker sập/nghẽn)
                expired_locks = [uid for uid, ts in self._active_user_locks.items() if now - ts > 20]
                for uid in expired_locks:
                    self._active_user_locks.pop(uid, None)

                # Kiểm tra trạng thái bận trên RAM
                if user_id in self._active_user_locks:
                    busy_text = "Đợi chút nha, mình đang bận xử lý câu hỏi trước của bạn. Nhắn chen ngang cũng bị trừ tin nhắn đó nha! ⏳"
                    await message.reply(busy_text, mention_author=False)
                    return

                # Thiết lập khóa trên RAM
                self._active_user_locks[user_id] = now

            # Hủy typing loop cũ của user này nếu có
            if user_id in self.active_typing_tasks:
                self.active_typing_tasks[user_id].cancel()

            # Định nghĩa typing loop ngầm gửi typing status liên tục mỗi 5s
            async def _typing_loop(channel_obj):
                try:
                    while True:
                        await self.bot.http.send_typing(channel_obj.id)
                        await asyncio.sleep(5)
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    self.logger.error(f"Error in typing loop: {e}")

            self.active_typing_tasks[user_id] = asyncio.create_task(_typing_loop(message.channel))

            # Xác định tên bot động
            bot_name = self.bot.user.name if self.bot.user else "Chad Gibiti"
            attachment_payloads = await self._collect_message_attachments(message)
            if attachment_payloads:
                sources = ",".join(sorted({str(item.get("source", "unknown")) for item in attachment_payloads}))
                self.logger.info(f"Collected {len(attachment_payloads)} attachment(s) for message {message.id} from {sources}")

            payload = {
                "message_id": str(message.id),
                "channel_id": str(message.channel.id),
                "user_id": user_id,
                "bot_name": bot_name,
                "content": message.content,
                "author_name": message.author.name,
                "author_display_name": message.author.display_name,
                "is_dm": is_dm,
                "mentions": [str(m.id) for m in message.mentions],
                "reference_message_id": str(message.reference.message_id) if message.reference else None,
                "attachments": attachment_payloads,
            }

            try:
                payload["type"] = "chat"
                success = await self.kafka_service.publish("discord-incoming", payload=payload, key=user_id)
                if not success:
                    raise RuntimeError("Redis publish returned False")
            except Exception as e:
                self.logger.error(f"Failed to publish incoming message: {e}")
                # Hủy typing loop nếu publish thất bại
                if user_id in self.active_typing_tasks:
                    self.active_typing_tasks[user_id].cancel()
                    self.active_typing_tasks.pop(user_id, None)
                # Giải phóng khóa trên RAM
                self._active_user_locks.pop(user_id, None)
                await self.db_repo.clear_user_processing_state(user_id)
                await message.reply("🚨 Hệ thống Redis đang lỗi. Vui lòng thử lại sau.", mention_author=False)

        @self.bot.event
        async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
            lm = self.voice_lock_manager
            if not lm or not self.bot.user:
                return

            if after.channel and after.channel.id in lm.locked_channels:
                whitelist = lm.load_whitelist()
                is_whitelisted = (
                    str(member.id) in whitelist
                    or member.id == lm.owner_id
                    or member.id == self.bot.user.id
                )

                if not is_whitelisted:
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

    async def start(self, token: str):
        async with self.bot:
            await self.bot.start(token)
