"""
Telegram bot handlers with inline keyboards and improved UX
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


class TelegramHandlers:
    """All Telegram bot handlers with inline keyboards"""
    
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
            [KeyboardButton("👥 Список пользователей"),]
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

    def get_cancel_keyboard(self) -> ReplyKeyboardMarkup:
        """Generate cancel keyboard"""
        keyboard = [[KeyboardButton("❌ Отмена")]]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

    def get_main_menu_keyboard(self) -> InlineKeyboardMarkup:
        """Generate main menu for users"""
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
                auction_message = await self._format_auction_message(current_auction)
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Участвовать", callback_data=f"register_join_{current_auction.auction_id}")
                ], [
                    InlineKeyboardButton("ℹ️ Обновить статус", callback_data=f"status_{current_auction.auction_id}")
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
        
        if current_auction:
            auction_message = await self._format_auction_message(current_auction)
            keyboard = self._get_auction_keyboard(current_auction.auction_id, user.user_id in current_auction.participants)
            # Create new keyboard with additional button
            new_keyboard = list(keyboard.inline_keyboard)
            new_keyboard.append([InlineKeyboardButton("📱 Главное меню", callback_data="main_menu")])
            keyboard = InlineKeyboardMarkup(new_keyboard)
            
            # Send media if available
            if current_auction.photo_url:
                await self.send_auction_media(update, current_auction, auction_message, keyboard)
            else:
                await update.message.reply_text(auction_message, parse_mode='Markdown', reply_markup=keyboard)
        else:
            # Show next scheduled auction if available
            next_auction = await self.auction_service.get_next_scheduled_auction()
            if next_auction:
                message = f"⏳ *Следующий аукцион:*\n\n" + await self._format_auction_message(next_auction)
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📱 Главное меню", callback_data="main_menu")]])
                await update.message.reply_text(message, parse_mode='Markdown', reply_markup=keyboard)
            else:
                keyboard = self.get_main_menu_keyboard()
                await update.message.reply_text("📭 Сейчас нет активных аукционов", reply_markup=keyboard)

    async def show_current_auction_for_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show current auction status for admin"""
        current_auction = await self.auction_service.get_current_auction()
        
        if current_auction:
            auction_message = await self._format_auction_message(current_auction)
            await update.message.reply_text(f"📊 *Текущий аукцион:*\n\n{auction_message}", parse_mode='Markdown')
        else:
            next_auction = await self.auction_service.get_next_scheduled_auction()
            if next_auction:
                message = f"⏳ *Следующий аукцион:*\n\n" + await self._format_auction_message(next_auction)
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
        """Handle text messages from keyboards"""
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
            await self.create_start(update, context)
        elif text == "🏁 Завершить аукцион" and user.is_admin:
            await self.end_auction(update, context)
        elif text == "📊 Статус аукционов":
            await self.status(update, context)
        elif text == "📋 Отложенные аукционы" and user.is_admin:
            await self.show_scheduled_auctions(update, context)
        elif text == "👥 Список пользователей" and user.is_admin:
            await self.show_users(update, context)
        elif text == "❌ Отмена":
            await self.cancel(update, context)
        else:
            if user.is_admin:
                await update.message.reply_text("Используйте кнопки меню для навигации.")
            else:
                # For regular users, show main menu
                keyboard = self.get_main_menu_keyboard()
                await update.message.reply_text("Выберите действие:", reply_markup=keyboard)

    # ============ CALLBACK HANDLERS ============

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle all callback queries"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user_id = update.effective_user.id
        user = await self.user_repo.get_user(user_id)
        
        if data == "main_menu":
            keyboard = self.get_main_menu_keyboard()
            try:
                await query.edit_message_text("📱 *Главное меню*\n\nВыберите действие:", parse_mode='Markdown', reply_markup=keyboard)
            except Exception:
                # If can't edit (e.g. media message), send new message
                await query.message.reply_text("📱 *Главное меню*\n\nВыберите действие:", parse_mode='Markdown', reply_markup=keyboard)
        
        elif data == "menu_current_auction":
            await self.show_current_auction_callback(query, context)
        
        elif data == "menu_profile":
            await self.show_profile_callback(query, context)
        
        elif data == "menu_history":
            await self.show_history_callback(query, context)
        
        elif data == "menu_help":
            await self.show_help_callback(query, context)
        
        elif data.startswith("register_join_"):
            auction_id = UUID(data.split('_')[2])
            context.user_data['join_auction_id'] = auction_id
            try:
                await query.edit_message_text("📝 Введите желаемый логин (только буквы, цифры и _):")
            except Exception:
                await query.message.reply_text("📝 Введите желаемый логин (только буквы, цифры и _):")
            return BotStates.REGISTER_USERNAME
        
        elif data == "register_start":
            try:
                await query.edit_message_text("📝 Введите желаемый логин (только буквы, цифры и _):")
            except Exception:
                await query.message.reply_text("📝 Введите желаемый логин (только буквы, цифры и _):")
            return BotStates.REGISTER_USERNAME
        
        elif data.startswith("join_"):
            await self.join_auction(update, context)
        
        elif data.startswith("bid_"):
            await self.bid_start(update, context)
        
        elif data.startswith("status_"):
            await self.show_status(update, context)
        
        elif data.startswith("end_auction_"):
            await self.end_auction_callback(update, context)
        
        elif data.startswith("user_"):
            await self.handle_user_action(update, context)
        
        elif data.startswith("block_") or data.startswith("unblock_"):
            await self.toggle_user_block(update, context)
        
        elif data == "cancel_end":
            try:
                await query.edit_message_text("❌ Завершение аукциона отменено")
            except Exception:
                await query.message.reply_text("❌ Завершение аукциона отменено")
        
        elif data == "back_to_users":
            # Recreate users list
            await self.show_users_callback(query, context)
        
        elif data == "cancel_users":
            try:
                await query.edit_message_text("✅ Закрыто")
            except Exception:
                await query.message.reply_text("✅ Закрыто")

    # ============ REGISTRATION HANDLERS ============

    async def register_username(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle username input"""
        # Handle callback query first (from inline buttons)
        if update.callback_query:
            query = update.callback_query
            await query.answer()
            
            # Check which callback was pressed
            if query.data.startswith("register_join_"):
                auction_id = UUID(query.data.split('_')[2])
                context.user_data['join_auction_id'] = auction_id
                await query.edit_message_text("📝 Введите желаемый логин (только буквы, цифры и _):")
                return BotStates.REGISTER_USERNAME
            elif query.data == "register_start":
                await query.edit_message_text("📝 Введите желаемый логин (только буквы, цифры и _):")
                return BotStates.REGISTER_USERNAME
        
        # Handle text message (username input)
        if not update.message or not update.message.text:
            await update.effective_message.reply_text("❌ Пожалуйста, введите текст")
            return BotStates.REGISTER_USERNAME
            
        if update.message.text == "❌ Отмена":
            return await self.cancel(update, context)
            
        username = update.message.text.strip()
        
        if not username.replace('_', '').isalnum():
            await update.message.reply_text("❌ Логин может содержать только буквы, цифры и _")
            return BotStates.REGISTER_USERNAME
        
        success = await self.auction_service.register_user(
            update.effective_user.id, 
            username,
            update.effective_user.username,
            update.effective_user.first_name,
            update.effective_user.last_name
        )
        
        if success:
            user = await self.user_repo.get_user(update.effective_user.id)
            message = f"✅ Регистрация успешна! Ваш логин: *{username}*"
            
            if user.is_admin:
                keyboard = self.get_admin_keyboard()
                message += "\n\nВы вошли как администратор."
                await update.message.reply_text(message, parse_mode='Markdown', reply_markup=keyboard)
            else:
                await update.message.reply_text(message, parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())
            
            # If joining auction after registration
            if 'join_auction_id' in context.user_data:
                auction_id = context.user_data['join_auction_id']
                await self.auction_service.join_auction(auction_id, update.effective_user.id)
                auction = await self.auction_repo.get_auction(auction_id)
                if auction:
                    auction_message = await self._format_auction_message(auction)
                    auction_keyboard = self._get_auction_keyboard(auction_id, True)
                    
                    if auction.photo_url:
                        await self.send_auction_media(update, auction, auction_message, auction_keyboard)
                    else:
                        await update.message.reply_text(auction_message, parse_mode='Markdown', reply_markup=auction_keyboard)
                del context.user_data['join_auction_id']
            else:
                # Show current auction after registration
                await self.show_current_auction_for_user(update, context, user)
        else:
            await update.message.reply_text("❌ Этот логин уже занят. Выберите другой:")
            return BotStates.REGISTER_USERNAME
        
        return ConversationHandler.END

    # ============ CALLBACK IMPLEMENTATIONS ============

    async def show_current_auction_callback(self, query, context):
        """Show current auction from callback"""
        current_auction = await self.auction_service.get_current_auction()
        user_id = query.from_user.id
        
        if current_auction:
            message = await self._format_auction_message(current_auction)
            keyboard = self._get_auction_keyboard(current_auction.auction_id, user_id in current_auction.participants)
            # Create new keyboard with additional button
            new_keyboard = list(keyboard.inline_keyboard)
            new_keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="main_menu")])
            keyboard = InlineKeyboardMarkup(new_keyboard)
            
            try:
                await query.edit_message_text(message, reply_markup=keyboard, parse_mode='Markdown')
            except Exception:
                await query.message.reply_text(message, reply_markup=keyboard, parse_mode='Markdown')
        else:
            next_auction = await self.auction_service.get_next_scheduled_auction()
            if next_auction:
                message = f"⏳ *Следующий аукцион:*\n\n" + await self._format_auction_message(next_auction)
            else:
                message = "📭 Сейчас нет активных аукционов"
            
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="main_menu")]])
            try:
                await query.edit_message_text(message, parse_mode='Markdown', reply_markup=keyboard)
            except Exception:
                await query.message.reply_text(message, parse_mode='Markdown', reply_markup=keyboard)

    async def show_profile_callback(self, query, context):
        """Show user profile from callback"""
        status = await self.auction_service.get_user_status(query.from_user.id)
        
        if not status["registered"]:
            await query.edit_message_text("❌ Ошибка получения профиля")
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
        
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="main_menu")]])
        await query.edit_message_text(message, parse_mode='Markdown', reply_markup=keyboard)

    async def show_history_callback(self, query, context):
        """Show auction history from callback"""
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
                    leader_name = leader_user.display_name if leader_user else auction.current_leader.username
                    message += f"🏆 Победитель: {leader_name}\n"
                
                message += f"📅 {auction.created_at.strftime('%d.%m.%Y')}\n\n"
        
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="main_menu")]])
        await query.edit_message_text(message, parse_mode='Markdown', reply_markup=keyboard)

    async def show_help_callback(self, query, context):
        """Show help from callback"""
        message = (
            "ℹ️ *Помощь по боту*\n\n"
            "🎯 *Текущий аукцион* - показать активный аукцион\n"
            "👤 *Мой профиль* - ваша информация и статистика\n"
            "📊 *История* - прошлые аукционы\n\n"
            "Для участия в аукционе нажмите '✅ Участвовать', "
            "затем используйте '💸 Перебить ставку' для размещения ставок."
        )
        
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="main_menu")]])
        await query.edit_message_text(message, parse_mode='Markdown', reply_markup=keyboard)

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show auction status"""
        auctions = await self.auction_repo.get_active_auctions()
        
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
                    leader_name = leader_user.display_name if leader_user else leader.username
                    message += f"👤 Лидер: {leader_name}\n"
                
                message += f"👥 Участников: {len(auction.participants)}\n"
                
                if auction.time_remaining:
                    message += f"⏰ Осталось: {auction.time_remaining}\n"
                else:
                    message += "⏰ Бессрочный\n"
                
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

    async def end_auction_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle end auction callback"""
        query = update.callback_query
        await query.answer()
        
        auction_id = UUID(query.data.split('_')[2])
        success = await self.auction_service.end_auction(auction_id, update.effective_user.id)
        
        if success:
            auction = await self.auction_repo.get_auction(auction_id)
            await query.edit_message_text(f"✅ Аукцион '{auction.title}' завершён")
        else:
            await query.edit_message_text("❌ Ошибка при завершении аукциона")

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle conversation cancellation"""
        user_id = update.effective_user.id
        user = await self.user_repo.get_user(user_id)
        
        if user:
            if user.is_admin:
                keyboard = self.get_admin_keyboard()
                await update.message.reply_text(
                    "❌ Операция отменена",
                    reply_markup=keyboard
                )
            else:
                keyboard = self.get_main_menu_keyboard()
                await update.message.reply_text(
                    "❌ Операция отменена",
                    reply_markup=keyboard
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

    async def _format_auction_message(self, auction: Auction) -> str:
        """Format auction information message"""
        message = f"🎯 *{auction.title}*\n\n"
        
        if auction.description:
            message += f"📄 {auction.description}\n\n"
        
        message += f"💰 Текущая цена: *{auction.current_price:,.0f}₽*\n"
        
        leader = auction.current_leader
        if leader:
            # Get user display name for leader
            leader_user = await self.user_repo.get_user(leader.user_id)
            leader_name = leader_user.display_name if leader_user else leader.username
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
            message += "⏰ Бессрочный\n"
        
        return message

    def _get_auction_keyboard(self, auction_id: UUID, is_participant: bool = False) -> InlineKeyboardMarkup:
        """Generate auction inline keyboard"""
        keyboard = []
        
        if not is_participant:
            keyboard.append([InlineKeyboardButton("✅ Участвовать", callback_data=f"join_{auction_id}")])
        else:
            keyboard.append([InlineKeyboardButton("💸 Перебить ставку", callback_data=f"bid_{auction_id}")])
        
        keyboard.append([InlineKeyboardButton("ℹ️ Обновить статус", callback_data=f"status_{auction_id}")])
        
        return InlineKeyboardMarkup(keyboard)

    # ============ ADMIN USER MANAGEMENT ============

    async def show_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show registered users (admin only)"""
        user = await self.user_repo.get_user(update.effective_user.id)
        if not user or not user.is_admin:
            await update.message.reply_text("❌ Только администраторы могут просматривать пользователей")
            return
        
        users = await self.user_repo.get_all_users()
        if not users:
            await update.message.reply_text("📭 Пользователей нет")
            return
        
        keyboard = []
        for user_obj in users[:10]:  # Show first 10 users
            status_emoji = "🚫" if user_obj.is_blocked else "✅"
            admin_emoji = " 👑" if user_obj.is_admin else ""
            keyboard.append([InlineKeyboardButton(
                f"{status_emoji} {user_obj.display_name}{admin_emoji}", 
                callback_data=f"user_{user_obj.user_id}"
            )])
        
        keyboard.append([InlineKeyboardButton("❌ Закрыть", callback_data="cancel_users")])
        
        await update.message.reply_text(
            f"👥 *Пользователи ({len(users)}):*\n\n"
            "✅ - активный\n🚫 - заблокированный\n👑 - администратор",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def show_users_callback(self, query, context):
        """Show users list from callback"""
        users = await self.user_repo.get_all_users()
        if not users:
            await query.edit_message_text("📭 Пользователей нет")
            return
        
        keyboard = []
        for user_obj in users[:10]:  # Show first 10 users
            status_emoji = "🚫" if user_obj.is_blocked else "✅"
            admin_emoji = " 👑" if user_obj.is_admin else ""
            keyboard.append([InlineKeyboardButton(
                f"{status_emoji} {user_obj.display_name}{admin_emoji}", 
                callback_data=f"user_{user_obj.user_id}"
            )])
        
        keyboard.append([InlineKeyboardButton("❌ Закрыть", callback_data="cancel_users")])
        
        await query.edit_message_text(
            f"👥 *Пользователи ({len(users)}):*\n\n"
            "✅ - активный\n🚫 - заблокированный\n👑 - администратор",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def handle_user_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle user action from admin panel"""
        query = update.callback_query
        await query.answer()
        
        user_id = int(query.data.split('_')[1])
        target_user = await self.user_repo.get_user(user_id)
        
        if not target_user:
            await query.edit_message_text("❌ Пользователь не найден")
            return
        
        if target_user.is_admin:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад к списку", callback_data="back_to_users")
            ]])
            await query.edit_message_text(
                f"👑 *Администратор*\n\n"
                f"👤 {target_user.display_name}\n"
                f"📅 Регистрация: {target_user.created_at.strftime('%d.%m.%Y')}\n\n"
                "⚠️ Нельзя заблокировать администратора",
                parse_mode='Markdown',
                reply_markup=keyboard
            )
            return
        
        block_text = "🔓 Разблокировать" if target_user.is_blocked else "🚫 Заблокировать"
        block_action = f"unblock_{user_id}" if target_user.is_blocked else f"block_{user_id}"
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(block_text, callback_data=block_action)],
            [InlineKeyboardButton("◀️ Назад к списку", callback_data="back_to_users")]
        ])
        
        status = "🚫 Заблокирован" if target_user.is_blocked else "✅ Активен"
        
        await query.edit_message_text(
            f"👤 *Пользователь*\n\n"
            f"Имя: {target_user.display_name}\n"
            f"Статус: {status}\n"
            f"Регистрация: {target_user.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
            "Выберите действие:",
            parse_mode='Markdown',
            reply_markup=keyboard
        )

    async def toggle_user_block(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Toggle user block status"""
        query = update.callback_query
        await query.answer()
        
        action, user_id = query.data.split('_')
        user_id = int(user_id)
        is_blocking = action == "block"
        
        target_user = await self.user_repo.get_user(user_id)
        if not target_user or target_user.is_admin:
            await query.edit_message_text("❌ Ошибка: пользователь не найден или является администратором")
            return
        
        await self.user_repo.update_user_status(user_id, is_blocking)
        
        action_text = "заблокирован" if is_blocking else "разблокирован"
        await query.edit_message_text(
            f"✅ Пользователь {target_user.display_name} {action_text}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад к списку", callback_data="back_to_users")
            ]])
        )

    # ============ AUCTION CREATION HANDLERS ============

    async def create_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start auction creation"""
        user = await self.user_repo.get_user(update.effective_user.id)
        if not user or not user.is_admin:
            await update.message.reply_text("❌ Только администраторы могут создавать аукционы")
            return ConversationHandler.END
        
        await update.message.reply_text(
            "📝 *Создание аукциона*\n\nВведите название лота:",
            parse_mode='Markdown',
            reply_markup=self.get_cancel_keyboard()
        )
        return BotStates.CREATE_TITLE

    async def create_title(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle auction title input"""
        if update.message.text == "❌ Отмена":
            return await self.cancel(update, context)
            
        title = update.message.text.strip()
        context.user_data['auction_title'] = title
        await update.message.reply_text(
            "💰 Введите стартовую цену (в рублях):",
            reply_markup=self.get_cancel_keyboard()
        )
        return BotStates.CREATE_START_PRICE

    async def create_start_price(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle start price input"""
        if update.message.text == "❌ Отмена":
            return await self.cancel(update, context)
            
        try:
            price = float(update.message.text.strip())
            if price <= 0:
                raise ValueError()
            context.user_data['start_price'] = price
            await update.message.reply_text(
                "⏰ Введите длительность аукциона в часах (или 0 для бесконечного):",
                reply_markup=self.get_cancel_keyboard()
            )
            return BotStates.CREATE_DURATION
        except ValueError:
            await update.message.reply_text("❌ Введите корректную цену")
            return BotStates.CREATE_START_PRICE

    async def create_duration(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle duration input"""
        if update.message.text == "❌ Отмена":
            return await self.cancel(update, context)
            
        try:
            duration = int(update.message.text.strip())
            if duration < 0:
                raise ValueError()
            context.user_data['duration'] = duration
            await update.message.reply_text(
                "📄 Введите описание лота (или 'пропустить'):",
                reply_markup=self.get_cancel_keyboard()
            )
            return BotStates.CREATE_DESCRIPTION
        except ValueError:
            await update.message.reply_text("❌ Введите корректное количество часов")
            return BotStates.CREATE_DURATION

    async def create_description(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle description input"""
        if update.message.text == "❌ Отмена":
            return await self.cancel(update, context)
            
        description = update.message.text.strip()
        if description.lower() != 'пропустить':
            context.user_data['description'] = description
        
        await update.message.reply_text(
            "🖼️ Отправьте медиа-файл (фото, видео, GIF) или напишите 'пропустить':",
            reply_markup=self.get_cancel_keyboard()
        )
        return BotStates.CREATE_MEDIA

    async def create_media(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle media input"""
        if update.message.text == "❌ Отмена":
            return await self.cancel(update, context)
        
        if update.message.text and update.message.text.lower() == 'пропустить':
            # No media
            pass
        elif update.message.photo:
            # Photo
            photo = update.message.photo[-1]  # Get highest resolution
            context.user_data['photo_url'] = photo.file_id
            context.user_data['media_type'] = 'photo'
        elif update.message.video:
            # Video
            context.user_data['photo_url'] = update.message.video.file_id
            context.user_data['media_type'] = 'video'
        elif update.message.animation:
            # GIF
            context.user_data['photo_url'] = update.message.animation.file_id
            context.user_data['media_type'] = 'animation'
        else:
            await update.message.reply_text(
                "❌ Пожалуйста, отправьте фото, видео, GIF или напишите 'пропустить'"
            )
            return BotStates.CREATE_MEDIA
        
        await update.message.reply_text(
            "💬 Введите приветственное сообщение для аукциона (или 'пропустить' для стандартного):",
            reply_markup=self.get_cancel_keyboard()
        )
        return BotStates.CREATE_CUSTOM_MESSAGE

    async def create_custom_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle custom message input and create auction"""
        if update.message.text == "❌ Отмена":
            return await self.cancel(update, context)
            
        custom_message = update.message.text.strip()
        if custom_message.lower() != 'пропустить':
            context.user_data['custom_message'] = custom_message
        
        # Create auction
        auction_id = await self.auction_service.create_auction(
            creator_id=update.effective_user.id,
            title=context.user_data['auction_title'],
            start_price=context.user_data['start_price'],
            duration_hours=context.user_data['duration'],
            description=context.user_data.get('description'),
            photo_url=context.user_data.get('photo_url'),
            media_type=context.user_data.get('media_type', 'photo'),
            custom_message=context.user_data.get('custom_message')
        )
        
        # Get created auction
        auction = await self.auction_repo.get_auction(auction_id)
        
        # Check if it's active or scheduled
        if auction.status == AuctionStatus.ACTIVE:
            await update.message.reply_text(
                "✅ Аукцион создан и запущен!",
                reply_markup=self.get_admin_keyboard()
            )
            
            # Broadcast to all users
            await self.broadcast_new_auction(auction)
        else:
            await update.message.reply_text(
                "✅ Аукцион создан и добавлен в очередь!",
                reply_markup=self.get_admin_keyboard()
            )
        
        return ConversationHandler.END

    async def broadcast_new_auction(self, auction: Auction):
        """Broadcast new auction to all users"""
        all_users = await self.user_repo.get_all_users()
        
        for user in all_users:
            if user.is_blocked or user.is_admin:
                continue
                
            try:
                welcome_msg = auction.custom_message or "🎉 *Новый аукцион начался!*"
                auction_message = await self._format_auction_message(auction)
                keyboard = self._get_auction_keyboard(auction.auction_id, user.user_id in auction.participants)
                
                await self.auction_service.notification_service.application.bot.send_message(
                    chat_id=user.user_id,
                    text=welcome_msg,
                    parse_mode='Markdown'
                )
                
                if auction.photo_url:
                    if auction.media_type == 'photo':
                        await self.auction_service.notification_service.application.bot.send_photo(
                            chat_id=user.user_id,
                            photo=auction.photo_url,
                            caption=auction_message,
                            parse_mode='Markdown',
                            reply_markup=keyboard
                        )
                    elif auction.media_type == 'video':
                        await self.auction_service.notification_service.application.bot.send_video(
                            chat_id=user.user_id,
                            video=auction.photo_url,
                            caption=auction_message,
                            parse_mode='Markdown',
                            reply_markup=keyboard
                        )
                    elif auction.media_type == 'animation':
                        await self.auction_service.notification_service.application.bot.send_animation(
                            chat_id=user.user_id,
                            animation=auction.photo_url,
                            caption=auction_message,
                            parse_mode='Markdown',
                            reply_markup=keyboard
                        )
                else:
                    await self.auction_service.notification_service.application.bot.send_message(
                        chat_id=user.user_id,
                        text=auction_message,
                        parse_mode='Markdown',
                        reply_markup=keyboard
                    )
            except Exception as e:
                # Log error but continue with other users
                pass

    # ============ BIDDING HANDLERS ============

    async def bid_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start bidding process"""
        query = update.callback_query
        await query.answer()
        
        auction_id = UUID(query.data.split('_')[1])
        user_id = update.effective_user.id
        
        user = await self.user_repo.get_user(user_id)
        if user and user.is_blocked:
            try:
                await query.edit_message_text("❌ Ваш аккаунт заблокирован и вы не можете участвовать в аукционах")
            except Exception:
                await query.message.reply_text("❌ Ваш аккаунт заблокирован и вы не можете участвовать в аукционах")
            return ConversationHandler.END
        
        auction = await self.auction_repo.get_auction(auction_id)
        if not auction or not auction.is_active:
            try:
                await query.edit_message_text("❌ Аукцион неактивен")
            except Exception:
                await query.message.reply_text("❌ Аукцион неактивен")
            return ConversationHandler.END
        
        if user_id not in auction.participants:
            try:
                await query.edit_message_text("❌ Сначала присоединитесь к аукциону")
            except Exception:
                await query.message.reply_text("❌ Сначала присоединитесь к аукциону")
            return ConversationHandler.END
        
        self.bid_contexts[user_id] = auction_id
        bid_message = (
            f"💸 Текущая ставка: *{auction.current_price:,.0f}₽*\n\n"
            f"Введите вашу ставку (больше {auction.current_price:,.0f}₽):"
        )
        
        try:
            await query.edit_message_text(bid_message, parse_mode='Markdown')
        except Exception:
            # If can't edit (media message), send new message
            await query.message.reply_text(bid_message, parse_mode='Markdown')
        
        return BotStates.PLACE_BID

    async def place_bid(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle bid amount input"""
        if update.message.text == "❌ Отмена":
            user_id = update.effective_user.id
            if user_id in self.bid_contexts:
                del self.bid_contexts[user_id]
            return await self.cancel(update, context)
            
        try:
            amount = float(update.message.text.strip())
            user_id = update.effective_user.id
            auction_id = self.bid_contexts.get(user_id)
            
            if not auction_id:
                await update.message.reply_text("❌ Ошибка: контекст ставки потерян")
                return ConversationHandler.END
            
            success = await self.auction_service.place_bid(auction_id, user_id, amount)
            if success:
                await update.message.reply_text(f"✅ Ставка {amount:,.0f}₽ принята!")
                
                # Show updated auction
                auction = await self.auction_repo.get_auction(auction_id)
                if auction:
                    message = await self._format_auction_message(auction)
                    keyboard = self._get_auction_keyboard(auction_id, True)
                    # Create new keyboard with additional button
                    new_keyboard = list(keyboard.inline_keyboard)
                    new_keyboard.append([InlineKeyboardButton("📱 Главное меню", callback_data="main_menu")])
                    keyboard = InlineKeyboardMarkup(new_keyboard)
                    
                    if auction.photo_url:
                        await self.send_auction_media(update, auction, message, keyboard)
                    else:
                        await update.message.reply_text(message, reply_markup=keyboard, parse_mode='Markdown')
            else:
                auction = await self.auction_repo.get_auction(auction_id)
                await update.message.reply_text(
                    f"❌ Ставка должна быть больше {auction.current_price:,.0f}₽"
                )
                return BotStates.PLACE_BID
            
        except ValueError:
            await update.message.reply_text("❌ Введите корректную сумму")
            return BotStates.PLACE_BID
        
        finally:
            user_id = update.effective_user.id
            if user_id in self.bid_contexts:
                del self.bid_contexts[user_id]
        
        return ConversationHandler.END

    # ============ MORE CALLBACK HANDLERS ============

    async def join_auction(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle join auction button"""
        query = update.callback_query
        await query.answer()
        
        auction_id = UUID(query.data.split('_')[1])
        user_id = update.effective_user.id
        
        user = await self.user_repo.get_user(user_id)
        if not user:
            try:
                await query.edit_message_text("❌ Сначала зарегистрируйтесь командой /start")
            except Exception:
                await query.message.reply_text("❌ Сначала зарегистрируйтесь командой /start")
            return
        
        if user.is_blocked:
            try:
                await query.edit_message_text("❌ Ваш аккаунт заблокирован и вы не можете участвовать в аукционах")
            except Exception:
                await query.message.reply_text("❌ Ваш аккаунт заблокирован и вы не можете участвовать в аукционах")
            return
        
        success = await self.auction_service.join_auction(auction_id, user_id)
        if success:
            auction = await self.auction_repo.get_auction(auction_id)
            message = await self._format_auction_message(auction)
            keyboard = self._get_auction_keyboard(auction_id, user_id in auction.participants)
            # Create new keyboard with additional button
            new_keyboard = list(keyboard.inline_keyboard)
            new_keyboard.append([InlineKeyboardButton("📱 Главное меню", callback_data="main_menu")])
            keyboard = InlineKeyboardMarkup(new_keyboard)
            
            try:
                await query.edit_message_text(message, reply_markup=keyboard, parse_mode='Markdown')
            except Exception:
                # If can't edit (media message), send new message
                await query.message.reply_text(message, reply_markup=keyboard, parse_mode='Markdown')
        else:
            try:
                await query.edit_message_text("❌ Не удалось присоединиться к аукциону")
            except Exception:
                await query.message.reply_text("❌ Не удалось присоединиться к аукциону")

    async def show_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle status button"""
        query = update.callback_query
        await query.answer()
        
        auction_id = UUID(query.data.split('_')[1])
        auction = await self.auction_repo.get_auction(auction_id)
        
        if not auction:
            try:
                await query.edit_message_text("❌ Аукцион не найден")
            except Exception:
                await query.message.reply_text("❌ Аукцион не найден")
            return
        
        message = await self._format_auction_message(auction)
        keyboard = self._get_auction_keyboard(auction_id, update.effective_user.id in auction.participants)
        # Create new keyboard with additional button
        new_keyboard = list(keyboard.inline_keyboard)
        new_keyboard.append([InlineKeyboardButton("📱 Главное меню", callback_data="main_menu")])
        keyboard = InlineKeyboardMarkup(new_keyboard)
        
        try:
            await query.edit_message_text(message, reply_markup=keyboard, parse_mode='Markdown')
        except Exception:
            # If can't edit (media message), send new message
            await query.message.reply_text(message, reply_markup=keyboard, parse_mode='Markdown')