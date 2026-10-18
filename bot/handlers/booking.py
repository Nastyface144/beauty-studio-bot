"""Пошаговая запись: направление → услуга → опции → мастер → дата → время → подтверждение и оплата."""
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
from bot.services.slots import day_grid, free_starts
from bot.utils.menu import main_menu_screen
from bot.utils.notify import notify_admins
from bot.utils.timeutil import now_local
from bot.utils.ui import safe_delete, show

log = logging.getLogger(__name__)
router = Router(name="booking")

ANY_MASTER = 0  # master_id в FSM: клиент выбрал «любой свободный мастер»


@dataclass
class Selection:
    service: Service
    options: list[Option]
    masters: list[Master]       # кого рассматриваем: одного выбранного или всех подходящих
    any_master: bool
    assigned: Master | None     # конкретный мастер (после выбора времени)

    @property
    def duration(self) -> int:
        return self.service.duration + sum(o.duration for o in self.options)

    @property
    def price(self) -> int:
        return self.service.price + sum(o.price for o in self.options)

    @property
    def master_title(self) -> str:
        if self.assigned:
            return self.assigned.name
        return texts.ANY_MASTER_TITLE if self.any_master else (self.masters[0].name if self.masters else "")


async def _selection(db: Database, data: dict, need_master: bool = False) -> Selection | None:
    """Восстанавливает выбор клиента из FSM. None — если данных не хватает (бот перезапускался и т.п.)."""
    service = await db.get_service(data["service_id"]) if data.get("service_id") else None
    if service is None:
        return None
    options = await db.get_options(data.get("option_ids", []))
    master_id = data.get("master_id")
    masters: list[Master] = []
    any_master = master_id == ANY_MASTER
    if any_master:
        masters = await db.masters_for_category(service.category)
    elif master_id:
        master = await db.get_master(master_id)
        if master is not None and service.category in master.categories:
            masters = [master]
    if need_master and not masters:
        return None
    assigned = None
    if data.get("assigned_master"):
        assigned = next((m for m in masters if m.id == data["assigned_master"]), None)
    return Selection(service, options, masters, any_master, assigned)


