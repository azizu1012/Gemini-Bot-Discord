import datetime
import json
import os

from discord import app_commands


class VoiceLockManager:
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

        self._whitelist_cache = None
        self.locked_channels: set[int] = self._load_locked_channels()
        self.enforced_names: dict[int, str] = self._load_enforced_names()
        self.ignore_next_updates: set[int] = set()

        os.makedirs(os.path.dirname(self.whitelist_file), exist_ok=True)

    def _load_locked_channels(self) -> set[int]:
        try:
            with open(self.locked_channels_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {int(item) for item in data}
        except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
            return set()

    def save_locked_channels(self):
        with open(self.locked_channels_file, "w", encoding="utf-8") as f:
            json.dump(list(self.locked_channels), f)

    def _load_enforced_names(self) -> dict[int, str]:
        try:
            with open(self.enforced_names_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {int(k): str(v) for k, v in data.items()}
        except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
            return {}

    def save_enforced_names(self):
        with open(self.enforced_names_file, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in self.enforced_names.items()}, f, ensure_ascii=False)

    def _default_whitelist(self) -> dict:
        return {str(self.owner_id): {"username": "owner", "id": str(self.owner_id)}}

    def load_whitelist(self, force_reload: bool = False) -> dict:
        if self._whitelist_cache is not None and not force_reload:
            return self._whitelist_cache
        try:
            with open(self.whitelist_file, "r", encoding="utf-8") as f:
                self._whitelist_cache = json.load(f)
        except FileNotFoundError:
            self._whitelist_cache = self._default_whitelist()
            self.save_whitelist(self._whitelist_cache)
        except json.JSONDecodeError:
            self._whitelist_cache = self._default_whitelist()
        return self._whitelist_cache

    def save_whitelist(self, data: dict):
        self._whitelist_cache = data
        os.makedirs(os.path.dirname(self.whitelist_file), exist_ok=True)
        with open(self.whitelist_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def log_action(self, message: str):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] {message}"
        print(log_line)
        try:
            with open(self.voice_lock_log_file, "a", encoding="utf-8") as f:
                f.write(log_line + "\n")
        except Exception:
            pass

    def is_owner_check(self):
        owner_id = self.owner_id

        async def predicate(interaction):
            return interaction.user.id == owner_id

        return app_commands.check(predicate)
