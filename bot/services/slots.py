"""Подбор свободного времени под длительность процедуры (чистая логика, без БД)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Iterable

Interval = tuple[datetime, datetime]


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def free_starts(
    day: date,
    duration_min: int,
    busy: Iterable[Interval],
    now: datetime,
    work_start: time,
    work_end: time,
    step_min: int = 30,
    min_lead_min: int = 30,
) -> list[datetime]:
    """Все времена начала в день `day`, когда процедура длиной `duration_min`
    целиком помещается в рабочие часы и не пересекается с занятыми интервалами."""
    if duration_min <= 0:
        return []

    busy = sorted(busy)
    day_start = datetime.combine(day, work_start)
    day_end = datetime.combine(day, work_end)
    earliest = now + timedelta(minutes=min_lead_min)
    length = timedelta(minutes=duration_min)
    step = timedelta(minutes=step_min)

    result: list[datetime] = []
    start = day_start
    while start + length <= day_end:
        end = start + length
        if start >= earliest and not any(overlaps(start, end, b_s, b_e) for b_s, b_e in busy):
            result.append(start)
        start += step
    return result
