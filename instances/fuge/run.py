#!/usr/bin/env python3
"""
Fuge Bot Instance Launcher
Loads shared core logic with per-instance personality (instructions.py)
Usage: python run.py
Deploy: pm2 start run.py --name fuge
"""

import asyncio
import sys
import os
from pathlib import Path

# --- Setup Python path ---
try:
    project_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(project_root / 'common_src'))
except IndexError:
    print("❌ Error: Incorrect directory structure", file=sys.stderr)
    sys.exit(1)

# --- Set working directory for .env ---
instance_dir = Path(__file__).resolve().parent
os.chdir(instance_dir)

# --- Imports ---
try:
    from core.config import get_config, logger
    from handlers.bot_core import BotCore
    from handlers.message_handler import MessageHandler
except ImportError as e:
    print(f"❌ Import failed: {e}", file=sys.stderr)
    sys.exit(1)


async def main():
    """Main entry point."""
    config = get_config()
    logger.info("📋 Fuge Configuration Loaded")
    logger.info(f"   Token: {config.TOKEN[:20]}...")
    logger.info(f"   API Keys: {len(config.GEMINI_API_KEYS)}")
    logger.info(f"   Model: {config.MODEL_NAME}")
    
    try:
        bot_core = BotCore(config)
        logger.info("✅ BotCore initialized")
        
        message_handler = MessageHandler(bot_core, config)
        logger.info("✅ MessageHandler initialized")
        
        @bot_core.bot.event
        async def on_message(message):
            await message_handler.handle_message(message, bot_core.bot)
        
        logger.info("🚀 Starting Fuge Bot...")
        logger.info("💡 Manage with PM2: pm2 start run.py --name fuge")
        await bot_core.start(config.TOKEN)
    
    except KeyError as e:
        logger.error(f"❌ Missing .env variable: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("⏹️ Shutdown by user")
    except Exception as e:
        logger.error(f"❌ Fatal: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
