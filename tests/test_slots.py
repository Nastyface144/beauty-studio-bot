from datetime import date, datetime, time

from bot.services.slots import free_starts

DAY = date(2026, 10, 20)
OPEN, CLOSE = time(9, 0), time(20, 0)
EARLY = datetime(2026, 10, 1, 12, 0)


def dt(h, m=0):
    return datetime.combine(DAY, time(h, m))


def test_empty_day_fits_until_closing():
    starts = free_starts(DAY, 90, [], EARLY, OPEN, CLOSE)
    assert starts[0] == dt(9)
    assert starts[-1] == dt(18, 30)  # 18:30 + 1:30 = 20:00
    assert len(starts) == 20


def test_busy_interval_excludes_overlapping_starts():
    busy = [(dt(12), dt(13, 30))]
    starts = free_starts(DAY, 60, busy, EARLY, OPEN, CLOSE)
    assert dt(11) in starts          # 11:00–12:00 вплотную до занятого
    assert dt(11, 30) not in starts  # залезает на 12:00
    assert dt(13) not in starts
    assert dt(13, 30) in starts      # сразу после


def test_long_procedure_needs_whole_gap():
    busy = [(dt(9), dt(10)), (dt(12), dt(20))]
    assert free_starts(DAY, 150, busy, EARLY, OPEN, CLOSE) == []
    assert free_starts(DAY, 120, busy, EARLY, OPEN, CLOSE) == [dt(10)]


def test_today_respects_lead_time():
    now = dt(14, 10)
    starts = free_starts(DAY, 60, [], now, OPEN, CLOSE, min_lead_min=30)
    assert starts[0] == dt(15)


def test_odd_duration_from_options():
    # 120 + 15 мин: последнее начало 17:30 (до 19:45)
    starts = free_starts(DAY, 135, [], EARLY, OPEN, CLOSE)
    assert starts[-1] == dt(17, 30)
