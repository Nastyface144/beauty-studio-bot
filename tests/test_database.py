from datetime import date, datetime, timedelta

from bot.database.models import CANCELLED, COMPLETED, CONFIRMED, EXPIRED, PENDING

NOW = datetime(2026, 10, 12, 10, 0)


async def _book(db, user_id=1, start=datetime(2026, 10, 14, 12, 0), master_id=1, service_id=2, now=NOW):
    master = await db.get_master(master_id)
    service = await db.get_service(service_id)
    return await db.create_booking(
        user_id=user_id, master=master, service=service, options=[],
        start=start, duration=service.duration, price=service.price,
        prepay=service.price * 30 // 100, now=now, hold_minutes=15,
    )


async def test_seed(db):
    assert len(await db.services()) == 8
    assert len(await db.masters_for_category("nails")) == 2
    assert len(await db.options("nails")) == 3
    assert await db.options("brows") == []
    assert len(await db.gallery("nails")) == 3


async def test_slot_cannot_be_double_booked(db):
    first = await _book(db, user_id=1)
    assert first and first.status == PENDING
    assert await _book(db, user_id=2) is None                       # тот же мастер, то же время
    assert await _book(db, user_id=2, master_id=2) is not None      # другой мастер — можно


async def test_new_pending_replaces_old_one(db):
    first = await _book(db, user_id=1)
    await _book(db, user_id=1, start=datetime(2026, 10, 15, 12, 0))
    assert (await db.get_booking(first.id)).status == CANCELLED


async def test_hold_expires_and_frees_slot(db):
    booking = await _book(db)
    later = NOW + timedelta(minutes=16)
    expired = await db.expire_pending(later)
    assert [b.id for b in expired] == [booking.id]
    assert (await db.get_booking(booking.id)).status == EXPIRED
    assert await _book(db, user_id=2, now=later) is not None


async def test_payment_confirms_and_sets_reminder_flags(db):
    booking = await _book(db)
    confirmed, ok = await db.confirm_payment(booking.id, "charge", NOW + timedelta(minutes=5))
    assert ok and confirmed.status == CONFIRMED
    # визит через двое суток — оба напоминания впереди
    assert await db.due_reminders(datetime(2026, 10, 13, 12, 0), 24)
    assert not await db.due_reminders(datetime(2026, 10, 13, 12, 0), 2)
    assert await db.due_reminders(datetime(2026, 10, 14, 10, 30), 2)


async def test_late_payment_conflict(db):
    booking = await _book(db)
    later = NOW + timedelta(minutes=20)
    await db.expire_pending(later)
    other = await _book(db, user_id=2, now=later)
    assert other is not None
    _, ok = await db.confirm_payment(booking.id, "charge", later)
    assert not ok


async def test_late_payment_without_conflict_is_accepted(db):
    booking = await _book(db)
    later = NOW + timedelta(minutes=20)
    await db.expire_pending(later)
    confirmed, ok = await db.confirm_payment(booking.id, "charge", later)
    assert ok and confirmed.status == CONFIRMED


async def test_visit_finishes_and_rating_once(db):
    booking = await _book(db)
    await db.confirm_payment(booking.id, "charge", NOW)
    done = await db.finish_visits(datetime(2026, 10, 14, 14, 0))
    assert [b.id for b in done] == [booking.id]
    assert (await db.get_booking(booking.id)).status == COMPLETED
    assert await db.set_rating(booking.id, 1, 5) is not None
    assert await db.set_rating(booking.id, 1, 1) is None      # повторно нельзя
    assert await db.set_rating(booking.id, 999, 5) is None    # чужую нельзя


async def test_blocks_make_time_busy(db):
    await db.add_block(datetime(2026, 10, 14, 9, 0), datetime(2026, 10, 14, 20, 0))
    assert await _book(db) is None
    closed = await db.closed_days(date(2026, 10, 12), date(2026, 10, 25), "09:00", "20:00")
    assert closed == {date(2026, 10, 14)}
    await db.remove_blocks(datetime(2026, 10, 14, 9, 0), datetime(2026, 10, 14, 20, 0))
    assert await _book(db) is not None
