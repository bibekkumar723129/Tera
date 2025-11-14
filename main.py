#!/usr/bin/env python3
"""
Main entry point for Terabox Downloader Bot
"""
import asyncio
import logging
import signal
from pathlib import Path

import config
from src.handlers.bot import create_bot
from src.database import db

# Configure logging
logging.basicConfig(
    level=config.LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class BotManager:
    """Manages bot lifecycle"""
    
    def __init__(self):
        self.bot = None
        self.running = False
    
    async def initialize(self):
        """Initialize the bot"""
        logger.info("Initializing Terabox Downloader Bot...")
        
        # Create download directory
        Path(config.DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)
        logger.info(f"Download directory: {config.DOWNLOAD_DIR}")
        
        # Connect to MongoDB
        if db.connect():
            logger.info("MongoDB connected successfully")
        else:
            logger.warning("Failed to connect to MongoDB - database features will be unavailable")
        
        # Create bot instance
        self.bot = create_bot(config.BOT_TOKEN)
        logger.info("Bot instance created")
    
    async def run(self):
        """Run the bot"""
        if not self.bot:
            await self.initialize()
        
        self.running = True
        logger.info("Starting bot...")
        
        # Send restart notification to all users and admin
        if self.bot:
            await self.bot.notify_restart()
        
        try:
            await self.bot.start()
            # Keep the bot running
            while self.running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
            await self.shutdown()
        except Exception as e:
            logger.error(f"Error running bot: {e}")
            await self.shutdown()
    
    async def shutdown(self):
        """Shutdown the bot gracefully"""
        logger.info("Shutting down bot...")
        self.running = False
        
        if self.bot:
            await self.bot.stop()
        
        # Disconnect from MongoDB
        db.disconnect()
        
        logger.info("Bot shutdown complete")


async def main():
    """Main function"""
    manager = BotManager()
    
    # Handle signals
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}")
        if manager.running:
            asyncio.create_task(manager.shutdown())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    await manager.run()


if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("Terabox Video Downloader Bot")
    logger.info("=" * 50)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot terminated by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        exit(1)
