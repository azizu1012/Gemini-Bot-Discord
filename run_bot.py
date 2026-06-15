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


async def run_bot_only(config):
    """Run bot without web server."""
    bot_core = None
    message_handler = None
    worker_task = None
    search_worker = None
    search_task = None

    try:
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
    logger.info(f"Model: {config.MODEL_NAME}")
    logger.info(f"Gemini API keys available: {len(config.GEMINI_API_KEYS)}")
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
