#!/usr/bin/env python3
"""
Azuris Discord Bot - Main Entry Point
Refactored from @clone with OOP architecture and clean separation of concerns.
"""

import asyncio
import sys
from pathlib import Path

from src.core.config import get_config, logger
from src.handlers.bot_core import BotCore
from src.handlers.message_handler import MessageHandler


async def main():
    """Initialize and run the Discord bot."""
    try:
        # Load configuration
        config = get_config()
        logger.info("Configuration loaded successfully")
        
        # Initialize bot core
        bot_core = BotCore(config)
        logger.info("BotCore initialized")
        
        # Initialize message handler
        message_handler = MessageHandler(bot_core, config)
        logger.info("MessageHandler initialized")
        
        # Register message handler
        @bot_core.bot.event
        async def on_message(message):
            await message_handler.handle_message(message, bot_core.bot)
        
        # Start the bot
        logger.info(f"Starting bot with token: {config.TOKEN[:20]}...")
        await bot_core.start(config.TOKEN)
    
    except KeyError as e:
        logger.error(f"Missing environment variable: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot shutdown by user")
    except Exception as e:
        logger.error(f"Unhandled exception: {e}")
        sys.exit(1)