async def _expired(cb: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    await state.clear()
    await show(cb, db, *main_menu_screen(settings, cb.from_user.id, texts.SESSION_EXPIRED))


def _booking_days(settings: Settings) -> list[date]:
    today = now_local(settings.timezone).date()
    return [today + timedelta(days=i) for i in range(settings.booking_days)]


async def _free_by_master(
    db: Database, settings: Settings, masters: list[Master], duration: int, days: list[date]
) -> dict[int, dict[date, list[datetime]]]:
    """Свободные начала по каждому мастеру и дню."""
    now = now_local(settings.timezone)
    weekly_off = await db.get_weekly_off()
    result = {}
    for m in masters:
        busy = await db.busy_intervals(m.id, days[0], days[-1], now)
        result[m.id] = {
            d: [] if d.weekday() in weekly_off else free_starts(
                d, duration, busy, now, settings.work_start, settings.work_end,
                settings.slot_step_min, settings.min_lead_min,
            )
            for d in days
        }
    return result


def _union(free: dict[int, dict[date, list[datetime]]], day: date) -> set[datetime]:
    return {s for by_day in free.values() for s in by_day.get(day, [])}


async def _days_off(db: Database, settings: Settings, days: list[date]) -> set[date]:
    """Нерабочие дни: выходные по графику и закрытые целиком (в том числе отпуск)."""
    weekly_off = await db.get_weekly_off()
    closed = await db.closed_days(days[0], days[-1], f"{settings.work_start:%H:%M}", f"{settings.work_end:%H:%M}")
    return {d for d in days if d.weekday() in weekly_off or d in closed}


async def _has_options(db: Database, category: str) -> bool:
    return bool(await db.options(category))


async def _header(db: Database, data: dict, name: str, sel: Selection | None = None) -> str:
    """Шапка шага: «Шаг N из M» и то, что клиент уже выбрал."""
    category = data.get("category")
    with_options = await _has_options(db, category) if category in CATEGORIES else True
    order = ["category", "service"] + (["options"] if with_options else []) + ["master", "date", "time"]
    recap: list[tuple[str, str]] = []
    if sel is not None:
        service = sel.service.name
        if sel.options and name != "options":
            service += " + " + ", ".join(o.name for o in sel.options)
        recap.append(("Услуга", service))
        if name in ("date", "time"):
            recap.append(("Мастер", sel.master_title))
        if name == "time" and data.get("day"):
            recap.append(("Дата", texts.short_date(parse_day_code(data["day"]))))
    return texts.step_header(order.index(name) + 1, len(order), recap)


# ---------- экраны шагов ----------

async def render_categories(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    head = await _header(db, await state.get_data(), "category")
    await show(cb, db, head + texts.choose_category(), kb.categories())


async def render_services(cb: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    data = await state.get_data()
    category = data.get("category")
    if category not in CATEGORIES:
        return await _expired(cb, state, db, settings)
    head = await _header(db, data, "service")
    await show(cb, db, head + texts.choose_service(category), kb.services(await db.services(category)))


async def render_options(cb: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    data = await state.get_data()
    sel = await _selection(db, data)
    if sel is None:
        return await _expired(cb, state, db, settings)
    items = await db.options(sel.service.category)
    selected = {o.id for o in sel.options}
    head = await _header(db, data, "options", sel)
    await show(cb, db, head + texts.choose_options(sel.options, sel.price), kb.options(items, selected))


async def render_masters(cb: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    data = await state.get_data()
    sel = await _selection(db, data)
    if sel is None:
        return await _expired(cb, state, db, settings)
    masters = await db.masters_for_category(sel.service.category)
    back_to = "options" if await _has_options(db, sel.service.category) else "services"
    head = await _header(db, data, "master", sel)
    await show(cb, db, head + texts.choose_master(masters, sel.duration, sel.price), kb.masters(masters, back_to))


async def render_calendar(
    cb: CallbackQuery, state: FSMContext, db: Database, settings: Settings, note: str = ""
) -> None:
    data = await state.get_data()
    sel = await _selection(db, data, need_master=True)
    if sel is None:
        return await _expired(cb, state, db, settings)
    days = _booking_days(settings)
    free = await _free_by_master(db, settings, sel.masters, sel.duration, days)
    available = {d for d in days if _union(free, d)}
    day_off = await _days_off(db, settings, days)
    text = await _header(db, data, "date", sel) + texts.choose_date()
    if note:
        text = f"{note}\n\n{text}"
    if not available:
        text += "\n\n" + texts.no_slots(settings.booking_days, sel.any_master)
    await show(cb, db, text, kb.booking_calendar(days, available, _calendar_month(data, available), day_off))


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
    free = _union(await _free_by_master(db, settings, sel.masters, sel.duration, [day]), day)
    if not free:
        return await render_calendar(cb, state, db, settings, note=texts.DAY_FULL)
    now = now_local(settings.timezone)
    # Сетка возможных начал одинакова для всех мастеров; свободно — если свободен хотя бы один
    candidates = day_grid(
        day, sel.duration, [], now, settings.work_start, settings.work_end,
        settings.slot_step_min, settings.min_lead_min,
    )
    grid = [(start, start in free) for start, _ in candidates]
    text = await _header(db, data, "time", sel) + texts.choose_time(sel.duration)
    await show(cb, db, text, kb.times(grid))


async def render_summary(cb: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    data = await state.get_data()
    sel = await _selection(db, data, need_master=True)
    if sel is None or sel.assigned is None or not data.get("day") or not data.get("time"):
        return await _expired(cb, state, db, settings)
    start = _start_from(data)
    prepay = calc_prepay(sel.price, settings.prepay_percent)
    text = texts.summary(sel.service, sel.options, sel.assigned.name, start, sel.duration, sel.price, prepay, settings)
    await show(cb, db, text, kb.summary(settings, sel.price, prepay))


def _start_from(data: dict) -> datetime:
    raw = data["time"]
    return datetime.combine(parse_day_code(data["day"]), time(int(raw[:2]), int(raw[2:])))


async def _pick_master_for(db: Database, settings: Settings, sel: Selection, start: datetime) -> Master | None:
    """Мастер, свободный в это время. При «любом мастере» — наименее загруженный в этот день."""
    day = start.date()
    free = await _free_by_master(db, settings, sel.masters, sel.duration, [day])
    candidates = [m for m in sel.masters if start in free[m.id][day]]
    if len(candidates) <= 1:
        return candidates[0] if candidates else None
    now = now_local(settings.timezone)
    loads = {}
    for m in candidates:
        busy = await db.busy_intervals(m.id, day, day, now)
        loads[m.id] = sum((e - s).total_seconds() for s, e in busy)
    return min(candidates, key=lambda m: loads[m.id])


# ---------- обработчики ----------

@router.callback_query(MenuCb.filter(F.action == "book"))
async def start_booking(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    await cb.answer()
    await state.clear()
    await db.upsert_user(cb.from_user.id, cb.from_user.full_name, cb.from_user.username)
    await render_categories(cb, state, db)


@router.callback_query(BookCb.filter(F.action == "cat"))
async def pick_category(
    cb: CallbackQuery, callback_data: BookCb, state: FSMContext, db: Database, settings: Settings
) -> None:
    await cb.answer()
    if callback_data.value not in CATEGORIES:
        return await render_categories(cb, state, db)
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
    await state.update_data(
        category=service.category, service_id=service.id, option_ids=[], master_id=None, assigned_master=None,
    )
    if await _has_options(db, service.category):
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
    await state.update_data(
        master_id=int(callback_data.value), assigned_master=None, day=None, time=None, month=None,
    )
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
    await cb.answer()
    try:
        day = parse_day_code(callback_data.value)
    except ValueError:
        return await _expired(cb, state, db, settings)
    if day not in _booking_days(settings):
        return await render_calendar(cb, state, db, settings, note=texts.DATE_UNAVAILABLE)
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
    chosen = datetime.combine(day, time(int(raw[:2]) % 24, int(raw[2:]) % 60))
    master = await _pick_master_for(db, settings, sel, chosen)
    if master is None:
        await cb.answer(texts.SLOT_TAKEN, show_alert=True)
        return await render_times(cb, state, db, settings)
    await cb.answer()
    await state.update_data(time=raw, assigned_master=master.id)
    await render_summary(cb, state, db, settings)


@router.callback_query(BookCb.filter(F.action == "back"))
async def go_back(
    cb: CallbackQuery, callback_data: BookCb, state: FSMContext, db: Database, settings: Settings
) -> None:
    await cb.answer()
    target = callback_data.value
    if target in ("calendar", "times"):
        await state.update_data(assigned_master=None)
    if target == "services":
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
        await render_categories(cb, state, db)


async def _create(db: Database, settings: Settings, cb: CallbackQuery, sel: Selection, master: Master,
                  start: datetime, now: datetime, pay_on_site: bool):
    return await db.create_booking(
        user_id=cb.from_user.id, master=master, service=sel.service, options=sel.options,
        start=start, duration=sel.duration, price=sel.price,
        prepay=calc_prepay(sel.price, settings.prepay_percent),
        now=now, hold_minutes=settings.hold_minutes, pay_on_site=pay_on_site,
    )


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
    if sel is None or sel.assigned is None or not data.get("day") or not data.get("time"):
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

    booking = await _create(db, settings, cb, sel, sel.assigned, start, now, pay_on_site)
    if booking is None and sel.any_master:
        # Мастера только что заняли — подбираем другого, свободного в это же время
        other = await _pick_master_for(db, settings, sel, start)
        if other is not None:
            booking = await _create(db, settings, cb, sel, other, start, now, pay_on_site)
    if booking is None:
        await cb.answer()
        return await show(cb, db, texts.SLOT_TAKEN, kb.slot_taken())

    log.info(
        "Новая %s #%s: %s, %s, мастер %s, клиент %s",
        "запись (оплата в салоне)" if pay_on_site else "бронь (оплата картой)",
        booking.id, booking.start, booking.service_name, booking.master_name, cb.from_user.full_name,
    )
    await state.clear()
    if pay_on_site:
        await cb.answer("Запись подтверждена")
        menu = kb.main_menu(is_admin=cb.from_user.id in settings.admin_ids)
        await show(cb, db, texts.payment_success(booking, settings), menu)
    else:
        await cb.answer("Время забронировано")
        await send_payment(bot, db, settings, booking)
    await notify_admins(bot, settings, texts.admin_new_booking(booking))
