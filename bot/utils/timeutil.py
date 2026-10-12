"""Работа с датой и временем студии.

В базе всё хранится в локальном времени студии строками «YYYY-MM-DD HH:MM»,
поэтому сравнение строк совпадает с хронологическим порядком.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

DT_FMT = "%Y-%m-%d %H:%M"
D_FMT = "%Y-%m-%d"

WEEKDAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
WEEKDAYS_FULL = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
MONTHS_GEN = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]
MONTHS_NOM = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]


def now_local(tz: ZoneInfo) -> datetime:
    """Текущее время студии без tzinfo (как в базе)."""
    return datetime.now(tz).replace(tzinfo=None, second=0, microsecond=0)


def to_str(dt: datetime) -> str:
    return dt.strftime(DT_FMT)


def from_str(raw: str) -> datetime:
    return datetime.strptime(raw, DT_FMT)


def date_to_str(d: date) -> str:
    return d.strftime(D_FMT)


def date_from_str(raw: str) -> date:
    return datetime.strptime(raw, D_FMT).date()


def human_date(d: date) -> str:
    """12 октября, понедельник"""
    return f"{d.day} {MONTHS_GEN[d.month - 1]}, {WEEKDAYS_FULL[d.weekday()]}"


def human_dt(dt: datetime) -> str:
    """12 октября (пн) в 14:30"""
    return f"{dt.day} {MONTHS_GEN[dt.month - 1]} ({WEEKDAYS_SHORT[dt.weekday()].lower()}) в {dt:%H:%M}"


def human_duration(minutes: int) -> str:
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours} ч {mins} мин"
    if hours:
        return f"{hours} ч"
    return f"{mins} мин"


def money(value: int) -> str:
    return f"{value:,}".replace(",", " ") + " ₽"
