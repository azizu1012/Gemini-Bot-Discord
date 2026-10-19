"""UI views for role rank management (/rolerank)."""

from __future__ import annotations

import math
from typing import Optional
import discord

from src.voice.role_hierarchy import (
    movable_roles,
    plan_role_move,
    role_is_movable,
    role_lines,
    role_order,
    role_rank,
    shorten,
    top_movable_slot,
)

PANEL_TIMEOUT = 300.0
ROLE_PAGE_SIZE = 25


class RolePanel(discord.ui.View):
    """Base ephemeral view that automatically cleans up after timeout."""

    def __init__(self, author_id: int, timeout: float = PANEL_TIMEOUT) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.message: Optional[discord.Message] = None
        self.detached = False
        self.embed: discord.Embed = discord.Embed()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Panel này chỉ người mở lệnh mới dùng được.", ephemeral=True
            )
            return False
        return True

    def detach(self) -> None:
        self.detached = True

    async def on_timeout(self) -> None:
        if self.detached or self.message is None:
            return
        for item in self.children:
            item.disabled = True
        try:
            self.embed.description = "⏳ Panel đã hết giờ."
            await self.message.edit(embed=self.embed, view=self)
        except discord.HTTPException:
            pass

    @discord.ui.button(label="✖ Đóng panel", style=discord.ButtonStyle.danger, row=1)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.detach()
        for item in self.children:
            item.disabled = True
        self.embed.description = "Panel đã đóng."
        await interaction.response.edit_message(embed=self.embed, view=None)


async def swap_panel(
    interaction: discord.Interaction,
    old_view: RolePanel,
    new_view: RolePanel,
) -> None:
    old_view.detach()
    await interaction.response.edit_message(embed=new_view.embed, view=new_view)
    try:
        new_view.message = await interaction.original_response()
    except discord.NotFound:
        pass


class RolePickerView(RolePanel):
    """Step 1/2: choose role to move."""

    def __init__(self, guild: discord.Guild, author_id: int) -> None:
        super().__init__(author_id)
        self.guild = guild
        self.page = 0
        self.roles = movable_roles(guild)
        self.total_pages = max(1, math.ceil(len(self.roles) / ROLE_PAGE_SIZE))
        self.refresh()

    def refresh(self) -> None:
        start = self.page * ROLE_PAGE_SIZE
        self.role_menu.options = [
            discord.SelectOption(
                label=shorten(f"#{role_rank(self.guild, role)} {role.name}", 100),
                value=str(role.id),
                description=shorten(f"{role_rank(self.guild, role) - 1} role đang ở trên", 100),
            )
            for role in self.roles[start : start + ROLE_PAGE_SIZE]
        ]
        self.prev_page.disabled = self.page == 0
        self.next_page.disabled = self.page >= self.total_pages - 1

        me = self.guild.me
        self.embed = discord.Embed(
            title="Kéo role lên cao hơn",
            colour=discord.Colour.blurple(),
            description=(
                "**Bước 1/2** — Chọn role bạn muốn kéo trong danh sách dưới đây:\n"
                "`✅` bot kéo được · `🔒` khóa (role cao hơn hoặc do integration quản lý)\n\n"
                + "\n".join(role_lines(self.guild))
            ),
        )
        self.embed.add_field(
            name="Trần của bot",
            value=(
                f"{me.top_role.mention} — bot chỉ kéo được role **dưới** role này"
                if me
                else "Không rõ"
            ),
        )
        self.embed.set_footer(
            text=f"Trang {self.page + 1}/{self.total_pages} · chỉ bạn thấy panel này"
        )

    @discord.ui.select(placeholder="🔼 Chọn role cần kéo lên", row=0)
    async def role_menu(self, interaction: discord.Interaction, menu: discord.ui.Select) -> None:
        role = self.guild.get_role(int(menu.values[0]))
        if role is None or not role_is_movable(self.guild, role):
            await interaction.response.send_message(
                "Role này không thể kéo được.", ephemeral=True
            )
            return
        await swap_panel(interaction, self, RolePositionView(self.guild, role, self.author_id))

    async def turn_page(self, interaction: discord.Interaction, delta: int) -> None:
        self.page = max(0, min(self.page + delta, self.total_pages - 1))
        self.refresh()
        await interaction.response.edit_message(embed=self.embed, view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, row=1)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.turn_page(interaction, -1)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.turn_page(interaction, 1)


