"""Обработчики платежей: pre_checkout, successful_payment, демо-оплата и отмена брони."""
from __future__ import annotations

import logging
from datetime import timedelta

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery

from bot import texts
from bot.config import Settings
from bot.database.db import Database
from bot.database.models import PENDING
from bot.keyboards import client as kb
from bot.keyboards.callbacks import MyCb
from bot.payments.service import finalize_payment, parse_payload, send_payment
from bot.utils.notify import notify_admins
from bot.utils.timeutil import now_local, to_str
from bot.utils.ui import safe_delete, show

log = logging.getLogger(__name__)
router = Router(name="payments")


def _is_active_pending(booking, settings: Settings) -> bool:
    return (
        booking is not None
        and booking.status == PENDING
        and booking.expires_at is not None
        and booking.expires_at > to_str(now_local(settings.timezone))
    )


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery, db: Database, settings: Settings) -> None:
    booking_id = parse_payload(query.invoice_payload)
    booking = await db.get_booking(booking_id) if booking_id else None

    if booking is None or booking.user_id != query.from_user.id:
        await query.answer(ok=False, error_message="Запись не найдена. Попробуйте записаться заново.")
        return
    if not _is_active_pending(booking, settings):
        await query.answer(
            ok=False,
            error_message="Время на оплату истекло, и бронь снята. Пожалуйста, запишитесь заново 🌸",
        )
        return
    if query.currency != "RUB" or query.total_amount != booking.prepay * 100:
        await query.answer(ok=False, error_message="Сумма счёта изменилась. Попробуйте записаться заново.")
        return

    # Даём платёжной системе время завершить платёж, чтобы бронь не снялась посередине
    await db.extend_hold(booking.id, now_local(settings.timezone) + timedelta(minutes=5))
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message, bot: Bot, db: Database, settings: Settings) -> None:
    payment = message.successful_payment
    booking_id = parse_payload(payment.invoice_payload)
    if booking_id is None:
        log.error("Оплата с неизвестным payload: %s", payment.invoice_payload)
        return
    log.info("Оплата записи #%s: %s", booking_id, payment.telegram_payment_charge_id)
    await finalize_payment(bot, db, settings, booking_id, payment.telegram_payment_charge_id)


@router.callback_query(MyCb.filter(F.action == "demo_pay"))
async def demo_pay(cb: CallbackQuery, callback_data: MyCb, bot: Bot, db: Database, settings: Settings) -> None:
    booking = await db.get_booking(callback_data.booking_id)
    if settings.payments_enabled or booking is None or booking.user_id != cb.from_user.id:
        await cb.answer("Эта кнопка больше не активна", show_alert=True)
        return
    if not _is_active_pending(booking, settings):
        await cb.answer("Время на оплату истекло 😔", show_alert=True)
        return
    await cb.answer("Оплата прошла ✨")
    await finalize_payment(bot, db, settings, booking.id, f"demo-{booking.id}")


@router.callback_query(MyCb.filter(F.action == "pay"))
async def pay_again(cb: CallbackQuery, callback_data: MyCb, bot: Bot, db: Database, settings: Settings) -> None:
    booking = await db.get_booking(callback_data.booking_id)
    if booking is None or booking.user_id != cb.from_user.id or not _is_active_pending(booking, settings):
        await cb.answer("Бронь уже неактивна 😔", show_alert=True)
        return
    await cb.answer()
    await safe_delete(bot, booking.user_id, booking.invoice_message_id)
    await send_payment(bot, db, settings, booking)


@router.callback_query(MyCb.filter(F.action == "drop"))
async def drop_pending(cb: CallbackQuery, callback_data: MyCb, bot: Bot, db: Database, settings: Settings) -> None:
    booking = await db.get_booking(callback_data.booking_id)
    if booking is None or booking.user_id != cb.from_user.id:
        await cb.answer()
        return
    await cb.answer()
    if booking.status == PENDING:
        await db.cancel_booking(booking.id)
        await db.set_invoice_message(booking.id, None)
        await notify_admins(bot, settings, texts.admin_cancelled(booking))
    await show(cb, db, texts.CANCELLED_OK, kb.restart_booking())
