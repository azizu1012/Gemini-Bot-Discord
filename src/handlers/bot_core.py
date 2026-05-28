import asyncio
import io
import json
import random
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import discord
from src.services.kafka_service import KafkaService
from discord import app_commands
from discord.ext import commands

from src.core.config import Config, logger
from src.core.custom_endpoint import CUSTOM_ENDPOINT_PRESETS, normalize_custom_endpoint, resolve_custom_endpoint_preset
from src.database.repository import DatabaseRepository
from src.managers.cleanup_manager import CleanupManager
from src.services.health_checker import get_health_checker
from src.voice.voice_lock import VoiceLockManager


CUSTOM_ENDPOINT_PRESET_LABELS = {
    "manual": "Nhập tay endpoint",
    "lm_studio": "LM Studio local",
    "ollama": "Ollama local",
}

CUSTOM_ENDPOINT_DUMMY_KEYS = {
    "lm_studio": "lm-studio-local",
    "ollama": "ollama-local",
}


def _custom_endpoint_preset_label(preset: Any) -> str:
    return CUSTOM_ENDPOINT_PRESET_LABELS.get(str(preset or "manual").strip().lower(), CUSTOM_ENDPOINT_PRESET_LABELS["manual"])


def _custom_endpoint_dummy_key(preset: Any) -> str:
    return CUSTOM_ENDPOINT_DUMMY_KEYS.get(str(preset or "manual").strip().lower(), "")


def _clean_custom_endpoint_preset(preset: Any) -> str:
    clean = str(preset or "manual").strip().lower()
    return clean if clean in CUSTOM_ENDPOINT_PRESETS else "manual"


def _flatten_note_preview(note: Dict[str, Any], max_len: int = 80) -> str:
    content = str(note.get("content", "")).replace("\n", " ").strip()
    if len(content) > max_len:
        return content[: max_len - 3] + "..."
    return content or "(empty)"