class RolePositionView(RolePanel):
    """Step 2/2: choose target slot for chosen role."""

    def __init__(self, guild: discord.Guild, role: discord.Role, author_id: int) -> None:
        super().__init__(author_id)
        self.guild = guild
        self.role = role
        self.page = 0
        self.current = role_rank(guild, role) - 1
        floor = top_movable_slot(guild)
        self.slots = [
            slot for slot in range(floor, len(role_order(guild))) if slot != self.current
        ]
        self.total_pages = max(1, math.ceil(len(self.slots) / ROLE_PAGE_SIZE))
        if not self.slots:
            self.remove_item(self.position_menu)
        self.refresh()

    def refresh(self) -> None:
        roles = role_order(self.guild)
        start = self.page * ROLE_PAGE_SIZE
        if self.slots:
            self.position_menu.options = [
                discord.SelectOption(
                    label=shorten(f"Vị trí #{slot + 1}", 100),
                    value=str(slot),
                    description=shorten(f"Đặt ngay trên {roles[slot].name}", 100),
                )
                for slot in self.slots[start : start + ROLE_PAGE_SIZE]
            ]
        self.prev_page.disabled = self.page == 0
        self.next_page.disabled = self.page >= self.total_pages - 1

        me = self.guild.me
        hint = (
            f"Hiện tại đang có {roles[self.slots[start]].mention} ở ngay bên dưới."
            if self.slots
            else "Role này đã ở vị trí cao nhất bot có thể kéo."
        )
        self.embed = discord.Embed(
            title="Kéo role lên cao hơn",
            colour=discord.Colour.blurple(),
            description=(
                f"**Bước 2/2** — Chọn vị trí mới cho {self.role.mention} "
                f"(đang ở **#{self.current + 1}**).\n"
                f"**👉** là role đang chọn, `✅` bot kéo được, `🔒` khóa.\n"
                f"{hint}\n\n"
                + "\n".join(role_lines(self.guild, highlight=self.role))
            ),
        )
        self.embed.add_field(
            name="Trần của bot",
            value=(
                f"{me.top_role.mention} — role không thể lên cao hơn điểm này"
                if me
                else "Không rõ"
            ),
        )
        self.embed.set_footer(
            text=f"Trang {self.page + 1}/{self.total_pages} · chỉ bạn thấy panel này"
        )

    @discord.ui.select(placeholder="🔼 Chọn vị trí mới cho role", row=0)
    async def position_menu(
        self, interaction: discord.Interaction, menu: discord.ui.Select
    ) -> None:
        role = self.guild.get_role(self.role.id)
        slot = int(menu.values[0])

        if role is None or not role_is_movable(self.guild, role):
            await interaction.response.send_message(
                "Role này không thể kéo được.", ephemeral=True
            )
            return

        old_rank = role_rank(self.guild, role)
        try:
            payload = plan_role_move(self.guild, role, slot)
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        if not payload:
            await interaction.response.send_message(
                "Role đã ở đúng vị trí đó rồi.", ephemeral=True
            )
            return

        try:
            await self.guild.edit_role_positions(
                payload, reason=f"Kéo role {role.name} theo yêu cầu của {interaction.user}"
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "Không kéo được: bot thiếu quyền Manage Roles hoặc role của bot không cao hơn.",
                ephemeral=True,
            )
            return
        except discord.HTTPException as e:
            await interaction.response.send_message(f"Lỗi khi kéo role: {e}", ephemeral=True)
            return

        await swap_panel(
            interaction,
            self,
            RoleDoneView(self.guild, role.id, old_rank, slot + 1, self.author_id),
        )

    async def turn_page(self, interaction: discord.Interaction, delta: int) -> None:
        self.page = max(0, min(self.page + delta, self.total_pages - 1))
        self.refresh()
        await interaction.response.edit_message(embed=self.embed, view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, row=1)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.turn_page(interaction, -1)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.turn_page(interaction, 1)


class RoleDoneView(RolePanel):
    """Panel shown after successfully moving a role."""

    def __init__(
        self,
        guild: discord.Guild,
        role_id: int,
        old_rank: int,
        new_rank: int,
        author_id: int,
    ) -> None:
        super().__init__(author_id)
        role = guild.get_role(role_id)
        role_name = role.mention if role else f"Role ID {role_id}"
        self.embed = discord.Embed(
            title="✅ Đã chuyển vị trí role thành công",
            colour=discord.Colour.green(),
            description=(
                f"Đã chuyển {role_name} từ hạng **#{old_rank}** lên hạng **#{new_rank}**.\n\n"
                + "\n".join(role_lines(guild, highlight=role))
            ),
        )
