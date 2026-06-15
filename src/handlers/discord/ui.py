import os
from typing import Any, Dict, List, Optional
import discord
from src.database.repository import DatabaseRepository


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
