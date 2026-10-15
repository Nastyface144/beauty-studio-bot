"""Предоплата через Telegram Payments (ЮKassa, тестовый режим).

Если PAYMENT_TOKEN не задан, бот работает в демо-режиме: вместо счёта
показывается кнопка «Оплатить (демо)», чтобы весь сценарий можно было пройти
без настройки платёжного провайдера.
"""
from __future__ import annotations

import math

from aiogram import Bot
from aiogram.types import LabeledPrice

from bot import texts
from bot.config import Settings
from bot.database.db import Database
from bot.database.models import Booking
from bot.keyboards import client as kb
from bot.utils.notify import notify_admins
from bot.utils.timeutil import money, now_local
from bot.utils.ui import safe_delete, send_screen

PAYLOAD_PREFIX = "booking:"


def calc_prepay(price: int, percent: int) -> int:
    return math.ceil(price * percent / 100)


def make_payload(booking_id: int) -> str:
    return f"{PAYLOAD_PREFIX}{booking_id}"


def parse_payload(payload: str) -> int | None:
    if not payload.startswith(PAYLOAD_PREFIX):
        return None
    raw = payload[len(PAYLOAD_PREFIX):]
    return int(raw) if raw.isdigit() else None


async def send_payment(bot: Bot, db: Database, settings: Settings, booking: Booking) -> None:
    """Показывает клиенту счёт на предоплату вместо текущего экрана."""
    chat_id = booking.user_id
    old_ui = await db.get_ui_message(chat_id)

    if settings.payments_enabled:
        msg = await bot.send_invoice(
            chat_id=chat_id,
            title=f"Предоплата {settings.prepay_percent}% за визит",
            description=texts.invoice_description(booking),
            payload=make_payload(booking.id),
            provider_token=settings.payment_token,
            currency="RUB",
            prices=[LabeledPrice(label=f"Предоплата {settings.prepay_percent}%", amount=booking.prepay * 100)],
            reply_markup=kb.invoice(booking),
        )
    else:
        msg = await bot.send_message(
            chat_id,
            "💳 <b>Предоплата</b>\n\n"
            + texts.booking_card(booking, settings)
            + f"\n\nК оплате: <b>{money(booking.prepay)}</b>\n\n"
            "<i>Платёжный токен не настроен, поэтому оплата работает в демо-режиме.</i>",
            reply_markup=kb.demo_payment(booking),
        )

    await db.set_invoice_message(booking.id, msg.message_id)
    await db.set_ui_message(chat_id, msg.message_id)
    if old_ui and old_ui != msg.message_id:
        await safe_delete(bot, chat_id, old_ui)


async def finalize_payment(
    bot: Bot, db: Database, settings: Settings, booking_id: int, charge_id: str
) -> None:
    """Подтверждает запись после успешной оплаты и сообщает клиенту и админу."""
    booking, ok = await db.confirm_payment(booking_id, charge_id, now_local(settings.timezone))
    if booking is None:
        return
    await safe_delete(bot, booking.user_id, booking.invoice_message_id)
    await db.set_invoice_message(booking.id, None)

    if ok:
        menu = kb.main_menu(is_admin=booking.user_id in settings.admin_ids)
        await send_screen(bot, db, booking.user_id, texts.payment_success(booking, settings), menu)
        await notify_admins(bot, settings, texts.admin_paid(booking))
    else:
        menu = kb.main_menu(is_admin=booking.user_id in settings.admin_ids)
        await send_screen(bot, db, booking.user_id, texts.payment_conflict(), menu)
        await notify_admins(bot, settings, texts.admin_conflict(booking))
