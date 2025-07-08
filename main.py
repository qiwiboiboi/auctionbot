"""
Main entry point for the Telegram Auction Bot
"""

import asyncio
import logging
import os
import sys
import signal
from dotenv import load_dotenv

from bot import TelegramBot
from services import AuctionScheduler


class GracefulShutdown:
    """Graceful shutdown handler"""
    def __init__(self):
        self.shutdown_event = asyncio.Event()
        
    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logging.info(f"Received signal {signum}, shutting down gracefully...")
        self.shutdown_event.set()


async def main():
    """Main application entry point"""
    # Load environment variables
    load_dotenv()
    
    # Setup logging
    log_level = os.getenv('LOG_LEVEL', 'INFO')
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=getattr(logging, log_level.upper())
    )
    
    # Get configuration
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")
    
    # Setup graceful shutdown
    shutdown_handler = GracefulShutdown()
    
    # Handle signals (works on Unix-like systems)
    if hasattr(signal, 'SIGINT'):
        signal.signal(signal.SIGINT, shutdown_handler.signal_handler)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, shutdown_handler.signal_handler)
    
    # Create bot and initialize database
    bot = TelegramBot()
    await bot.init_database()
    logging.info("Database initialized")
    
    # Create application
    application = bot.create_application(token)
    
    # Create and start scheduler
    scheduler = AuctionScheduler(bot.auction_service, bot.auction_repo)
    scheduler_task = asyncio.create_task(scheduler.start())
    
    try:
        # Start the bot
        logging.info("Starting Telegram Bot...")
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        
        # Keep running until shutdown signal
        logging.info("Bot started! Press Ctrl+C to stop.")
        
        # Wait for shutdown signal
        await shutdown_handler.shutdown_event.wait()
        
    except Exception as e:
        logging.error(f"Error: {e}")
        
    finally:
        # Cleanup
        logging.info("Shutting down...")
        
        # Stop scheduler
        await scheduler.stop()
        if not scheduler_task.cancelled():
            scheduler_task.cancel()
            try:
                await scheduler_task
            except asyncio.CancelledError:
                logging.info("Scheduler task cancelled")
        
        # Stop bot
        try:
            await application.updater.stop()
            await application.stop()
            await application.shutdown()
            logging.info("Bot stopped gracefully")
        except Exception as e:
            logging.error(f"Error during shutdown: {e}")


if __name__ == '__main__':
    # Windows compatibility
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Application interrupted by user")
        sys.exit(0)
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        sys.exit(1)