"""Сборка и запуск бота."""
from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError, TelegramUnauthorizedError
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from bot.config import Settings, load_settings
from bot.database.db import Database
from bot.handlers import admin, booking, common, gallery, menu, my_bookings
from bot.handlers.common import on_error
from bot.payments import handlers as payments
from bot.scheduler.jobs import setup_scheduler

log = logging.getLogger("bot")


async def _set_commands(bot: Bot, admin_ids) -> None:
    client_commands = [
        BotCommand(command="start", description="Главное меню"),
    ]
    await bot.set_my_commands(client_commands, scope=BotCommandScopeDefault())
    for admin_id in admin_ids:
        try:
            await bot.set_my_commands(
                client_commands + [BotCommand(command="admin", description="Админ-панель")],
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except TelegramAPIError as e:
            log.warning("Не удалось установить команды для админа %s: %s", admin_id, e)


def build_dispatcher(db: Database, settings: Settings) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage(), db=db, settings=settings)
    dp.errors.register(on_error)
    dp.include_routers(
        payments.router,
        admin.router,
        menu.router,
        booking.router,
        my_bookings.router,
        gallery.router,
        common.router,  # последним: ловит всё, что не обработали другие
    )
    return dp


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = load_settings()
    if not settings.admin_ids:
        log.warning("ADMIN_ID не задан — уведомления админу и /admin работать не будут")
    if not settings.payments_enabled:
        log.warning("PAYMENT_TOKEN не задан — предоплата работает в демо-режиме")

    db = Database(settings.db_path)
    await db.connect()
    await db.seed_demo_data(settings.gallery_dir)

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = build_dispatcher(db, settings)

    scheduler = setup_scheduler(bot, db, settings)
    try:
        try:
            me = await bot.get_me()
        except TelegramUnauthorizedError:
            raise RuntimeError("Telegram не принял BOT_TOKEN. Проверьте токен в .env (его выдаёт @BotFather).")
        except TelegramNetworkError as e:
            raise RuntimeError(f"Не удалось подключиться к Telegram: {e}. Проверьте интернет или VPN.")
        await _set_commands(bot, settings.admin_ids)
        scheduler.start()
        log.info("Бот @%s запущен. Откройте https://t.me/%s и нажмите /start", me.username, me.username)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
        await bot.session.close()
        await db.close()
