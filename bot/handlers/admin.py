"""Админ-панель: записи по датам, отмена записи, закрытие дней и времени,
регулярные выходные, статистика, журнал и фото в галерею."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, Filter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot import texts
from bot.config import Settings
from bot.database.db import Database
from bot.database.models import CONFIRMED, PENDING
from bot.demo_data import CATEGORIES
from bot.keyboards import admin as kb
from bot.keyboards.calendar import parse_day_code, parse_month_code
from bot.keyboards.callbacks import AdminCb
from bot.utils.logs import read_events
from bot.utils.timeutil import WEEKDAYS_FULL, from_str, money, now_local, to_str
from bot.utils.menu import main_menu_screen
from bot.utils.notify import notify_admins_except
from bot.utils.ui import safe_delete, send_screen, show

log = logging.getLogger(__name__)


class IsAdmin(Filter):
    async def __call__(self, event: TelegramObject, settings: Settings) -> bool:
        user = getattr(event, "from_user", None)
        return user is not None and user.id in settings.admin_ids


class AdminStates(StatesGroup):
    waiting_photo = State()


router = Router(name="admin")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


def _parse_day(raw: str) -> date | None:
    try:
        return parse_day_code(raw)
    except (ValueError, IndexError):
        return None


def _close_range(settings: Settings) -> list[date]:
    today = now_local(settings.timezone).date()
    return [today + timedelta(days=i) for i in range(settings.booking_days + 30)]


def _view_range(settings: Settings) -> list[date]:
    today = now_local(settings.timezone).date()
    return [today + timedelta(days=i) for i in range(-7, settings.booking_days)]


def _day_slots(day: date, settings: Settings) -> list[datetime]:
    step = timedelta(minutes=settings.slot_step_min)
    cur = datetime.combine(day, settings.work_start)
    end = datetime.combine(day, settings.work_end)
    slots = []
    while cur < end:
        slots.append(cur)
        cur += step
    return slots


def _closed_slots(blocks, slots: list[datetime], settings: Settings) -> set[datetime]:
    """Слоты дня, которые пересекаются с закрытым временем."""
    step = timedelta(minutes=settings.slot_step_min)
    return {
        s for s in slots
        if any(b.start < to_str(s + step) and b.end > to_str(s) for b in blocks)
    }


# ---------- экраны ----------

async def render_home(event, db: Database, settings: Settings, notice: str = "") -> None:
    await show(event, db, texts.admin_home(settings, notice), kb.home())


async def render_day(cb: CallbackQuery, db: Database, settings: Settings, day: date) -> None:
    now = now_local(settings.timezone)
    bookings = await db.bookings_for_day(day, now)
    day_off = day.weekday() in await db.get_weekly_off()
    await show(cb, db, texts.admin_day(day, bookings, day_off), kb.day_view(day, bookings))


async def render_view_calendar(
    cb: CallbackQuery, db: Database, settings: Settings, month: tuple[int, int] | None = None
) -> None:
    days = _view_range(settings)
    if month is None:
        today = now_local(settings.timezone).date()
        month = (today.year, today.month)
    counts = await db.booking_counts(days[0], days[-1], now_local(settings.timezone))
    markup = kb.view_calendar(days, counts, await db.get_weekly_off(), month)
    await show(cb, db, texts.admin_view_pick_day(), markup)


async def render_booking(cb: CallbackQuery, db: Database, settings: Settings, booking_id: int) -> None:
    booking = await db.get_booking(booking_id)
    if booking is None:
        return await render_view_calendar(cb, db, settings)
    can_cancel = booking.status in (PENDING, CONFIRMED) and booking.start_dt > now_local(settings.timezone)
    await show(cb, db, texts.admin_booking(booking), kb.booking_card(booking, can_cancel))


async def render_close_calendar(
    cb: CallbackQuery, db: Database, settings: Settings, month: tuple[int, int] | None = None
) -> None:
    days = _close_range(settings)
    closed = await db.closed_days(
        days[0], days[-1], f"{settings.work_start:%H:%M}", f"{settings.work_end:%H:%M}"
    )
    markup = kb.close_calendar(days, closed, await db.get_weekly_off(), month)
    await show(cb, db, texts.admin_close_pick_day(), markup)


async def render_close_day(cb: CallbackQuery, db: Database, settings: Settings, day: date) -> None:
    now = now_local(settings.timezone)
    slots = _day_slots(day, settings)
    closed_slots = _closed_slots(await db.blocks_for_day(day), slots, settings)
    day_closed = bool(slots) and len(closed_slots) == len(slots)
    day_start = datetime.combine(day, settings.work_start)
    day_end = datetime.combine(day, settings.work_end)
    active = await db.count_active_between(day_start, day_end, now)
    day_off = day.weekday() in await db.get_weekly_off()
    await show(
        cb, db,
        texts.admin_close_day(day, day_closed, active, day_off),
        kb.close_day(day, slots, closed_slots, day_closed),
    )


# ---------- главное меню ----------

@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    await state.clear()
    await render_home(message, db, settings)
    await safe_delete(message.bot, message.chat.id, message.message_id)


@router.callback_query(AdminCb.filter(F.action == "home"))
async def home(cb: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    await cb.answer()
    await state.clear()
    await render_home(cb, db, settings)


# ---------- записи ----------

@router.callback_query(AdminCb.filter(F.action.in_({"today", "tomorrow"})))
async def day_bookings(cb: CallbackQuery, callback_data: AdminCb, db: Database, settings: Settings) -> None:
    await cb.answer()
    today = now_local(settings.timezone).date()
    await render_day(cb, db, settings, today + timedelta(days=1 if callback_data.action == "tomorrow" else 0))


@router.callback_query(AdminCb.filter(F.action == "view"))
async def view_calendar(cb: CallbackQuery, callback_data: AdminCb, db: Database, settings: Settings) -> None:
    await cb.answer()
    await render_view_calendar(cb, db, settings, parse_month_code(callback_data.value))


@router.callback_query(AdminCb.filter(F.action == "vday"))
async def view_day(cb: CallbackQuery, callback_data: AdminCb, db: Database, settings: Settings) -> None:
    await cb.answer()
    day = _parse_day(callback_data.value)
    if day is None:
        return await render_view_calendar(cb, db, settings)
    await render_day(cb, db, settings, day)


@router.callback_query(AdminCb.filter(F.action == "bk"))
async def view_booking(cb: CallbackQuery, callback_data: AdminCb, db: Database, settings: Settings) -> None:
    await cb.answer()
    if not callback_data.value.isdigit():
        return await render_view_calendar(cb, db, settings)
    await render_booking(cb, db, settings, int(callback_data.value))


@router.callback_query(AdminCb.filter(F.action == "bk_cancel"))
async def ask_cancel_booking(cb: CallbackQuery, callback_data: AdminCb, db: Database, settings: Settings) -> None:
    booking = await db.get_booking(int(callback_data.value)) if callback_data.value.isdigit() else None
    if booking is None or booking.status not in (PENDING, CONFIRMED):
        await cb.answer("Эту запись уже нельзя отменить", show_alert=True)
        return await render_view_calendar(cb, db, settings)
    await cb.answer()
    await show(cb, db, texts.admin_cancel_confirm(booking), kb.booking_cancel_confirm(booking))


@router.callback_query(AdminCb.filter(F.action == "bk_cancel_ok"))
async def cancel_booking(
    cb: CallbackQuery, callback_data: AdminCb, bot: Bot, db: Database, settings: Settings
) -> None:
    booking = await db.get_booking(int(callback_data.value)) if callback_data.value.isdigit() else None
    if booking is None or booking.status not in (PENDING, CONFIRMED):
        await cb.answer("Эту запись уже нельзя отменить", show_alert=True)
        return await render_view_calendar(cb, db, settings)

    await db.cancel_booking(booking.id)
    if booking.status == PENDING:
        await safe_delete(bot, booking.user_id, booking.invoice_message_id)
        await db.set_invoice_message(booking.id, None)
    log.info("Админ %s отменил запись #%s (%s, %s)", cb.from_user.id, booking.id, booking.start, booking.client_name)

    notice = f"❌ Запись #{booking.id} ({booking.start_dt:%d.%m} в {booking.start_dt:%H:%M}) отменена."
    if booking.user_id == cb.from_user.id:
        await cb.answer("Запись отменена")  # админ отменил свою же (тестовую) запись
    else:
        try:
            await send_screen(
                bot, db, booking.user_id,
                *main_menu_screen(settings, booking.user_id, texts.client_cancelled_by_studio(booking, settings)),
            )
            notice += " Клиент получил сообщение."
            await cb.answer("Запись отменена, клиент уведомлён")
        except TelegramAPIError as e:
            log.warning("Не удалось уведомить клиента %s об отмене: %s", booking.user_id, e)
            notice += " ⚠️ Клиенту не удалось написать — свяжитесь с ним."
            await cb.answer()
    if booking.status == CONFIRMED:
        notice += f"\n💸 Не забудьте вернуть предоплату {money(booking.prepay)}."
    await render_home(cb, db, settings, notice=notice)
    await notify_admins_except(bot, settings, cb.from_user.id, texts.admin_cancelled_by_studio(booking))


# ---------- статистика и журнал ----------

@router.callback_query(AdminCb.filter(F.action == "stats"))
async def stats(cb: CallbackQuery, db: Database, settings: Settings) -> None:
    await cb.answer()
    now = now_local(settings.timezone)
    await show(cb, db, texts.admin_stats(await db.stats(now), now), kb.stats())


@router.callback_query(AdminCb.filter(F.action == "logs"))
async def logs(cb: CallbackQuery, callback_data: AdminCb, db: Database, settings: Settings) -> None:
    await cb.answer()
    errors_only = callback_data.value == "err"
    events = read_events(settings.log_path, errors_only=errors_only)
    await show(cb, db, texts.admin_logs(events, errors_only), kb.logs(errors_only))


# ---------- выходные по дням недели ----------

@router.callback_query(AdminCb.filter(F.action == "weekly"))
async def weekly(cb: CallbackQuery, db: Database) -> None:
    await cb.answer()
    off = await db.get_weekly_off()
    await show(cb, db, texts.admin_weekly(off), kb.weekly(off))


@router.callback_query(AdminCb.filter(F.action == "wk"))
async def toggle_weekday(cb: CallbackQuery, callback_data: AdminCb, db: Database) -> None:
    if not callback_data.value.isdigit() or int(callback_data.value) > 6:
        await cb.answer()
        return
    day = int(callback_data.value)
    off = await db.get_weekly_off()
    off ^= {day}
    await db.set_weekly_off(off)
    state = "выходной 💤" if day in off else "рабочий ✅"
    log.info("Админ %s: %s теперь %s", cb.from_user.id, WEEKDAYS_FULL[day], state)
    await cb.answer(f"{WEEKDAYS_FULL[day].capitalize()} — {state}")
    await show(cb, db, texts.admin_weekly(off), kb.weekly(off))


# ---------- закрытие дня / времени ----------

@router.callback_query(AdminCb.filter(F.action == "close"))
async def close_calendar(cb: CallbackQuery, callback_data: AdminCb, db: Database, settings: Settings) -> None:
    await cb.answer()
    await render_close_calendar(cb, db, settings, parse_month_code(callback_data.value))


@router.callback_query(AdminCb.filter(F.action == "day"))
async def close_pick_day(cb: CallbackQuery, callback_data: AdminCb, db: Database, settings: Settings) -> None:
    await cb.answer()
    day = _parse_day(callback_data.value)
    if day is None:
        return await render_close_calendar(cb, db, settings)
    await render_close_day(cb, db, settings, day)


@router.callback_query(AdminCb.filter(F.action == "day_toggle"))
async def toggle_day(cb: CallbackQuery, callback_data: AdminCb, db: Database, settings: Settings) -> None:
    day = _parse_day(callback_data.value)
    if day is None:
        await cb.answer()
        return await render_close_calendar(cb, db, settings)
    start = datetime.combine(day, settings.work_start)
    end = datetime.combine(day, settings.work_end)
    slots = _day_slots(day, settings)
    fully_closed = bool(slots) and len(_closed_slots(await db.blocks_for_day(day), slots, settings)) == len(slots)
    await db.remove_blocks(start, end)
    if fully_closed:
        log.info("Админ %s открыл день %s", cb.from_user.id, day)
        await cb.answer("День открыт 🔓")
    else:
        await db.add_block(start, end)
        log.info("Админ %s закрыл день %s", cb.from_user.id, day)
        await cb.answer("День закрыт 🔒")
    await render_close_day(cb, db, settings, day)


@router.callback_query(AdminCb.filter(F.action == "slot"))
async def toggle_slot(cb: CallbackQuery, callback_data: AdminCb, db: Database, settings: Settings) -> None:
    raw = callback_data.value
    try:
        start = datetime.strptime(raw, "%Y%m%d%H%M")
    except ValueError:
        await cb.answer()
        return await render_close_calendar(cb, db, settings)
    end = start + timedelta(minutes=settings.slot_step_min)
    overlapping = [
        b for b in await db.blocks_for_day(start.date())
        if b.start < to_str(end) and b.end > to_str(start)
    ]
    if overlapping:
        # Открываем слот: снимаем пересекающиеся закрытия и возвращаем их части вне слота
        await db.remove_blocks(start, end)
        for b in overlapping:
            b_start, b_end = from_str(b.start), from_str(b.end)
            if b_start < start:
                await db.add_block(b_start, start)
            if b_end > end:
                await db.add_block(end, b_end)
        log.info("Админ %s открыл время %s", cb.from_user.id, to_str(start))
        await cb.answer(f"{start:%H:%M} открыто 🔓")
    else:
        await db.add_block(start, end)
        log.info("Админ %s закрыл время %s", cb.from_user.id, to_str(start))
        await cb.answer(f"{start:%H:%M} закрыто 🔒")
    await render_close_day(cb, db, settings, start.date())


# ---------- фото в галерею ----------

@router.callback_query(AdminCb.filter(F.action == "photo"))
async def photo_pick(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    await cb.answer()
    await state.clear()
    await show(cb, db, texts.admin_photo_pick(), kb.photo_categories())


@router.callback_query(AdminCb.filter(F.action == "photo_cat"))
async def photo_category(cb: CallbackQuery, callback_data: AdminCb, state: FSMContext, db: Database) -> None:
    await cb.answer()
    if callback_data.value not in CATEGORIES:
        return await show(cb, db, texts.admin_photo_pick(), kb.photo_categories())
    await state.set_state(AdminStates.waiting_photo)
    await state.update_data(photo_category=callback_data.value)
    await show(cb, db, texts.admin_photo_wait(callback_data.value), kb.photo_wait())


@router.message(AdminStates.waiting_photo, F.photo)
async def photo_received(message: Message, state: FSMContext, bot: Bot, db: Database) -> None:
    category = (await state.get_data()).get("photo_category")
    if category not in CATEGORIES:
        await state.clear()
        return
    caption = (message.caption or "").strip()[:200]
    await db.add_photo(category, message.photo[-1].file_id, caption)
    log.info("Админ %s добавил фото в раздел %s", message.from_user.id, category)
    await safe_delete(bot, message.chat.id, message.message_id)
    await show(message, db, texts.admin_photo_saved(category), kb.photo_wait())


@router.message(AdminStates.waiting_photo, ~F.text.startswith("/"))
async def photo_wrong(message: Message, db: Database, bot: Bot, state: FSMContext) -> None:
    category = (await state.get_data()).get("photo_category", "")
    await safe_delete(bot, message.chat.id, message.message_id)
    await show(
        message, db,
        "Нужна именно фотография 📸 (не файлом).\n\n" + texts.admin_photo_wait(category),
        kb.photo_wait(),
    )
