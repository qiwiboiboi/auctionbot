"""
Main bot class that orchestrates all components
"""

from telegram import Update
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, 
    ConversationHandler, MessageHandler, filters
)

from repositories import SQLiteUserRepository, SQLiteAuctionRepository
from services import AuctionService, TelegramNotificationService
# Импортируем из папки handlers
from handlers import TelegramHandlers, BotStates


class TelegramBot:
    """Main Telegram bot class"""
    
    def __init__(self):
        # Initialize repositories (SQLite by default)
        self.user_repo = SQLiteUserRepository()
        self.auction_repo = SQLiteAuctionRepository()
        
        # Services will be initialized after application creation
        self.notification_service = None
        self.auction_service = None
        self.handlers = None

    async def init_database(self):
        """Initialize database tables"""
        await self.user_repo.init_db()
        await self.auction_repo.init_db()

    def create_application(self, token: str) -> Application:
        """Create and configure Telegram application"""
        application = Application.builder().token(token).build()
        
        # Initialize services with application
        self.notification_service = TelegramNotificationService(application)
        self.notification_service.user_repo = self.user_repo
        
        self.auction_service = AuctionService(
            self.user_repo, 
            self.auction_repo, 
            self.notification_service
        )
        
        # Initialize handlers
        self.handlers = TelegramHandlers(
            self.auction_service,
            self.user_repo,
            self.auction_repo
        )
        
        # Register all handlers
        self._register_handlers(application)
        
        return application

    def _register_handlers(self, application: Application):
        """Register all bot handlers"""
        
        # Conversation handler for registration
        register_conv = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(self.handlers.register_username, pattern=r'^register_join_'),
                CallbackQueryHandler(self.handlers.register_username, pattern=r'^register_start$')
            ],
            states={
                BotStates.REGISTER_USERNAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handlers.register_username)
                ]
            },
            fallbacks=[
                CommandHandler('cancel', self.handlers.cancel),
                MessageHandler(filters.Regex('^❌ Отмена$'), self.handlers.cancel)
            ],
            per_message=False
        )
        
        # Conversation handler for auction creation
        create_conv = ConversationHandler(
            entry_points=[MessageHandler(filters.Regex('^➕ Создать аукцион$'), self.handlers.create_start)],
            states={
                BotStates.CREATE_TITLE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handlers.create_title)
                ],
                BotStates.CREATE_START_PRICE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handlers.create_start_price)
                ],
                BotStates.CREATE_DURATION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handlers.create_duration)
                ],
                BotStates.CREATE_DESCRIPTION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handlers.create_description)
                ],
                BotStates.CREATE_MEDIA: [
                    MessageHandler(
                        (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.ANIMATION) & ~filters.COMMAND, 
                        self.handlers.create_media
                    )
                ],
                BotStates.CREATE_CUSTOM_MESSAGE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handlers.create_custom_message)
                ]
            },
            fallbacks=[
                CommandHandler('cancel', self.handlers.cancel),
                MessageHandler(filters.Regex('^❌ Отмена$'), self.handlers.cancel)
            ],
            per_message=False
        )
        
        # Conversation handler for bidding
        bid_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.handlers.bid_start, pattern=r'^bid_')],
            states={
                BotStates.PLACE_BID: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handlers.place_bid)
                ]
            },
            fallbacks=[
                CommandHandler('cancel', self.handlers.cancel),
                MessageHandler(filters.Regex('^❌ Отмена$'), self.handlers.cancel)
            ],
            per_message=False
        )
        
        # Add conversation handlers FIRST (highest priority)
        application.add_handler(register_conv)
        application.add_handler(create_conv)  
        application.add_handler(bid_conv)
        
        # Command handlers
        application.add_handler(CommandHandler('start', self.handlers.start))
        
        # Callback query handlers - handle all callbacks through one handler
        application.add_handler(CallbackQueryHandler(self.handlers.handle_callback))
        
        # Text message handlers for keyboard buttons (lowest priority)
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handlers.handle_text))