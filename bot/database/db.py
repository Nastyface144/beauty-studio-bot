"""Доступ к SQLite через aiosqlite.

Используется одно соединение на всё приложение. Операции из нескольких
запросов (создание записи, подтверждение оплаты) выполняются под asyncio.Lock,
чтобы два клиента не могли занять один и тот же слот одновременно.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import aiosqlite

from bot import demo_data
from bot.database.models import (
    CANCELLED, COMPLETED, CONFIRMED, EXPIRED, PENDING,
    Block, Booking, GalleryItem, Master, Option, Service,
)
from bot.utils.timeutil import date_to_str, from_str, to_str

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id       INTEGER PRIMARY KEY,
    full_name     TEXT NOT NULL DEFAULT '',
    username      TEXT,
    ui_message_id INTEGER,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS masters (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    about      TEXT NOT NULL DEFAULT '',
    categories TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS services (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    category    TEXT NOT NULL,
    name        TEXT NOT NULL,
    price       INTEGER NOT NULL,
    duration    INTEGER NOT NULL,
    description TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS options (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    name     TEXT NOT NULL,
    price    INTEGER NOT NULL,
    duration INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS bookings (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id            INTEGER NOT NULL,
    master_id          INTEGER NOT NULL,
    master_name        TEXT NOT NULL,
    service_id         INTEGER NOT NULL,
    service_name       TEXT NOT NULL,
    option_ids         TEXT NOT NULL DEFAULT '[]',
    options_text       TEXT NOT NULL DEFAULT '',
    start              TEXT NOT NULL,
    end                TEXT NOT NULL,
    price              INTEGER NOT NULL,
    prepay             INTEGER NOT NULL,
    status             TEXT NOT NULL,
    expires_at         TEXT,
    invoice_message_id INTEGER,
    charge_id          TEXT,
    reminded_24        INTEGER NOT NULL DEFAULT 0,
    reminded_2         INTEGER NOT NULL DEFAULT 0,
    review_requested   INTEGER NOT NULL DEFAULT 0,
    rating             INTEGER,
    created_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bookings_master_start ON bookings(master_id, start);
CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings(user_id);
CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(status);
CREATE TABLE IF NOT EXISTS blocks (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    start TEXT NOT NULL,
    end   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gallery (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    category   TEXT NOT NULL,
    file_id    TEXT,
    file_path  TEXT,
    caption    TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

BOOKING_SELECT = """
SELECT b.*, COALESCE(u.full_name, '') AS client_name, u.username AS client_username
FROM bookings b LEFT JOIN users u ON u.user_id = b.user_id
"""

# Запись занимает слот, если оплачена или ещё ждёт оплаты и бронь не истекла
ACTIVE_CONDITION = "(b.status = 'confirmed' OR (b.status = 'pending' AND b.expires_at > :now))"


def _booking(row: aiosqlite.Row) -> Booking:
    return Booking(
        id=row["id"],
        user_id=row["user_id"],
        master_id=row["master_id"],
        master_name=row["master_name"],
        service_id=row["service_id"],
        service_name=row["service_name"],
        options_text=row["options_text"],
        start=row["start"],
        end=row["end"],
        price=row["price"],
        prepay=row["prepay"],
        status=row["status"],
        expires_at=row["expires_at"],
        invoice_message_id=row["invoice_message_id"],
        rating=row["rating"],
        client_name=row["client_name"],
        client_username=row["client_username"],
    )


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    # ---------- lifecycle ----------

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path, isolation_level=None)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(SCHEMA)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("База данных не подключена")
        return self._conn

    async def _fetchone(self, sql: str, params=()) -> aiosqlite.Row | None:
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchone()

    async def _fetchall(self, sql: str, params=()) -> list[aiosqlite.Row]:
        async with self.conn.execute(sql, params) as cur:
            return list(await cur.fetchall())

    async def seed_demo_data(self, gallery_dir: Path) -> None:
        """Заполняет справочники демо-данными при первом запуске."""
        row = await self._fetchone("SELECT COUNT(*) AS c FROM masters")
        if row["c"]:
            return
        log.info("Первый запуск: заполняю демо-данные")
        await self.conn.executemany(
            "INSERT INTO masters(name, about, categories) VALUES (?, ?, ?)", demo_data.MASTERS
        )
        await self.conn.executemany(
            "INSERT INTO services(category, name, price, duration, description) VALUES (?, ?, ?, ?, ?)",
            demo_data.SERVICES,
        )
        await self.conn.executemany(
            "INSERT INTO options(category, name, price, duration) VALUES (?, ?, ?, ?)",
            demo_data.OPTIONS,
        )
        # Путь храним относительно папки галереи, чтобы проект можно было переносить
        photos = [
            (cat, name, caption)
            for cat, name, caption in demo_data.GALLERY
            if (gallery_dir / name).exists()
        ]
        await self.conn.executemany(
            "INSERT INTO gallery(category, file_path, caption) VALUES (?, ?, ?)", photos
        )

    # ---------- users ----------

    async def upsert_user(self, user_id: int, full_name: str, username: str | None) -> None:
        await self.conn.execute(
            """INSERT INTO users(user_id, full_name, username) VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET full_name = excluded.full_name,
                                                  username = excluded.username""",
            (user_id, full_name, username),
        )

    async def get_ui_message(self, user_id: int) -> int | None:
        row = await self._fetchone("SELECT ui_message_id FROM users WHERE user_id = ?", (user_id,))
        return row["ui_message_id"] if row else None

    async def set_ui_message(self, user_id: int, message_id: int) -> None:
        await self.conn.execute(
            """INSERT INTO users(user_id, ui_message_id) VALUES (?, ?)
               ON CONFLICT(user_id) DO UPDATE SET ui_message_id = excluded.ui_message_id""",
            (user_id, message_id),
        )

    # ---------- catalog ----------

    async def masters_for_category(self, category: str) -> list[Master]:
        rows = await self._fetchall("SELECT * FROM masters ORDER BY id")
        masters = [
            Master(r["id"], r["name"], r["about"], r["categories"].split(","))
            for r in rows
        ]
        return [m for m in masters if category in m.categories]

    async def get_master(self, master_id: int) -> Master | None:
        r = await self._fetchone("SELECT * FROM masters WHERE id = ?", (master_id,))
        return Master(r["id"], r["name"], r["about"], r["categories"].split(",")) if r else None

    async def services(self, category: str | None = None) -> list[Service]:
        if category:
            rows = await self._fetchall(
                "SELECT * FROM services WHERE category = ? ORDER BY id", (category,)
            )
        else:
            rows = await self._fetchall("SELECT * FROM services ORDER BY id")
        return [Service(r["id"], r["category"], r["name"], r["price"], r["duration"], r["description"]) for r in rows]

    async def get_service(self, service_id: int) -> Service | None:
        r = await self._fetchone("SELECT * FROM services WHERE id = ?", (service_id,))
        if not r:
            return None
        return Service(r["id"], r["category"], r["name"], r["price"], r["duration"], r["description"])

    async def options(self, category: str) -> list[Option]:
        rows = await self._fetchall("SELECT * FROM options WHERE category = ? ORDER BY id", (category,))
        return [Option(r["id"], r["category"], r["name"], r["price"], r["duration"]) for r in rows]

    async def get_options(self, ids: list[int]) -> list[Option]:
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        rows = await self._fetchall(f"SELECT * FROM options WHERE id IN ({marks}) ORDER BY id", ids)
        return [Option(r["id"], r["category"], r["name"], r["price"], r["duration"]) for r in rows]

    # ---------- availability ----------

    async def busy_intervals(
        self, master_id: int, day_from: date, day_to: date, now: datetime
    ) -> list[tuple[datetime, datetime]]:
        """Занятые интервалы мастера (активные записи + закрытое время студии)."""
        lo = date_to_str(day_from) + " 00:00"
        hi = date_to_str(day_to + timedelta(days=1)) + " 00:00"
        rows = await self._fetchall(
            f"""SELECT b.start, b.end FROM bookings b
                WHERE b.master_id = :master AND b.start < :hi AND b.end > :lo AND {ACTIVE_CONDITION}
                UNION ALL
                SELECT start, end FROM blocks WHERE start < :hi AND end > :lo""",
            {"master": master_id, "lo": lo, "hi": hi, "now": to_str(now)},
        )
        return [(from_str(r["start"]), from_str(r["end"])) for r in rows]

    async def _slot_taken(
        self, master_id: int, start: str, end: str, now: datetime, exclude_id: int | None = None
    ) -> bool:
        row = await self._fetchone(
            f"""SELECT 1 FROM bookings b
                WHERE b.master_id = :master AND b.start < :end AND b.end > :start
                  AND b.id != :exclude AND {ACTIVE_CONDITION}
                UNION ALL
                SELECT 1 FROM blocks WHERE start < :end AND end > :start
                LIMIT 1""",
            {"master": master_id, "start": start, "end": end, "now": to_str(now), "exclude": exclude_id or 0},
        )
        return row is not None

    # ---------- bookings ----------

    async def create_booking(
        self,
        *,
        user_id: int,
        master: Master,
        service: Service,
        options: list[Option],
        start: datetime,
        duration: int,
        price: int,
        prepay: int,
        now: datetime,
        hold_minutes: int,
    ) -> Booking | None:
        """Создаёт запись в статусе «ждёт оплаты». None — если слот уже заняли."""
        start_s = to_str(start)
        end_s = to_str(start + timedelta(minutes=duration))
        async with self._lock:
            # У клиента может быть только одна неоплаченная бронь — старую отпускаем
            await self.conn.execute(
                "UPDATE bookings SET status = ? WHERE user_id = ? AND status = ?",
                (CANCELLED, user_id, PENDING),
            )
            if await self._slot_taken(master.id, start_s, end_s, now):
                return None
            cur = await self.conn.execute(
                """INSERT INTO bookings(user_id, master_id, master_name, service_id, service_name,
                       option_ids, options_text, start, end, price, prepay, status, expires_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id, master.id, master.name, service.id, service.name,
                    json.dumps([o.id for o in options]), ", ".join(o.name for o in options),
                    start_s, end_s, price, prepay, PENDING,
                    to_str(now + timedelta(minutes=hold_minutes)), to_str(now),
                ),
            )
            booking_id = cur.lastrowid
        return await self.get_booking(booking_id)

    async def get_booking(self, booking_id: int) -> Booking | None:
        row = await self._fetchone(BOOKING_SELECT + " WHERE b.id = ?", (booking_id,))
        return _booking(row) if row else None

    async def set_invoice_message(self, booking_id: int, message_id: int | None) -> None:
        await self.conn.execute(
            "UPDATE bookings SET invoice_message_id = ? WHERE id = ?", (message_id, booking_id)
        )

    async def extend_hold(self, booking_id: int, until: datetime) -> None:
        await self.conn.execute(
            "UPDATE bookings SET expires_at = MAX(expires_at, ?) WHERE id = ? AND status = ?",
            (to_str(until), booking_id, PENDING),
        )

    async def confirm_payment(
        self, booking_id: int, charge_id: str, now: datetime
    ) -> tuple[Booking | None, bool]:
        """Отмечает запись оплаченной. Возвращает (запись, ok).
        ok=False — если пока шла оплата, слот успел уйти другому клиенту."""
        async with self._lock:
            booking = await self.get_booking(booking_id)
            if booking is None:
                return None, False
            if booking.status == CONFIRMED:
                return booking, True
            if booking.status != PENDING and await self._slot_taken(
                booking.master_id, booking.start, booking.end, now, exclude_id=booking.id
            ):
                await self.conn.execute(
                    "UPDATE bookings SET charge_id = ? WHERE id = ?", (charge_id, booking_id)
                )
                return booking, False
            start = booking.start_dt
            await self.conn.execute(
                """UPDATE bookings SET status = ?, charge_id = ?, expires_at = NULL,
                       reminded_24 = ?, reminded_2 = ? WHERE id = ?""",
                (
                    CONFIRMED, charge_id,
                    int(start - now <= timedelta(hours=24)),
                    int(start - now <= timedelta(hours=2)),
                    booking_id,
                ),
            )
        return await self.get_booking(booking_id), True

    async def cancel_booking(self, booking_id: int) -> None:
        await self.conn.execute(
            "UPDATE bookings SET status = ?, expires_at = NULL WHERE id = ?", (CANCELLED, booking_id)
        )

    async def user_upcoming(self, user_id: int, now: datetime) -> list[Booking]:
        rows = await self._fetchall(
            BOOKING_SELECT + f" WHERE b.user_id = :user AND b.start > :now AND {ACTIVE_CONDITION} ORDER BY b.start",
            {"user": user_id, "now": to_str(now)},
        )
        return [_booking(r) for r in rows]

    async def bookings_for_day(self, day: date, now: datetime) -> list[Booking]:
        lo = date_to_str(day) + " 00:00"
        hi = date_to_str(day + timedelta(days=1)) + " 00:00"
        rows = await self._fetchall(
            BOOKING_SELECT
            + f""" WHERE b.start >= :lo AND b.start < :hi
                   AND ({ACTIVE_CONDITION} OR b.status = 'completed') ORDER BY b.start, b.master_id""",
            {"lo": lo, "hi": hi, "now": to_str(now)},
        )
        return [_booking(r) for r in rows]

    async def expire_pending(self, now: datetime) -> list[Booking]:
        """Снимает брони, которые не оплатили вовремя."""
        async with self._lock:
            rows = await self._fetchall(
                BOOKING_SELECT + " WHERE b.status = ? AND b.expires_at <= ?", (PENDING, to_str(now))
            )
            if rows:
                await self.conn.executemany(
                    "UPDATE bookings SET status = ? WHERE id = ?", [(EXPIRED, r["id"]) for r in rows]
                )
        return [_booking(r) for r in rows]

    async def due_reminders(self, now: datetime, hours: int) -> list[Booking]:
        column = "reminded_24" if hours == 24 else "reminded_2"
        rows = await self._fetchall(
            BOOKING_SELECT + f" WHERE b.status = ? AND b.{column} = 0 AND b.start > ? AND b.start <= ?",
            (CONFIRMED, to_str(now), to_str(now + timedelta(hours=hours))),
        )
        return [_booking(r) for r in rows]

    async def mark_reminded(self, booking_id: int, hours: int) -> None:
        column = "reminded_24" if hours == 24 else "reminded_2"
        await self.conn.execute(f"UPDATE bookings SET {column} = 1 WHERE id = ?", (booking_id,))

    async def finish_visits(self, now: datetime) -> list[Booking]:
        """Переводит прошедшие визиты в «состоялся» и возвращает тех, кого спросить об оценке."""
        async with self._lock:
            rows = await self._fetchall(
                BOOKING_SELECT + " WHERE b.status = ? AND b.end <= ? AND b.review_requested = 0",
                (CONFIRMED, to_str(now)),
            )
            if rows:
                await self.conn.executemany(
                    "UPDATE bookings SET status = ?, review_requested = 1 WHERE id = ?",
                    [(COMPLETED, r["id"]) for r in rows],
                )
        return [_booking(r) for r in rows]

    async def set_rating(self, booking_id: int, user_id: int, rating: int) -> Booking | None:
        cur = await self.conn.execute(
            "UPDATE bookings SET rating = ? WHERE id = ? AND user_id = ? AND rating IS NULL AND status = ?",
            (rating, booking_id, user_id, COMPLETED),
        )
        if cur.rowcount == 0:
            return None
        return await self.get_booking(booking_id)

    # ---------- blocks ----------

    async def blocks_for_day(self, day: date) -> list[Block]:
        lo = date_to_str(day) + " 00:00"
        hi = date_to_str(day + timedelta(days=1)) + " 00:00"
        rows = await self._fetchall(
            "SELECT * FROM blocks WHERE start < ? AND end > ? ORDER BY start", (hi, lo)
        )
        return [Block(r["id"], r["start"], r["end"]) for r in rows]

    async def closed_days(self, day_from: date, day_to: date, day_start: str, day_end: str) -> set[date]:
        """Дни, закрытые целиком (блок покрывает весь рабочий день)."""
        rows = await self._fetchall(
            "SELECT start, end FROM blocks WHERE start >= ? AND start < ?",
            (date_to_str(day_from) + " 00:00", date_to_str(day_to + timedelta(days=1)) + " 00:00"),
        )
        result = set()
        for r in rows:
            s, e = from_str(r["start"]), from_str(r["end"])
            if s.strftime("%H:%M") <= day_start and e.strftime("%H:%M") >= day_end and s.date() == e.date():
                result.add(s.date())
        return result

    async def add_block(self, start: datetime, end: datetime) -> None:
        await self.conn.execute(
            "INSERT INTO blocks(start, end) VALUES (?, ?)", (to_str(start), to_str(end))
        )

    async def remove_blocks(self, start: datetime, end: datetime) -> None:
        """Удаляет закрытия, которые пересекаются с интервалом."""
        await self.conn.execute(
            "DELETE FROM blocks WHERE start < ? AND end > ?", (to_str(end), to_str(start))
        )

    async def count_active_between(self, start: datetime, end: datetime, now: datetime) -> int:
        row = await self._fetchone(
            f"SELECT COUNT(*) AS c FROM bookings b WHERE b.start < :end AND b.end > :start AND {ACTIVE_CONDITION}",
            {"start": to_str(start), "end": to_str(end), "now": to_str(now)},
        )
        return row["c"]

    # ---------- регулярные выходные ----------

    async def get_weekly_off(self) -> set[int]:
        """Дни недели (0 = пн … 6 = вс), в которые студия не работает."""
        row = await self._fetchone("SELECT value FROM kv WHERE key = 'weekly_off'")
        if not row or not row["value"]:
            return set()
        return {int(x) for x in row["value"].split(",") if x.isdigit() and int(x) < 7}

    async def set_weekly_off(self, days: set[int]) -> None:
        await self.conn.execute(
            "INSERT INTO kv(key, value) VALUES ('weekly_off', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (",".join(str(d) for d in sorted(days)),),
        )

    # ---------- админка: обзор и статистика ----------

    async def booking_counts(self, day_from: date, day_to: date, now: datetime) -> dict[date, int]:
        """Сколько активных и состоявшихся записей в каждый день периода."""
        rows = await self._fetchall(
            f"""SELECT substr(b.start, 1, 10) AS d, COUNT(*) AS c FROM bookings b
                WHERE b.start >= :lo AND b.start < :hi
                  AND ({ACTIVE_CONDITION} OR b.status = 'completed')
                GROUP BY d""",
            {"lo": date_to_str(day_from), "hi": date_to_str(day_to + timedelta(days=1)), "now": to_str(now)},
        )
        return {date.fromisoformat(r["d"]): r["c"] for r in rows}

    async def stats(self, now: datetime) -> dict:
        month_start = now.replace(day=1, hour=0, minute=0)
        params = {"now": to_str(now), "month": to_str(month_start)}
        row = await self._fetchone(
            """SELECT
                  (SELECT COUNT(*) FROM bookings b WHERE b.start > :now AND b.status = 'confirmed') AS upcoming,
                  (SELECT COUNT(*) FROM bookings b WHERE b.status = 'pending' AND b.expires_at > :now) AS pending,
                  (SELECT COUNT(*) FROM bookings b WHERE b.start >= :month
                       AND b.status IN ('confirmed', 'completed')) AS month_visits,
                  (SELECT COALESCE(SUM(b.price), 0) FROM bookings b WHERE b.start >= :month
                       AND b.status IN ('confirmed', 'completed')) AS month_revenue,
                  (SELECT COALESCE(SUM(b.prepay), 0) FROM bookings b WHERE b.start >= :month
                       AND b.status IN ('confirmed', 'completed')) AS month_prepay,
                  (SELECT COUNT(*) FROM bookings b WHERE b.start >= :month AND b.status = 'cancelled'
                       AND b.charge_id IS NOT NULL) AS month_cancelled,
                  (SELECT COUNT(*) FROM bookings b WHERE b.start >= :month AND b.status = 'expired') AS month_expired,
                  (SELECT AVG(rating) FROM bookings WHERE rating IS NOT NULL) AS avg_rating,
                  (SELECT COUNT(rating) FROM bookings WHERE rating IS NOT NULL) AS ratings,
                  (SELECT COUNT(*) FROM users) AS clients""",
            params,
        )
        return dict(row)

    # ---------- gallery ----------

    async def gallery(self, category: str) -> list[GalleryItem]:
        rows = await self._fetchall(
            "SELECT * FROM gallery WHERE category = ? ORDER BY id", (category,)
        )
        return [GalleryItem(r["id"], r["category"], r["file_id"], r["file_path"], r["caption"]) for r in rows]

    async def add_photo(self, category: str, file_id: str, caption: str) -> None:
        await self.conn.execute(
            "INSERT INTO gallery(category, file_id, caption) VALUES (?, ?, ?)", (category, file_id, caption)
        )

    async def cache_photo_file_id(self, item_id: int, file_id: str) -> None:
        await self.conn.execute("UPDATE gallery SET file_id = ? WHERE id = ?", (file_id, item_id))

    async def delete_photo(self, item_id: int) -> None:
        await self.conn.execute("DELETE FROM gallery WHERE id = ?", (item_id,))
