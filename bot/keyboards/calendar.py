"""Инлайн-календарь на N дней вперёд."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

from aiogram.types import InlineKeyboardButton

from bot.keyboards.callbacks import NOOP
from bot.utils.timeutil import MONTHS_NOM, WEEKDAYS_SHORT


def day_code(d: date) -> str:
    return d.strftime("%Y%m%d")


def parse_day_code(raw: str) -> date:
    return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))


def month_code(year: int, month: int) -> str:
    return f"{year:04d}{month:02d}"


def parse_month_code(raw: str) -> tuple[int, int] | None:
    if len(raw) != 6 or not raw.isdigit():
        return None
    year, month = int(raw[:4]), int(raw[4:])
    return (year, month) if 1 <= month <= 12 else None


def months_of(days: list[date]) -> list[tuple[int, int]]:
    """Месяцы, в которые попадают дни диапазона, по порядку."""
    result: list[tuple[int, int]] = []
    for d in days:
        if (d.year, d.month) not in result:
            result.append((d.year, d.month))
    return result


def pick_month(days: list[date], wanted: tuple[int, int] | None) -> tuple[int, int] | None:
    months = months_of(days)
    if not months:
        return None
    return wanted if wanted in months else months[0]


def _noop(text: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=NOOP)


def calendar_rows(
    days: list[date],
    label: Callable[[date], str | None],
    callback: Callable[[date], str],
    month: tuple[int, int] | None = None,
    nav: Callable[[tuple[int, int]], str] | None = None,
) -> list[list[InlineKeyboardButton]]:
    """Календарь на один месяц: ◀️ Месяц ▶️, дни недели и сетка по неделям.

    Показываются только дни диапазона `days`, попавшие в `month`. Стрелки листают
    к соседним месяцам диапазона (callback из `nav`). `label(d)` возвращает текст
    кнопки для доступного дня или None для недоступного.
    """
    months = months_of(days)
    month = pick_month(days, month)
    if month is None:
        return []
    idx = months.index(month)
    prev_btn = (
        InlineKeyboardButton(text="◀️", callback_data=nav(months[idx - 1]))
        if nav and idx > 0 else _noop(" ")
    )
    next_btn = (
        InlineKeyboardButton(text="▶️", callback_data=nav(months[idx + 1]))
        if nav and idx < len(months) - 1 else _noop(" ")
    )
    rows = [
        [prev_btn, _noop(f"{MONTHS_NOM[month[1] - 1]} {month[0]}"), next_btn],
        [_noop(w) for w in WEEKDAYS_SHORT],
    ]

    in_range = {d for d in days if (d.year, d.month) == month}
    first, last = min(in_range), max(in_range)
    cursor = first - timedelta(days=first.weekday())
    while cursor <= last:
        row = []
        for _ in range(7):
            if cursor not in in_range:
                row.append(_noop(" "))
            else:
                text = label(cursor)
                if text is None:
                    row.append(_noop("✕"))
                else:
                    row.append(InlineKeyboardButton(text=text, callback_data=callback(cursor)))
            cursor += timedelta(days=1)
        rows.append(row)
    return rows
