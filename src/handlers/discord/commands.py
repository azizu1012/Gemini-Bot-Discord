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

    @bot.tree.command(name="lock", description="Khóa phòng voice hiện tại và kick người không whitelist")
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

        bot_user = bot.user
        if bot_user is None:
            await interaction.followup.send("⚠️ Bot chưa sẵn sàng.", ephemeral=True)
            return

        whitelist = voice_lock_manager.load_whitelist()

        default_role = interaction.guild.default_role
        overwrite = channel.overwrites_for(default_role)
        overwrite.connect = False
        await channel.set_permissions(default_role, overwrite=overwrite, reason="Lock room command")

        voice_lock_manager.locked_channels.add(channel.id)
        voice_lock_manager.save_locked_channels()
        voice_lock_manager.log_action(f"🔒 LOCK tại {channel.name} bởi {interaction.user.name}")

        kicked_users: List[str] = []
        for member in channel.members:
            if str(member.id) in whitelist or member.id == voice_lock_manager.owner_id or member.id == bot_user.id:
                member_overwrite = channel.overwrites_for(member)
                member_overwrite.connect = True
                await channel.set_permissions(member, overwrite=member_overwrite)
                continue
            try:
                await member.move_to(None, reason="Locked out by owner")
                kicked_users.append(member.name)
                voice_lock_manager.log_action(f"🧹 LOCK-KICK: {member.name} ({member.id})")
            except Exception as e:
                logger.warning(f"Kick fail {member.name}: {e}")

        msg = f"🔒 Đã khóa channel **{channel.name}**."
        if kicked_users:
            msg += f"\n👢 Đã kick {len(kicked_users)} người: {', '.join(kicked_users)}"
        await interaction.followup.send(msg, ephemeral=True)

    @bot.tree.command(name="unlock", description="Mở khóa phòng voice hiện tại")
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

        voice_lock_manager.locked_channels.discard(channel.id)
        if channel.id in voice_lock_manager.enforced_names:
            del voice_lock_manager.enforced_names[channel.id]
            voice_lock_manager.save_enforced_names()
        voice_lock_manager.save_locked_channels()
        voice_lock_manager.log_action(f"🔓 UNLOCK tại {channel.name} bởi {interaction.user.name}")

        await interaction.followup.send(f"🔓 Đã mở khóa channel **{channel.name}**.", ephemeral=True)

    @bot.tree.command(name="move", description="Chuyển một thành viên sang voice channel khác")
    @app_commands.autocomplete(member=bot_core_instance._member_autocomplete, channel=bot_core_instance._voice_channel_autocomplete)
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
            if target_channel.id in voice_lock_manager.locked_channels:
                await target_channel.set_permissions(target_member, connect=True)
            await target_member.move_to(target_channel)
            await interaction.followup.send(f"✅ Đã chuyển vào {target_channel.name}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Lỗi: {e}", ephemeral=True)

    @bot.tree.command(name="move_all", description="Chuyển owner + whitelist từ phòng hiện tại sang phòng khác")
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

        whitelist = voice_lock_manager.load_whitelist()

        if source_channel.id == target_channel.id:
            await interaction.followup.send("⚠️ Bạn chọn trùng phòng hiện tại.", ephemeral=True)
            return

        moved_count = 0
        for m in source_channel.members:
            if str(m.id) in whitelist or m.id == voice_lock_manager.owner_id:
                try:
                    await m.move_to(target_channel, reason="Mass move by owner")
                    moved_count += 1
                except Exception:
                    pass

        if source_channel.id in voice_lock_manager.locked_channels:
            voice_lock_manager.locked_channels.discard(source_channel.id)
            voice_lock_manager.locked_channels.add(target_channel.id)
            voice_lock_manager.save_locked_channels()

            default_role = interaction.guild.default_role
            old_overwrite = source_channel.overwrites_for(default_role)
            old_overwrite.connect = None
            await source_channel.set_permissions(default_role, overwrite=old_overwrite)

            new_overwrite = target_channel.overwrites_for(default_role)
            new_overwrite.connect = False
            await target_channel.set_permissions(default_role, overwrite=new_overwrite)

            voice_lock_manager.log_action(f"✈️ MASS-MOVE + RELOCK tại {target_channel.name}")

        await interaction.followup.send(
            f"✅ Đã chuyển {moved_count} thành viên sang **{target_channel.name}**.",
            ephemeral=True,
        )

    @bot.tree.command(name="set_room", description="Đổi tên/trạng thái phòng hiện tại và khóa sửa tên")
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
        voice_lock_manager.ignore_next_updates.add(channel.id)

        if name:
            try:
                await channel.edit(name=name, reason="Owner room rename")
                voice_lock_manager.enforced_names[channel.id] = name
                voice_lock_manager.save_enforced_names()
                updates.append(f"Tên phòng: **{name}**")
            except discord.errors.Forbidden:
                await interaction.followup.send("❌ Bot thiếu quyền Manage Channels để đổi tên.", ephemeral=True)
                voice_lock_manager.ignore_next_updates.discard(channel.id)
                return

        if status is not None:
            logger.info("VoiceChannel.status edit is not supported in discord.py; skipped status update request.")

        await asyncio.sleep(3)
        voice_lock_manager.ignore_next_updates.discard(channel.id)

        if updates:
            voice_lock_manager.log_action(f"✏️ SET_ROOM: {' | '.join(updates)} ở {channel.id}")
            await interaction.followup.send(
                "✅ Đã cập nhật và bật chống sửa tên phòng.\n" + "\n".join(f"🔹 {u}" for u in updates),
                ephemeral=True,
            )
        else:
            await interaction.followup.send("⚠️ Bạn chưa nhập name/status để đổi.", ephemeral=True)

    @bot.tree.command(name="add_privet", description="Thêm người vào whitelist để không bị kick khi lock")
    @owner_check
    async def add_privet(interaction: discord.Interaction, member: discord.Member):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            pass

        whitelist = voice_lock_manager.load_whitelist()
        user_id_str = str(member.id)
        if user_id_str in whitelist:
            await interaction.followup.send(f"⚠️ **{member.display_name}** đã có trong whitelist.", ephemeral=True)
            return

        whitelist[user_id_str] = {"username": member.name, "id": user_id_str}
        voice_lock_manager.save_whitelist(whitelist)

        owner_channel = get_requester_voice_channel(interaction)
        if owner_channel is not None:
            member_overwrite = owner_channel.overwrites_for(member)
            member_overwrite.connect = True
            await owner_channel.set_permissions(member, overwrite=member_overwrite)

        await interaction.followup.send(
            f"✅ Đã thêm **{member.display_name}** vào whitelist.",
            ephemeral=True,
        )

    @bot.tree.command(name="remove_privet", description="Xóa một người khỏi whitelist")
    @owner_check
    async def remove_privet(interaction: discord.Interaction, member: discord.Member):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            pass

        whitelist = voice_lock_manager.load_whitelist()
        user_id_str = str(member.id)

        if user_id_str == str(voice_lock_manager.owner_id):
            await interaction.followup.send("❌ Bạn không thể tự loại khỏi whitelist.", ephemeral=True)
            return

        if user_id_str not in whitelist:
            await interaction.followup.send(f"⚠️ {member.display_name} không có trong whitelist.", ephemeral=True)
            return

        del whitelist[user_id_str]
        voice_lock_manager.save_whitelist(whitelist)

        owner_channel = get_requester_voice_channel(interaction)
        if owner_channel is not None:
            if member in owner_channel.members:
                await member.move_to(None, reason="Removed from whitelist by owner")

            member_overwrite = owner_channel.overwrites_for(member)
            member_overwrite.connect = None
            await owner_channel.set_permissions(member, overwrite=member_overwrite)

        await interaction.followup.send(
            f"🗑️ Đã xóa **{member.display_name}** khỏi whitelist.",
            ephemeral=True,
        )

    @bot.tree.command(name="list_privet", description="Liệt kê whitelist voice-room")
    @owner_check
    async def list_privet(interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            pass

        whitelist = voice_lock_manager.load_whitelist()
        if len(whitelist) <= 1:
            await interaction.followup.send("📜 Danh sách trống (ngoài owner).", ephemeral=True)
            return

        lines = ["📜 **Whitelist voice-room:**"]
        for uid, data in whitelist.items():
            if uid == str(voice_lock_manager.owner_id):
                continue
            username = data.get("username", "Unknown")
            lines.append(f"🔹 **{username}** `(UID: {uid})`")

        await interaction.followup.send("\n".join(lines), ephemeral=True)

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
