import asyncio
import io
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import discord
from discord import app_commands
from discord.ext import commands

from src.handlers.discord.ui import (
    GlobalNoteView,
    GlobalNoteDemoteView,
    ImageHistoryView,
    EndpointConfigFlow,
    SDKChoiceView,
    SLOT_LABELS,
    SLOT_ORDER,
    normalize_models,
)
from src.core.llm.gateway import get_llm_gateway
from src.core.llm.resolver import get_endpoint_resolver, mask_api_key, resolve_model_id
from src.voice import RolePickerView


def register_slash_commands(bot_core_instance):
    bot = bot_core_instance.bot
    db_repo = bot_core_instance.db_repo
    config = bot_core_instance.config
    logger = bot_core_instance.logger
    resolver = get_endpoint_resolver()
    resolver.set_db_repo(db_repo)
    gateway = get_llm_gateway()
    kafka_service = bot_core_instance.kafka_service
    voice_lock_manager = bot_core_instance.voice_lock_manager
    room_lock_service = getattr(bot_core_instance, "room_lock_service", None)
    room_tools_service = getattr(bot_core_instance, "room_tools_service", None)

    def is_admin():
        async def predicate(interaction: discord.Interaction) -> bool:
            return await bot_core_instance._is_admin_user(str(interaction.user.id))

        return app_commands.check(predicate)

    def is_moderator_or_admin():
        async def predicate(interaction: discord.Interaction) -> bool:
            uid = str(interaction.user.id)
            return await bot_core_instance._is_admin_user(uid) or await bot_core_instance._is_moderator_user(uid)

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

    @bot.tree.command(name="ping", description="Kiểm tra bot còn phản hồi")
    async def ping(interaction: discord.Interaction):
        await interaction.response.send_message("Bot đang hoạt động.", ephemeral=True)

    @bot.tree.command(name="reset-chat", description="Clear your chat history")
    async def reset_chat_slash(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = str(interaction.user.id)
        bot_core_instance.confirmation_pending[user_id] = {"timestamp": datetime.now(), "awaiting": True}
        await interaction.followup.send("Clear chat history? Reply **yes** or **y** in 60 seconds! 😳", ephemeral=True)

    @bot.tree.command(name="health_check", description="Kiểm tra endpoint LLM, 4 model slot và PostgreSQL (ADMIN ONLY)")
    @is_moderator_or_admin()
    async def health_check_slash(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(
            title="🩺 Health Check",
            color=discord.Color.blurple(),
            timestamp=datetime.now(),
        )

        configured = await resolver.is_configured()
        if not configured:
            embed.add_field(
                name="Endpoint",
                value="❌ Bot chưa được cấu hình. Chạy `/endpoint config`.",
                inline=False,
            )
        else:
            active = await resolver.get_active_sdk()
            ep = await resolver.get_endpoint(active) or {}
            start = time.perf_counter()
            try:
                raw_models = await gateway.list_models_for(
                    sdk=active, base_url=ep.get("base_url") or "", api_key=ep.get("api_key") or ""
                )
                latency_ms = int((time.perf_counter() - start) * 1000)
                model_ids = {m["id"] for m in normalize_models(raw_models)}
                slots = await resolver.get_slot_models(active)
                slot_lines = []
                for slot in SLOT_ORDER:
                    resolved_id = resolve_model_id(slots, slot)
                    found = bool(resolved_id and resolved_id in model_ids)
                    slot_lines.append(f"{'✅' if found else '⚠️'} {SLOT_LABELS[slot]}: `{resolved_id or '(chưa resolve được)'}`")
                embed.add_field(
                    name=f"Endpoint `{active}`",
                    value=f"URL: `{ep.get('base_url')}`\nLatency: `{latency_ms} ms`",
                    inline=False,
                )
                embed.add_field(name="4 slot", value="\n".join(slot_lines), inline=False)
                await db_repo.update_endpoint_check_status(active, True, None)
            except Exception as e:
                await db_repo.update_endpoint_check_status(active, False, str(e)[:300])
                embed.add_field(
                    name=f"Endpoint `{active}`",
                    value=f"❌ Lỗi: `{str(e)[:200]}`",
                    inline=False,
                )

        try:
            await db_repo.init_db()
            embed.add_field(name="PostgreSQL", value="✅ OK", inline=True)
        except Exception as e:
            embed.add_field(name="PostgreSQL", value=f"❌ `{str(e)[:120]}`", inline=True)

        await interaction.followup.send(embed=embed, ephemeral=True)

    endpoint_group = app_commands.Group(
        name="endpoint",
        description="Quản lý endpoint LLM: config / view / switch / models / test (ADMIN ONLY)",
    )

    @endpoint_group.command(name="config", description="Cấu hình endpoint mới: chọn SDK → URL/Key → chọn model 4 slot")
    @is_admin()
    async def endpoint_config(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        flow = EndpointConfigFlow(
            gateway=gateway,
            resolver=resolver,
            db_repo=db_repo,
            config=config,
            admin_user_id=str(interaction.user.id),
        )
        await flow.start(interaction)

    @endpoint_group.command(name="view", description="Xem cấu hình endpoint hiện tại (URL, key ẩn, 4 slot)")
    @is_admin()
    async def endpoint_view(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        endpoints = await db_repo.get_llm_endpoints()
        active = await db_repo.get_active_sdk()
        embed = discord.Embed(title="📡 Cấu hình Endpoint", color=discord.Color.blurple())
        embed.add_field(name="SDK active", value=f"`{active}`" if active else "*chưa có*", inline=False)
        for sdk in ("genai", "openai"):
            row = endpoints.get(sdk)
            if not row:
                embed.add_field(name=sdk, value="*chưa cấu hình*", inline=False)
                continue
            ep = await resolver.get_endpoint(sdk) or {}
            slots = await db_repo.get_llm_model_slots(sdk)
            slot_lines = "\n".join(
                f"- {SLOT_LABELS[s]}: `{slots.get(s) or '(để trống → default rule)'}`" for s in SLOT_ORDER
            )
            if row.get("last_checked_at"):
                ok = "✅" if row.get("last_check_ok") else "❌"
                last_check = f"{ok} lúc {row.get('last_checked_at')}"
                if row.get("last_check_error"):
                    last_check += f" — `{str(row.get('last_check_error'))[:150]}`"
            else:
                last_check = "chưa test lần nào"
            embed.add_field(
                name=sdk,
                value=(
                    f"URL: `{row.get('base_url')}`\n"
                    f"Key: `{mask_api_key(ep.get('api_key') or '')}`\n"
                    f"Cập nhật: {row.get('updated_at')} bởi `{row.get('updated_by')}`\n"
                    f"Check gần nhất: {last_check}\n"
                    f"{slot_lines}"
                ),
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @endpoint_group.command(name="switch", description="Đổi SDK active (không tự chuyển provider lúc runtime)")
    @is_admin()
    async def endpoint_switch(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        endpoints = await db_repo.get_llm_endpoints()

        async def on_choose(choice_interaction: discord.Interaction, sdk: str):
            if sdk not in endpoints:
                await choice_interaction.response.send_message(
                    f"❌ SDK `{sdk}` chưa được cấu hình. Chạy `/endpoint config` trước.",
                    ephemeral=True,
                )
                return
            ok = await db_repo.set_active_sdk(sdk, updated_by=f"admin:{choice_interaction.user.id}")
            resolver.invalidate()
            if ok:
                await choice_interaction.response.send_message(
                    f"✅ Đã chuyển SDK active sang `{sdk}`.", ephemeral=True
                )
            else:
                await choice_interaction.response.send_message(
                    f"⚠️ Không chuyển được sang `{sdk}` (chưa cấu hình).", ephemeral=True
                )

        await interaction.followup.send(
            "🔁 Chọn SDK muốn kích hoạt:", view=SDKChoiceView(on_choose), ephemeral=True
        )

    @endpoint_group.command(name="models", description="Fetch lại danh sách model và gán lại 4 slot")
    @is_admin()
    async def endpoint_models(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        active = await resolver.get_active_sdk()
        ep = await resolver.get_endpoint(active) if active else None
        if not active or not ep:
            await interaction.followup.send(
                "❌ Bot chưa được cấu hình endpoint. Chạy `/endpoint config` trước.", ephemeral=True
            )
            return
        try:
            raw_models = await gateway.list_models_for(
                sdk=active, base_url=ep.get("base_url") or "", api_key=ep.get("api_key") or ""
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Không lấy được danh sách model: `{str(e)[:300]}`", ephemeral=True)
            return
        models = normalize_models(raw_models)
        if not models:
            await interaction.followup.send("❌ Endpoint trả về danh sách model rỗng.", ephemeral=True)
            return
        flow = EndpointConfigFlow(
            gateway=gateway,
            resolver=resolver,
            db_repo=db_repo,
            config=config,
            admin_user_id=str(interaction.user.id),
        )
        slots = await flow.run_slot_pickers(interaction, models)
        if slots is None:
            return
        await db_repo.upsert_llm_model_slots(active, slots, updated_by=f"admin:{interaction.user.id}")
        resolver.invalidate()
        await interaction.followup.send(embed=flow.summary_embed(active, ep.get("base_url") or "", slots), ephemeral=True)

    @endpoint_group.command(name="test", description="Ping endpoint + xác minh 4 model slot tồn tại + đo latency")
    @is_admin()
    async def endpoint_test(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        active = await resolver.get_active_sdk()
        ep = await resolver.get_endpoint(active) if active else None
        if not active or not ep:
            await interaction.followup.send(
                "❌ Bot chưa được cấu hình endpoint. Chạy `/endpoint config` trước.", ephemeral=True
            )
            return
        start = time.perf_counter()
        try:
            raw_models = await gateway.list_models_for(
                sdk=active, base_url=ep.get("base_url") or "", api_key=ep.get("api_key") or ""
            )
            latency_ms = int((time.perf_counter() - start) * 1000)
            model_ids = {m["id"] for m in normalize_models(raw_models)}
            slots = await resolver.get_slot_models(active)
            lines = []
            all_ok = True
            for slot in SLOT_ORDER:
                resolved_id = resolve_model_id(slots, slot)
                found = bool(resolved_id and resolved_id in model_ids)
                all_ok = all_ok and found
                lines.append(f"{'✅' if found else '❌'} {SLOT_LABELS[slot]}: `{resolved_id or '(chưa resolve được)'}`")
            await db_repo.update_endpoint_check_status(active, True, None)
            embed = discord.Embed(
                title="🔌 Endpoint Test",
                color=discord.Color.green() if all_ok else discord.Color.orange(),
            )
            embed.add_field(name="SDK", value=f"`{active}`", inline=True)
            embed.add_field(name="Latency", value=f"`{latency_ms} ms`", inline=True)
            embed.add_field(name="4 slot", value="\n".join(lines), inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await db_repo.update_endpoint_check_status(active, False, str(e)[:300])
            await interaction.followup.send(f"❌ Endpoint lỗi: `{str(e)[:300]}`", ephemeral=True)

    bot.tree.add_command(endpoint_group)

    @bot.tree.command(name="imagine", description="Tạo ảnh bằng AI (Premium/Admin)")
    @app_commands.describe(
        action="Chọn hành động: Tạo ảnh mới hoặc Xem lịch sử",
        prompt="Mô tả ảnh bạn muốn tạo (chỉ bắt buộc khi Tạo ảnh mới)",
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Tạo ảnh mới", value="create"),
        app_commands.Choice(name="Lịch sử ảnh", value="history"),
    ])
    async def imagine_slash(interaction: discord.Interaction, action: app_commands.Choice[str], prompt: Optional[str] = None):
        user_id = str(interaction.user.id)

        if action.value == "history":
            await interaction.response.defer(ephemeral=True)
            history = await db_repo.get_generated_images(user_id, limit=25)
            if not history:
                await interaction.followup.send("Bạn chưa tạo ảnh nào hoặc không có lịch sử.", ephemeral=True)
                return

            view = ImageHistoryView(history)
            await interaction.followup.send("Vui lòng chọn một prompt từ danh sách bên dưới để xem lại ảnh:", view=view, ephemeral=True)
            return

        if not prompt:
            await interaction.response.send_message("⚠️ Bạn cần nhập `prompt` để tạo ảnh mới!", ephemeral=True)
            return

        logger.info(f"User {user_id} requested /imagine to create image with prompt: {prompt}")

        if not (await bot_core_instance._is_admin_user(user_id) or await bot_core_instance._is_moderator_user(user_id) or await db_repo.is_premium_user(user_id)):
            try:
                await interaction.response.defer(ephemeral=True)

                encrypted_path = Path(config.PROJECT_ROOT) / "assets" / "encrypted" / "donate_momo_anh_tr.png.enc"
                key = config.DONATE_ENCRYPTION_KEY

                if not encrypted_path.exists() or not key:
                    await interaction.followup.send("⚠️ Lệnh `/imagine` chỉ dành cho người dùng **Premium**! Vui lòng liên hệ admin để cấp quyền.", ephemeral=True)
                    return

                try:
                    from cryptography.fernet import Fernet

                    fernet = Fernet(key.encode())
                    encrypted_data = encrypted_path.read_bytes()
                    decrypted_data = fernet.decrypt(encrypted_data)

                    file_obj = discord.File(
                        fp=io.BytesIO(decrypted_data),
                        filename="donate_momo_anh_tr.png",
                    )

                    msg = await interaction.followup.send(
                        content=(
                            "⚠️ Lệnh `/imagine` chỉ dành cho người dùng **Premium**!\n"
                            "Cảm ơn bạn đã cân nhắc ủng hộ! Đây là mã QR Momo của Anh Tr, hãy donate và liên hệ admin để cấp quyền nhé:\n"
                            "_Tin nhắn này sẽ tự xóa sau 2 phút._"
                        ),
                        file=file_obj,
                        ephemeral=True,
                    )

                    async def auto_delete():
                        await asyncio.sleep(120)
                        try:
                            await msg.delete()  # type: ignore[union-attr]
                        except (discord.NotFound, discord.Forbidden):
                            pass

                    bot.loop.create_task(auto_delete())

                except Exception as e:
                    logger.error(f"Error sending Momo QR in imagine_slash: {e}")
                    await interaction.followup.send("⚠️ Lệnh `/imagine` chỉ dành cho người dùng **Premium**! Vui lòng liên hệ admin để cấp quyền.", ephemeral=True)
            except Exception:
                pass
            return

        await interaction.response.defer(ephemeral=False)
        await interaction.followup.send("⏳ Đang gửi yêu cầu tạo ảnh...")

        interaction_id_str = str(interaction.id)
        bot_core_instance.active_interactions[interaction_id_str] = interaction

        payload = {
            "type": "slash_command",
            "command": "imagine",
            "action": "create",
            "prompt": prompt,
            "interaction_id": interaction_id_str,
            "user_id": user_id,
            "channel_id": str(interaction.channel_id),
            "author_display_name": interaction.user.display_name
        }
        await kafka_service.publish("discord-incoming", payload=payload, key=user_id)

    @bot.tree.command(name="premium", description="Tính năng Premium")
    @app_commands.describe(action="Chọn hành động", user="Người dùng (chỉ dành cho add/check)")
    @app_commands.choices(action=[
        app_commands.Choice(name="Check (Kiểm tra Premium)", value="check"),
        app_commands.Choice(name="Buy (Mua Premium)", value="buy"),
        app_commands.Choice(name="Add (Thêm Premium - Admin)", value="add"),
    ])
    async def premium_slash(interaction: discord.Interaction, action: app_commands.Choice[str], user: Optional[discord.User] = None):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            logger.error("Interaction not found for premium command.")
            return

        requester_id = str(interaction.user.id)
        target_user_id = str(user.id) if user else requester_id
        is_admin = await bot_core_instance._is_admin_user(requester_id)

        if action.value == "add":
            if not is_admin:
                await interaction.followup.send("❌ Bạn không có quyền sử dụng lệnh này!", ephemeral=True)
                return
            if not user:
                await interaction.followup.send("❌ Vui lòng chọn người dùng cần thêm vào danh sách Premium!", ephemeral=True)
                return

            await db_repo.add_premium_user(target_user_id)
            await interaction.followup.send(f"🎉 Đã thêm **{user.display_name}** vào danh sách Premium thành công!", ephemeral=True)
            return

        if action.value == "check":
            if await bot_core_instance._is_admin_user(target_user_id):
                await interaction.followup.send(
                    f"👑 {'Bạn' if target_user_id == requester_id else (user.display_name if user else 'Người này')} là **Admin** của bot!",
                    ephemeral=True,
                )
                return

            if await bot_core_instance._is_moderator_user(target_user_id):
                await interaction.followup.send(
                    f"🛡️ {'Bạn' if target_user_id == requester_id else (user.display_name if user else 'Người này')} là **Moderator** của bot!",
                    ephemeral=True,
                )
                return

            if await db_repo.is_premium_user(target_user_id):
                await interaction.followup.send(
                    f"✨ {'Bạn' if target_user_id == requester_id else (user.display_name if user else 'Người này')} đang sử dụng bản **Premium**!",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    f"😔 {'Bạn' if target_user_id == requester_id else (user.display_name if user else 'Người này')} **chưa có Premium**. Dùng `/premium action:Buy` để nâng cấp nhé!",
                    ephemeral=True,
                )
            return

        if action.value == "buy":
            is_moderator = await bot_core_instance._is_moderator_user(requester_id)
            if is_admin or is_moderator or await db_repo.is_premium_user(requester_id):
                await interaction.followup.send("✨ Bạn đã có quyền Premium/Admin/Moderator rồi nhé! Không cần mua thêm đâu 🥰", ephemeral=True)
                return

            donate_platforms = {
                "anhtr_momo": {
                    "file": "donate_momo_anh_tr.png.enc",
                    "original_filename": "donate_momo_anh_tr.png",
                }
            }

            info = donate_platforms.get("anhtr_momo")
            if not info:
                await interaction.followup.send("Thông tin donate không khả dụng.", ephemeral=True)
                return
            encrypted_path = Path(config.PROJECT_ROOT) / "assets" / "encrypted" / info["file"]

            if not encrypted_path.exists():
                await interaction.followup.send("Mã QR hiện không khả dụng. Vui lòng liên hệ Admin.", ephemeral=True)
                return

            key = config.DONATE_ENCRYPTION_KEY
            try:
                from cryptography.fernet import Fernet

                fernet = Fernet(key.encode())
                decrypted_data = fernet.decrypt(encrypted_path.read_bytes())
                file_obj = discord.File(fp=io.BytesIO(decrypted_data), filename=info["original_filename"])

                msg = (
                    "✨ **Nâng cấp lên Premium** ✨\n\n"
                    "Với bản Premium, bạn sẽ được:\n"
                    "- 🔓 **Mở khóa không giới hạn** số tin nhắn chat (miễn phí chỉ 50 tin nhắn/ngày).\n"
                    "- 🎨 **Sử dụng lệnh `/imagine`** tạo ảnh AI chất lượng cao.\n"
                    "- 💬 **Sử dụng tính năng chat DM** riêng tư với bot.\n\n"
                    "Để mua Premium, vui lòng quét mã QR Momo của Anh Tr bên dưới để donate. Sau khi donate, hãy liên hệ Admin kèm theo ảnh chụp màn hình giao dịch để được kích hoạt ngay nhé!"
                )
                await interaction.followup.send(content=msg, file=file_obj, ephemeral=True)
            except Exception as e:
                logger.error(f"Error decrypting Momo QR for buy premium: {e}")
                await interaction.followup.send("Không thể tải mã QR lúc này. Vui lòng liên hệ Admin.", ephemeral=True)

    @bot.tree.command(name="moderator", description="Quản lý Moderator động (ADMIN ONLY)")
    @app_commands.describe(action="Chọn hành động", user="Người dùng")
    @app_commands.choices(action=[
        app_commands.Choice(name="Check (Kiểm tra)", value="check"),
        app_commands.Choice(name="Add (Thêm Moderator)", value="add"),
        app_commands.Choice(name="Remove (Xóa Moderator)", value="remove"),
    ])
    @is_admin()
    async def moderator_slash(interaction: discord.Interaction, action: app_commands.Choice[str], user: discord.User):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            logger.error("Interaction not found for moderator command.")
            return

        requester_id = str(interaction.user.id)
        target_user_id = str(user.id)
        is_admin_req = await bot_core_instance._is_admin_user(requester_id)

        if not is_admin_req:
            await interaction.followup.send("❌ Bạn không phải Admin hệ thống, không có quyền quản lý Moderator!", ephemeral=True)
            return

        if action.value == "add":
            if target_user_id in config.ADMIN_USER_IDS:
                await interaction.followup.send(f"👑 **{user.display_name}** đã là Admin cấu hình tĩnh!", ephemeral=True)
                return
            if target_user_id in config.MODERATOR_USER_IDS:
                await interaction.followup.send(f"🛡️ **{user.display_name}** đã là Moderator cấu hình tĩnh!", ephemeral=True)
                return

            await db_repo.add_moderator_user(target_user_id)
            await interaction.followup.send(f"🎉 Đã thăng chức **{user.display_name}** làm Moderator động thành công!", ephemeral=True)
            return

        if action.value == "remove":
            if target_user_id in config.ADMIN_USER_IDS or target_user_id in config.MODERATOR_USER_IDS:
                await interaction.followup.send("❌ Không thể hạ chức tài khoản cấu hình tĩnh trong .env!", ephemeral=True)
                return

            removed = await db_repo.remove_moderator_user(target_user_id)
            if removed:
                await interaction.followup.send(f"✅ Đã hạ chức người dùng **{user.display_name}** khỏi vai trò Moderator.", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Người dùng **{user.display_name}** không phải Moderator động.", ephemeral=True)
            return

        if action.value == "check":
            is_static_admin = target_user_id in config.ADMIN_USER_IDS
            is_static_mod = target_user_id in config.MODERATOR_USER_IDS
            is_dynamic_admin = await db_repo.is_admin_user(target_user_id)
            is_dynamic_mod = await db_repo.is_moderator_user(target_user_id)

            if is_static_admin:
                await interaction.followup.send(f"👑 **{user.display_name}** là Admin hệ thống (tĩnh).", ephemeral=True)
            elif is_dynamic_admin:
                await interaction.followup.send(f"👑 **{user.display_name}** là Admin hệ thống (động).", ephemeral=True)
            elif is_static_mod:
                await interaction.followup.send(f"🛡️ **{user.display_name}** là Moderator hệ thống (tĩnh).", ephemeral=True)
            elif is_dynamic_mod:
                await interaction.followup.send(f"🛡️ **{user.display_name}** là Moderator hệ thống (động).", ephemeral=True)
            else:
                await interaction.followup.send(f"👤 **{user.display_name}** là người dùng bình thường.", ephemeral=True)
            return

    @bot.tree.command(name="reset-all", description="Clear all DB (ADMIN ONLY)")
    @is_admin()
    async def reset_all_slash(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        admin_id = str(interaction.user.id)
        bot_core_instance.admin_confirmation_pending[admin_id] = {"timestamp": datetime.now(), "awaiting": True}
        await interaction.followup.send("⚠️ **ADMIN CONFIRM**: Reply **YES RESET** in 60 seconds to clear all DB!", ephemeral=True)

    @bot.tree.command(name="global-notes", description="Browse global shared memory notes (ADMIN ONLY)")
    @app_commands.describe(limit="Max notes to load (1-100)")
    @is_moderator_or_admin()
    async def global_notes_slash(interaction: discord.Interaction, limit: app_commands.Range[int, 1, 100] = 40):
        await interaction.response.defer(ephemeral=True)
        notes = await db_repo.get_global_notes_db(limit=int(limit))

        if not notes:
            await interaction.followup.send("No global notes found.", ephemeral=True)
            return

        view = GlobalNoteView(notes, page_size=8)
        await interaction.followup.send(content=view.summary_text(), view=view, ephemeral=True)

    @bot.tree.command(name="global-note-demote", description="Demote shared note from global (ADMIN ONLY)")
    @app_commands.describe(target="(Optional) note_id hoặc fact_hash để demote nhanh")
    @is_moderator_or_admin()
    async def global_note_demote_slash(interaction: discord.Interaction, target: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)

        token = (target or "").strip()
        if token:
            changed_by_id = False
            if "-" in token:
                changed_by_id = await db_repo.demote_global_note_by_id_db(token)

            changed_by_hash = 0
            if not changed_by_id:
                changed_by_hash = await db_repo.demote_global_fact_hash_db(token)

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

        notes = await db_repo.get_global_notes_db(limit=100)
        if not notes:
            await interaction.followup.send("No global notes found.", ephemeral=True)
            return

        view = GlobalNoteDemoteView(notes, db_repo, page_size=8)
        await interaction.followup.send(content=view.summary_text(), view=view, ephemeral=True)

    @bot.tree.command(name="message_to", description="Send message to user (ADMIN ONLY)")
    @app_commands.describe(user="Target user", message="Message content", channel="Optional channel")
    @is_moderator_or_admin()
    async def message_to_slash(interaction: discord.Interaction, user: discord.User, message: str, channel: Optional[discord.TextChannel] = None):
        await interaction.response.defer(ephemeral=True)
        requester_id = str(interaction.user.id)
        is_admin_req = await bot_core_instance._is_admin_user(requester_id)
        is_moderator = await bot_core_instance._is_moderator_user(requester_id)

        if is_moderator and not is_admin_req:
            if not channel:
                await interaction.followup.send("❌ Moderator không được quyền gửi DM trực tiếp!", ephemeral=True)
                return
            if not interaction.guild or channel.guild != interaction.guild:
                await interaction.followup.send("❌ Moderator chỉ được phép gửi tin nhắn trong server sở tại!", ephemeral=True)
                return

        user_id = str(user.id)
        cleaned_message = " ".join(message.strip().split())

        try:
            target_user = await bot.fetch_user(int(user_id))
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
                await channel.send(f"{target_user.mention} {cleaned_message}")
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
            logger.error(f"Error sending message to {user_id}: {e}")

    donate_platforms = {
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
        "anhtr_momo": {
            "file": "donate_momo_anh_tr.png.enc",
            "display_name": "Momo (Anh Tr)",
            "original_filename": "donate_momo_anh_tr.png",
            "message": "Cảm ơn bạn đã cân nhắc ủng hộ! Đây là mã QR Momo của Anh Tr:",
        },
    }

    @bot.tree.command(name="donate", description="Hiện mã QR ủng hộ (Ko-fi, PayPal hoặc Momo)")
    @app_commands.describe(platform="Chọn nền tảng ủng hộ (mặc định: Ko-fi)")
    @app_commands.choices(platform=[
        app_commands.Choice(name="Ko-fi (recommended)", value="kofi"),
        app_commands.Choice(name="PayPal", value="paypal"),
        app_commands.Choice(name="Momo - Anh Tr", value="anhtr_momo"),
    ])
    async def donate_slash(interaction: discord.Interaction, platform: Optional[app_commands.Choice[str]] = None):
        await interaction.response.defer()

        selected = platform.value if platform else "kofi"
        info = donate_platforms.get(selected)
        if not info:
            await interaction.followup.send("Nền tảng không hợp lệ.", ephemeral=True)
            return

        encrypted_path = Path(config.PROJECT_ROOT) / "assets" / "encrypted" / info["file"]
        if not encrypted_path.exists():
            logger.error(f"Donate: encrypted file not found: {encrypted_path}")
            await interaction.followup.send("Mã QR hiện không khả dụng. Vui lòng thử lại sau.", ephemeral=True)
            return

        key = config.DONATE_ENCRYPTION_KEY
        if not key:
            logger.error("Donate: DONATE_ENCRYPTION_KEY not configured")
            await interaction.followup.send("Mã QR hiện không khả dụng. Vui lòng thử lại sau.", ephemeral=True)
            return

        try:
            from cryptography.fernet import Fernet

            fernet = Fernet(key.encode())
            encrypted_data = encrypted_path.read_bytes()
            decrypted_data = fernet.decrypt(encrypted_data)
        except Exception as e:
            logger.error(f"Donate: decryption failed: {e}")
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
                await msg.delete()  # type: ignore[union-attr]
            except (discord.NotFound, discord.Forbidden):
                pass

        bot.loop.create_task(auto_delete())

    if not voice_lock_manager:
        return

    owner_check = voice_lock_manager.is_owner_check()

    @bot.tree.command(name="lock", description="Khóa phòng voice hiện tại, chặn người ngoài allowlist và dọn tin nhắn vi phạm")
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

        if room_lock_service and room_lock_service.is_locked(channel.id):
            await interaction.followup.send(
                f"Phòng **{channel.name}** đang bị khóa rồi. Dùng `/unlock` trước khi khóa lại.",
                ephemeral=True,
            )
            return

        if room_lock_service:
            outcome = await room_lock_service.lock(channel, interaction.user.id)
            embed = discord.Embed(
                title=f"🔒 Đã khóa phòng {channel.name}",
                colour=discord.Colour.red(),
                timestamp=outcome.record.locked_at,
            )
            kicked_str = ", ".join(outcome.kicked) if outcome.kicked else "Không có ai ngoài allowlist"
            embed.add_field(name="Đã kick ngoài allowlist", value=kicked_str, inline=False)
            if outcome.purge and outcome.purge.has_work:
                embed.add_field(name="Dọn tin nhắn", value=outcome.purge.summary(), inline=False)
            if outcome.reactions_removed:
                embed.add_field(name="Biểu cảm đã gỡ", value=f"Đã gỡ {outcome.reactions_removed} biểu cảm", inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)

    @bot.tree.command(name="unlock", description="Mở khóa phòng voice hiện tại cho tất cả mọi người")
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

        if room_lock_service:
            if not room_lock_service.is_locked(channel.id):
                await interaction.followup.send(
                    f"Phòng **{channel.name}** đang mở, không cần mở khóa.", ephemeral=True
                )
                return
            record = await room_lock_service.unlock(channel)
            embed = discord.Embed(
                title=f"🔓 Đã mở khóa {channel.name}",
                colour=discord.Colour.green(),
                description=f"Phòng **{channel.name}** đã mở lại cho tất cả mọi người.",
            )
            if record:
                embed.add_field(name="Mốc đã khóa", value=f"<t:{int(record.locked_at.timestamp())}:F>")
            await interaction.followup.send(embed=embed, ephemeral=True)

    @bot.tree.command(name="locklist", description="Xem danh sách các phòng voice đang khóa trong server")
    @owner_check
    async def lock_list(interaction: discord.Interaction):
        if not interaction.guild:
            return
        if room_lock_service:
            channels = room_lock_service.locked_channels(interaction.guild)
            if not channels:
                await interaction.response.send_message("Server này chưa có phòng nào đang khóa.", ephemeral=True)
                return
            lines = []
            for ch in channels:
                rec = room_lock_service.record(ch.id)
                stamp = int(rec.locked_at.timestamp()) if rec else 0
                lines.append(f"🔒 {ch.mention} — khóa lúc <t:{stamp}:F>")
            await interaction.response.send_message("\n".join(lines), ephemeral=True)

    async def _handle_allow_member(interaction: discord.Interaction, member: discord.Member):
        if not room_lock_service:
            return
        if member.id == interaction.user.id:
            await interaction.response.send_message("Bạn là chủ phòng, đã có quyền sẵn.", ephemeral=True)
            return
        room_lock_service.whitelist.add(member.id, member.display_name)
        granted = await room_lock_service.grant_access(member)
        await interaction.response.send_message(
            f"✅ Đã thêm {member.mention} vào allowlist · mở quyền ở **{granted}** phòng đang khóa.",
            ephemeral=True,
        )

    @bot.tree.command(name="allow", description="Thêm người vào allowlist phòng voice khóa")
    @owner_check
    async def allow_member(interaction: discord.Interaction, member: discord.Member):
        await _handle_allow_member(interaction, member)

    @bot.tree.command(name="add_privet", description="Thêm người vào whitelist để không bị kick khi lock (alias của /allow)")
    @owner_check
    async def add_privet(interaction: discord.Interaction, member: discord.Member):
        await _handle_allow_member(interaction, member)

    async def _handle_remove_member(interaction: discord.Interaction, member: discord.Member):
        if not room_lock_service:
            return
        if not room_lock_service.whitelist.contains(member.id):
            await interaction.response.send_message(f"{member.mention} không có trong allowlist.", ephemeral=True)
            return
        room_lock_service.whitelist.remove(member.id)
        revoked = await room_lock_service.revoke_access(member)
        await interaction.response.send_message(
            f"🚫 Đã loại {member.mention} khỏi allowlist · đóng quyền ở **{revoked}** phòng đang khóa.",
            ephemeral=True,
        )

    @bot.tree.command(name="allowremove", description="Xóa người khỏi allowlist phòng voice khóa")
    @owner_check
    async def allow_remove_member(interaction: discord.Interaction, member: discord.Member):
        await _handle_remove_member(interaction, member)

    @bot.tree.command(name="remove_privet", description="Xóa người khỏi whitelist (alias của /allowremove)")
    @owner_check
    async def remove_privet(interaction: discord.Interaction, member: discord.Member):
        await _handle_remove_member(interaction, member)

    async def _handle_list_allow(interaction: discord.Interaction):
        if not room_lock_service:
            return
        entries = room_lock_service.whitelist.entries()
        if not entries:
            await interaction.response.send_message("📜 Allowlist đang trống (ngoài owner).", ephemeral=True)
            return
        lines = ["📜 **Danh sách Allowlist:**"]
        for uid, username in entries:
            lines.append(f"🔹 <@{uid}> (`{username or 'Unknown'}` - `{uid}`)")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @bot.tree.command(name="allowlist", description="Xem danh sách allowlist phòng voice khóa")
    @owner_check
    async def allow_list(interaction: discord.Interaction):
        await _handle_list_allow(interaction)

    @bot.tree.command(name="list_privet", description="Liệt kê whitelist voice-room (alias của /allowlist)")
    @owner_check
    async def list_privet(interaction: discord.Interaction):
        await _handle_list_allow(interaction)

    @bot.tree.command(name="move", description="Chuyển một thành viên sang voice channel khác")
    @app_commands.autocomplete(member=bot_core_instance._member_autocomplete, channel=bot_core_instance._voice_channel_autocomplete)
    @owner_check
    async def move_member(interaction: discord.Interaction, member: str, channel: str):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            return
        if not room_tools_service or not interaction.guild:
            await interaction.followup.send("⚠️ Dịch vụ voice chưa sẵn sàng.", ephemeral=True)
            return
        try:
            target_member = interaction.guild.get_member(int(member))
            target_channel = interaction.guild.get_channel(int(channel))
            if not target_member or not isinstance(target_channel, discord.VoiceChannel):
                await interaction.followup.send("⚠️ Không tìm thấy thành viên hoặc phòng voice hợp lệ.", ephemeral=True)
                return
            ok, msg = await room_tools_service.move_member(target_member, target_channel, interaction.user)
            await interaction.followup.send(msg, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Lỗi: {e}", ephemeral=True)

    @bot.tree.command(name="move_all", description="Chuyển bạn và toàn bộ người trong allowlist sang phòng khác")
    @owner_check
    async def move_all(interaction: discord.Interaction, target_channel: discord.VoiceChannel):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass
        if not room_tools_service or not interaction.guild:
            await interaction.followup.send("⚠️ Dịch vụ voice chưa sẵn sàng.", ephemeral=True)
            return

        source = get_requester_voice_channel(interaction)
        if source is None:
            await interaction.followup.send("⚠️ Bạn đang không ở trong voice.", ephemeral=True)
            return
        if source.id == target_channel.id:
            await interaction.followup.send("⚠️ Bạn chọn trùng phòng hiện tại.", ephemeral=True)
            return

        moved, failed = await room_tools_service.move_all(source, target_channel, interaction.user)
        text = f"Đã chuyển **{moved}** người sang **{target_channel.name}**."
        if failed:
            text += f"\nKhông chuyển được: {', '.join(failed[:8])}"
        await interaction.followup.send(text, ephemeral=True)

    @bot.tree.command(name="set_room", description="Đổi tên và trạng thái phòng hiện tại (khóa tên nếu phòng đang bị lock)")
    @app_commands.describe(name="Tên mới", status="Trạng thái mới")
    @owner_check
    async def set_room(interaction: discord.Interaction, name: Optional[str] = None, status: Optional[str] = None):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass
        if not room_tools_service:
            await interaction.followup.send("⚠️ Dịch vụ voice chưa sẵn sàng.", ephemeral=True)
            return

        channel = get_requester_voice_channel(interaction)
        if channel is None:
            await interaction.followup.send("⚠️ Bạn đang không ở trong voice.", ephemeral=True)
            return

        if name is None and status is None:
            await interaction.followup.send(
                f"Phòng **{channel.name}** — status: `{getattr(channel, 'status', None) or 'trống'}`.\n"
                "Dùng `/set_room name: ... status: ...` để đổi.",
                ephemeral=True,
            )
            return

        ok, updates = await room_tools_service.set_room(channel, name=name, status=status)
        if ok:
            await interaction.followup.send(
                "✅ Đã cập nhật phòng:\n" + "\n".join(f"🔹 {u}" for u in updates),
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"❌ Cập nhật thất bại: {', '.join(updates) if updates else 'Lỗi không xác định'}",
                ephemeral=True,
            )

    @bot.tree.command(name="rolerank", description="Kéo thứ hạng role lên cao hơn bằng menu chọn trực quan (ADMIN ONLY)")
    @is_admin()
    async def rolerank_command(interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return
        if not guild.me.guild_permissions.manage_roles:
            await interaction.response.send_message("Bot thiếu quyền Manage Roles trong server này.", ephemeral=True)
            return
        view = RolePickerView(guild, interaction.user.id)
        await interaction.response.send_message(embed=view.embed, view=view, ephemeral=True)
        try:
            view.message = await interaction.original_response()
        except discord.NotFound:
            pass

    change_group = app_commands.Group(name="change", description="Đổi biệt danh thành viên trong server (ADMIN ONLY)")

    @change_group.command(name="bd", description="Đổi biệt danh của bạn hoặc một thành viên")
    @is_admin()
    @app_commands.describe(
        nickname="Biệt danh mới (tối đa 32 ký tự)",
        member="Người cần đổi biệt danh (bỏ trống = đổi tên chính bạn)",
    )
    async def change_bd(
        interaction: discord.Interaction,
        nickname: str,
        member: Optional[discord.Member] = None,
    ):
        if len(nickname) > 32:
            await interaction.response.send_message("Biệt danh không được quá 32 ký tự.", ephemeral=True)
            return

        target = member if member is not None else interaction.user
        me = interaction.guild.me if interaction.guild else None
        if not me or not me.guild_permissions.manage_nicknames:
            await interaction.response.send_message("Bot thiếu quyền Manage Nicknames trong server này.", ephemeral=True)
            return

        try:
            await target.edit(nick=nickname)
            who = interaction.user.mention if target == interaction.user else target.mention
            await interaction.response.send_message(f"Đã đổi biệt danh của {who} thành **{nickname}**", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                "Không đổi được: bot thiếu quyền hoặc role của bot thấp hơn role của người cần đổi.",
                ephemeral=True,
            )
        except discord.HTTPException as error:
            await interaction.response.send_message(f"Lỗi khi đổi biệt danh: {error}", ephemeral=True)

    bot.tree.add_command(change_group)

    @bot.tree.error
    async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Lệnh này chỉ dành cho owner đã cấu hình.", ephemeral=True)
            return
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ Đã có lỗi: {error}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Đã có lỗi: {error}", ephemeral=True)
        except Exception:
            pass
