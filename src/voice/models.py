"""Domain models and value objects for voice room locking, enforcement, and role hierarchy."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple
import discord


def utcnow() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


def parse_iso(value: str) -> datetime:
    """Parse ISO date string, ensuring UTC timezone."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@dataclass
class LockRecord:
    """Record of a locked voice channel."""

    channel_id: int
    locked_at: datetime
    locked_by: Optional[int] = None
    enforced_name: Optional[str] = None

    def to_json(self) -> Dict[str, Any]:
        """Serialize record to dictionary suitable for JSON storage."""
        return {
            "channel_id": self.channel_id,
            "locked_at": self.locked_at.isoformat(),
            "locked_by": self.locked_by,
            "enforced_name": self.enforced_name,
        }

    @classmethod
    def from_json(cls, channel_id: int, data: Dict[str, Any]) -> LockRecord:
        """Construct record from JSON dictionary."""
        return cls(
            channel_id=int(data.get("channel_id", channel_id)),
            locked_at=parse_iso(data["locked_at"]),
            locked_by=data.get("locked_by"),
            enforced_name=data.get("enforced_name"),
        )


@dataclass
class PurgeReport:
    """Report of a message purge operation in a voice channel."""

    scanned: int = 0
    violations: int = 0
    deleted: int = 0
    failed: int = 0
    names: List[str] = field(default_factory=list)

    @property
    def has_work(self) -> bool:
        """Return True if any messages violated room policy."""
        return self.violations > 0

    def summary(self) -> str:
        """Return human-readable summary for Discord UI."""
        if not self.has_work:
            return "Không có tin nhắn nào vi phạm."
        parts = [f"đã xóa **{self.deleted}** tin nhắn"]
        if self.failed:
            parts.append(f"**{self.failed}** tin không xóa được")
        return " · ".join(parts) + "."


@dataclass
class LockOutcome:
    """Result of a room lock operation for UI presentation."""

    record: LockRecord
    kicked: List[str] = field(default_factory=list)
    purge: Optional[PurgeReport] = None
    reactions_removed: int = 0


@dataclass
class RoleMovePlan:
    """Value object representing an atomic role movement plan across guild positions."""

    role: discord.Role
    target_slot: int
    payload: Dict[discord.Role, int] = field(default_factory=dict)

    @property
    def has_changes(self) -> bool:
        """Return True if any role positions will change."""
        return bool(self.payload)

    def items(self) -> Iterator[Tuple[discord.Role, int]]:
        """Iterate over (role, new_position) pairs."""
        return iter(self.payload.items())

    def __iter__(self) -> Iterator[discord.Role]:
        return iter(self.payload)

    def __getitem__(self, role: discord.Role) -> int:
        return self.payload[role]

    def __contains__(self, role: discord.Role) -> bool:
        return role in self.payload

    def __len__(self) -> int:
        return len(self.payload)
