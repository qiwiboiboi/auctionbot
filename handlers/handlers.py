"""
Main handlers file combining all handler classes
"""

from uuid import UUID
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

# Удаляем сложные импорты, просто наследуемся от ConversationHandlers
from handlers.conversations import ConversationHandlers


class TelegramHandlers(ConversationHandlers):
    """Complete Telegram bot handlers combining all functionality"""
    pass  # Все методы уже есть в ConversationHandlers
    """Complete Telegram bot handlers combining all functionality"""

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
                    # Show only username for regular users  
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