def _format_note_detail(note: Dict[str, Any]) -> str:
    content = str(note.get("content", ""))
    if len(content) > 1600:
        content = content[:1600] + "\n... (truncated)"
    return (
        "🧾 **Global note detail**\n"
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


class ImageHistorySelect(discord.ui.Select):
    def __init__(self, history: List[Dict[str, Any]]):
        self.history = history
        options = []
        for i, record in enumerate(history):
            prompt = str(record.get("prompt", ""))
            label = prompt[:97] + "..." if len(prompt) > 100 else prompt
            options.append(discord.SelectOption(label=label, description=f"Ảnh #{i + 1}", value=str(i)))
        super().__init__(placeholder="Chọn một prompt từ lịch sử...", options=options)

    async def callback(self, interaction: discord.Interaction):
        idx = int(self.values[0])
        record = self.history[idx]

        embed = discord.Embed(
            title="Lịch sử ảnh",
            description=f"**Prompt:** {record.get('prompt', '')}",
            color=discord.Color.green(),
        )

        image_url = record.get("image_url", "")
        file = None
        if image_url.startswith(("http://", "https://")):
            embed.set_image(url=image_url)
        else:
            import os
            if os.path.exists(image_url):
                filename = os.path.basename(image_url)
                file = discord.File(image_url, filename=filename)
                embed.set_image(url=f"attachment://{filename}")
            else:
                embed.set_image(url=image_url)

        if file:
            await interaction.response.edit_message(content=None, embed=embed, attachments=[file], view=self.view)
        else:
            await interaction.response.edit_message(content=None, embed=embed, view=self.view)


class ImageHistoryView(discord.ui.View):
    def __init__(self, history: List[Dict[str, Any]]):
        super().__init__(timeout=300)
        self.add_item(ImageHistorySelect(history))


class CustomApiConfigView(discord.ui.View):
    def __init__(
        self,
        models: List[Dict[str, Any]],
        current_config: Dict[str, Any],
        db_repo: DatabaseRepository,
        router: Any,
        updated_by: str,
        provider_config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(timeout=300)
        self.models = list(models[:25])
        self.db_repo = db_repo
        self.router = router
        self.updated_by = updated_by
        self.provider_config = provider_config or {}
        self.reasoning_model_id = self._initial_model_id(current_config.get("reasoning_model_id"))
        self.final_model_id = self._initial_model_id(current_config.get("final_model_id"))
        self.image_generator_model_id = self._initial_model_id(current_config.get("image_generator_model_id"), allow_none=True)
        self._rebuild_components()

    def _initial_model_id(self, value: Any, allow_none: bool = False) -> Optional[str]:
        model_ids = [str(model.get("model_id")) for model in self.models if model.get("model_id")]
        selected = str(value or "").strip()
        if selected in model_ids:
            return selected
        if allow_none:
            return None
        return model_ids[0] if model_ids else None

    def _option_label(self, model: Dict[str, Any]) -> str:
        label = str(model.get("display_name") or model.get("model_id") or "model")
        return label[:97] + "..." if len(label) > 100 else label

    def _option_description(self, model: Dict[str, Any]) -> str:
        model_id = str(model.get("model_id") or "")
        return model_id[:97] + "..." if len(model_id) > 100 else model_id

    def _model_id_from_value(self, value: str) -> Optional[str]:
        if value == "__none__":
            return None
        try:
            idx = int(value)
        except (TypeError, ValueError):
            return None
        if 0 <= idx < len(self.models):
            return str(self.models[idx].get("model_id") or "") or None
        return None

    def _build_options(self, selected_model_id: Optional[str], include_none: bool = False) -> List[discord.SelectOption]:
        options: List[discord.SelectOption] = []
        if include_none:
            options.append(discord.SelectOption(
                label="Không dùng custom image generator",
                description="Giữ luồng Gemini Imagen mặc định hoặc bỏ qua custom image model.",
                value="__none__",
                default=selected_model_id is None,
            ))
        for idx, model in enumerate(self.models):
            model_id = str(model.get("model_id") or "")
            if not model_id:
                continue
            options.append(discord.SelectOption(
                label=self._option_label(model),
                description=self._option_description(model),
                value=str(idx),
                default=model_id == selected_model_id,
            ))
        return options[:25]

    def summary_text(self) -> str:
        image_text = self.image_generator_model_id or "Không dùng custom image generator"
        endpoint_preset = _clean_custom_endpoint_preset(self.provider_config.get("endpoint_preset"))
        endpoint = str(self.provider_config.get("normalized_base_url") or self.provider_config.get("endpoint_base_url") or "chưa lưu")
        return (
            "⚙️ **Custom API Config**\n"
            "Chọn model custom đang alive cho từng vai trò rồi bấm Save.\n\n"
            f"- Đang chạy: `{_custom_endpoint_preset_label(endpoint_preset)}`\n"
            f"- Endpoint: `{endpoint}`\n"
            f"- Reasoning: `{self.reasoning_model_id or 'chưa chọn'}`\n"
            f"- Final output: `{self.final_model_id or 'chưa chọn'}`\n"
            f"- Image generator: `{image_text}`\n\n"
            f"Model alive hiển thị: `{len(self.models)}`"
        )

    def _rebuild_components(self) -> None:
        self.clear_items()

        reasoning_select = discord.ui.Select(
            placeholder="Chọn model reasoning",
            min_values=1,
            max_values=1,
            options=self._build_options(self.reasoning_model_id),
            disabled=not self.models,
        )
        final_select = discord.ui.Select(
            placeholder="Chọn model final output",
            min_values=1,
            max_values=1,
            options=self._build_options(self.final_model_id),
            disabled=not self.models,
        )
        image_select = discord.ui.Select(
            placeholder="Chọn model image generator nếu có",
            min_values=1,
            max_values=1,
            options=self._build_options(self.image_generator_model_id, include_none=True),
            disabled=not self.models,
        )

        async def on_reasoning(select_interaction: discord.Interaction):
            self.reasoning_model_id = self._model_id_from_value(reasoning_select.values[0])
            self._rebuild_components()
            await select_interaction.response.edit_message(content=self.summary_text(), view=self)

        async def on_final(select_interaction: discord.Interaction):
            self.final_model_id = self._model_id_from_value(final_select.values[0])
            self._rebuild_components()
            await select_interaction.response.edit_message(content=self.summary_text(), view=self)

        async def on_image(select_interaction: discord.Interaction):
            self.image_generator_model_id = self._model_id_from_value(image_select.values[0])
            self._rebuild_components()
            await select_interaction.response.edit_message(content=self.summary_text(), view=self)

        async def on_save(button_interaction: discord.Interaction):
            alive_models = await self.db_repo.get_alive_custom_api_models(provider="openai")
            alive_model_ids = {str(model.get("model_id")) for model in alive_models if model.get("model_id")}
            required = [self.reasoning_model_id, self.final_model_id]
            if not all(model_id and model_id in alive_model_ids for model_id in required):
                await button_interaction.response.send_message(
                    "⚠️ Model reasoning/final đã không còn alive hoặc chưa được chọn. Hãy chạy /health_check rồi mở lại config.",
                    ephemeral=True,
                )
                return
            if self.image_generator_model_id and self.image_generator_model_id not in alive_model_ids:
                await button_interaction.response.send_message(
                    "⚠️ Model image generator đã không còn alive. Hãy chọn lại hoặc để trống.",
                    ephemeral=True,
                )
                return
            saved = await self.db_repo.set_bot_model_config(
                self.reasoning_model_id,
                self.final_model_id,
                self.image_generator_model_id,
                self.updated_by,
            )
            await self.router.refresh_custom_models_from_db(force=True)
            endpoint_preset = _clean_custom_endpoint_preset(self.provider_config.get("endpoint_preset"))
            endpoint = str(self.provider_config.get("normalized_base_url") or self.provider_config.get("endpoint_base_url") or "chưa lưu")
            await button_interaction.response.edit_message(
                content=(
                    "✅ Đã lưu Custom API Config.\n"
                    f"- Endpoint mode: `{_custom_endpoint_preset_label(endpoint_preset)}`\n"
                    f"- Endpoint: `{endpoint}`\n"
                    f"- Reasoning: `{saved.get('reasoning_model_id')}`\n"
                    f"- Final output: `{saved.get('final_model_id')}`\n"
                    f"- Image generator: `{saved.get('image_generator_model_id') or 'Không dùng custom image generator'}`"
                ),
                view=None,
            )

        reasoning_select.callback = on_reasoning
        final_select.callback = on_final
        image_select.callback = on_image
        self.add_item(reasoning_select)
        self.add_item(final_select)
        self.add_item(image_select)

        save_button = discord.ui.Button(label="Save", style=discord.ButtonStyle.success)
        save_button.callback = on_save
        self.add_item(save_button)


class CustomApiEndpointModal(discord.ui.Modal):
    def __init__(
        self,
        db_repo: DatabaseRepository,
        health_checker: Any,
        router: Any,
        updated_by: str,
        endpoint_preset: str = "manual",
        initial_endpoint: str = "",
    ):
        self.endpoint_preset = _clean_custom_endpoint_preset(endpoint_preset)
        preset_endpoint = resolve_custom_endpoint_preset(self.endpoint_preset)
        endpoint_default = str(initial_endpoint or preset_endpoint or "")
        super().__init__(title=f"Custom API - {_custom_endpoint_preset_label(self.endpoint_preset)}")
        self.db_repo = db_repo
        self.health_checker = health_checker
        self.router = router
        self.updated_by = updated_by
        self.endpoint_input = discord.ui.TextInput(
            label="Endpoint custom API",
            placeholder="https://provider.example/ hoặc http://host:port/",
            default=endpoint_default[:4000],
            required=True,
            max_length=4000,
        )
        api_key_required = self.endpoint_preset == "manual"
        self.api_key_input = discord.ui.TextInput(
            label="API key",
            placeholder="Bỏ trống với LM Studio/Ollama local nếu server không kiểm tra auth" if not api_key_required else "Nhập key của endpoint OpenAI-compatible",
            required=api_key_required,
            max_length=4000,
            style=discord.TextStyle.short,
        )
        self.add_item(self.endpoint_input)
        self.add_item(self.api_key_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        endpoint_raw = str(self.endpoint_input.value or "").strip()
        api_key = str(self.api_key_input.value or "").strip()
        if not api_key and self.endpoint_preset != "manual":
            api_key = _custom_endpoint_dummy_key(self.endpoint_preset)
        if not api_key:
            await interaction.followup.send("⚠️ API key không được để trống với endpoint nhập tay.", ephemeral=True)
            return

        try:
            normalized_endpoint = normalize_custom_endpoint(endpoint_raw)
        except ValueError as endpoint_error:
            await interaction.followup.send(f"⚠️ Endpoint không hợp lệ: {endpoint_error}", ephemeral=True)
            return

        scan_result = await self.health_checker.scan_openai_models(api_key, normalized_endpoint)
        models = list(scan_result.get("models") or [])
        if not scan_result.get("scan_success") or not scan_result.get("alive") or not models:
            await interaction.followup.send(
                "⚠️ Không áp dụng cấu hình mới vì scan `/v1/models` thất bại.\n"
                f"Lỗi: `{str(scan_result.get('error') or 'không tìm thấy model alive')[:500]}`",
                ephemeral=True,
            )
            return

        try:
            from datetime import timezone

            key_row = await self.db_repo.upsert_provider_api_key(api_key, provider="openai")
            await self.db_repo.deactivate_other_provider_keys(provider="openai", keep_key_id=key_row.get("key_id"))
            provider_config = await self.db_repo.set_custom_provider_config(
                provider="openai",
                endpoint_base_url=endpoint_raw,
                normalized_base_url=normalized_endpoint,
                active_key_id=key_row.get("key_id"),
                is_enabled=True,
                last_scan_ok=True,
                last_scan_error="",
                updated_by=self.updated_by,
                endpoint_preset=self.endpoint_preset,
            )
            checked_at = datetime.now(timezone.utc)
            await self.db_repo.upsert_custom_api_models(
                provider="openai",
                models=models,
                checked_at=checked_at,
            )
            await self.db_repo.mark_missing_custom_api_models_dead(
                provider="openai",
                seen_model_ids=[
                    str(model.get("id") or model.get("model") or model.get("name") or "").strip()
                    for model in models
                    if str(model.get("id") or model.get("model") or model.get("name") or "").strip()
                ],
                checked_at=checked_at,
            )
            await self.router.refresh_custom_provider_config(force=True)
            await self.router.refresh_custom_models_from_db(force=True)
            await self.health_checker.gemini_mgr.clear_custom_api_clients()
        except Exception as save_error:
            logger.error(f"Failed to save custom provider config: {save_error}")
            await interaction.followup.send(f"⚠️ Scan model thành công nhưng lưu DB thất bại: `{save_error}`", ephemeral=True)
            return

        alive_models = await self.db_repo.get_alive_custom_api_models(provider="openai")
        current_config = await self.db_repo.get_bot_model_config()
        view = CustomApiConfigView(
            alive_models,
            current_config,
            self.db_repo,
            self.router,
            self.updated_by,
            provider_config=provider_config,
        )
        await interaction.followup.send(
            "✅ Đã lưu endpoint/API key và quét model thành công.\n"
            f"Endpoint mode: `{_custom_endpoint_preset_label(self.endpoint_preset)}`\n"
            f"Endpoint đang dùng: `{normalized_endpoint}`\n\n"
            f"{view.summary_text()}",
            view=view,
            ephemeral=True,
        )


class CustomApiEndpointPresetView(discord.ui.View):
    def __init__(
        self,
        db_repo: DatabaseRepository,
        health_checker: Any,
        router: Any,
        updated_by: str,
        provider_config: Optional[Dict[str, Any]] = None,
        legacy_endpoint: str = "",
    ):
        super().__init__(timeout=180)
        self.db_repo = db_repo
        self.health_checker = health_checker
        self.router = router
        self.updated_by = updated_by
        self.provider_config = provider_config or {}
        self.legacy_endpoint = str(legacy_endpoint or "").strip()
        self.current_preset = _clean_custom_endpoint_preset(self.provider_config.get("endpoint_preset"))
        self._build_components()

    def summary_text(self) -> str:
        endpoint = str(self.provider_config.get("normalized_base_url") or self.provider_config.get("endpoint_base_url") or self.legacy_endpoint or "chưa cấu hình")
        is_enabled = bool(self.provider_config.get("is_enabled")) if self.provider_config else False
        status_text = "ĐÃ BẬT" if is_enabled else "ĐANG TẮT"
        return (
            "Chọn loại endpoint custom API trước khi nhập chi tiết hoặc bấm **Dùng cấu hình hiện tại** để bỏ qua.\n\n"
            f"- Đang chạy: `{_custom_endpoint_preset_label(self.current_preset)}` ({status_text})\n"
            f"- Endpoint hiện tại: `{endpoint}`\n\n"
            "Manual giữ chuẩn OpenAI-compatible cho provider production. LM Studio/Ollama chỉ là preset local để điền nhanh endpoint."
        )

    def _initial_endpoint_for_preset(self, preset: str) -> str:
        clean_preset = _clean_custom_endpoint_preset(preset)
        stored_endpoint = str(self.provider_config.get("endpoint_base_url") or self.provider_config.get("normalized_base_url") or "").strip()
        if clean_preset == self.current_preset and stored_endpoint:
            return stored_endpoint
        preset_endpoint = resolve_custom_endpoint_preset(clean_preset)
        if preset_endpoint:
            return preset_endpoint
        return self.legacy_endpoint if clean_preset == "manual" else ""

    def _build_components(self) -> None:
        preset_select = discord.ui.Select(
            placeholder="Chọn loại endpoint custom API",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label="Nhập tay endpoint",
                    description="Dùng provider production hoặc endpoint OpenAI-compatible bất kỳ.",
                    value="manual",
                    default=self.current_preset == "manual",
                ),
                discord.SelectOption(
                    label="LM Studio local",
                    description="Mặc định http://127.0.0.1:1234/; API key có thể để trống.",
                    value="lm_studio",
                    default=self.current_preset == "lm_studio",
                ),
                discord.SelectOption(
                    label="Ollama local",
                    description="Mặc định http://127.0.0.1:11434/; API key có thể để trống.",
                    value="ollama",
                    default=self.current_preset == "ollama",
                ),
            ],
        )

        async def on_select(select_interaction: discord.Interaction):
            selected_preset = _clean_custom_endpoint_preset(preset_select.values[0])
            await select_interaction.response.send_modal(CustomApiEndpointModal(
                db_repo=self.db_repo,
                health_checker=self.health_checker,
                router=self.router,
                updated_by=self.updated_by,
                endpoint_preset=selected_preset,
                initial_endpoint=self._initial_endpoint_for_preset(selected_preset),
            ))

        preset_select.callback = on_select
        self.add_item(preset_select)

        skip_disabled = not self.provider_config or not self.provider_config.get("normalized_base_url") or self.provider_config.get("active_key_id") is None
        skip_button = discord.ui.Button(label="Dùng cấu hình hiện tại", style=discord.ButtonStyle.secondary, disabled=skip_disabled)

        async def on_skip(button_interaction: discord.Interaction):
            if skip_disabled:
                await button_interaction.response.send_message(
                    "⚠️ Chưa có cấu hình endpoint/API key hợp lệ để dùng lại. Hãy chọn mode và nhập lại endpoint.",
                    ephemeral=True,
                )
                return

            alive_models = await self.db_repo.get_alive_custom_api_models(provider="openai")
            if not alive_models:
                await button_interaction.response.send_message(
                    "⚠️ Chưa có model alive. Hãy chạy /health_check rồi thử lại.",
                    ephemeral=True,
                )
                return

            current_config = await self.db_repo.get_bot_model_config()
            view = CustomApiConfigView(
                alive_models,
                current_config,
                self.db_repo,
                self.router,
                self.updated_by,
                provider_config=self.provider_config,
            )
            await button_interaction.response.edit_message(content=view.summary_text(), view=view)

        skip_button.callback = on_skip
        self.add_item(skip_button)


class BotCore:
    """Core bot initialization and event handling for Kafka-based architecture."""

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
        self.kafka_service = KafkaService(bootstrap_servers=self.config.KAFKA_BOOTSTRAP_SERVERS, client_id="bot-core")
        self.active_interactions: Dict[str, discord.Interaction] = {}
        self.active_typing_tasks: Dict[str, asyncio.Task] = {}
        self._outgoing_queues: Dict[str, asyncio.Queue] = {}
        self._outgoing_senders: Dict[str, asyncio.Task] = {}
        self._delivery_state: Dict[str, Dict[str, Any]] = {}
        self._consume_task: Optional[asyncio.Task] = None

        self.voice_lock_manager: Optional[VoiceLockManager] = self._build_voice_lock_manager()
        self._voice_enforce_task: Optional[asyncio.Task] = None

        self._register_slash_commands()
        self._register_events()

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
                except Exception as kafka_err:
                    self.logger.error(f"Failed to publish invalidate_cache for user {user_id}: {kafka_err}")
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
                except Exception as kafka_err:
                    self.logger.error(f"Failed to publish invalidate_all_cache: {kafka_err}")
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

    async def setup_kafka(self):
        try:
            await self.kafka_service.start_producer()
            await self.kafka_service.start_consumer("discord-outgoing", group_id="azuris_bot_dispatcher_group")
            self._consume_task = asyncio.create_task(self.consume_outgoing_loop())
        except Exception as e:
            self.logger.error(f"Failed to start BotCore Kafka services: {e}")
            raise

    async def consume_outgoing_loop(self):
        self.logger.info("BotCore Kafka consumer loop started. Listening for outgoing replies...")
        consumer = self.kafka_service.consumers.get("discord-outgoing")
        if not consumer:
            self.logger.error("Consumer for 'discord-outgoing' not found in KafkaService")
            return

        try:
            async for msg in consumer:
                payload = msg.value
                asyncio.create_task(self.handle_outgoing_payload(payload))
        except asyncio.CancelledError:
            self.logger.info("BotCore Kafka consumer loop cancelled")
        except Exception as e:
            self.logger.error(f"Error in BotCore Kafka consumer loop: {e}")

    async def handle_outgoing_payload(self, payload: dict):
        action = payload.get("action")
        channel_id_str = payload.get("channel_id")
        user_id = payload.get("user_id") or "unknown"
        self.logger.info(f"[KAFKA-RECV] BotCore consumed outgoing event | Action: {action} | User: {user_id} | MsgID/IntID: {payload.get('reference_message_id') or payload.get('interaction_id')}")

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
            self.logger.error(f"Failed to handle outgoing Kafka payload: {e}")

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
        def is_admin():
            async def predicate(interaction: discord.Interaction) -> bool:
                return await self._is_admin_user(str(interaction.user.id))

            return app_commands.check(predicate)

        def is_moderator_or_admin():
            async def predicate(interaction: discord.Interaction) -> bool:
                uid = str(interaction.user.id)
                return await self._is_admin_user(uid) or await self._is_moderator_user(uid)

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

        @self.bot.tree.command(name="ping", description="Kiểm tra bot còn phản hồi")
        async def ping(interaction: discord.Interaction):
            await interaction.response.send_message("Bot đang hoạt động.", ephemeral=True)

        @self.bot.tree.command(name="reset-chat", description="Clear your chat history")
        async def reset_chat_slash(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            user_id = str(interaction.user.id)
            self.confirmation_pending[user_id] = {"timestamp": datetime.now(), "awaiting": True}
            await interaction.followup.send("Clear chat history? Reply **yes** or **y** in 60 seconds! 😳", ephemeral=True)

        @self.bot.tree.command(name="health_check", description="Kiểm tra thủ công trạng thái custom API keys (ADMIN ONLY)")
        @is_moderator_or_admin()
        async def health_check_slash(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            from src.core.api_router import get_api_router

            router = get_api_router()
            provider_config = await self.db_repo.get_custom_provider_config(provider="openai")
            if not await router.is_custom_enabled_async(force=True):
                if provider_config is None:
                    await interaction.followup.send("⚠️ Chưa có cấu hình custom provider. Hãy chạy /custom_api_config để nhập endpoint/API key trước.", ephemeral=True)
                else:
                    await interaction.followup.send("⚠️ Custom provider đang tắt hoặc thiếu endpoint/key. Hãy bật bằng /enable_custom_api true hoặc chạy lại /custom_api_config.", ephemeral=True)
                return

            endpoint_preset = str((provider_config or {}).get("endpoint_preset") or "manual").strip().lower()
            model_config = await self.db_repo.get_bot_model_config()
            selected_model_ids = [
                model_config.get("reasoning_model_id"),
                model_config.get("final_model_id"),
            ]
            full_key_scan = endpoint_preset == "manual"

            await interaction.followup.send("⏳ Đang ping health check và quét /v1/models...", ephemeral=True)

            report = await self.health_checker.run_health_check_cycle(
                full_key_scan=full_key_scan,
                selected_model_ids=selected_model_ids,
                ping_selected_models=True,
            )

            key_lines = []
            for entry in report.get("key_checks", []):
                emoji = "✅" if entry.get("alive") else "❌"
                error_text = f" — {entry.get('error')}" if entry.get("error") else ""
                key_lines.append(f"{emoji} `{entry.get('key')}` ({entry.get('provider')}){error_text}")
            key_block = "\n".join(key_lines) if key_lines else "(không có key để kiểm tra)"

            ping_lines = []
            for entry in report.get("model_ping", []):
                emoji = "✅" if entry.get("alive") else "❌"
                err_text = f" — {entry.get('error')}" if entry.get("error") else ""
                ping_lines.append(f"{emoji} `{entry.get('model_id')}` qua `{entry.get('key')}`{err_text}")
            ping_block = "\n".join(ping_lines) if ping_lines else "(không ping model)"

            model_scan = report.get("model_scan", {})
            model_scan_text = (
                f"keys sống/chết: {model_scan.get('alive_keys', 0)}/{model_scan.get('dead_keys', 0)}; "
                f"models alive: {model_scan.get('models_alive', 0)}"
            )
            if model_scan.get("error"):
                model_scan_text += f"; lỗi: {model_scan.get('error')}"

            await interaction.followup.send(
                "✅ Hoàn tất health check.\n\n"
                f"**Trạng thái API keys**\n{key_block}\n\n"
                f"**Ping model đã chọn**\n{ping_block}\n\n"
                f"**Model scan**\n{model_scan_text}",
                ephemeral=True,
            )

        @self.bot.tree.command(name="enable_custom_api", description="Bật/tắt custom endpoint OpenAI (ADMIN ONLY)")
        @app_commands.describe(state="Bật (true) hoặc Tắt (false)")
        @is_moderator_or_admin()
        async def enable_custom_api_slash(interaction: discord.Interaction, state: bool):
            await interaction.response.defer(ephemeral=True)
            import os
            from src.core.api_router import get_api_router

            router = get_api_router()
            provider_config = await self.db_repo.get_custom_provider_config(provider="openai")
            if provider_config is None:
                os.environ["ENABLE_CUSTOM_ENDPOINT"] = "false" if not state else os.environ.get("ENABLE_CUSTOM_ENDPOINT", "false")
                if state:
                    await interaction.followup.send("⚠️ Chưa có cấu hình custom provider trong DB. Hãy chạy /custom_api_config để nhập endpoint/API key trước.", ephemeral=True)
                else:
                    await interaction.followup.send("✅ Custom provider chưa có cấu hình DB; đã giữ trạng thái tắt.", ephemeral=True)
                return

            saved = await self.db_repo.set_custom_provider_enabled("openai", state, str(interaction.user.id))
            await router.refresh_custom_provider_config(force=True)
            status_text = "ĐÃ BẬT" if state else "ĐÃ TẮT"
            if not state:
                await self.health_checker.gemini_mgr.clear_custom_api_clients()
                await interaction.followup.send(f"✅ {status_text} Custom Endpoint (OpenAI). Cấu hình endpoint/key được giữ lại trong DB.", ephemeral=True)
                return

            if not saved or not saved.get("normalized_base_url") or saved.get("active_key_id") is None:
                await interaction.followup.send("⚠️ Cấu hình custom provider thiếu endpoint hoặc API key. Hãy chạy lại /custom_api_config.", ephemeral=True)
                return

            model_config = await self.db_repo.get_bot_model_config()
            selected_model_ids = [
                model_config.get("reasoning_model_id"),
                model_config.get("final_model_id"),
            ]
            report = await self.health_checker.run_health_check_cycle(
                force_send_alerts=False,
                full_key_scan=False,
                selected_model_ids=selected_model_ids,
                ping_selected_models=True,
            )
            alive_models = await self.db_repo.get_alive_custom_api_models(provider="openai")
            key_checks = report.get("key_checks", [])
            alive_keys = sum(1 for k in key_checks if k.get("alive"))
            dead_keys = sum(1 for k in key_checks if not k.get("alive"))
            report_text = f"Key sống/chết: {alive_keys}/{dead_keys}."
            await interaction.followup.send(
                f"✅ {status_text} Custom Endpoint (OpenAI) thành công!\n"
                f"{report_text}\n"
                f"Model custom đang alive: `{len(alive_models)}`.",
                ephemeral=True,
            )

        @self.bot.tree.command(name="custom_api_config", description="Chọn endpoint/API key và model custom API")
        @is_moderator_or_admin()
        async def custom_api_config_slash(interaction: discord.Interaction):
            import os
            from src.core.api_router import get_api_router

            router = get_api_router()
            try:
                provider_config = await self.db_repo.get_custom_provider_config(provider="openai")
            except Exception as config_error:
                self.logger.warning(f"Không đọc được custom provider config trước khi mở modal: {config_error}")
                provider_config = None
            legacy_endpoint = os.getenv("OPENAI_CUSTOM_ENDPOINT", "").strip()
            view = CustomApiEndpointPresetView(
                db_repo=self.db_repo,
                health_checker=self.health_checker,
                router=router,
                updated_by=str(interaction.user.id),
                provider_config=provider_config,
                legacy_endpoint=legacy_endpoint,
            )
            await interaction.response.send_message(view.summary_text(), view=view, ephemeral=True)

        @self.bot.tree.command(name="imagine", description="Tạo ảnh bằng AI (Premium/Admin)")
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
                history = await self.db_repo.get_generated_images(user_id, limit=25)
                if not history:
                    await interaction.followup.send("Bạn chưa tạo ảnh nào hoặc không có lịch sử.", ephemeral=True)
                    return

                view = ImageHistoryView(history)
                await interaction.followup.send("Vui lòng chọn một prompt từ danh sách bên dưới để xem lại ảnh:", view=view, ephemeral=True)
                return

            if not prompt:
                await interaction.response.send_message("⚠️ Bạn cần nhập `prompt` để tạo ảnh mới!", ephemeral=True)
                return

            self.logger.info(f"User {user_id} requested /imagine to create image with prompt: {prompt}")

            if not (await self._is_admin_user(user_id) or await self._is_moderator_user(user_id) or await self.db_repo.is_premium_user(user_id)):
                try:
                    await interaction.response.defer(ephemeral=True)

                    encrypted_path = Path(self.config.PROJECT_ROOT) / "assets" / "encrypted" / "donate_momo_anh_tr.png.enc"
                    key = self.config.DONATE_ENCRYPTION_KEY

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
                                await msg.delete()
                            except (discord.NotFound, discord.Forbidden):
                                pass

                        self.bot.loop.create_task(auto_delete())

                    except Exception as e:
                        self.logger.error(f"Error sending Momo QR in imagine_slash: {e}")
                        await interaction.followup.send("⚠️ Lệnh `/imagine` chỉ dành cho người dùng **Premium**! Vui lòng liên hệ admin để cấp quyền.", ephemeral=True)
                except Exception:
                    pass
                return

            await interaction.response.defer(ephemeral=False)
            await interaction.followup.send("⏳ Đang gửi yêu cầu tạo ảnh qua Kafka...")

            interaction_id_str = str(interaction.id)
            self.active_interactions[interaction_id_str] = interaction

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
            await self.kafka_service.publish("discord-incoming", payload=payload, key=user_id)

        @self.bot.tree.command(name="premium", description="Tính năng Premium")
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
                self.logger.error("Interaction not found for premium command.")
                return

            requester_id = str(interaction.user.id)
            target_user_id = str(user.id) if user else requester_id
            is_admin = await self._is_admin_user(requester_id)

            if action.value == "add":
                if not is_admin:
                    await interaction.followup.send("❌ Bạn không có quyền sử dụng lệnh này!", ephemeral=True)
                    return
                if not user:
                    await interaction.followup.send("❌ Vui lòng chọn người dùng cần thêm vào danh sách Premium!", ephemeral=True)
                    return

                await self.db_repo.add_premium_user(target_user_id)
                await interaction.followup.send(f"🎉 Đã thêm **{user.display_name}** vào danh sách Premium thành công!", ephemeral=True)
                return

            if action.value == "check":
                if await self._is_admin_user(target_user_id):
                    await interaction.followup.send(
                        f"👑 {'Bạn' if target_user_id == requester_id else (user.display_name if user else 'Người này')} là **Admin** của bot!",
                        ephemeral=True,
                    )
                    return

                if await self._is_moderator_user(target_user_id):
                    await interaction.followup.send(
                        f"🛡️ {'Bạn' if target_user_id == requester_id else (user.display_name if user else 'Người này')} là **Moderator** của bot!",
                        ephemeral=True,
                    )
                    return

                if await self.db_repo.is_premium_user(target_user_id):
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
                is_moderator = await self._is_moderator_user(requester_id)
                if is_admin or is_moderator or await self.db_repo.is_premium_user(requester_id):
                    await interaction.followup.send("✨ Bạn đã có quyền Premium/Admin/Moderator rồi nhé! Không cần mua thêm đâu 🥰", ephemeral=True)
                    return

                donate_platforms = {
                    "anhtr_momo": {
                        "file": "donate_momo_anh_tr.png.enc",
                        "original_filename": "donate_momo_anh_tr.png",
                    }
                }

                info = donate_platforms.get("anhtr_momo")
                encrypted_path = Path(self.config.PROJECT_ROOT) / "assets" / "encrypted" / info["file"]

                if not encrypted_path.exists():
                    await interaction.followup.send("Mã QR hiện không khả dụng. Vui lòng liên hệ Admin.", ephemeral=True)
                    return

                key = self.config.DONATE_ENCRYPTION_KEY
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
                    self.logger.error(f"Error decrypting Momo QR for buy premium: {e}")
                    await interaction.followup.send("Không thể tải mã QR lúc này. Vui lòng liên hệ Admin.", ephemeral=True)

        @self.bot.tree.command(name="moderator", description="Quản lý Moderator động (ADMIN ONLY)")
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
                self.logger.error("Interaction not found for moderator command.")
                return

            requester_id = str(interaction.user.id)
            target_user_id = str(user.id)
            is_admin_req = await self._is_admin_user(requester_id)

            if not is_admin_req:
                await interaction.followup.send("❌ Bạn không phải Admin hệ thống, không có quyền quản lý Moderator!", ephemeral=True)
                return

            if action.value == "add":
                if target_user_id in self.config.ADMIN_USER_IDS:
                    await interaction.followup.send(f"👑 **{user.display_name}** đã là Admin cấu hình tĩnh!", ephemeral=True)
                    return
                if target_user_id in self.config.MODERATOR_USER_IDS:
                    await interaction.followup.send(f"🛡️ **{user.display_name}** đã là Moderator cấu hình tĩnh!", ephemeral=True)
                    return

                await self.db_repo.add_moderator_user(target_user_id)
                await interaction.followup.send(f"🎉 Đã thăng chức **{user.display_name}** làm Moderator động thành công!", ephemeral=True)
                return

            if action.value == "remove":
                if target_user_id in self.config.ADMIN_USER_IDS or target_user_id in self.config.MODERATOR_USER_IDS:
                    await interaction.followup.send("❌ Không thể hạ chức tài khoản cấu hình tĩnh trong .env!", ephemeral=True)
                    return

                removed = await self.db_repo.remove_moderator_user(target_user_id)
                if removed:
                    await interaction.followup.send(f"✅ Đã hạ chức người dùng **{user.display_name}** khỏi vai trò Moderator.", ephemeral=True)
                else:
                    await interaction.followup.send(f"❌ Người dùng **{user.display_name}** không phải Moderator động.", ephemeral=True)
                return

            if action.value == "check":
                is_static_admin = target_user_id in self.config.ADMIN_USER_IDS
                is_static_mod = target_user_id in self.config.MODERATOR_USER_IDS
                is_dynamic_admin = await self.db_repo.is_admin_user(target_user_id)
                is_dynamic_mod = await self.db_repo.is_moderator_user(target_user_id)

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

        @self.bot.tree.command(name="reset-all", description="Clear all DB (ADMIN ONLY)")
        @is_admin()
        async def reset_all_slash(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            admin_id = str(interaction.user.id)
            self.admin_confirmation_pending[admin_id] = {"timestamp": datetime.now(), "awaiting": True}
            await interaction.followup.send("⚠️ **ADMIN CONFIRM**: Reply **YES RESET** in 60 seconds to clear all DB!", ephemeral=True)

        @self.bot.tree.command(name="global-notes", description="Browse global shared memory notes (ADMIN ONLY)")
        @app_commands.describe(limit="Max notes to load (1-100)")
        @is_moderator_or_admin()
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
        @is_moderator_or_admin()
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
        @app_commands.describe(user="Target user", message="Message content", channel="Optional channel")
        @is_moderator_or_admin()
        async def message_to_slash(interaction: discord.Interaction, user: discord.User, message: str, channel: Optional[discord.TextChannel] = None):
            await interaction.response.defer(ephemeral=True)
            requester_id = str(interaction.user.id)
            is_admin = await self._is_admin_user(requester_id)
            is_moderator = await self._is_moderator_user(requester_id)

            if is_moderator and not is_admin:
                if not channel:
                    await interaction.followup.send("❌ Moderator không được quyền gửi DM trực tiếp!", ephemeral=True)
                    return
                if not interaction.guild or channel.guild != interaction.guild:
                    await interaction.followup.send("❌ Moderator chỉ được phép gửi tin nhắn trong server sở tại!", ephemeral=True)
                    return

            user_id = str(user.id)
            cleaned_message = " ".join(message.strip().split())

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
                self.logger.error(f"Error sending message to {user_id}: {e}")

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

        @self.bot.tree.command(name="donate", description="Hiện mã QR ủng hộ (Ko-fi, PayPal hoặc Momo)")
        @app_commands.describe(platform="Chọn nền tảng ủng hộ (mặc định: Ko-fi)")
        @app_commands.choices(platform=[
            app_commands.Choice(name="Ko-fi (recommended)", value="kofi"),
            app_commands.Choice(name="PayPal", value="paypal"),
            app_commands.Choice(name="Momo - Anh Tr", value="anhtr_momo"),
        ])
        async def donate_slash(interaction: discord.Interaction, platform: app_commands.Choice[str] = None):
            await interaction.response.defer()

            selected = platform.value if platform else "kofi"
            info = donate_platforms.get(selected)
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
                f"✅ Đã thêm **{member.display_name}** vào whitelist.",
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
                f"🗑️ Đã xóa **{member.display_name}** khỏi whitelist.",
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
                username = data.get("username", "Unknown")
                lines.append(f"🔹 **{username}** `(UID: {uid})`")

            await interaction.followup.send("\n".join(lines), ephemeral=True)

        @self.bot.tree.error
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

        _ = (ping, reset_chat_slash, health_check_slash, enable_custom_api_slash, custom_api_config_slash, imagine_slash, premium_slash, reset_all_slash,
             global_notes_slash, global_note_demote_slash, message_to_slash, donate_slash,
             lock_room, unlock_room, move_member, move_all, set_room, add_privet, remove_privet, list_privet, on_app_command_error)

    def _register_events(self):
        @self.bot.event
        async def on_ready():
            self.logger.info(f"Bot logged in as {self.bot.user.name} (ID: {self.bot.user.id})")

            await self.db_repo.init_db()
            try:
                await self.setup_kafka()
            except Exception as e:
                self.logger.error(f"Failed to start Kafka producer: {e}")

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

            stage = "đang xử lý"
            try:
                busy_state = await self.db_repo.set_user_processing_state(user_id, stage)
            except Exception as e:
                self.logger.error(f"Error checking processing state: {e}")
                await message.reply("🚨 Lỗi kết nối database. Vui lòng thử lại sau.", mention_author=False)
                return

            if busy_state:
                busy_text = f"Đợi chút nha, mình đang bận {busy_state}. Nhắn chen ngang cũng bị trừ tin nhắn đó nha!"
                await message.reply(busy_text, mention_author=False)
                return

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
                    raise RuntimeError("Kafka publish returned False")
            except Exception as e:
                self.logger.error(f"Failed to publish incoming message: {e}")
                # Hủy typing loop nếu publish thất bại
                if user_id in self.active_typing_tasks:
                    self.active_typing_tasks[user_id].cancel()
                    self.active_typing_tasks.pop(user_id, None)
                await self.db_repo.clear_user_processing_state(user_id)
                await message.reply("🚨 Hệ thống Kafka đang lỗi. Vui lòng thử lại sau.", mention_author=False)

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
