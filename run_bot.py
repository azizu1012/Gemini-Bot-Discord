#!/usr/bin/env python3
"""
Run Azuris bot with optional web server.
Usage:
    python run_bot.py                  # Run bot only
    python run_bot.py --server         # Run bot + Flask web server
"""

import asyncio
import argparse
import sys
from pathlib import Path
from threading import Thread

from src.core.config import get_config, logger
from src.handlers.bot_core import BotCore
from src.handlers.message_handler import MessageHandler
from src.handlers.bot_server import BotServer


async def run_bot_only(config):
    """Run bot without web server."""
    try:
        # Initialize bot
        bot_core = BotCore(config)
        logger.info("✅ BotCore initialized")
        
        # Initialize message handler
        message_handler = MessageHandler(bot_core, config)
        logger.info("✅ MessageHandler initialized")
        
        # Register message handler
        @bot_core.bot.event
        async def on_message(message):
            await message_handler.handle_message(message, bot_core.bot)
        
        # Start bot
        logger.info("🚀 Starting Azuris Discord Bot...")
        await bot_core.start(config.TOKEN)
    
    except KeyError as e:
        logger.error(f"❌ Missing environment variable: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        sys.exit(1)


async def run_bot_with_server(config):
    """Run bot with Flask web server."""
    try:
        # Initialize bot
        bot_core = BotCore(config)
        logger.info("✅ BotCore initialized")
        
        # Initialize message handler
        message_handler = MessageHandler(bot_core, config)
        logger.info("✅ MessageHandler initialized")
        
        # Register message handler
        @bot_core.bot.event
        async def on_message(message):
            await message_handler.handle_message(message, bot_core.bot)
        
        # Initialize web server
        bot_server = BotServer(config, bot_core)
        logger.info("✅ BotServer initialized")
        
        # Run web server in separate thread
        def run_server():
            bot_server.run(host='127.0.0.1', port=5000, debug=False)
        
        server_thread = Thread(target=run_server, daemon=True)
        server_thread.start()
        logger.info("🌐 Web server started in background")
        
        # Start bot
        logger.info("🚀 Starting Azuris Discord Bot with web server...")
        await bot_core.start(config.TOKEN)
    
    except KeyError as e:
        logger.error(f"❌ Missing environment variable: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        sys.exit(1)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Azuris Discord Bot')
    parser.add_argument('--server', action='store_true', help='Enable Flask web server')
    parser.add_argument('--config', type=str, default='.env', help='Config file path')
    
    args = parser.parse_args()
    
    # Load config
    config = get_config()
    logger.info(f"📋 Configuration loaded")
    logger.info(f"   Bot token: {config.TOKEN[:20]}...")
    logger.info(f"   Model: {config.MODEL_NAME}")
    logger.info(f"   API keys: {len(config.GEMINI_API_KEYS)} available")
    
    # Run bot
    try:
        if args.server:
            asyncio.run(run_bot_with_server(config))
        else:
            asyncio.run(run_bot_only(config))
    except KeyboardInterrupt:
        logger.info("⏹️ Bot shutdown by user")
    except Exception as e:
        logger.error(f"❌ Unhandled exception: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
