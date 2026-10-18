"""«Мои записи»: просмотр, отмена, оценка визита."""
from __future__ import annotations

import logging
from datetime import timedelta

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from bot import texts
from bot.config import Settings
from bot.database.db import Database
from bot.database.models import CONFIRMED, PENDING, Booking
from bot.keyboards import client as kb
from bot.keyboards.callbacks import MenuCb, MyCb, RateCb
from bot.utils.notify import notify_admins
from bot.utils.menu import main_menu_screen
from bot.utils.timeutil import now_local, to_str
from bot.utils.ui import safe_delete, send_screen, show

log = logging.getLogger(__name__)
router = Router(name="my_bookings")


def _can_cancel(b: Booking, settings: Settings) -> bool:
    if b.status == PENDING:
        return True  # неоплаченную бронь можно отпустить в любой момент
    return b.start_dt - now_local(settings.timezone) >= timedelta(hours=settings.cancel_hours)


async def _own_upcoming(db: Database, settings: Settings, user_id: int, booking_id: int) -> Booking | None:
    booking = await db.get_booking(booking_id)
    if booking is None or booking.user_id != user_id:
        return None
    now = now_local(settings.timezone)
    if booking.start_dt <= now:
        return None
    if booking.status == PENDING and (booking.expires_at or "") <= to_str(now):
        return None
    if booking.status not in (PENDING, CONFIRMED):
        return None
    return booking


async def render_list(cb: CallbackQuery, db: Database, settings: Settings) -> None:
    items = await db.user_upcoming(cb.from_user.id, now_local(settings.timezone))
    await show(cb, db, texts.my_bookings(bool(items)), kb.my_bookings(items))


@router.callback_query(MenuCb.filter(F.action == "my"))
async def my_list(cb: CallbackQuery, db: Database, settings: Settings) -> None:
    await cb.answer()
    await render_list(cb, db, settings)


@router.callback_query(MyCb.filter(F.action == "view"))
async def view(cb: CallbackQuery, callback_data: MyCb, db: Database, settings: Settings) -> None:
    booking = await _own_upcoming(db, settings, cb.from_user.id, callback_data.booking_id)
    if booking is None:
        await cb.answer("Эта запись уже неактуальна", show_alert=True)
        return await render_list(cb, db, settings)
    await cb.answer()
    can_cancel = _can_cancel(booking, settings)
    text = "📋 <b>Ваша запись</b>\n\n" + texts.booking_card(booking, settings)
    if not can_cancel:
        text += texts.cancel_too_late(settings)
    await show(cb, db, text, kb.my_booking(booking, can_cancel, settings.on_site_available))


@router.callback_query(MyCb.filter(F.action == "cancel"))
async def ask_cancel(cb: CallbackQuery, callback_data: MyCb, db: Database, settings: Settings) -> None:
    booking = await _own_upcoming(db, settings, cb.from_user.id, callback_data.booking_id)
    if booking is None:
        await cb.answer("Эта запись уже неактуальна", show_alert=True)
        return await render_list(cb, db, settings)
    if not _can_cancel(booking, settings):
        await cb.answer(f"Отмена возможна не позднее чем за {settings.cancel_hours} ч", show_alert=True)
        return
    await cb.answer()
    await show(cb, db, texts.cancel_confirm(booking, settings), kb.cancel_confirm(booking))


@router.callback_query(MyCb.filter(F.action == "cancel_ok"))
async def do_cancel(
    cb: CallbackQuery, callback_data: MyCb, bot: Bot, db: Database, settings: Settings
) -> None:
    booking = await _own_upcoming(db, settings, cb.from_user.id, callback_data.booking_id)
    if booking is None:
        await cb.answer("Эта запись уже неактуальна", show_alert=True)
        return await render_list(cb, db, settings)
    if not _can_cancel(booking, settings):
        await cb.answer(f"Отмена возможна не позднее чем за {settings.cancel_hours} ч", show_alert=True)
        return
    await cb.answer()
    await db.cancel_booking(booking.id)
    log.info("Клиент %s отменил запись #%s (%s)", cb.from_user.full_name, booking.id, booking.start)
    if booking.status == PENDING:
        await safe_delete(bot, booking.user_id, booking.invoice_message_id)
        await db.set_invoice_message(booking.id, None)
    await show(cb, db, *main_menu_screen(settings, cb.from_user.id, texts.CANCELLED_OK))
    await notify_admins(bot, settings, texts.admin_cancelled(booking))


@router.callback_query(RateCb.filter())
async def rate(cb: CallbackQuery, callback_data: RateCb, bot: Bot, db: Database, settings: Settings) -> None:
    stars = callback_data.stars
    if not 1 <= stars <= 5:
        await cb.answer()
        return
    booking = await db.set_rating(callback_data.booking_id, cb.from_user.id, stars)
    if booking is None:
        await cb.answer("Оценка уже учтена, спасибо 💗")
        return
    log.info("Оценка %s/5 за запись #%s", stars, booking.id)
    await cb.answer("Спасибо! 💗")
    # Просьба об оценке была отдельным сообщением — убираем её и показываем меню с благодарностью
    await send_screen(bot, db, cb.from_user.id, *main_menu_screen(settings, cb.from_user.id, texts.review_thanks(stars)))
    if cb.message:
        await safe_delete(bot, cb.from_user.id, cb.message.message_id)
    await notify_admins(bot, settings, texts.admin_rating(booking, stars))
