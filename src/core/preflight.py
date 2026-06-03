import asyncio
import importlib.metadata
import os
import sys
import traceback
from pathlib import Path
from typing import Dict, List, Tuple
from urllib.parse import urlsplit, urlunsplit

import asyncpg

from .config import Config, logger

KEY_PACKAGES = [
    "google-genai",
    "discord.py",
    "python-dotenv",
    "aiohttp",
    "openai",
    "requests",
    "pypdf",
    "asyncpg",
    "aiokafka",
]


def _mask_database_url(database_url: str) -> str:
    if not database_url:
        return "<missing>"
    try:
        parsed = urlsplit(database_url)
        if parsed.password is None:
            return database_url
        username = parsed.username or ""
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        netloc = f"{username}:***@{host}{port}"
        return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
    except Exception:
        return "<masked>"


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

    logger.info(f"Database URL: {_mask_database_url(config.DATABASE_URL)}")
    logger.info(f"Kafka Servers: {config.KAFKA_BOOTSTRAP_SERVERS}")
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


async def _verify_database_connection(database_url: str, retries: int = 5, delay_seconds: float = 2.0) -> None:
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        conn = None
        try:
            conn = await asyncpg.connect(dsn=database_url, timeout=5, ssl=False)
            await conn.fetchval("SELECT 1")
            return
        except Exception as e:
            last_error = e
            logger.warning(f"Database check attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                await asyncio.sleep(delay_seconds)
        finally:
            if conn is not None:
                try:
                    await conn.close()
                except Exception:
                    pass

    raise ConnectionError(f"Could not connect to PostgreSQL after {retries} attempts: {last_error}")


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

    asyncio.run(_verify_database_connection(config.DATABASE_URL, retries=5, delay_seconds=2.0))

    try:
        _ensure_writable_file_path(config.WEATHER_CACHE_PATH)
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
