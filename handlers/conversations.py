"""
Conversation handlers for auction bot
"""

from uuid import UUID
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler

from domain import Auction, AuctionStatus

# Import base handlers with relative import
try:
    from .base import BaseHandlers, BotStates
except ImportError:
    from base import BaseHandlers, BotStates


class ConversationHandlers(BaseHandlers):
    """Handlers for conversations (registration, auction creation, bidding, editing, broadcasting)"""

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
                context.user_data['state'] = BotStates.REGISTER_USERNAME
                await query.edit_message_text("📝 Введите желаемый логин (только буквы, цифры и _):")
                return BotStates.REGISTER_USERNAME
            elif query.data == "register_start":
                context.user_data['state'] = BotStates.REGISTER_USERNAME
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
                    # Show user keyboard first
                    user_keyboard = self.get_user_keyboard()
                    await update.message.reply_text(
                        "🎯 Добро пожаловать в аукцион!",
                        reply_markup=user_keyboard
                    )
                    
                    auction_message = await self._format_auction_message(auction, is_admin=False)
                    auction_keyboard = self._get_auction_keyboard(auction_id, True, is_admin=False)
                    
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
        
        # Clear state
        context.user_data.clear()
        return ConversationHandler.END

    # ============ BROADCAST HANDLERS ============

    async def broadcast_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start broadcast message creation"""
        user = await self.user_repo.get_user(update.effective_user.id)
        if not user or not user.is_admin:
            await update.message.reply_text("❌ Только администраторы могут отправлять рассылки")
            return ConversationHandler.END
        
        context.user_data['state'] = BotStates.BROADCAST_MESSAGE
        await update.message.reply_text(
            "📢 *Создание рассылки*\n\nВведите сообщение для отправки всем пользователям:",
            parse_mode='Markdown',
            reply_markup=self.get_cancel_keyboard()
        )
        return BotStates.BROADCAST_MESSAGE

    async def broadcast_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle broadcast message input"""
        if update.message.text == "❌ Отмена":
            return await self.cancel(update, context)
            
        message = update.message.text.strip()
        
        # Send broadcast
        success_count = await self.send_broadcast(message)
        
        await update.message.reply_text(
            f"✅ Рассылка отправлена {success_count} пользователям",
            reply_markup=self.get_admin_keyboard()
        )
        
        # Clear state
        context.user_data.clear()
        return ConversationHandler.END

    async def send_broadcast(self, message: str) -> int:
        """Send broadcast message to all users"""
        all_users = await self.user_repo.get_all_users()
        success_count = 0
        
        for user in all_users:
            if user.is_blocked or user.is_admin:
                continue
                
            try:
                await self.auction_service.notification_service.application.bot.send_message(
                    chat_id=user.user_id,
                    text=f"📢 *Сообщение от администратора:*\n\n{message}",
                    parse_mode='Markdown'
                )
                success_count += 1
            except Exception:
                # Log error but continue with other users
                pass
        
        return success_count

    # ============ EDIT AUCTION HANDLERS ============

    async def edit_auction_select(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle auction selection for editing"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "cancel_edit":
            await query.edit_message_text("❌ Редактирование отменено")
            return
        
        auction_id = UUID(query.data.split('_')[2])
        auction = await self.auction_repo.get_auction(auction_id)
        
        if not auction:
            await query.edit_message_text("❌ Аукцион не найден")
            return
        
        # Show edit options
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Название", callback_data=f"edit_title_{auction_id}")],
            [InlineKeyboardButton("📄 Описание", callback_data=f"edit_description_{auction_id}")],
            [InlineKeyboardButton("💰 Стартовая цена", callback_data=f"edit_price_{auction_id}")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_edit")]
        ])
        
        await query.edit_message_text(
            f"✏️ *Редактирование аукциона:*\n\n"
            f"🎯 {auction.title}\n"
            f"📄 {auction.description or 'Без описания'}\n"
            f"💰 Стартовая цена: {auction.start_price:,.0f}₽\n\n"
            f"Выберите что изменить:",
            parse_mode='Markdown',
            reply_markup=keyboard
        )

    async def edit_title_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start editing auction title"""
        query = update.callback_query
        await query.answer()
        
        auction_id = UUID(query.data.split('_')[2])
        context.user_data['edit_auction_id'] = auction_id
        context.user_data['state'] = BotStates.EDIT_AUCTION_TITLE
        
        await query.edit_message_text("✏️ Введите новое название аукциона:")
        return BotStates.EDIT_AUCTION_TITLE

    async def edit_title_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle title edit input"""
        if update.message.text == "❌ Отмена":
            return await self.cancel(update, context)
            
        new_title = update.message.text.strip()
        auction_id = context.user_data['edit_auction_id']
        
        success = await self.auction_service.edit_auction_title(auction_id, new_title)
        
        if success:
            await update.message.reply_text(
                f"✅ Название изменено на: *{new_title}*",
                parse_mode='Markdown',
                reply_markup=self.get_admin_keyboard()
            )
            
            # Notify all participants about the change
            await self.notify_auction_edited(auction_id, f"Название изменено на: {new_title}")
        else:
            await update.message.reply_text(
                "❌ Ошибка при изменении названия",
                reply_markup=self.get_admin_keyboard()
            )
        
        context.user_data.clear()
        return ConversationHandler.END

    async def edit_description_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start editing auction description"""
        query = update.callback_query
        await query.answer()
        
        auction_id = UUID(query.data.split('_')[2])
        context.user_data['edit_auction_id'] = auction_id
        context.user_data['state'] = BotStates.EDIT_AUCTION_DESCRIPTION
        
        await query.edit_message_text("📄 Введите новое описание аукциона:")
        return BotStates.EDIT_AUCTION_DESCRIPTION

    async def edit_description_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle description edit input"""
        if update.message.text == "❌ Отмена":
            return await self.cancel(update, context)
            
        new_description = update.message.text.strip()
        auction_id = context.user_data['edit_auction_id']
        
        success = await self.auction_service.edit_auction_description(auction_id, new_description)
        
        if success:
            await update.message.reply_text(
                f"✅ Описание изменено",
                reply_markup=self.get_admin_keyboard()
            )
            
            # Notify all participants about the change
            await self.notify_auction_edited(auction_id, f"Описание обновлено")
        else:
            await update.message.reply_text(
                "❌ Ошибка при изменении описания",
                reply_markup=self.get_admin_keyboard()
            )
        
        context.user_data.clear()
        return ConversationHandler.END

    async def edit_price_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start editing auction start price"""
        query = update.callback_query
        await query.answer()
        
        auction_id = UUID(query.data.split('_')[2])
        auction = await self.auction_repo.get_auction(auction_id)
        
        if auction and auction.bids:
            await query.edit_message_text("❌ Нельзя изменить стартовую цену после размещения ставок")
            return
        
        context.user_data['edit_auction_id'] = auction_id
        context.user_data['state'] = BotStates.EDIT_AUCTION_PRICE
        
        await query.edit_message_text("💰 Введите новую стартовую цену (в рублях):")
        return BotStates.EDIT_AUCTION_PRICE

    async def edit_price_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle price edit input"""
        if update.message.text == "❌ Отмена":
            return await self.cancel(update, context)
            
        try:
            new_price = float(update.message.text.strip())
            if new_price <= 0:
                raise ValueError()
                
            auction_id = context.user_data['edit_auction_id']
            success = await self.auction_service.edit_auction_price(auction_id, new_price)
            
            if success:
                await update.message.reply_text(
                    f"✅ Стартовая цена изменена на: *{new_price:,.0f}₽*",
                    parse_mode='Markdown',
                    reply_markup=self.get_admin_keyboard()
                )
                
                # Notify all participants about the change
                await self.notify_auction_edited(auction_id, f"Стартовая цена изменена на: {new_price:,.0f}₽")
            else:
                await update.message.reply_text(
                    "❌ Ошибка при изменении цены",
                    reply_markup=self.get_admin_keyboard()
                )
        except ValueError:
            await update.message.reply_text("❌ Введите корректную цену")
            return BotStates.EDIT_AUCTION_PRICE
        
        context.user_data.clear()
        return ConversationHandler.END

    async def notify_auction_edited(self, auction_id: UUID, change_description: str):
        """Notify all participants about auction edit"""
        auction = await self.auction_repo.get_auction(auction_id)
        if not auction:
            return
        
        message = f"✏️ *Аукцион '{auction.title}' был изменен*\n\n{change_description}"
        
        # Notify all participants
        for participant_id in auction.participants:
            try:
                await self.auction_service.notification_service.application.bot.send_message(
                    chat_id=participant_id,
                    text=message,
                    parse_mode='Markdown'
                )
            except Exception:
                pass

    # ============ CALLBACK HANDLERS ============

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle all callback queries"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user_id = update.effective_user.id
        user = await self.user_repo.get_user(user_id)
        
        # Handle only essential callbacks for auctions and admin actions
        if data.startswith("register_join_"):
            auction_id = UUID(data.split('_')[2])
            context.user_data['join_auction_id'] = auction_id
            context.user_data['state'] = BotStates.REGISTER_USERNAME
            try:
                await query.edit_message_text("📝 Введите желаемый логин (только буквы, цифры и _):")
            except Exception:
                await query.message.reply_text("📝 Введите желаемый логин (только буквы, цифры и _):")
            return BotStates.REGISTER_USERNAME
        
        elif data == "register_start":
            context.user_data['state'] = BotStates.REGISTER_USERNAME
            try:
                await query.edit_message_text("📝 Введите желаемый логин (только буквы, цифры и _):")
            except Exception:
                await query.message.reply_text("📝 Введите желаемый логин (только буквы, цифры и _):")
            return BotStates.REGISTER_USERNAME
        
        elif data.startswith("join_"):
            await self.join_auction(update, context)
        
        elif data.startswith("bid_"):
            await self.bid_start(update, context)
        
        elif data.startswith("end_auction_"):
            await self.end_auction_callback(update, context)
        
        elif data.startswith("user_"):
            await self.handle_user_action(update, context)
        
        elif data.startswith("block_") or data.startswith("unblock_"):
            await self.toggle_user_block(update, context)
        
        elif data.startswith("edit_auction_"):
            await self.edit_auction_select(update, context)
        
        elif data.startswith("edit_title_"):
            return await self.edit_title_start(update, context)
        
        elif data.startswith("edit_description_"):
            return await self.edit_description_start(update, context)
        
        elif data.startswith("edit_price_"):
            return await self.edit_price_start(update, context)
        
        elif data == "cancel_end":
            try:
                await query.edit_message_text("❌ Завершение аукциона отменено")
            except Exception:
                await query.message.reply_text("❌ Завершение аукциона отменено")
        
        elif data == "cancel_edit":
            try:
                await query.edit_message_text("❌ Редактирование отменено")
            except Exception:
                await query.message.reply_text("❌ Редактирование отменено")
        
        elif data == "back_to_users":
            # Recreate users list
            await self.show_users_callback(query, context)
        
        elif data == "cancel_users":
            try:
                await query.edit_message_text("✅ Закрыто")
            except Exception:
                await query.message.reply_text("✅ Закрыто")("edit_price_")
            return await self.edit_price_start(update, context)
        
        elif data == "cancel_end":
            try:
                await query.edit_message_text("❌ Завершение аукциона отменено")
            except Exception:
                await query.message.reply_text("❌ Завершение аукциона отменено")
        
        elif data == "cancel_edit":
            try:
                await query.edit_message_text("❌ Редактирование отменено")
            except Exception:
                await query.message.reply_text("❌ Редактирование отменено")
        
        elif data == "back_to_users":
            # Recreate users list
            await self.show_users_callback(query, context)
        
        elif data == "cancel_users":
            try:
                await query.edit_message_text("✅ Закрыто")
            except Exception:
                await query.message.reply_text("✅ Закрыто")

    # ============ CALLBACK IMPLEMENTATIONS ============

    async def show_current_auction_callback(self, query, context):
        """Show current auction from callback"""
        current_auction = await self.auction_service.get_current_auction()
        user_id = query.from_user.id
        
        if current_auction:
            message = await self._format_auction_message(current_auction, is_admin=False)
            keyboard = self._get_auction_keyboard(current_auction.auction_id, user_id in current_auction.participants, is_admin=False)
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
                message = f"⏳ *Следующий аукцион:*\n\n" + await self._format_auction_message(next_auction, is_admin=False)
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
        message += f"Имя: {user.username}\n"  # Show username instead of display_name
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
                    leader_name = leader_user.username if leader_user else auction.current_leader.username
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
            message = await self._format_auction_message(auction, is_admin=False)
            keyboard = self._get_auction_keyboard(auction_id, user_id in auction.participants, is_admin=False)
            
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
            # Show username with telegram link for admin
            display_text = f"{status_emoji} {user_obj.display_name}{admin_emoji}"
            if user_obj.telegram_username:
                display_text += f" (@{user_obj.telegram_username})"
            
            keyboard.append([InlineKeyboardButton(
                display_text, 
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
            # Show username with telegram link for admin
            display_text = f"{status_emoji} {user_obj.display_name}{admin_emoji}"
            if user_obj.telegram_username:
                display_text += f" (@{user_obj.telegram_username})"
                
            keyboard.append([InlineKeyboardButton(
                display_text, 
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
        
        # Add contact button for admin
        keyboard_buttons = [
            [InlineKeyboardButton(block_text, callback_data=block_action)]
        ]
        
        if target_user.telegram_username:
            keyboard_buttons.append([InlineKeyboardButton("💬 Написать в ЛС", url=f"https://t.me/{target_user.telegram_username}")])
        
        keyboard_buttons.append([InlineKeyboardButton("◀️ Назад к списку", callback_data="back_to_users")])
        keyboard = InlineKeyboardMarkup(keyboard_buttons)
        
        status = "🚫 Заблокирован" if target_user.is_blocked else "✅ Активен"
        telegram_info = f"@{target_user.telegram_username}" if target_user.telegram_username else "Не указан"
        
        await query.edit_message_text(
            f"👤 *Пользователь*\n\n"
            f"Имя: {target_user.display_name}\n"
            f"Telegram: {telegram_info}\n"
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
        
        context.user_data['state'] = BotStates.CREATE_TITLE
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
        context.user_data['state'] = BotStates.CREATE_START_PRICE
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
            context.user_data['state'] = BotStates.CREATE_DURATION
            await update.message.reply_text(
                "⏰ Введите длительность аукциона в часах (минимум 1 час):",
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
            if duration < 1:  # Minimum 1 hour
                await update.message.reply_text("❌ Минимальная длительность аукциона - 1 час")
                return BotStates.CREATE_DURATION
            context.user_data['duration'] = duration
            context.user_data['state'] = BotStates.CREATE_DESCRIPTION
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
        
        context.user_data['state'] = BotStates.CREATE_MEDIA
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
        
        context.user_data['state'] = BotStates.CREATE_CUSTOM_MESSAGE
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
        
        # Clear state
        context.user_data.clear()
        return ConversationHandler.END

    async def broadcast_new_auction(self, auction: Auction):
        """Broadcast new auction to all users"""
        all_users = await self.user_repo.get_all_users()
        
        for user in all_users:
            if user.is_blocked or user.is_admin:
                continue
                
            try:
                welcome_msg = auction.custom_message or "🎉 *Новый аукцион начался!*"
                auction_message = await self._format_auction_message(auction, is_admin=False)
                keyboard = self._get_auction_keyboard(auction.auction_id, user.user_id in auction.participants, is_admin=False)
                
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
        context.user_data['state'] = BotStates.PLACE_BID
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
                context.user_data.clear()
                return ConversationHandler.END
            
            success = await self.auction_service.place_bid(auction_id, user_id, amount)
            if success:
                await update.message.reply_text(f"✅ Ставка {amount:,.0f}₽ принята!")
                
                # Show updated auction
                auction = await self.auction_repo.get_auction(auction_id)
                if auction:
                    message = await self._format_auction_message(auction, is_admin=False)
                    keyboard = self._get_auction_keyboard(auction_id, True, is_admin=False)
                    
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
        
        # Clear state
        context.user_data.clear()
        return ConversationHandler.END