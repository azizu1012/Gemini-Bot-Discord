#!/usr/bin/env python3
"""
Run Chad Gibiti bot with optional web server.

Usage:
    python run_bot.py                     # Run bot only
    python run_bot.py --server            # Run bot + FastAPI gateway server
    python run_bot.py --preflight         # Validate runtime and exit
"""

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def _norm_path(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def _resolve_preferred_python() -> Path | None:
    explicit_python = (os.getenv("AZURIS_PYTHON") or "").strip()
    if not explicit_python:
        return None

    candidate = Path(explicit_python)
    if candidate.exists():
        return candidate.resolve()
    return None


def _ensure_preferred_interpreter() -> None:
    script_path = Path(__file__).resolve()
    target_python = _resolve_preferred_python()
    if target_python is None:
        return

    current_python = Path(sys.executable).resolve()
    if _norm_path(current_python) == _norm_path(target_python):
        return

    print(f"[INFO] Re-launching with preferred interpreter: {target_python}")
    result = subprocess.run([str(target_python), str(script_path), *sys.argv[1:]], check=False)
    raise SystemExit(result.returncode)


_ensure_preferred_interpreter()

from src.core.config import get_config, logger
from src.core.preflight import emit_startup_banner, run_preflight_checks
from src.handlers.discord.bot_core import BotCore
from src.handlers.message_handler import MessageHandler
from src.services.search_subtask_worker import SearchSubtaskWorker


def _mask_token(token: str) -> str:
    if not token:
        return "<missing>"
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}...{token[-4:]}"


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


_WORKER_LOCK_KEY = "azuris:worker:instance-lock"
_WORKER_LOCK_VALUE = os.getenv("AZURIS_INSTANCE_ID") or str(os.getpid())


async def _acquire_worker_lock(config):
    """Acquire a Redis lock (NX EX) representing the single worker instance.

    Returns a callable that releases the lock, or None if the lock was not
    acquired (either it is held by another instance, or Redis is unavailable and
    we proceed fail-open for local dev).
    """
    try:
        import redis.asyncio as aioredis

        redis_client = aioredis.from_url(config.REDIS_URL, decode_responses=True)
    except Exception as e:
        logger.warning(f"Redis unavailable for worker lock ({e}); proceeding fail-open.")
        return None

    try:
        acquired = await redis_client.set(_WORKER_LOCK_KEY, _WORKER_LOCK_VALUE, nx=True, ex=3600)
        if not acquired:
            logger.error(
                "Another worker instance appears to be running (Redis lock "
                f"'{_WORKER_LOCK_KEY}' is held). Refusing to start a second worker "
                "to preserve per-user ordering and cache coherence."
            )
            await redis_client.close()
            sys.exit(1)
        logger.info("Acquired single-worker Redis lock.")
    except Exception as e:
        logger.warning(f"Could not acquire worker lock ({e}); proceeding fail-open.")
        await redis_client.close()
        return None

    async def _release():
        try:
            # Only release if we still own the lock.
            owned = await redis_client.get(_WORKER_LOCK_KEY)
            if owned == _WORKER_LOCK_VALUE:
                await redis_client.delete(_WORKER_LOCK_KEY)
        except Exception as e:
            logger.warning(f"Failed to release worker lock ({e}).")
        finally:
            await redis_client.close()

    return _release


async def run_bot_only(config):
    """Run bot without web server."""
    bot_core = None
    message_handler = None
    worker_task = None
    search_worker = None
    search_task = None
    release_worker_lock = None

    try:
        release_worker_lock = await _acquire_worker_lock(config)

        bot_core = BotCore(config)
        logger.info("BotCore initialized")

        message_handler = MessageHandler(config)
        logger.info("MessageHandler initialized")

        logger.info("Starting background worker for MessageHandler")
        worker_task = asyncio.create_task(message_handler.start_worker())

        if os.getenv("SEARCH_SUBTASKS_ENABLED", "false").lower() == "true":
            search_worker = SearchSubtaskWorker(config)
            logger.info("Starting SearchSubtaskWorker")
            search_task = asyncio.create_task(search_worker.start_worker())

        logger.info("Starting Chad Gibiti Discord bot")
        await bot_core.start(config.TOKEN)

    except KeyError as e:
        logger.error(f"Missing environment variable: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
    finally:
        if worker_task is not None and not worker_task.done():
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass

        if search_task is not None and not search_task.done():
            search_task.cancel()
            try:
                await search_task
            except asyncio.CancelledError:
                pass

        if search_worker is not None:
            await search_worker.shutdown()

        if message_handler is not None:
            await message_handler.shutdown()

        if bot_core is not None:
            await bot_core.shutdown()

        if release_worker_lock is not None:
            await release_worker_lock()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Chad Gibiti Discord Bot")
    parser.add_argument("--preflight", action="store_true", help="Validate runtime paths/dependencies and exit")
    parser.add_argument("--config", type=str, default=".env", help="Config file path (legacy, retained for compatibility)")

    args = parser.parse_args()

    config = get_config()
    logger.info("Configuration loaded")
    emit_startup_banner(config)

    preflight_require_token = not args.preflight
    preflight_ok, _ = run_preflight_checks(config, require_token=preflight_require_token)
    if not preflight_ok:
        sys.exit(1)

    if args.preflight:
        logger.info("Preflight only mode complete.")
        sys.exit(0)

    if not config.TOKEN:
        logger.error("Missing DISCORD_TOKEN. Please set it in your environment.")
        sys.exit(1)

    logger.info(f"Token preview: {_mask_token(config.TOKEN)}")
    logger.info(f"Database URL: {_mask_database_url(config.DATABASE_URL)}")
    logger.info(f"Redis URL: {config.REDIS_URL}")

    try:
        asyncio.run(run_bot_only(config))
    except KeyboardInterrupt:
        logger.info("Bot shutdown signal received (KeyboardInterrupt). This often happens during process-manager restart.")
    except Exception as e:
        logger.error(f"Unhandled exception: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
