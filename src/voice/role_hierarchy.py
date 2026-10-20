"""Role hierarchy service and role movement planning."""

from __future__ import annotations

from typing import Dict, List, Optional
import discord
from src.voice.models import RoleMovePlan


class RoleHierarchyService:
    """Domain service managing guild role hierarchies, permissions, and position movement plans."""

    @staticmethod
    def shorten(text: str, limit: int = 88) -> str:
        """Clean and truncate string with an ellipsis if it exceeds limit."""
        cleaned = " ".join(text.split()) or "(không tên)"
        return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"

    def get_role_order(self, guild: discord.Guild) -> List[discord.Role]:
        """Return guild roles ordered from highest to lowest position."""
        roles = [role for role in guild.roles if not role.is_default()]
        roles.sort(key=lambda role: role.position, reverse=True)
        return roles

    def is_movable(self, guild: discord.Guild, role: discord.Role) -> bool:
        """Check if bot can move this role (must be below bot's top role)."""
        me = guild.me
        if me is None or role.is_default() or role.managed:
            return False
        if not me.guild_permissions.manage_roles:
            return False
        return role.position < me.top_role.position

    def get_movable_roles(self, guild: discord.Guild) -> List[discord.Role]:
        """Return all roles that the bot is allowed to rearrange."""
        return [role for role in self.get_role_order(guild) if self.is_movable(guild, role)]

    def get_rank(self, guild: discord.Guild, role: discord.Role) -> int:
        """Current rank: 1 is the highest position in the guild."""
        return next((i + 1 for i, item in enumerate(self.get_role_order(guild)) if item.id == role.id), 0)

    def get_top_movable_slot(self, guild: discord.Guild) -> int:
        """Highest slot (0-based) that bot is permitted to place a role into."""
        roles = self.get_role_order(guild)
        me = guild.me
        if me is None:
            return len(roles)
        for index, role in enumerate(roles):
            if role.id == me.top_role.id:
                return index + 1
        return 0

    def plan_move(self, guild: discord.Guild, role: discord.Role, slot: int) -> RoleMovePlan:
        """Calculate atomic payload {Role: position} to move `role` into `slot`."""
        roles = self.get_role_order(guild)
        current = next((i for i, item in enumerate(roles) if item.id == role.id), None)
        if current is None or not 0 <= slot < len(roles):
            raise ValueError("Vị trí đích không hợp lệ.")
        if slot < self.get_top_movable_slot(guild):
            raise ValueError("Không thể đặt role cao hơn role cao nhất của bot.")
        if not self.is_movable(guild, role):
            raise ValueError("Role này bot không thể kéo được.")

        wanted = list(roles)
        wanted.pop(current)
        wanted.insert(slot, role)

        payload: Dict[discord.Role, int] = {}
        for index, item in enumerate(wanted):
            if not self.is_movable(guild, item):
                continue
            new_position = len(roles) - index
            if item.position != new_position:
                payload[item] = new_position

        return RoleMovePlan(role=role, target_slot=slot, payload=payload)

    def format_hierarchy_lines(
        self,
        guild: discord.Guild,
        highlight: Optional[discord.Role] = None,
        limit: int = 14,
    ) -> List[str]:
        """Format human-readable lines showing role positions with icons."""
        roles = self.get_role_order(guild)
        lines = []
        for index, role in enumerate(roles[:limit]):
            mark = "✅" if self.is_movable(guild, role) else "🔒"
            if highlight is not None and role.id == highlight.id:
                mark = "👉"
            lines.append(f"`#{index + 1}` {mark} {role.mention}")
        if len(roles) > limit:
            lines.append(f"*… và {len(roles) - limit} role khác*")
        return lines or ["*Server chưa có role nào.*"]


# Global default instance and backward-compatible functional facades
role_hierarchy_service = RoleHierarchyService()

shorten = role_hierarchy_service.shorten
role_order = role_hierarchy_service.get_role_order
role_is_movable = role_hierarchy_service.is_movable
movable_roles = role_hierarchy_service.get_movable_roles
role_rank = role_hierarchy_service.get_rank
top_movable_slot = role_hierarchy_service.get_top_movable_slot
role_lines = role_hierarchy_service.format_hierarchy_lines


def plan_role_move(guild: discord.Guild, role: discord.Role, slot: int) -> Dict[discord.Role, int]:
    """Backward-compatible helper returning raw dictionary payload."""
    return role_hierarchy_service.plan_move(guild, role, slot).payload
