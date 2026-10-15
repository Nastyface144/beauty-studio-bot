"""Клавиатуры админ-панели."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.database.models import CONFIRMED, Booking
from bot.demo_data import CATEGORIES, category_title
from bot.keyboards.calendar import calendar_rows, day_code
from bot.keyboards.callbacks import AdminCb
from bot.utils.timeutil import WEEKDAYS_FULL


def _btn(text: str, action: str, value: str = "") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=AdminCb(action=action, value=value).pack())


def back(action: str = "home", value: str = "", text: str = "◀️ Назад") -> InlineKeyboardButton:
    return _btn(text, action, value)


def home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("📅 Сегодня", "today"), _btn("📅 Завтра", "tomorrow")],
        [_btn("📋 Все записи по датам", "view")],
        [_btn("🔒 Закрыть день или время", "close")],
        [_btn("💤 Выходные по дням недели", "weekly")],
        [_btn("📊 Статистика", "stats"), _btn("🧾 Журнал", "logs", "all")],
        [_btn("📸 Добавить фото в галерею", "photo")],
    ])


def day_view(day: date, bookings: list[Booking]) -> InlineKeyboardMarkup:
    rows = []
    for b in bookings:
        mark = "✅" if b.status in (CONFIRMED, "completed") else "⏳"
        text = f"{mark} {b.start[-5:]} · {b.master_name} · {b.client_name or 'Клиент'}"
        rows.append([_btn(text[:60], "bk", str(b.id))])
    prev_day, next_day = day - timedelta(days=1), day + timedelta(days=1)
    rows.append([
        _btn(f"◀️ {prev_day:%d.%m}", "vday", day_code(prev_day)),
        _btn("🔄", "vday", day_code(day)),
        _btn(f"{next_day:%d.%m} ▶️", "vday", day_code(next_day)),
    ])
    rows.append([_btn("📅 Другая дата", "view")])
    rows.append([back(text="◀️ В админку")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def view_calendar(days: list[date], counts: dict[date, int], weekly_off: set[int]) -> InlineKeyboardMarkup:
    def label(d: date) -> str:
        if counts.get(d):
            return f"{d.day}•"
        if d.weekday() in weekly_off:
            return "💤"
        return str(d.day)

    rows = calendar_rows(days, label=label, callback=lambda d: AdminCb(action="vday", value=day_code(d)).pack())
    rows.append([back()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def booking_card(b: Booking, can_cancel: bool) -> InlineKeyboardMarkup:
    rows = []
    if can_cancel:
        rows.append([_btn("❌ Отменить запись", "bk_cancel", str(b.id))])
    rows.append([back("vday", day_code(b.start_dt.date()), "◀️ К записям дня")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def booking_cancel_confirm(b: Booking) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("Да, отменить и уведомить клиента", "bk_cancel_ok", str(b.id))],
        [back("bk", str(b.id), "◀️ Нет, оставить")],
    ])


def close_calendar(days: list[date], closed: set[date], weekly_off: set[int]) -> InlineKeyboardMarkup:
    def label(d: date) -> str:
        if d in closed:
            return "🔒"
        if d.weekday() in weekly_off:
            return "💤"
        return str(d.day)

    rows = calendar_rows(days, label=label, callback=lambda d: AdminCb(action="day", value=day_code(d)).pack())
    rows.append([back()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def close_day(day: date, slots: list[datetime], closed_slots: set[datetime], day_closed: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for s in slots:
        mark = "🔒 " if s in closed_slots else ""
        kb.add(_btn(f"{mark}{s:%H:%M}", "slot", s.strftime("%Y%m%d%H%M")))
    kb.adjust(4)
    kb.row(_btn("🔓 Открыть весь день" if day_closed else "🔒 Закрыть весь день", "day_toggle", day_code(day)))
    kb.row(_btn("📋 Записи на этот день", "vday", day_code(day)))
    kb.row(back("close"))
    return kb.as_markup()


def weekly(off: set[int]) -> InlineKeyboardMarkup:
    rows = []
    for i, name in enumerate(WEEKDAYS_FULL):
        state = "💤 выходной" if i in off else "✅ рабочий"
        rows.append([_btn(f"{name.capitalize()} — {state}", "wk", str(i))])
    rows.append([back()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def stats() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🔄 Обновить", "stats")],
        [back()],
    ])


def logs(errors_only: bool) -> InlineKeyboardMarkup:
    current = "err" if errors_only else "all"
    switch = ("🧾 Все события", "all") if errors_only else ("⚠️ Только ошибки", "err")
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🔄 Обновить", "logs", current), _btn(switch[0], "logs", switch[1])],
        [back()],
    ])


def photo_categories() -> InlineKeyboardMarkup:
    rows = [[_btn(category_title(key), "photo_cat", key)] for key in CATEGORIES]
    rows.append([back()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def photo_wait() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("✅ Готово", "home")]])
