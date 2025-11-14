#!/usr/bin/env python3
"""
Main entry point for Terabox Downloader Bot
Includes HTTP server for Render Web Service deployment
"""
import asyncio
import logging
import signal
import os
from pathlib import Path
from aiohttp import web

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
    """Manages bot lifecycle and HTTP server"""
    
    def __init__(self):
        self.bot = None
        self.running = False
        self.app = None
        self.runner = None
    
    async def initialize(self):
        """Initialize the bot and HTTP server"""
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
        
        # Setup HTTP server for Render Web Service
        self.app = web.Application()
        self.app.router.add_get('/', self.health_check)
        self.app.router.add_get('/health', self.health_check)
    
    async def health_check(self, request):
        """Health check endpoint for Render"""
        return web.json_response({'status': 'ok', 'service': 'terabox-bot'})
    
    async def run(self):
        """Run the bot and HTTP server"""
        if not self.bot:
            await self.initialize()
        
        self.running = True
        logger.info("Starting bot and HTTP server...")
        
        # Get port from environment or use default
        port = int(os.environ.get('PORT', 8000))
        logger.info(f"HTTP server will listen on port {port}")
        
        # Start HTTP server
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '0.0.0.0', port)
        await site.start()
        logger.info(f"HTTP server started on 0.0.0.0:{port}")
        
        # Send restart notification to all users and admin
        if self.bot:
            await self.bot.notify_restart()
        
        try:
            await self.bot.start()
            # Keep running
            while self.running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
            await self.shutdown()
        except Exception as e:
            logger.error(f"Error running bot: {e}")
            await self.shutdown()
    
    async def shutdown(self):
        """Shutdown the bot and server gracefully"""
        logger.info("Shutting down bot and server...")
        self.running = False
        
        if self.bot:
            await self.bot.stop()
        
        if self.runner:
            await self.runner.cleanup()
        
        # Disconnect from MongoDB
        db.disconnect()
        
        logger.info("Bot and server shutdown complete")


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
