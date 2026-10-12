"""Клавиатуры админ-панели."""
from __future__ import annotations

from datetime import date, datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.demo_data import CATEGORIES, category_title
from bot.keyboards.calendar import calendar_rows, day_code
from bot.keyboards.callbacks import AdminCb


def _btn(text: str, action: str, value: str = "") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=AdminCb(action=action, value=value).pack())


def back(action: str = "home", value: str = "") -> InlineKeyboardButton:
    return _btn("◀️ Назад", action, value)


def home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("📅 Записи на сегодня", "today"), _btn("📅 На завтра", "tomorrow")],
        [_btn("🔒 Закрыть день или время", "close")],
        [_btn("📸 Добавить фото в галерею", "photo")],
    ])


def day_view(current: str) -> InlineKeyboardMarkup:
    other = ("tomorrow", "➡️ На завтра") if current == "today" else ("today", "⬅️ На сегодня")
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🔄 Обновить", current), _btn(other[1], other[0])],
        [back()],
    ])


def close_calendar(days: list[date], closed: set[date]) -> InlineKeyboardMarkup:
    rows = calendar_rows(
        days,
        label=lambda d: "🔒" if d in closed else str(d.day),
        callback=lambda d: AdminCb(action="day", value=day_code(d)).pack(),
    )
    rows.append([back()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def close_day(day: date, slots: list[datetime], closed_slots: set[datetime], day_closed: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for s in slots:
        mark = "🔒 " if s in closed_slots else ""
        kb.add(_btn(f"{mark}{s:%H:%M}", "slot", s.strftime("%Y%m%d%H%M")))
    kb.adjust(4)
    kb.row(_btn("🔓 Открыть весь день" if day_closed else "🔒 Закрыть весь день", "day_toggle", day_code(day)))
    kb.row(back("close"))
    return kb.as_markup()


def photo_categories() -> InlineKeyboardMarkup:
    rows = [[_btn(category_title(key), "photo_cat", key)] for key in CATEGORIES]
    rows.append([back()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def photo_wait() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("✅ Готово", "home")]])
