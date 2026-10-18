"""Фоновые задачи: снятие неоплаченных броней, напоминания и просьба об оценке.

Задачи каждые 30 секунд сверяются с базой, поэтому ничего не теряется
при перезапуске бота: всё состояние хранится в SQLite.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot import texts
from bot.config import Settings
from bot.database.db import Database
from bot.keyboards import client as kb
from bot.utils.notify import notify_admins
from bot.utils.menu import main_menu_screen
from bot.utils.timeutil import now_local
from bot.utils.ui import safe_delete, send_screen

log = logging.getLogger(__name__)


async def expire_unpaid(bot: Bot, db: Database, settings: Settings) -> None:
    for booking in await db.expire_pending(now_local(settings.timezone)):
        log.info("Бронь #%s снята: не оплачена за %s мин", booking.id, settings.hold_minutes)
        try:
            await safe_delete(bot, booking.user_id, booking.invoice_message_id)
            await db.set_invoice_message(booking.id, None)
            await send_screen(
                bot, db, booking.user_id,
                *main_menu_screen(settings, booking.user_id, texts.hold_expired(booking)),
            )
        except TelegramAPIError as e:
            log.warning("Не удалось сообщить клиенту %s о снятии брони: %s", booking.user_id, e)
        await notify_admins(bot, settings, texts.admin_expired(booking))


async def send_reminders(bot: Bot, db: Database, settings: Settings) -> None:
    now = now_local(settings.timezone)
    # Сначала второе (ближнее): если до визита уже меньше его срока, первое не нужно
    for which in (1, 0):
        for booking in await db.due_reminders(now, which):
            # Сколько реально осталось до визита (задача идёт раз в 30 секунд, округляем до часа)
            hours = max(1, round((booking.start_dt - now).total_seconds() / 3600))
            await db.mark_reminded(booking.id, which)
            if which == 1:
                await db.mark_reminded(booking.id, 0)
            try:
                await bot.send_message(
                    booking.user_id, texts.reminder(booking, settings, hours), reply_markup=kb.reminder(True),
                )
            except TelegramAPIError as e:
                log.warning("Напоминание #%s не доставлено: %s", booking.id, e)


async def request_reviews(bot: Bot, db: Database, settings: Settings) -> None:
    for booking in await db.finish_visits(now_local(settings.timezone)):
        try:
            await bot.send_message(booking.user_id, texts.review_request(booking), reply_markup=kb.rating(booking.id))
        except TelegramAPIError as e:
            log.warning("Запрос оценки #%s не доставлен: %s", booking.id, e)


async def admin_digest(bot: Bot, db: Database, settings: Settings) -> None:
    """Вечерняя сводка админу: кто придёт завтра."""
    now = now_local(settings.timezone)
    tomorrow = now.date() + timedelta(days=1)
    bookings = await db.bookings_for_day(tomorrow, now)
    await notify_admins(bot, settings, texts.admin_digest(tomorrow, bookings))
    log.info("Сводка на завтра отправлена: %s записей", len(bookings))


async def _safe(job, *args) -> None:
    try:
        await job(*args)
    except Exception:  # задача не должна останавливать планировщик
        log.exception("Ошибка в фоновой задаче %s", job.__name__)


def setup_scheduler(bot: Bot, db: Database, settings: Settings) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    for job in (expire_unpaid, send_reminders, request_reviews):
        scheduler.add_job(
            _safe, "interval", seconds=30, args=(job, bot, db, settings),
            id=job.__name__, max_instances=1, coalesce=True,
        )
    scheduler.add_job(
        _safe, "cron", hour=settings.digest_time.hour, minute=settings.digest_time.minute,
        args=(admin_digest, bot, db, settings), id="admin_digest", max_instances=1, coalesce=True,
        misfire_grace_time=600,
    )
    return scheduler
