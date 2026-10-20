"""Atomic file-based stores and storage protocols for voice room locks and whitelists."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Protocol, Set, Tuple, runtime_checkable

from src.voice.models import LockRecord, utcnow


@runtime_checkable
class LockStoreProtocol(Protocol):
    """Protocol defining the interface for voice lock persistence."""

    def lock(self, channel_id: int, locked_by: Optional[int] = None) -> LockRecord:
        ...

    def unlock(self, channel_id: int) -> Optional[LockRecord]:
        ...

    def get(self, channel_id: int) -> Optional[LockRecord]:
        ...

    def is_locked(self, channel_id: int) -> bool:
        ...

    def set_enforced_name(self, channel_id: int, name: Optional[str]) -> None:
        ...

    def records(self) -> Iterator[LockRecord]:
        ...

    def channel_ids(self) -> Set[int]:
        ...


@runtime_checkable
class WhitelistStoreProtocol(Protocol):
    """Protocol defining the interface for voice room whitelist persistence."""

    def add(self, user_id: int, username: str = "") -> None:
        ...

    def remove(self, user_id: int) -> bool:
        ...

    def contains(self, user_id: int) -> bool:
        ...

    def ids(self) -> Set[int]:
        ...

    def entries(self) -> List[Tuple[int, str]]:
        ...


class JsonStore:
    """Base class: keeps a dict in RAM and flushes atomically to JSON on change."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._data: dict = self._read()

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self._data, handle, indent=4, ensure_ascii=False)
            os.replace(tmp_name, self.path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise


class LockStore(JsonStore):
    """Store for tracking locked voice channels, persisting across bot restarts."""

    def lock(self, channel_id: int, locked_by: Optional[int] = None) -> LockRecord:
        record = LockRecord(channel_id, utcnow(), locked_by)
        self._data[str(channel_id)] = record.to_json()
        self._flush()
        return record

    def unlock(self, channel_id: int) -> Optional[LockRecord]:
        record = self.get(channel_id)
        if self._data.pop(str(channel_id), None) is not None:
            self._flush()
        return record

    def get(self, channel_id: int) -> Optional[LockRecord]:
        raw = self._data.get(str(channel_id))
        return LockRecord.from_json(channel_id, raw) if raw else None

    def is_locked(self, channel_id: int) -> bool:
        return str(channel_id) in self._data

    def set_enforced_name(self, channel_id: int, name: Optional[str]) -> None:
        record = self.get(channel_id)
        if record is None:
            return
        record.enforced_name = name
        self._data[str(channel_id)] = record.to_json()
        self._flush()

    def records(self) -> Iterator[LockRecord]:
        for key, raw in list(self._data.items()):
            try:
                yield LockRecord.from_json(int(key), raw)
            except (ValueError, KeyError):
                continue

    def channel_ids(self) -> Set[int]:
        ids: Set[int] = set()
        for key in self._data:
            try:
                ids.add(int(key))
            except ValueError:
                continue
        return ids


class WhitelistStore(JsonStore):
    """Store for tracking members allowed inside locked rooms."""

    def add(self, user_id: int, username: str = "") -> None:
        self._data[str(user_id)] = {"id": str(user_id), "username": username}
        self._flush()

    def remove(self, user_id: int) -> bool:
        if self._data.pop(str(user_id), None) is not None:
            self._flush()
            return True
        return False

    def contains(self, user_id: int) -> bool:
        return str(user_id) in self._data

    def ids(self) -> Set[int]:
        result: Set[int] = set()
        for key in self._data:
            try:
                result.add(int(key))
            except ValueError:
                continue
        return result

    def entries(self) -> List[Tuple[int, str]]:
        result: List[Tuple[int, str]] = []
        for key, value in self._data.items():
            try:
                name = value.get("username", "") if isinstance(value, dict) else ""
                result.append((int(key), name))
            except ValueError:
                continue
        return sorted(result, key=lambda item: item[0])
