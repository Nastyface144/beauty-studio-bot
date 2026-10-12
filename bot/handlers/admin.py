"""Админ-панель: записи на сегодня/завтра, закрытие дня или времени, фото в галерею."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command, Filter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot import texts
from bot.config import Settings
from bot.database.db import Database
from bot.demo_data import CATEGORIES
from bot.keyboards import admin as kb
from bot.keyboards.calendar import parse_day_code
from bot.keyboards.callbacks import AdminCb
from bot.utils.timeutil import from_str, now_local, to_str
from bot.utils.ui import safe_delete, show


class IsAdmin(Filter):
    async def __call__(self, event: TelegramObject, settings: Settings) -> bool:
        user = getattr(event, "from_user", None)
        return user is not None and user.id in settings.admin_ids


class AdminStates(StatesGroup):
    waiting_photo = State()


router = Router(name="admin")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


def _day_range(settings: Settings) -> list[date]:
    today = now_local(settings.timezone).date()
    return [today + timedelta(days=i) for i in range(settings.booking_days + 14)]


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


async def render_home(event, db: Database, settings: Settings) -> None:
    await show(event, db, texts.admin_home(settings), kb.home())


async def render_day_bookings(cb: CallbackQuery, db: Database, settings: Settings, which: str) -> None:
    now = now_local(settings.timezone)
    day = now.date() + timedelta(days=1 if which == "tomorrow" else 0)
    bookings = await db.bookings_for_day(day, now)
    await show(cb, db, texts.admin_day(day, bookings), kb.day_view(which))


async def render_close_calendar(cb: CallbackQuery, db: Database, settings: Settings) -> None:
    days = _day_range(settings)
    closed = await db.closed_days(
        days[0], days[-1], f"{settings.work_start:%H:%M}", f"{settings.work_end:%H:%M}"
    )
    await show(cb, db, texts.admin_close_pick_day(), kb.close_calendar(days, closed))


async def render_close_day(cb: CallbackQuery, db: Database, settings: Settings, day: date) -> None:
    now = now_local(settings.timezone)
    slots = _day_slots(day, settings)
    closed_slots = _closed_slots(await db.blocks_for_day(day), slots, settings)
    day_closed = bool(slots) and len(closed_slots) == len(slots)
    day_start = datetime.combine(day, settings.work_start)
    day_end = datetime.combine(day, settings.work_end)
    active = await db.count_active_between(day_start, day_end, now)
    await show(
        cb, db,
        texts.admin_close_day(day, day_closed, active),
        kb.close_day(day, slots, closed_slots, day_closed),
    )


# ---------- команды ----------

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


@router.callback_query(AdminCb.filter(F.action.in_({"today", "tomorrow"})))
async def day_bookings(cb: CallbackQuery, callback_data: AdminCb, db: Database, settings: Settings) -> None:
    await cb.answer()
    await render_day_bookings(cb, db, settings, callback_data.action)


# ---------- закрытие дня / времени ----------

@router.callback_query(AdminCb.filter(F.action == "close"))
async def close_calendar(cb: CallbackQuery, db: Database, settings: Settings) -> None:
    await cb.answer()
    await render_close_calendar(cb, db, settings)


@router.callback_query(AdminCb.filter(F.action == "day"))
async def close_pick_day(cb: CallbackQuery, callback_data: AdminCb, db: Database, settings: Settings) -> None:
    await cb.answer()
    try:
        day = parse_day_code(callback_data.value)
    except ValueError:
        return await render_close_calendar(cb, db, settings)
    await render_close_day(cb, db, settings, day)


@router.callback_query(AdminCb.filter(F.action == "day_toggle"))
async def toggle_day(cb: CallbackQuery, callback_data: AdminCb, db: Database, settings: Settings) -> None:
    try:
        day = parse_day_code(callback_data.value)
    except ValueError:
        await cb.answer()
        return await render_close_calendar(cb, db, settings)
    start = datetime.combine(day, settings.work_start)
    end = datetime.combine(day, settings.work_end)
    slots = _day_slots(day, settings)
    fully_closed = bool(slots) and len(_closed_slots(await db.blocks_for_day(day), slots, settings)) == len(slots)
    await db.remove_blocks(start, end)
    if fully_closed:
        await cb.answer("День открыт 🔓")
    else:
        await db.add_block(start, end)
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
        await cb.answer(f"{start:%H:%M} открыто 🔓")
    else:
        await db.add_block(start, end)
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
