"""Role hierarchy calculation and role movement planning."""

from __future__ import annotations

from typing import Dict, List, Optional
import discord


def shorten(text: str, limit: int = 88) -> str:
    cleaned = " ".join(text.split()) or "(không tên)"
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"


def role_order(guild: discord.Guild) -> List[discord.Role]:
    """Return guild roles ordered from highest to lowest position."""
    roles = [role for role in guild.roles if not role.is_default()]
    roles.sort(key=lambda role: role.position, reverse=True)
    return roles


def role_is_movable(guild: discord.Guild, role: discord.Role) -> bool:
    """Check if bot can move this role (must be below bot's top role)."""
    me = guild.me
    if me is None or role.is_default() or role.managed:
        return False
    if not me.guild_permissions.manage_roles:
        return False
    return role.position < me.top_role.position


def movable_roles(guild: discord.Guild) -> List[discord.Role]:
    return [role for role in role_order(guild) if role_is_movable(guild, role)]


def role_rank(guild: discord.Guild, role: discord.Role) -> int:
    """Current rank: 1 is the highest."""
    return next((i + 1 for i, item in enumerate(role_order(guild)) if item.id == role.id), 0)


def top_movable_slot(guild: discord.Guild) -> int:
    """Highest slot (0-based) that bot is permitted to place a role into."""
    roles = role_order(guild)
    me = guild.me
    if me is None:
        return len(roles)
    for index, role in enumerate(roles):
        if role.id == me.top_role.id:
            return index + 1
    return 0


def plan_role_move(
    guild: discord.Guild, role: discord.Role, slot: int
) -> Dict[discord.Role, int]:
    """Calculate payload {Role: position} to move `role` into `slot`."""
    roles = role_order(guild)
    current = next((i for i, item in enumerate(roles) if item.id == role.id), None)
    if current is None or not 0 <= slot < len(roles):
        raise ValueError("Vị trí đích không hợp lệ.")
    if slot < top_movable_slot(guild):
        raise ValueError("Không thể đặt role cao hơn role cao nhất của bot.")
    if not role_is_movable(guild, role):
        raise ValueError("Role này bot không thể kéo được.")

    wanted = list(roles)
    wanted.pop(current)
    wanted.insert(slot, role)

    payload: Dict[discord.Role, int] = {}
    for index, item in enumerate(wanted):
        if not role_is_movable(guild, item):
            continue
        new_position = len(roles) - index
        if item.position != new_position:
            payload[item] = new_position
    return payload


def role_lines(
    guild: discord.Guild,
    highlight: Optional[discord.Role] = None,
    limit: int = 14,
) -> List[str]:
    roles = role_order(guild)
    lines = []
    for index, role in enumerate(roles[:limit]):
        mark = "✅" if role_is_movable(guild, role) else "🔒"
        if highlight is not None and role.id == highlight.id:
            mark = "👉"
        lines.append(f"`#{index + 1}` {mark} {role.mention}")
    if len(roles) > limit:
        lines.append(f"*… và {len(roles) - limit} role khác*")
    return lines or ["*Server chưa có role nào.*"]
