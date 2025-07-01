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
    CREATE_INITIAL_LEADER = 6
    PLACE_BID = 7
    ADMIN_ACTION = 8


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
            [KeyboardButton("👥 Список пользователей"), KeyboardButton("⚙️ Настройки")]
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

    def get_user_keyboard(self) -> ReplyKeyboardMarkup:
        """Generate user keyboard"""
        keyboard = [
            [KeyboardButton("🎯 Текущий аукцион"), KeyboardButton("👤 Мой профиль")],
            [KeyboardButton("📊 История"), KeyboardButton("ℹ️ Помощь")]
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

    def get_cancel_keyboard(self) -> ReplyKeyboardMarkup:
        """Generate cancel keyboard"""
        keyboard = [[KeyboardButton("❌ Отмена")]]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

    # ============ MAIN HANDLERS ============

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command - show current auction or registration"""
        user_id = update.effective_user.id
        user = await self.user_repo.get_user(user_id)
        
        if user:
            # User is registered, show appropriate interface
            if user.is_admin:
                keyboard = self.get_admin_keyboard()
                message = f"👋 Добро пожаловать, *{user.display_name}*!\n\nВы вошли как администратор."
            else:
                keyboard = self.get_user_keyboard()
                message = f"👋 Добро пожаловать, *{user.display_name}*!"
                
                # Show current auction if available
                current_auction = await self.auction_service.get_current_auction()
                if current_auction:
                    auction_message = self._format_auction_message(current_auction)
                    auction_keyboard = self._get_auction_keyboard(current_auction.auction_id, user_id in current_auction.participants)
                    
                    await update.message.reply_text(message, parse_mode='Markdown', reply_markup=keyboard)
                    await update.message.reply_text(auction_message, parse_mode='Markdown', reply_markup=auction_keyboard)
                    return
            
            await update.message.reply_text(message, parse_mode='Markdown', reply_markup=keyboard)
        else:
            # New user - show current auction with registration
            current_auction = await self.auction_service.get_current_auction()
            if current_auction:
                auction_message = self._format_auction_message(current_auction)
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Участвовать", callback_data=f"register_join_{current_auction.auction_id}")
                ], [
                    InlineKeyboardButton("ℹ️ Обновить статус", callback_data=f"status_{current_auction.auction_id}")
                ]])
                
                await update.message.reply_text(
                    "🎯 *Добро пожаловать в Аукцион-бот!*\n\n"
                    "Для участия в аукционе необходимо зарегистрироваться.",
                    parse_mode='Markdown'
                )
                await update.message.reply_text(auction_message, parse_mode='Markdown', reply_markup=keyboard)
            else:
                await update.message.reply_text(
                    "🎯 *Добро пожаловать в Аукцион-бот!*\n\n"
                    "Сейчас нет активных аукционов.\n"
                    "Нажмите /register для регистрации.",
                    parse_mode='Markdown'
                )

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages from keyboards"""
        text = update.message.text
        user_id = update.effective_user.id
        user = await self.user_repo.get_user(user_id)
        
        if not user:
            await update.message.reply_text("Сначала зарегистрируйтесь командой /start")
            return
        
        # Handle different button presses
        if text == "🎯 Текущий аукцион":
            await self.show_current_auction(update, context)
        elif text == "👤 Мой профиль":
            await self.me(update, context)
        elif text == "➕ Создать аукцион" and user.is_admin:
            await self.create_start(update, context)
        elif text == "🏁 Завершить аукцион" and user.is_admin:
            await self.end_auction(update, context)
        elif text == "📊 Статус аукционов":
            await self.status(update, context)
        elif text == "📋 Отложенные аукционы" and user.is_admin:
            await self.show_scheduled_auctions(update, context)
        elif text == "👥 Список пользователей" and user.is_admin:
            await self.show_users(update, context)
        elif text == "ℹ️ Помощь":
            await self.show_help(update, context)
        elif text == "❌ Отмена":
            await self.cancel(update, context)
        else:
            await update.message.reply_text("Используйте кнопки меню для навигации.")

    async def show_current_auction(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show current active auction"""
        current_auction = await self.auction_service.get_current_auction()
        user_id = update.effective_user.id
        
        if current_auction:
            message = self._format_auction_message(current_auction)
            keyboard = self._get_auction_keyboard(current_auction.auction_id, user_id in current_auction.participants)
            await update.message.reply_text(message, reply_markup=keyboard, parse_mode='Markdown')
        else:
            # Show next scheduled auction if available
            next_auction = await self.auction_service.get_next_scheduled_auction()
            if next_auction:
                message = f"⏳ *Следующий аукцион:*\n\n" + self._format_auction_message(next_auction)
                await update.message.reply_text(message, parse_mode='Markdown')
            else:
                await update.message.reply_text("📭 Сейчас нет активных аукционов")

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

    async def show_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show registered users count (admin only)"""
        # This would require a method to get all users from repository
        await update.message.reply_text("👥 Функция в разработке")

    async def show_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show help information"""
        await update.message.reply_text(
            "ℹ️ *Помощь по боту*\n\n"
            "🎯 *Текущий аукцион* - показать активный аукцион\n"
            "👤 *Мой профиль* - ваша информация и статистика\n"
            "📊 *История* - ваши прошлые участия\n\n"
            "Для участия в аукционе нажмите '✅ Участвовать', "
            "затем используйте '💸 Перебить ставку' для размещения ставок.",
            parse_mode='Markdown'
        )

    # ============ REGISTRATION HANDLERS ============

    async def register_and_join(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle registration + join auction callback"""
        query = update.callback_query
        await query.answer()
        
        auction_id = UUID(query.data.split('_')[2])
        user_id = update.effective_user.id
        
        # Store auction ID for after registration
        context.user_data['join_auction_id'] = auction_id
        
        await query.edit_message_text("Введите желаемый логин (только буквы, цифры и _):")
    async def register_username(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle username input"""
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
            if user.is_admin:
                keyboard = self.get_admin_keyboard()
                message = f"✅ Регистрация успешна! Ваш логин: *{username}*\n\nВы вошли как администратор."
            else:
                keyboard = self.get_user_keyboard()
                message = f"✅ Регистрация успешна! Ваш логин: *{username}*"
            
            await update.message.reply_text(message, parse_mode='Markdown', reply_markup=keyboard)
            
            # If joining auction after registration
            if 'join_auction_id' in context.user_data:
                auction_id = context.user_data['join_auction_id']
                await self.auction_service.join_auction(auction_id, update.effective_user.id)
                auction = await self.auction_repo.get_auction(auction_id)
                if auction:
                    auction_message = self._format_auction_message(auction)
                    auction_keyboard = self._get_auction_keyboard(auction_id, True)
                    await update.message.reply_text(auction_message, parse_mode='Markdown', reply_markup=auction_keyboard)
                del context.user_data['join_auction_id']
        else:
            await update.message.reply_text("❌ Этот логин уже занят. Выберите другой:")
            return BotStates.REGISTER_USERNAME
        
        return ConversationHandler.END

    async def register_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start registration process"""
        user = await self.user_repo.get_user(update.effective_user.id)
        if user:
            await update.message.reply_text(f"Вы уже зарегистрированы как *{user.username}*", parse_mode='Markdown')
            return ConversationHandler.END
        
        await update.message.reply_text(
            "Введите желаемый логин (только буквы, цифры и _):",
            reply_markup=self.get_cancel_keyboard()
        )
        return BotStates.REGISTER_USERNAME

    async def register_username(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle username input"""
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
            if user.is_admin:
                keyboard = self.get_admin_keyboard()
                message = f"✅ Регистрация успешна! Ваш логин: *{username}*\n\nВы вошли как администратор."
            else:
                keyboard = self.get_user_keyboard()
                message = f"✅ Регистрация успешна! Ваш логин: *{username}*"
            
            await update.message.reply_text(message, parse_mode='Markdown', reply_markup=keyboard)
            
            # If joining auction after registration
            if 'join_auction_id' in context.user_data:
                auction_id = context.user_data['join_auction_id']
                await self.auction_service.join_auction(auction_id, update.effective_user.id)
                auction = await self.auction_repo.get_auction(auction_id)
                if auction:
                    auction_message = self._format_auction_message(auction)
                    auction_keyboard = self._get_auction_keyboard(auction_id, True)
                    await update.message.reply_text(auction_message, parse_mode='Markdown', reply_markup=auction_keyboard)
                del context.user_data['join_auction_id']
        else:
            await update.message.reply_text("❌ Этот логин уже занят. Выберите другой:")
            return BotStates.REGISTER_USERNAME
        
        return ConversationHandler.END

    async def me(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user profile"""
        status = await self.auction_service.get_user_status(update.effective_user.id)
        
        if not status["registered"]:
            await update.message.reply_text("❌ Вы не зарегистрированы. Используйте /start")
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
                elif auction.initial_leader_username:
                    message += f"👤 Лидер: {auction.initial_leader_username}\n"
                
                message += f"👥 Участников: {len(auction.participants)}\n"
                
                if auction.time_remaining:
                    message += f"⏰ Осталось: {auction.time_remaining}\n"
                else:
                    message += "⏰ Бессрочный\n"
                
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

    # ============ AUCTION CREATION HANDLERS ============

    async def create_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start auction creation"""
        user = await self.user_repo.get_user(update.effective_user.id)
        if not user or not user.is_admin:
            await update.message.reply_text("❌ Только администраторы могут создавать аукционы")
            return ConversationHandler.END
        
        await update.message.reply_text(
            "📝 Введите название лота:",
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
            "👤 Введите логин стартового лидера (или 'пропустить'):",
            reply_markup=self.get_cancel_keyboard()
        )
        return BotStates.CREATE_INITIAL_LEADER

    async def create_initial_leader(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle initial leader input and create auction"""
        if update.message.text == "❌ Отмена":
            return await self.cancel(update, context)
            
        initial_leader = update.message.text.strip()
        if initial_leader.lower() != 'пропустить':
            context.user_data['initial_leader'] = initial_leader
        
        # Create auction
        auction_id = await self.auction_service.create_auction(
            creator_id=update.effective_user.id,
            title=context.user_data['auction_title'],
            start_price=context.user_data['start_price'],
            duration_hours=context.user_data['duration'],
            description=context.user_data.get('description'),
            initial_leader_username=context.user_data.get('initial_leader')
        )
        
        # Get created auction
        auction = await self.auction_repo.get_auction(auction_id)
        
        # Check if it's active or scheduled
        if auction.status == AuctionStatus.ACTIVE:
            # Send auction message to all users
            message = f"🎉 *Новый аукцион!*\n\n" + self._format_auction_message(auction)
            keyboard = self._get_auction_keyboard(auction_id)
            
            await update.message.reply_text(
                "✅ Аукцион создан и запущен!",
                reply_markup=self.get_admin_keyboard()
            )
            await update.message.reply_text(message, reply_markup=keyboard, parse_mode='Markdown')
        else:
            # Scheduled auction
            message = f"⏳ *Аукцион запланирован*\n\n" + self._format_auction_message(auction)
            await update.message.reply_text(
                "✅ Аукцион создан и добавлен в очередь!",
                reply_markup=self.get_admin_keyboard()
            )
            await update.message.reply_text(message, parse_mode='Markdown')
        
        return ConversationHandler.END

    # ============ BIDDING HANDLERS ============

    async def bid_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start bidding process"""
        query = update.callback_query
        await query.answer()
        
        auction_id = UUID(query.data.split('_')[1])
        user_id = update.effective_user.id
        
        auction = await self.auction_repo.get_auction(auction_id)
        if not auction or not auction.is_active:
            await query.edit_message_text("❌ Аукцион неактивен")
            return ConversationHandler.END
        
        if user_id not in auction.participants:
            await query.edit_message_text("❌ Сначала присоединитесь к аукциону")
            return ConversationHandler.END
        
        self.bid_contexts[user_id] = auction_id
        await query.edit_message_text(
            f"💸 Текущая ставка: *{auction.current_price:,.0f}₽*\n\n"
            f"Введите вашу ставку (больше {auction.current_price:,.0f}₽):",
            parse_mode='Markdown'
        )
        return BotStates.PLACE_BID

    async def place_bid(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle bid amount input"""
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
                    message = self._format_auction_message(auction)
                    keyboard = self._get_auction_keyboard(auction_id, True)
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
            if user_id in self.bid_contexts:
                del self.bid_contexts[user_id]
        
        return ConversationHandler.END

    # ============ CALLBACK HANDLERS ============

    async def join_auction(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle join auction button"""
        query = update.callback_query
        await query.answer()
        
        auction_id = UUID(query.data.split('_')[1])
        user_id = update.effective_user.id
        
        user = await self.user_repo.get_user(user_id)
        if not user:
            await query.edit_message_text("❌ Сначала зарегистрируйтесь командой /start")
            return
        
        success = await self.auction_service.join_auction(auction_id, user_id)
        if success:
            auction = await self.auction_repo.get_auction(auction_id)
            message = self._format_auction_message(auction)
            keyboard = self._get_auction_keyboard(auction_id, user_id in auction.participants)
            await query.edit_message_text(message, reply_markup=keyboard, parse_mode='Markdown')
        else:
            await query.edit_message_text("❌ Не удалось присоединиться к аукциону")

    async def show_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle status button"""
        query = update.callback_query
        await query.answer()
        
        auction_id = UUID(query.data.split('_')[1])
        auction = await self.auction_repo.get_auction(auction_id)
        
        if not auction:
            await query.edit_message_text("❌ Аукцион не найден")
            return
        
        message = self._format_auction_message(auction)
        keyboard = self._get_auction_keyboard(auction_id, update.effective_user.id in auction.participants)
        await query.edit_message_text(message, reply_markup=keyboard, parse_mode='Markdown')

    async def end_auction_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle end auction callback"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "cancel_end":
            await query.edit_message_text("❌ Завершение аукциона отменено")
            return
        
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
            keyboard = self.get_admin_keyboard() if user.is_admin else self.get_user_keyboard()
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

    def _format_auction_message(self, auction: Auction) -> str:
        """Format auction information message"""
        message = f"🎯 *{auction.title}*\n\n"
        
        if auction.description:
            message += f"📄 {auction.description}\n\n"
        
        message += f"💰 Текущая цена: *{auction.current_price:,.0f}₽*\n"
        
        leader = auction.current_leader
        if leader:
            message += f"👤 Лидер: {leader.username}\n"
        elif auction.initial_leader_username:
            message += f"👤 Лидер: {auction.initial_leader_username}\n"
        
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