"""
Base handlers and keyboard generators
"""

from uuid import UUID
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler

from domain import Auction, AuctionStatus
from services import AuctionService
from repositories import UserRepository, AuctionRepository


class BotStates:
    """Conversation states for bot interactions"""
    REGISTER_USERNAME = 1
    CREATE_TITLE = 2
    CREATE_START_PRICE = 3
    CREATE_DURATION = 4
    CREATE_DESCRIPTION = 5
    CREATE_MEDIA = 6
    CREATE_CUSTOM_MESSAGE = 7
    PLACE_BID = 8
    ADMIN_ACTION = 9
    BROADCAST_MESSAGE = 10
    EDIT_AUCTION_TITLE = 11
    EDIT_AUCTION_DESCRIPTION = 12
    EDIT_AUCTION_PRICE = 13


class BaseHandlers:
    """Base handlers with keyboard generators and utility methods"""
    
    def __init__(self, auction_service: AuctionService, user_repo: UserRepository, auction_repo: AuctionRepository):
        self.auction_service = auction_service
        self.user_repo = user_repo
        self.auction_repo = auction_repo
        self.bid_contexts = {}  # user_id -> auction_id for bidding

    # ============ KEYBOARD GENERATORS ============

    def get_admin_keyboard(self) -> ReplyKeyboardMarkup:
        """Generate admin keyboard"""
        keyboard = [
            [KeyboardButton("➕ Создать аукцион"), KeyboardButton("🏁 Завершить аукцион")],
            [KeyboardButton("📊 Статус аукционов"), KeyboardButton("📋 Отложенные аукционы")],
            [KeyboardButton("👥 Список пользователей"), KeyboardButton("✏️ Редактировать аукцион")],
            [KeyboardButton("📢 Рассылка"),]
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

    def get_cancel_keyboard(self) -> ReplyKeyboardMarkup:
        """Generate cancel keyboard"""
        keyboard = [[KeyboardButton("❌ Отмена")]]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

    def get_user_keyboard(self) -> ReplyKeyboardMarkup:
        """Generate main keyboard for regular users"""
        keyboard = [
            [KeyboardButton("🎯 Текущий аукцион"), KeyboardButton("👤 Мой профиль")],
            [KeyboardButton("📊 История"), KeyboardButton("ℹ️ Помощь")]
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

    def get_main_menu_keyboard(self) -> InlineKeyboardMarkup:
        """Generate inline menu for callbacks (deprecated, use get_user_keyboard instead)"""
        keyboard = [
            [InlineKeyboardButton("🎯 Текущий аукцион", callback_data="menu_current_auction")],
            [InlineKeyboardButton("👤 Мой профиль", callback_data="menu_profile")],
            [InlineKeyboardButton("📊 История", callback_data="menu_history"), 
             InlineKeyboardButton("ℹ️ Помощь", callback_data="menu_help")]
        ]
        return InlineKeyboardMarkup(keyboard)

    # ============ MAIN HANDLERS ============

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command - show current auction or registration"""
        user_id = update.effective_user.id
        user = await self.user_repo.get_user(user_id)
        
        if user:
            if user.is_blocked:
                await update.message.reply_text("❌ Ваш аккаунт заблокирован администратором.")
                return
                
            # User is registered, show appropriate interface
            if user.is_admin:
                keyboard = self.get_admin_keyboard()
                await update.message.reply_text(
                    f"👋 Добро пожаловать, *{user.display_name}*!\n\nВы вошли как администратор.",
                    parse_mode='Markdown', 
                    reply_markup=keyboard
                )
                # Show current auction for admin too
                await self.show_current_auction_for_admin(update, context)
            else:
                # Show current auction immediately for users
                await self.show_current_auction_for_user(update, context, user)
        else:
            # New user - show current auction with registration
            current_auction = await self.auction_service.get_current_auction()
            if current_auction:
                auction_message = await self._format_auction_message(current_auction, is_admin=False)
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Участвовать", callback_data=f"register_join_{current_auction.auction_id}")
                ]])
                
                welcome_msg = current_auction.custom_message or "🎯 *Добро пожаловать в Аукцион-бот!*\n\nДля участия в аукционе необходимо зарегистрироваться."
                
                await update.message.reply_text(welcome_msg, parse_mode='Markdown')
                
                # Send media if available
                if current_auction.photo_url:
                    await self.send_auction_media(update, current_auction, auction_message, keyboard)
                else:
                    await update.message.reply_text(auction_message, parse_mode='Markdown', reply_markup=keyboard)
            else:
                await update.message.reply_text(
                    "🎯 *Добро пожаловать в Аукцион-бот!*\n\n"
                    "Сейчас нет активных аукционов.\n"
                    "Нажмите кнопку ниже для регистрации.",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("📝 Зарегистрироваться", callback_data="register_start")
                    ]])
                )

    async def show_current_auction_for_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user):
        """Show current auction for regular user"""
        current_auction = await self.auction_service.get_current_auction()
        
        # First show user keyboard
        user_keyboard = self.get_user_keyboard()
        
        if current_auction:
            auction_message = await self._format_auction_message(current_auction, is_admin=False)
            inline_keyboard = self._get_auction_keyboard(current_auction.auction_id, user.user_id in current_auction.participants, is_admin=False)
            
            # Send welcome message with user keyboard
            await update.message.reply_text(
                f"👋 Добро пожаловать, *{user.username}*!",
                parse_mode='Markdown',
                reply_markup=user_keyboard
            )
            
            # Send media if available
            if current_auction.photo_url:
                await self.send_auction_media(update, current_auction, auction_message, inline_keyboard)
            else:
                await update.message.reply_text(auction_message, parse_mode='Markdown', reply_markup=inline_keyboard)
        else:
            # Show next scheduled auction if available
            next_auction = await self.auction_service.get_next_scheduled_auction()
            if next_auction:
                message = f"⏳ *Следующий аукцион:*\n\n" + await self._format_auction_message(next_auction, is_admin=False)
            else:
                message = "📭 Сейчас нет активных аукционов"
            
            await update.message.reply_text(
                f"👋 Добро пожаловать, *{user.username}*!\n\n{message}",
                parse_mode='Markdown',
                reply_markup=user_keyboard
            )

    async def show_current_auction_for_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show current auction status for admin"""
        current_auction = await self.auction_service.get_current_auction()
        
        if current_auction:
            auction_message = await self._format_auction_message(current_auction, is_admin=True)
            await update.message.reply_text(f"📊 *Текущий аукцион:*\n\n{auction_message}", parse_mode='Markdown')
        else:
            next_auction = await self.auction_service.get_next_scheduled_auction()
            if next_auction:
                message = f"⏳ *Следующий аукцион:*\n\n" + await self._format_auction_message(next_auction, is_admin=True)
                await update.message.reply_text(message, parse_mode='Markdown')

    async def send_auction_media(self, update: Update, auction: Auction, caption: str, keyboard: InlineKeyboardMarkup):
        """Send auction media with caption"""
        try:
            if auction.media_type == 'photo':
                await update.message.reply_photo(photo=auction.photo_url, caption=caption, parse_mode='Markdown', reply_markup=keyboard)
            elif auction.media_type == 'video':
                await update.message.reply_video(video=auction.photo_url, caption=caption, parse_mode='Markdown', reply_markup=keyboard)
            elif auction.media_type == 'animation':
                await update.message.reply_animation(animation=auction.photo_url, caption=caption, parse_mode='Markdown', reply_markup=keyboard)
            else:
                await update.message.reply_text(caption, parse_mode='Markdown', reply_markup=keyboard)
        except Exception:
            # Fallback to text if media fails
            await update.message.reply_text(caption, parse_mode='Markdown', reply_markup=keyboard)

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages from keyboards - only if not in conversation"""
        # Check if we're in a conversation state
        if context.user_data.get('state') is not None:
            # We're in a conversation, don't handle here
            return
            
        text = update.message.text
        user_id = update.effective_user.id
        user = await self.user_repo.get_user(user_id)
        
        if not user:
            await update.message.reply_text("Сначала зарегистрируйтесь командой /start")
            return
        
        if user.is_blocked:
            await update.message.reply_text("❌ Ваш аккаунт заблокирован администратором.")
            return
        
        # Handle different button presses
        if text == "➕ Создать аукцион" and user.is_admin:
            # This will be handled by ConversationHandler
            return
        elif text == "🏁 Завершить аукцион" and user.is_admin:
            await self.end_auction(update, context)
        elif text == "📊 Статус аукционов":
            await self.status(update, context)
        elif text == "📋 Отложенные аукционы" and user.is_admin:
            await self.show_scheduled_auctions(update, context)
        elif text == "👥 Список пользователей" and user.is_admin:
            await self.show_users(update, context)
        elif text == "✏️ Редактировать аукцион" and user.is_admin:
            await self.edit_auction_menu(update, context)
        elif text == "📢 Рассылка" and user.is_admin:
            # This will be handled by ConversationHandler
            return
        elif text == "🎯 Текущий аукцион" and not user.is_admin:
            await self.show_current_auction_text(update, context)
        elif text == "👤 Мой профиль" and not user.is_admin:
            await self.show_profile_text(update, context)
        elif text == "📊 История" and not user.is_admin:
            await self.show_history_text(update, context)
        elif text == "ℹ️ Помощь" and not user.is_admin:
            await self.show_help_text(update, context)
        elif text == "❌ Отмена":
            # This will be handled by ConversationHandler
            return
        else:
            if user.is_admin:
                await update.message.reply_text("Используйте кнопки меню для навигации.")
            else:
                # For regular users, remind about available buttons
                await update.message.reply_text("Используйте кнопки меню для навигации.")

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle conversation cancellation"""
        user_id = update.effective_user.id
        user = await self.user_repo.get_user(user_id)
        
        # Clear conversation state
        context.user_data.clear()
        
        if user:
            if user.is_admin:
                keyboard = self.get_admin_keyboard()
                await update.message.reply_text(
                    "❌ Операция отменена",
                    reply_markup=keyboard
                )
            else:
                user_keyboard = self.get_user_keyboard()
                await update.message.reply_text(
                    "❌ Операция отменена",
                    reply_markup=user_keyboard
                )
        else:
            await update.message.reply_text(
                "❌ Операция отменена",
                reply_markup=ReplyKeyboardRemove()
            )
        
        # Clean up bid context if exists
        if user_id in self.bid_contexts:
            del self.bid_contexts[user_id]
            
        return ConversationHandler.END

    # ============ UTILITY METHODS ============

    async def _format_auction_message(self, auction: Auction, is_admin: bool = False) -> str:
        """Format auction information message"""
        message = f"🎯 *{auction.title}*\n\n"
        
        if auction.description:
            message += f"📄 {auction.description}\n\n"
        
        message += f"💰 Текущая цена: *{auction.current_price:,.0f}₽*\n"
        
        leader = auction.current_leader
        if leader:
            # Get user display name for leader
            leader_user = await self.user_repo.get_user(leader.user_id)
            if is_admin and leader_user:
                # For admin - show full info with telegram username
                leader_name = leader_user.display_name
                if leader_user.telegram_username:
                    leader_name += f" (@{leader_user.telegram_username})"
            else:
                # For users - show only username without brackets
                leader_name = leader_user.username if leader_user else leader.username
            message += f"👤 Лидер: {leader_name}\n"
        
        message += f"👥 Участников: {len(auction.participants)}\n"
        message += f"📊 Ставок: {len(auction.bids)}\n"
        
        if auction.is_scheduled:
            if auction.time_until_start:
                message += f"⏰ Начнется через: {auction.time_until_start}\n"
            else:
                message += "⏰ Готов к запуску\n"
        elif auction.time_remaining:
            message += f"⏰ Осталось: {auction.time_remaining}\n"
        else:
            # This should not happen - all auctions should have duration
            message += "⚠️ Ошибка: время не установлено\n"
        
        return message

    def _get_auction_keyboard(self, auction_id: UUID, is_participant: bool = False, is_admin: bool = False) -> InlineKeyboardMarkup:
        """Generate auction inline keyboard"""
        keyboard = []
        
        if not is_participant:
            keyboard.append([InlineKeyboardButton("✅ Участвовать", callback_data=f"join_{auction_id}")])
        else:
            keyboard.append([InlineKeyboardButton("💸 Перебить ставку", callback_data=f"bid_{auction_id}")])
        
        # Remove "Update Status" button as requested
        
        return InlineKeyboardMarkup(keyboard)

    # ============ STATUS AND INFO HANDLERS ============

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show auction status"""
        auctions = await self.auction_repo.get_active_auctions()
        user = await self.user_repo.get_user(update.effective_user.id)
        is_admin = user and user.is_admin
        
        if not auctions:
            # Show scheduled auctions if no active ones
            scheduled = await self.auction_repo.get_scheduled_auctions()
            if scheduled:
                message = "⏳ *Следующие аукционы:*\n\n"
                for auction in scheduled[:3]:  # Show first 3
                    message += f"🎯 *{auction.title}*\n"
                    message += f"💰 Стартовая цена: {auction.start_price:,.0f}₽\n"
                    if auction.time_until_start:
                        message += f"⏰ Начнется через: {auction.time_until_start}\n"
                    message += "\n"
            else:
                message = "📭 Нет активных или запланированных аукционов"
        else:
            message = "📊 *Активные аукционы:*\n\n"
            for auction in auctions:
                message += f"🎯 *{auction.title}*\n"
                message += f"💰 Текущая цена: {auction.current_price:,.0f}₽\n"
                
                leader = auction.current_leader
                if leader:
                    # Get user display name for leader
                    leader_user = await self.user_repo.get_user(leader.user_id)
                    if is_admin and leader_user:
                        # For admin - show full info with telegram username
                        leader_name = leader_user.display_name
                        if leader_user.telegram_username:
                            leader_name += f" (@{leader_user.telegram_username})"
                    else:
                        # For users - show only username
                        leader_name = leader_user.username if leader_user else leader.username
                    message += f"👤 Лидер: {leader_name}\n"
                
                message += f"👥 Участников: {len(auction.participants)}\n"
                
                if auction.time_remaining:
                    message += f"⏰ Осталось: {auction.time_remaining}\n"
                else:
                    message += "⚠️ Ошибка: время не установлено\n"
                
                message += "\n"
        
        await update.message.reply_text(message, parse_mode='Markdown')

    async def show_scheduled_auctions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show scheduled auctions (admin only)"""
        scheduled_auctions = await self.auction_repo.get_scheduled_auctions()
        
        if not scheduled_auctions:
            await update.message.reply_text("📭 Нет отложенных аукционов")
            return
        
        message = "📋 *Отложенные аукционы:*\n\n"
        for i, auction in enumerate(scheduled_auctions, 1):
            message += f"{i}. *{auction.title}*\n"
            message += f"💰 Стартовая цена: {auction.start_price:,.0f}₽\n"
            if auction.time_until_start:
                message += f"⏰ Начнется через: {auction.time_until_start}\n"
            message += "\n"
        
        await update.message.reply_text(message, parse_mode='Markdown')

    async def end_auction(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """End auction (admin only)"""
        user = await self.user_repo.get_user(update.effective_user.id)
        if not user or not user.is_admin:
            await update.message.reply_text("❌ Только администраторы могут завершать аукционы")
            return
        
        auctions = await self.auction_repo.get_active_auctions()
        if not auctions:
            await update.message.reply_text("📭 Активных аукционов нет")
            return
        
        if len(auctions) == 1:
            success = await self.auction_service.end_auction(auctions[0].auction_id, update.effective_user.id)
            if success:
                await update.message.reply_text(f"✅ Аукцион '{auctions[0].title}' завершён")
            else:
                await update.message.reply_text("❌ Ошибка при завершении аукциона")
        else:
            # Create inline keyboard for auction selection
            keyboard = []
            for auction in auctions:
                keyboard.append([InlineKeyboardButton(
                    f"🏁 {auction.title}", 
                    callback_data=f"end_auction_{auction.auction_id}"
                )])
            keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_end")])
            
            await update.message.reply_text(
                "Выберите аукцион для завершения:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    async def edit_auction_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show edit auction menu (admin only)"""
        user = await self.user_repo.get_user(update.effective_user.id)
        if not user or not user.is_admin:
            await update.message.reply_text("❌ Только администраторы могут редактировать аукционы")
            return
        
        auctions = await self.auction_repo.get_active_auctions()
        if not auctions:
            await update.message.reply_text("📭 Нет активных аукционов для редактирования")
            return
        
        keyboard = []
        for auction in auctions:
            keyboard.append([InlineKeyboardButton(
                f"✏️ {auction.title}", 
                callback_data=f"edit_auction_{auction.auction_id}"
            )])
        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_edit")])
        
        await update.message.reply_text(
            "Выберите аукцион для редактирования:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # ============ TEXT HANDLERS FOR USERS ============

    async def show_current_auction_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show current auction for user from text button"""
        current_auction = await self.auction_service.get_current_auction()
        user_id = update.effective_user.id
        
        if current_auction:
            message = await self._format_auction_message(current_auction, is_admin=False)
            keyboard = self._get_auction_keyboard(current_auction.auction_id, user_id in current_auction.participants, is_admin=False)
            
            if current_auction.photo_url:
                await self.send_auction_media(update, current_auction, message, keyboard)
            else:
                await update.message.reply_text(message, reply_markup=keyboard, parse_mode='Markdown')
        else:
            next_auction = await self.auction_service.get_next_scheduled_auction()
            if next_auction:
                message = f"⏳ *Следующий аукцион:*\n\n" + await self._format_auction_message(next_auction, is_admin=False)
            else:
                message = "📭 Сейчас нет активных аукционов"
            
            await update.message.reply_text(message, parse_mode='Markdown')

    async def show_profile_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user profile from text button"""
        status = await self.auction_service.get_user_status(update.effective_user.id)
        
        if not status["registered"]:
            await update.message.reply_text("❌ Ошибка получения профиля")
            return
        
        user = status["user"]
        message = f"👤 *Ваш профиль*\n\n"
        message += f"Логин: {user.username}\n"
        message += f"Имя: {user.display_name}\n"
        message += f"Статус: {'👑 Администратор' if user.is_admin else '👤 Участник'}\n"
        message += f"Регистрация: {user.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
        
        if status["participating_in"]:
            message += "📊 *Участие в аукционах:*\n"
            for participation in status["participating_in"]:
                auction = participation["auction"]
                user_bid = participation["user_bid"]
                is_leader = participation["is_leader"]
                
                message += f"\n🎯 {auction.title}\n"
                if user_bid:
                    message += f"Ваша ставка: {user_bid.amount:,.0f}₽\n"
                    message += f"Статус: {'🏆 Лидер' if is_leader else '👤 Участник'}\n"
                else:
                    message += "Ставок нет\n"
        else:
            message += "Вы не участвуете в аукционах"
        
        await update.message.reply_text(message, parse_mode='Markdown')

    async def show_history_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show auction history from text button"""
        completed_auctions = await self.auction_repo.get_completed_auctions()
        
        if not completed_auctions:
            message = "📭 История аукционов пуста"
        else:
            message = "📊 *История аукционов:*\n\n"
            for auction in completed_auctions[:5]:  # Show last 5
                message += f"🎯 *{auction.title}*\n"
                message += f"💰 Итоговая цена: {auction.current_price:,.0f}₽\n"
                
                if auction.current_leader:
                    leader_user = await self.user_repo.get_user(auction.current_leader.user_id)
                    leader_name = leader_user.username if leader_user else auction.current_leader.username
                    message += f"🏆 Победитель: {leader_name}\n"
                
                message += f"📅 {auction.created_at.strftime('%d.%m.%Y')}\n\n"
        
        await update.message.reply_text(message, parse_mode='Markdown')

    async def show_help_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show help from text button"""
        message = (
            "ℹ️ *Помощь по боту*\n\n"
            "🎯 *Текущий аукцион* - показать активный аукцион\n"
            "👤 *Мой профиль* - ваша информация и статистика\n"
            "📊 *История* - прошлые аукционы\n\n"
            "Для участия в аукционе нажмите '✅ Участвовать', "
            "затем используйте '💸 Перебить ставку' для размещения ставок."
        )
        
        await update.message.reply_text(message, parse_mode='Markdown')