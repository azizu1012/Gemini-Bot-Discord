import importlib.metadata
import os
import sys
import traceback
from pathlib import Path
from typing import Dict, List, Tuple

from .config import Config, logger

KEY_PACKAGES = [
    "google-genai",
    "discord.py",
    "python-dotenv",
    "Flask",
    "aiohttp",
]


def get_dependency_versions() -> Dict[str, str]:
    versions: Dict[str, str] = {}
    for pkg in KEY_PACKAGES:
        try:
            versions[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            versions[pkg] = "<missing>"
    return versions


def emit_startup_banner(config: Config) -> None:
    logger.info("=" * 70)
    logger.info("AZURIS STARTUP CONTEXT")
    logger.info("=" * 70)
    logger.info(f"Python executable: {sys.executable}")
    logger.info(f"Current working directory: {os.getcwd()}")
    logger.info(f"Project root: {config.PROJECT_ROOT}")
    for key, value in config.get_runtime_paths().items():
        logger.info(f"Runtime path [{key}]: {value}")
    logger.info("=" * 70)


def _ensure_writable_file_path(path_str: str) -> None:
    path = Path(path_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8"):
        pass


def _ensure_writable_dir(path_str: str) -> None:
    path = Path(path_str)
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".write_probe"
    with open(probe, "w", encoding="utf-8") as fh:
        fh.write("ok")
    probe.unlink(missing_ok=True)


def run_preflight_checks(config: Config, require_token: bool = False) -> Tuple[bool, List[str]]:
    errors: List[str] = []

    if require_token and not config.TOKEN:
        errors.append("DISCORD_TOKEN is missing")

    if not config.GEMINI_API_KEYS:
        errors.append("No Gemini API key found (GEMINI_API_KEY_*)")

    versions = get_dependency_versions()
    for pkg, version in versions.items():
        if version == "<missing>":
            errors.append(f"Missing dependency: {pkg}")

    try:
        _ensure_writable_file_path(config.DB_PATH)
        _ensure_writable_file_path(config.DB_BACKUP_PATH)
        _ensure_writable_file_path(config.WEATHER_CACHE_PATH)
        _ensure_writable_file_path(config.QUOTA_STATE_PATH)
        _ensure_writable_file_path(config.LOCKED_CHANNELS_FILE)
        _ensure_writable_file_path(config.ENFORCED_NAMES_FILE)
        _ensure_writable_file_path(config.VOICE_WHITELIST_FILE)
        _ensure_writable_file_path(config.VOICE_LOCK_LOG_FILE)
        _ensure_writable_file_path(config.LOG_PATH)
        _ensure_writable_dir(config.FILE_STORAGE_PATH)
    except Exception:
        errors.append(f"Runtime path check failed: {traceback.format_exc()}")

    for pkg, version in versions.items():
        logger.info(f"Dependency [{pkg}] = {version}")

    if errors:
        for err in errors:
            logger.error(f"Preflight error: {err}")
        return False, errors

    logger.info("Preflight checks passed.")
    return True, []
