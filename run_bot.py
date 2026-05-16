#!/usr/bin/env python3
"""
Run Azuris bot with optional web server.

Usage:
    python run_bot.py                     # Run bot only
    python run_bot.py --server            # Run bot + Flask web server
    python run_bot.py --preflight         # Validate runtime and exit
"""

import argparse
import asyncio
import sys
from threading import Thread

from src.core.config import get_config, logger
from src.core.preflight import emit_startup_banner, run_preflight_checks
from src.handlers.bot_core import BotCore
from src.handlers.bot_server import BotServer
from src.handlers.message_handler import MessageHandler


def _mask_token(token: str) -> str:
    if not token:
        return "<missing>"
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}...{token[-4:]}"


def _register_message_handler(bot_core: BotCore, message_handler: MessageHandler) -> None:
    async def on_message(message):
        await message_handler.handle_message(message, bot_core.bot)

    bot_core.bot.event(on_message)


async def run_bot_only(config):
    """Run bot without web server."""
    message_handler = None
    try:
        bot_core = BotCore(config)
        logger.info("BotCore initialized")

        message_handler = MessageHandler(bot_core, config)
        logger.info("MessageHandler initialized")

        _register_message_handler(bot_core, message_handler)

        logger.info("Starting Azuris Discord bot")
        await bot_core.start(config.TOKEN)

    except KeyError as e:
        logger.error(f"Missing environment variable: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
    finally:
        if message_handler is not None:
            await message_handler.close_gemini_clients()


async def run_bot_with_server(config):
    """Run bot with Flask web server."""
    message_handler = None
    try:
        bot_core = BotCore(config)
        logger.info("BotCore initialized")

        message_handler = MessageHandler(bot_core, config)
        logger.info("MessageHandler initialized")

        _register_message_handler(bot_core, message_handler)

        bot_server = BotServer(config, bot_core)
        logger.info("BotServer initialized")

        def run_server():
            bot_server.run(host="127.0.0.1", port=5000, debug=False)

        server_thread = Thread(target=run_server, daemon=True)
        server_thread.start()
        logger.info("Web server started in background")

        logger.info("Starting Azuris Discord bot with web server")
        await bot_core.start(config.TOKEN)

    except KeyError as e:
        logger.error(f"Missing environment variable: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
    finally:
        if message_handler is not None:
            await message_handler.close_gemini_clients()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Azuris Discord Bot")
    parser.add_argument("--server", action="store_true", help="Enable Flask web server")
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
    logger.info(f"Database path: {config.DB_PATH}")

    try:
        if args.server:
            asyncio.run(run_bot_with_server(config))
        else:
            asyncio.run(run_bot_only(config))
    except KeyboardInterrupt:
        logger.info("Bot shutdown signal received (KeyboardInterrupt). This often happens during process-manager restart.")
    except Exception as e:
        logger.error(f"Unhandled exception: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
