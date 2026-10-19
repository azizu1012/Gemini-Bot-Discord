"""Data models for voice room locking, enforcement, and purging."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso(value: str) -> datetime:
    """Parse ISO date string, ensuring UTC timezone."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class LockRecord:
    """Record of a locked voice channel."""

    __slots__ = ("channel_id", "locked_at", "locked_by", "enforced_name")

    def __init__(
        self,
        channel_id: int,
        locked_at: datetime,
        locked_by: Optional[int] = None,
        enforced_name: Optional[str] = None,
    ) -> None:
        self.channel_id = channel_id
        self.locked_at = locked_at
        self.locked_by = locked_by
        self.enforced_name = enforced_name

    def to_json(self) -> dict:
        return {
            "channel_id": self.channel_id,
            "locked_at": self.locked_at.isoformat(),
            "locked_by": self.locked_by,
            "enforced_name": self.enforced_name,
        }

    @classmethod
    def from_json(cls, channel_id: int, data: dict) -> "LockRecord":
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
        return self.violations > 0

    def summary(self) -> str:
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
