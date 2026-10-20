import logging
import os
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit
import discord
from src.database.repository import DatabaseRepository
from src.core.llm.resolver import DEFAULT_BASE_URLS, encrypt_api_key, normalize_base_url


logger = logging.getLogger(__name__)


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

        select.callback = on_select  # type: ignore[attr-defined]
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

        prev_button.callback = on_prev  # type: ignore[attr-defined]
        next_button.callback = on_next  # type: ignore[attr-defined]
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

        select.callback = on_select  # type: ignore[attr-defined]
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

        prev_button.callback = on_prev  # type: ignore[attr-defined]
        next_button.callback = on_next  # type: ignore[attr-defined]
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


# ══════════════════════════════════════════════════════════════
# Endpoint & model picker UI (endpoint-only refactor)
# ══════════════════════════════════════════════════════════════

MODELS_PER_PAGE = 25

SLOT_ORDER = ("reasoning", "final", "fallback", "vision")
SLOT_LABELS = {
    "reasoning": "🧠 Reasoning",
    "final": "✍️ Final",
    "fallback": "🪂 Fallback",
    "vision": "👁️ Vision",
}


def normalize_models(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Chuẩn hóa + dedupe + sort danh sách model trả về từ adapter."""
    seen: Dict[str, Dict[str, Any]] = {}
    for item in raw or []:
        model_id = str((item or {}).get("id") or "").strip()
        if not model_id or model_id in seen:
            continue
        display = (
            str((item or {}).get("name") or (item or {}).get("display_name") or (item or {}).get("display") or "")
            .strip()
            or model_id
        )
        seen[model_id] = {"id": model_id, "name": display}
    return sorted(seen.values(), key=lambda m: m["id"].lower())


def filter_models(models: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    q = (query or "").strip().lower()
    if not q:
        return list(models)
    return [
        m for m in models
        if q in str(m.get("id") or "").lower() or q in str(m.get("name") or "").lower()
    ]


def paginate_models(models: List[Dict[str, Any]], page: int, page_size: int = MODELS_PER_PAGE) -> List[Dict[str, Any]]:
    if page < 0:
        page = 0
    start = page * page_size
    return list(models[start:start + page_size])


def total_model_pages(count: int, page_size: int = MODELS_PER_PAGE) -> int:
    return max(1, (count + page_size - 1) // page_size)


class ModelPickerView(discord.ui.View):
    """Picker 1 slot: select 25 model/trang + Trước/Sau + Tìm kiếm + Để trống + Xác nhận."""

    def __init__(self, *, models: List[Dict[str, Any]], slot: str):
        super().__init__(timeout=300)
        self.models = list(models)
        self.slot = slot
        self.query = ""
        self.page = 0
        self.selected_model_id: Optional[str] = None
        self.skipped = False
        self.confirmed = False
        self._build()

    @property
    def filtered(self) -> List[Dict[str, Any]]:
        return filter_models(self.models, self.query)

    @property
    def total_pages(self) -> int:
        return total_model_pages(len(self.filtered))

    @property
    def page_models(self) -> List[Dict[str, Any]]:
        return paginate_models(self.filtered, self.page)

    def apply_query(self, query: str) -> None:
        self.query = query or ""
        self.page = 0
        self._build()

    def summary_embed(self) -> discord.Embed:
        label = SLOT_LABELS.get(self.slot, self.slot)
        description = f"Trang {self.page + 1}/{self.total_pages} · {len(self.filtered)} model"
        if self.query:
            description += f"\n🔍 Từ khóa: `{self.query}`"
        embed = discord.Embed(title=f"Chọn model cho slot {label}", description=description, color=discord.Color.blurple())
        current = self.selected_model_id or "(chưa chọn — có thể bấm 🚫 Để trống)"
        embed.add_field(name="Model đang chọn", value=f"`{current}`", inline=False)
        return embed

    def _build(self) -> None:
        self.clear_items()
        page_models = self.page_models
        if page_models:
            options = []
            for m in page_models:
                label = str(m.get("id") or "")[:100]
                desc = str(m.get("name") or "")[:100]
                options.append(discord.SelectOption(label=label, description=desc if desc != label else None, value=label))
            select = discord.ui.Select(
                placeholder=f"Chọn model (trang {self.page + 1}/{self.total_pages})",
                options=options,
            )

            async def on_select(interaction: discord.Interaction):
                self.selected_model_id = select.values[0]
                await interaction.response.edit_message(embed=self.summary_embed(), view=self)

            select.callback = on_select  # type: ignore[attr-defined]
            self.add_item(select)

        prev_button = discord.ui.Button(label="◀ Trước", style=discord.ButtonStyle.secondary, disabled=self.page <= 0)
        next_button = discord.ui.Button(label="Sau ▶", style=discord.ButtonStyle.secondary, disabled=self.page >= self.total_pages - 1)
        search_button = discord.ui.Button(label="🔍 Tìm kiếm", style=discord.ButtonStyle.primary)
        skip_button = discord.ui.Button(label="🚫 Để trống", style=discord.ButtonStyle.secondary)
        confirm_button = discord.ui.Button(label="✅ Xác nhận", style=discord.ButtonStyle.success)

        async def on_prev(interaction: discord.Interaction):
            self.page = max(0, self.page - 1)
            self._build()
            await interaction.response.edit_message(embed=self.summary_embed(), view=self)

        async def on_next(interaction: discord.Interaction):
            self.page = min(self.total_pages - 1, self.page + 1)
            self._build()
            await interaction.response.edit_message(embed=self.summary_embed(), view=self)

        async def on_search(interaction: discord.Interaction):
            await interaction.response.send_modal(SearchModal(self))

        async def on_skip(interaction: discord.Interaction):
            self.selected_model_id = None
            self.skipped = True
            self.confirmed = True
            self.stop()
            await interaction.response.edit_message(content="🚫 Đã chọn để trống — sẽ áp default rule.", embed=None, view=None)

        async def on_confirm(interaction: discord.Interaction):
            if not self.selected_model_id:
                await interaction.response.send_message("Hãy chọn model trong menu, hoặc bấm 🚫 Để trống.", ephemeral=True)
                return
            self.confirmed = True
            self.stop()
            await interaction.response.edit_message(content=f"✅ Đã chọn `{self.selected_model_id}`.", embed=None, view=None)

        prev_button.callback = on_prev  # type: ignore[attr-defined]
        next_button.callback = on_next  # type: ignore[attr-defined]
        search_button.callback = on_search  # type: ignore[attr-defined]
        skip_button.callback = on_skip  # type: ignore[attr-defined]
        confirm_button.callback = on_confirm  # type: ignore[attr-defined]
        self.add_item(prev_button)
        self.add_item(next_button)
        self.add_item(search_button)
        self.add_item(skip_button)
        self.add_item(confirm_button)


class SearchModal(discord.ui.Modal, title="🔍 Tìm kiếm model"):
    keyword = discord.ui.TextInput(label="Từ khóa (khớp id hoặc tên)", required=False, max_length=100)

    def __init__(self, view: ModelPickerView):
        super().__init__(timeout=300)
        self.picker = view

    async def on_submit(self, interaction: discord.Interaction):
        self.picker.apply_query(str(self.keyword.value or ""))
        await interaction.response.edit_message(embed=self.picker.summary_embed(), view=self.picker)


class SDKChoiceView(discord.ui.View):
    """2 nút chọn SDK; `on_choose(interaction, sdk)` do nơi gọi cung cấp."""

    def __init__(self, on_choose):
        super().__init__(timeout=300)
        self._on_choose = on_choose
        genai_button = discord.ui.Button(label="Google genAI", style=discord.ButtonStyle.primary)
        openai_button = discord.ui.Button(label="OpenAI-compatible", style=discord.ButtonStyle.secondary)

        async def on_genai(interaction: discord.Interaction):
            await self._on_choose(interaction, "genai")

        async def on_openai(interaction: discord.Interaction):
            await self._on_choose(interaction, "openai")

        genai_button.callback = on_genai  # type: ignore[attr-defined]
        openai_button.callback = on_openai  # type: ignore[attr-defined]
        self.add_item(genai_button)
        self.add_item(openai_button)


class EndpointConfigModal(discord.ui.Modal, title="Cấu hình Endpoint"):
    def __init__(self, *, flow: "EndpointConfigFlow", sdk: str, default_url: str):
        super().__init__(timeout=300)
        self.flow = flow
        self.sdk = sdk
        self.url_input = discord.ui.TextInput(label="Base URL", default=default_url, required=True)
        self.key_input = discord.ui.TextInput(label="API Key", required=True)
        self.add_item(self.url_input)
        self.add_item(self.key_input)

    async def on_submit(self, interaction: discord.Interaction):
        url = str(self.url_input.value or "").strip()
        key = str(self.key_input.value or "").strip()
        if not url or not key:
            await interaction.response.send_message("❌ URL và Key không được để trống.", ephemeral=True)
            return
        await self.flow.configure(interaction, self.sdk, url, key)


class EndpointConfigFlow:
    """Điều phối /endpoint config: SDK → modal URL/Key → validate + fetch models → picker 4 slot → lưu DB."""

    def __init__(self, *, gateway, resolver, db_repo, config, admin_user_id: str):
        self.gateway = gateway
        self.resolver = resolver
        self.db_repo = db_repo
        self.config = config
        self.admin_user_id = admin_user_id

    async def start(self, interaction: discord.Interaction) -> None:
        await interaction.followup.send(
            "🧭 Chọn SDK cho endpoint mới:",
            view=SDKChoiceView(self._on_sdk_choose),
            ephemeral=True,
        )

    async def _on_sdk_choose(self, interaction: discord.Interaction, sdk: str) -> None:
        default_url = DEFAULT_BASE_URLS.get(sdk, "")
        await interaction.response.send_modal(EndpointConfigModal(flow=self, sdk=sdk, default_url=default_url))

    async def configure(self, interaction: discord.Interaction, sdk: str, base_url: str, api_key: str) -> None:
        base_url = normalize_base_url(sdk, base_url)
        parsed = urlsplit(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            await interaction.response.send_message(
                f"❌ Base URL không hợp lệ: `{base_url}`.\n"
                "Ví dụ hợp lệ: `http://127.0.0.1:58100/v1`",
                ephemeral=True,
            )
            return

        # Modal submit là một interaction MỚI, chưa được defer. Nếu gọi network
        # (list_models) trước khi defer, interaction sẽ hết hạn sau 3 giây và
        # followup.send sau đó ném "Interaction has not been responded to".
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            raw_models = await self.gateway.list_models_for(sdk=sdk, base_url=base_url, api_key=api_key)
        except Exception as e:
            logger.exception("Endpoint config failed while listing models (sdk=%s url=%s)", sdk, base_url)
            await interaction.followup.send(
                f"❌ Không kết nối/không lấy được model list từ endpoint:\n`{str(e)[:300]}`\nCấu hình CHƯA được lưu.",
                ephemeral=True,
            )
            return

        models = normalize_models(raw_models)
        if not models:
            await interaction.followup.send(
                "❌ Endpoint trả về danh sách model rỗng. Cấu hình CHƯA được lưu.", ephemeral=True
            )
            return

        slots = await self.run_slot_pickers(interaction, models)
        if slots is None:
            return

        encrypted = encrypt_api_key(api_key, getattr(self.config, "DONATE_ENCRYPTION_KEY", "") or "")
        updated_by = f"admin:{self.admin_user_id}"
        try:
            await self.db_repo.upsert_llm_endpoint(sdk, base_url, encrypted, updated_by)
            await self.db_repo.upsert_llm_model_slots(sdk, slots, updated_by)
            await self.db_repo.set_active_sdk(sdk, updated_by)
        except Exception as e:
            logger.exception("Endpoint config failed while saving to DB (sdk=%s)", sdk)
            await interaction.followup.send(f"❌ Lỗi lưu DB: `{str(e)[:300]}`", ephemeral=True)
            return

        self.resolver.invalidate()
        await interaction.followup.send(embed=self.summary_embed(sdk, base_url, slots), ephemeral=True)

    async def run_slot_pickers(self, interaction: discord.Interaction, models: List[Dict[str, Any]]) -> Optional[Dict[str, Optional[str]]]:
        """Chạy picker tuần tự cho 4 slot (reasoning → final → fallback → vision). Trả None nếu hết hạn."""
        slots: Dict[str, Optional[str]] = {}
        for slot in SLOT_ORDER:
            view = ModelPickerView(models=models, slot=slot)
            picker_msg = await interaction.followup.send(embed=view.summary_embed(), view=view, ephemeral=True, wait=True)
            await view.wait()
            if not view.confirmed:
                await picker_msg.edit(content="⌛ Hết thời gian chọn. Chạy lại để làm lại.", embed=None, view=None)
                return None
            slots[slot] = view.selected_model_id
        return slots

    def summary_embed(self, sdk: str, base_url: str, slots: Dict[str, Optional[str]]) -> discord.Embed:
        lines = []
        for slot in SLOT_ORDER:
            value = slots.get(slot)
            lines.append(f"- {SLOT_LABELS[slot]}: `{value or '(để trống → default rule)'}`")
        embed = discord.Embed(title="✅ Đã lưu cấu hình endpoint", color=discord.Color.green())
        embed.add_field(name="SDK active", value=f"`{sdk}`", inline=True)
        embed.add_field(name="URL", value=f"`{base_url}`", inline=True)
        embed.add_field(name="4 slot", value="\n".join(lines), inline=False)
        return embed
