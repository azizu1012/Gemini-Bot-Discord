#!/usr/bin/env python3
"""
Run Azuris bot with optional web server.

Usage:
    python run_bot.py                  # Run bot only
    python run_bot.py --server         # Run bot + Flask web server
"""

import argparse
import asyncio
import sys
from threading import Thread

from src.core.config import get_config, logger
from src.handlers.bot_core import BotCore
from src.handlers.message_handler import MessageHandler
from src.handlers.bot_server import BotServer


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


async def run_bot_with_server(config):
    """Run bot with Flask web server."""
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


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Azuris Discord Bot")
    parser.add_argument("--server", action="store_true", help="Enable Flask web server")
    parser.add_argument("--config", type=str, default=".env", help="Config file path")

    args = parser.parse_args()

    config = get_config()
    logger.info("Configuration loaded")

    if not config.TOKEN:
        logger.error("Missing DISCORD_TOKEN. Please set it in your environment.")
        sys.exit(1)

    logger.info(f"Token preview: {_mask_token(config.TOKEN)}")
    logger.info(f"Model: {config.MODEL_NAME}")
    logger.info(f"Gemini API keys available: {len(config.GEMINI_API_KEYS)}")

    try:
        if args.server:
            asyncio.run(run_bot_with_server(config))
        else:
            asyncio.run(run_bot_only(config))
    except KeyboardInterrupt:
        logger.info("Bot shutdown by user")
    except Exception as e:
        logger.error(f"Unhandled exception: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
