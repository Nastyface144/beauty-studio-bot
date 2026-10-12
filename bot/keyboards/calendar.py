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


def _noop(text: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=NOOP)


def calendar_rows(
    days: list[date],
    label: Callable[[date], str | None],
    callback: Callable[[date], str],
) -> list[list[InlineKeyboardButton]]:
    """Строки календаря: заголовок месяца, дни недели и сетка по неделям.

    `label(d)` возвращает текст кнопки для доступного дня или None для недоступного.
    """
    if not days:
        return []
    first, last = days[0], days[-1]
    months = MONTHS_NOM[first.month - 1]
    if last.month != first.month:
        months += f" – {MONTHS_NOM[last.month - 1]}"
    rows = [[_noop(f"🗓 {months} {last.year}")], [_noop(w) for w in WEEKDAYS_SHORT]]

    in_range = set(days)
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
