"""Пошаговая запись: категория → услуга → опции → мастер → дата → время → итог."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot import texts
from bot.config import Settings
from bot.database.db import Database
from bot.database.models import PENDING, Master, Option, Service
from bot.demo_data import CATEGORIES
from bot.keyboards import client as kb
from bot.keyboards.calendar import day_code, parse_day_code, parse_month_code
from bot.keyboards.callbacks import BookCb, MenuCb
from bot.payments.service import calc_prepay, send_payment
from bot.services.slots import free_starts
from bot.utils.notify import notify_admins
from bot.utils.menu import main_menu_screen
from bot.utils.timeutil import now_local
from bot.utils.ui import safe_delete, show

log = logging.getLogger(__name__)
router = Router(name="booking")


@dataclass
class Selection:
    service: Service
    options: list[Option]
    master: Master | None

    @property
    def duration(self) -> int:
        return self.service.duration + sum(o.duration for o in self.options)

    @property
    def price(self) -> int:
        return self.service.price + sum(o.price for o in self.options)


async def _selection(db: Database, data: dict, need_master: bool = False) -> Selection | None:
    """Восстанавливает выбор клиента из FSM. None — если данных не хватает (бот перезапускался и т.п.)."""
    service = await db.get_service(data["service_id"]) if data.get("service_id") else None
    if service is None:
        return None
    options = await db.get_options(data.get("option_ids", []))
    master = await db.get_master(data["master_id"]) if data.get("master_id") else None
    if need_master and (master is None or service.category not in master.categories):
        return None
    return Selection(service, options, master)


async def _expired(cb: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    await state.clear()
    await show(cb, db, *main_menu_screen(settings, cb.from_user.id, texts.SESSION_EXPIRED))


def _booking_days(settings: Settings) -> list[date]:
    today = now_local(settings.timezone).date()
    return [today + timedelta(days=i) for i in range(settings.booking_days)]


async def _free_by_day(
    db: Database, settings: Settings, master_id: int, duration: int, days: list[date]
) -> dict[date, list[datetime]]:
    now = now_local(settings.timezone)
    busy = await db.busy_intervals(master_id, days[0], days[-1], now)
    weekly_off = await db.get_weekly_off()
    return {
        d: [] if d.weekday() in weekly_off else free_starts(
            d, duration, busy, now, settings.work_start, settings.work_end,
            settings.slot_step_min, settings.min_lead_min,
        )
        for d in days
    }


# ---------- экраны шагов ----------

async def render_categories(cb: CallbackQuery, db: Database) -> None:
    await show(cb, db, texts.choose_category(), kb.categories())


async def render_services(cb: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    data = await state.get_data()
    category = data.get("category")
    if category not in CATEGORIES:
        return await _expired(cb, state, db, settings)
    await show(cb, db, texts.choose_service(category), kb.services(await db.services(category)))


async def render_options(cb: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    sel = await _selection(db, await state.get_data())
    if sel is None:
        return await _expired(cb, state, db, settings)
    items = await db.options(sel.service.category)
    selected = {o.id for o in sel.options}
    await show(cb, db, texts.choose_options(sel.service, sel.options), kb.options(items, selected))


async def render_masters(cb: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    sel = await _selection(db, await state.get_data())
    if sel is None:
        return await _expired(cb, state, db, settings)
    has_options = bool(await db.options(sel.service.category))
    masters = await db.masters_for_category(sel.service.category)
    await show(cb, db, texts.choose_master(), kb.masters(masters, "options" if has_options else "services"))


async def render_calendar(
    cb: CallbackQuery, state: FSMContext, db: Database, settings: Settings, note: str = ""
) -> None:
    data = await state.get_data()
    sel = await _selection(db, data, need_master=True)
    if sel is None:
        return await _expired(cb, state, db, settings)
    days = _booking_days(settings)
    free = await _free_by_day(db, settings, sel.master.id, sel.duration, days)
    available = {d for d, starts in free.items() if starts}
    text = texts.choose_date(sel.master.name, sel.duration)
    if note:
        text = f"{note}\n\n{text}"
    if not available:
        text += "\n\n" + texts.no_slots(settings.booking_days)
    await show(cb, db, text, kb.booking_calendar(days, available, _calendar_month(data, available)))


def _calendar_month(data: dict, available: set[date]) -> tuple[int, int] | None:
    """Какой месяц показать: выбранный стрелками → месяц выбранного дня → первый со свободным временем."""
    if data.get("month"):
        return parse_month_code(data["month"])
    if data.get("day"):
        day = parse_day_code(data["day"])
        return day.year, day.month
    if available:
        first = min(available)
        return first.year, first.month
    return None


async def render_times(cb: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    data = await state.get_data()
    sel = await _selection(db, data, need_master=True)
    if sel is None or not data.get("day"):
        return await _expired(cb, state, db, settings)
    day = parse_day_code(data["day"])
    starts = (await _free_by_day(db, settings, sel.master.id, sel.duration, [day]))[day]
    if not starts:
        return await render_calendar(cb, state, db, settings, note="😔 На этот день свободного времени уже нет.")
    await show(cb, db, texts.choose_time(day, sel.duration), kb.times(starts))


async def render_summary(cb: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    data = await state.get_data()
    sel = await _selection(db, data, need_master=True)
    if sel is None or not data.get("day") or not data.get("time"):
        return await _expired(cb, state, db, settings)
    start = _start_from(data)
    prepay = calc_prepay(sel.price, settings.prepay_percent)
    text = texts.summary(sel.service, sel.options, sel.master.name, start, sel.duration, sel.price, prepay, settings)
    await show(cb, db, text, kb.summary(settings, prepay))


def _start_from(data: dict) -> datetime:
    raw = data["time"]
    return datetime.combine(parse_day_code(data["day"]), time(int(raw[:2]), int(raw[2:])))


# ---------- обработчики ----------

@router.callback_query(MenuCb.filter(F.action == "book"))
async def start_booking(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    await cb.answer()
    await state.clear()
    await db.upsert_user(cb.from_user.id, cb.from_user.full_name, cb.from_user.username)
    await render_categories(cb, db)


@router.callback_query(BookCb.filter(F.action == "cat"))
async def pick_category(
    cb: CallbackQuery, callback_data: BookCb, state: FSMContext, db: Database, settings: Settings
) -> None:
    await cb.answer()
    if callback_data.value not in CATEGORIES:
        return await render_categories(cb, db)
    await state.set_data({"category": callback_data.value})
    await render_services(cb, state, db, settings)


@router.callback_query(BookCb.filter(F.action == "srv"))
async def pick_service(
    cb: CallbackQuery, callback_data: BookCb, state: FSMContext, db: Database, settings: Settings
) -> None:
    await cb.answer()
    service = await db.get_service(int(callback_data.value)) if callback_data.value.isdigit() else None
    if service is None:
        return await _expired(cb, state, db, settings)
    await state.update_data(category=service.category, service_id=service.id, option_ids=[], master_id=None)
    if await db.options(service.category):
        await render_options(cb, state, db, settings)
    else:
        await render_masters(cb, state, db, settings)


@router.callback_query(BookCb.filter(F.action == "opt"))
async def toggle_option(
    cb: CallbackQuery, callback_data: BookCb, state: FSMContext, db: Database, settings: Settings
) -> None:
    await cb.answer()
    data = await state.get_data()
    sel = await _selection(db, data)
    if sel is None or not callback_data.value.isdigit():
        return await _expired(cb, state, db, settings)
    allowed = {o.id for o in await db.options(sel.service.category)}
    option_id = int(callback_data.value)
    selected = set(data.get("option_ids", []))
    if option_id in allowed:
        selected ^= {option_id}
    await state.update_data(option_ids=sorted(selected))
    await render_options(cb, state, db, settings)


@router.callback_query(BookCb.filter(F.action == "opts_done"))
async def options_done(cb: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    await cb.answer()
    await render_masters(cb, state, db, settings)


@router.callback_query(BookCb.filter(F.action == "mst"))
async def pick_master(
    cb: CallbackQuery, callback_data: BookCb, state: FSMContext, db: Database, settings: Settings
) -> None:
    await cb.answer()
    if not callback_data.value.isdigit():
        return await _expired(cb, state, db, settings)
    await state.update_data(master_id=int(callback_data.value), day=None, time=None, month=None)
    await render_calendar(cb, state, db, settings)


@router.callback_query(BookCb.filter(F.action == "month"))
async def switch_month(
    cb: CallbackQuery, callback_data: BookCb, state: FSMContext, db: Database, settings: Settings
) -> None:
    await cb.answer()
    if parse_month_code(callback_data.value):
        await state.update_data(month=callback_data.value)
    await render_calendar(cb, state, db, settings)


@router.callback_query(BookCb.filter(F.action == "day"))
async def pick_day(
    cb: CallbackQuery, callback_data: BookCb, state: FSMContext, db: Database, settings: Settings
) -> None:
    try:
        day = parse_day_code(callback_data.value)
    except ValueError:
        await cb.answer()
        return await _expired(cb, state, db, settings)

    await cb.answer()
    if day not in _booking_days(settings):
        return await render_calendar(cb, state, db, settings, note="Эта дата уже недоступна.")
    await state.update_data(day=day_code(day), month=None)
    await render_times(cb, state, db, settings)


@router.callback_query(BookCb.filter(F.action == "time"))
async def pick_time(
    cb: CallbackQuery, callback_data: BookCb, state: FSMContext, db: Database, settings: Settings
) -> None:
    data = await state.get_data()
    sel = await _selection(db, data, need_master=True)
    raw = callback_data.value
    if sel is None or not data.get("day") or len(raw) != 4 or not raw.isdigit():
        await cb.answer()
        return await _expired(cb, state, db, settings)
    day = parse_day_code(data["day"])
    starts = (await _free_by_day(db, settings, sel.master.id, sel.duration, [day]))[day]
    chosen = datetime.combine(day, time(int(raw[:2]) % 24, int(raw[2:]) % 60))
    if chosen not in starts:
        await cb.answer(texts.SLOT_TAKEN, show_alert=True)
        return await render_times(cb, state, db, settings)
    await cb.answer()
    await state.update_data(time=raw)
    await render_summary(cb, state, db, settings)


@router.callback_query(BookCb.filter(F.action == "back"))
async def go_back(
    cb: CallbackQuery, callback_data: BookCb, state: FSMContext, db: Database, settings: Settings
) -> None:
    await cb.answer()
    target = callback_data.value
    if target == "cats":
        await render_categories(cb, db)
    elif target == "services":
        await render_services(cb, state, db, settings)
    elif target == "options":
        await render_options(cb, state, db, settings)
    elif target == "masters":
        await render_masters(cb, state, db, settings)
    elif target == "calendar":
        await render_calendar(cb, state, db, settings)
    elif target == "times":
        await render_times(cb, state, db, settings)
    else:
        await render_categories(cb, db)


@router.callback_query(BookCb.filter(F.action == "confirm"))
async def confirm(
    cb: CallbackQuery, callback_data: BookCb, state: FSMContext, bot: Bot, db: Database, settings: Settings
) -> None:
    # Способ оплаты: выбранный кнопкой, если он сейчас разрешён, иначе доступный
    if callback_data.value == "cash" and settings.on_site_available:
        pay_on_site = True
    elif callback_data.value == "online" and settings.online_available:
        pay_on_site = False
    else:
        pay_on_site = not settings.online_available
    data = await state.get_data()
    sel = await _selection(db, data, need_master=True)
    if sel is None or not data.get("day") or not data.get("time"):
        await cb.answer()
        return await _expired(cb, state, db, settings)

    start = _start_from(data)
    now = now_local(settings.timezone)
    if start < now + timedelta(minutes=settings.min_lead_min):
        await cb.answer(texts.SLOT_TAKEN, show_alert=True)
        return await render_times(cb, state, db, settings)

    # Старые неоплаченные счета клиента больше не нужны — новая бронь их заменит
    for old in await db.user_upcoming(cb.from_user.id, now):
        if old.status == PENDING:
            await safe_delete(bot, old.user_id, old.invoice_message_id)

    booking = await db.create_booking(
        user_id=cb.from_user.id,
        master=sel.master,
        service=sel.service,
        options=sel.options,
        start=start,
        duration=sel.duration,
        price=sel.price,
        prepay=calc_prepay(sel.price, settings.prepay_percent),
        now=now,
        hold_minutes=settings.hold_minutes,
        pay_on_site=pay_on_site,
    )
    if booking is None:
        await cb.answer()
        return await show(cb, db, texts.SLOT_TAKEN, kb.slot_taken())

    log.info(
        "Новая %s #%s: %s, %s, мастер %s, клиент %s",
        "запись (оплата в студии)" if pay_on_site else "бронь (предоплата)",
        booking.id, booking.start, booking.service_name, booking.master_name, cb.from_user.full_name,
    )
    await state.clear()
    if pay_on_site:
        await cb.answer("Вы записаны ✨")
        menu = kb.main_menu(is_admin=cb.from_user.id in settings.admin_ids)
        await show(cb, db, texts.payment_success(booking, settings), menu)
    else:
        await cb.answer("Время закреплено за вами ✨")
        await send_payment(bot, db, settings, booking)
    await notify_admins(bot, settings, texts.admin_new_booking(booking))
