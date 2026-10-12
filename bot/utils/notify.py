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
