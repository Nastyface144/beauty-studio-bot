"""Интерфейс «одного сообщения»: бот редактирует текущее сообщение вместо отправки нового.

Если отредактировать нельзя (например, текст нужно заменить на фото, сообщение
слишком старое или это счёт на оплату), старое сообщение удаляется и вместо него
отправляется новое, так что в чате всё равно остаётся одно «живое» сообщение.
"""
from __future__ import annotations

import logging
from typing import Union

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    CallbackQuery, FSInputFile, InaccessibleMessage, InlineKeyboardMarkup, InputMediaPhoto, Message,
)

from bot.database.db import Database

log = logging.getLogger(__name__)

Photo = Union[str, FSInputFile]


async def safe_delete(bot: Bot, chat_id: int, message_id: int | None) -> None:
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id, message_id)
    except (TelegramBadRequest, TelegramForbiddenError):
        pass  # уже удалено или старше 48 часов — не страшно


async def send_screen(
    bot: Bot,
    db: Database,
    chat_id: int,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
    photo: Photo | None = None,
) -> Message:
    """Отправляет новый экран и удаляет предыдущий."""
    old_id = await db.get_ui_message(chat_id)
    if photo is not None:
        msg = await bot.send_photo(chat_id, photo, caption=text, reply_markup=markup)
    else:
        msg = await bot.send_message(chat_id, text, reply_markup=markup)
    await db.set_ui_message(chat_id, msg.message_id)
    if old_id and old_id != msg.message_id:
        await safe_delete(bot, chat_id, old_id)
    return msg


async def show(
    event: Union[CallbackQuery, Message],
    db: Database,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
    photo: Photo | None = None,
) -> Message:
    """Показывает экран: редактирует сообщение с кнопкой, если это возможно."""
    bot = event.bot
    if isinstance(event, Message):
        return await send_screen(bot, db, event.chat.id, text, markup, photo)

    msg = event.message
    chat_id = event.from_user.id
    if msg is None or isinstance(msg, InaccessibleMessage):
        return await send_screen(bot, db, chat_id, text, markup, photo)

    try:
        if photo is None and msg.text is not None:
            result = await msg.edit_text(text, reply_markup=markup)
        elif photo is not None and msg.photo:
            result = await msg.edit_media(InputMediaPhoto(media=photo, caption=text), reply_markup=markup)
        else:
            return await _replace(msg, db, chat_id, text, markup, photo)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return msg
        log.debug("Не удалось отредактировать сообщение (%s), отправляю новое", e)
        return await _replace(msg, db, chat_id, text, markup, photo)

    await db.set_ui_message(chat_id, msg.message_id)
    return result if isinstance(result, Message) else msg


async def _replace(old: Message, db: Database, chat_id: int, text, markup, photo) -> Message:
    new = await send_screen(old.bot, db, chat_id, text, markup, photo)
    if new.message_id != old.message_id:
        await safe_delete(old.bot, chat_id, old.message_id)
    return new
