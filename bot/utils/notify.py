"""Уведомления администраторам."""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from bot.config import Settings

log = logging.getLogger(__name__)


async def notify_admins(bot: Bot, settings: Settings, text: str) -> None:
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except TelegramAPIError as e:
            # Админ мог не запускать бота или заблокировать его — запись клиента от этого не страдает
            log.warning("Не удалось уведомить админа %s: %s", admin_id, e)


async def notify_admins_except(bot: Bot, settings: Settings, skip_id: int, text: str) -> None:
    """Сообщить остальным админам (тот, кто сделал действие, и так в курсе)."""
    for admin_id in settings.admin_ids - {skip_id}:
        try:
            await bot.send_message(admin_id, text)
        except TelegramAPIError as e:
            log.warning("Не удалось уведомить админа %s: %s", admin_id, e)
