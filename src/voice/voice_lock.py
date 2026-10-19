"""Backward-compatible VoiceLockManager facade bridging to RoomLockService and Stores."""

from __future__ import annotations

import datetime
import os
from pathlib import Path
from typing import Any, Dict, Optional, Set

from discord import app_commands
from src.voice.store import LockStore, WhitelistStore
from src.voice.models import LockRecord


class VoiceLockManager:
    """Facade maintaining backward compatibility with legacy VoiceLockManager callers."""

    def __init__(
        self,
        owner_id: int,
        whitelist_file: str,
        locked_channels_file: str,
        enforced_names_file: str,
        voice_lock_log_file: str,
    ):
        self.owner_id = owner_id
        self.whitelist_file = whitelist_file
        self.locked_channels_file = locked_channels_file
        self.enforced_names_file = enforced_names_file
        self.voice_lock_log_file = voice_lock_log_file

        self.lock_store = LockStore(Path(locked_channels_file))
        self.whitelist_store = WhitelistStore(Path(whitelist_file))
        self.ignore_next_updates: Set[int] = set()

    @property
    def locked_channels(self) -> Set[int]:
        return self.lock_store.channel_ids()

    @property
    def enforced_names(self) -> Dict[int, str]:
        names = {}
        for rec in self.lock_store.records():
            if rec.enforced_name:
                names[rec.channel_id] = rec.enforced_name
        return names

    def save_locked_channels(self) -> None:
        pass  # LockStore auto-flushes atomically

    def save_enforced_names(self) -> None:
        pass  # LockStore auto-flushes atomically

    def load_whitelist(self, force_reload: bool = False) -> Dict[str, Any]:
        data = self.whitelist_store._read() if force_reload else self.whitelist_store._data
        if not data:
            data = {str(self.owner_id): {"username": "owner", "id": str(self.owner_id)}}
            self.whitelist_store._data = data
            self.whitelist_store._flush()
        return data

    def save_whitelist(self, data: dict) -> None:
        self.whitelist_store._data = data
        self.whitelist_store._flush()

    def log_action(self, message: str) -> None:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] {message}"
        try:
            os.makedirs(os.path.dirname(self.voice_lock_log_file), exist_ok=True)
            with open(self.voice_lock_log_file, "a", encoding="utf-8") as f:
                f.write(log_line + "\n")
        except Exception:
            pass

    def is_owner_check(self):
        owner_id = self.owner_id

        async def predicate(interaction):
            return interaction.user.id == owner_id

        return app_commands.check(predicate)
