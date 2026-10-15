"""Глобальный обработчик ошибок (регистрируется на диспетчере) и ответы на «непонятные» апдейты."""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ErrorEvent, Message

from bot.config import Settings
from bot.database.db import Database
from bot.utils.menu import main_menu_screen
from bot.utils.ui import safe_delete, show

log = logging.getLogger(__name__)
router = Router(name="common")


async def on_error(event: ErrorEvent) -> bool:
    """Логируем ошибку и мягко сообщаем пользователю — бот продолжает работать."""
    log.exception("Ошибка при обработке апдейта %s", event.update.update_id, exc_info=event.exception)
    update = event.update
    try:
        if update.callback_query:
            await update.callback_query.answer(
                "Что-то пошло не так 😔 Попробуйте ещё раз или откройте /start", show_alert=True
            )
        elif update.message:
            await update.message.answer("Что-то пошло не так 😔 Попробуйте ещё раз или нажмите /start")
    except TelegramAPIError:
        pass
    return True


@router.message()
async def fallback(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    """Любой текст вне сценария — просто показываем меню, чтобы клиент не потерялся."""
    if message.successful_payment:
        return
    await state.clear()
    await show(message, db, *main_menu_screen(settings, message.from_user.id))
    await safe_delete(message.bot, message.chat.id, message.message_id)


@router.callback_query()
async def stale_button(cb: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    """Кнопка из старого сообщения, которую уже нечем обработать."""
    await cb.answer("Эта кнопка устарела — открываю меню ✨")
    await state.clear()
    await show(cb, db, *main_menu_screen(settings, cb.from_user.id))
