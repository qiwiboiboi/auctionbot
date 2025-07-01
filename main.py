"""
Main entry point for the Telegram Auction Bot
"""

import asyncio
import logging
import os
import sys
from dotenv import load_dotenv

from bot import TelegramBot
from services import AuctionScheduler


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
    
    # Create bot and initialize database
    bot = TelegramBot()
    await bot.init_database()
    logging.info("Database initialized")
    
    # Create application
    application = bot.create_application(token)
    
    # Create and start scheduler
    scheduler_interval = int(os.getenv('SCHEDULER_INTERVAL', '60'))
    scheduler = AuctionScheduler(bot.auction_service, bot.auction_repo)
    scheduler_task = asyncio.create_task(scheduler.start())
    
    try:
        # Start the bot
        logging.info("Starting Telegram Bot...")
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        
        # Keep running - Windows compatible
        logging.info("Bot started! Press Ctrl+C to stop.")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logging.info("Received KeyboardInterrupt")
            
    except Exception as e:
        logging.error(f"Error: {e}")
    finally:
        # Cleanup
        logging.info("Shutting down...")
        await scheduler.stop()
        if not scheduler_task.cancelled():
            scheduler_task.cancel()
            try:
                await scheduler_task
            except asyncio.CancelledError:
                pass
        
        await application.updater.stop()
        await application.stop()
        await application.shutdown()


if __name__ == '__main__':
    # Windows compatibility
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())