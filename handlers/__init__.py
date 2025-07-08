"""
Handlers package for Telegram auction bot
"""

from .base import BotStates, BaseHandlers
from .conversations import ConversationHandlers

# Создаем TelegramHandlers здесь же
class TelegramHandlers(ConversationHandlers):
    """Complete Telegram bot handlers combining all functionality"""
    pass  # Все методы уже есть в ConversationHandlers

__all__ = ['BotStates', 'BaseHandlers', 'ConversationHandlers', 'TelegramHandlers']