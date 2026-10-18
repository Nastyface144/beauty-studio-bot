"""Настройки бота: читаются из .env / переменных окружения."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _parse_ids(raw: str) -> frozenset[int]:
    ids = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            ids.add(int(part))
    return frozenset(ids)


def _parse_int(raw: str | None, default: int, lo: int, hi: int) -> int:
    try:
        return min(max(int(str(raw).strip()), lo), hi)
    except (TypeError, ValueError):
        return default


def _parse_reminders(raw: str | None) -> tuple[int, int]:
    """«12,6» → (12, 6): первое напоминание раньше второго."""
    try:
        first, second = sorted((int(x) for x in str(raw).replace(";", ",").split(",")[:2]), reverse=True)
        if 0 < second < first <= 72:
            return first, second
    except (TypeError, ValueError):
        pass
    return 12, 6


def _parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on", "да")


def _parse_time(raw: str, default: time) -> time:
    try:
        hours, minutes = raw.strip().split(":")
        return time(int(hours), int(minutes))
    except (ValueError, AttributeError):
        return default


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    payment_token: str
    timezone: ZoneInfo
    db_path: Path

    studio_name: str = "Bloom Beauty Studio"
    studio_address: str = "Москва, ул. Цветочная, 12, 2 этаж"
    studio_phone: str = "+7 (999) 123-45-67"
    studio_instagram: str = ""
    studio_map_url: str = ""

    work_start: time = time(9, 0)
    work_end: time = time(20, 0)
    slot_step_min: int = 30
    booking_days: int = 30
    min_lead_min: int = 30
    prepay_percent: int = 30
    hold_minutes: int = 15
    cancel_hours: int = 12

    pay_online: bool = False   # оплата картой в боте (выключена: запись создаётся сразу)
    pay_on_site: bool = True   # оплата в студии мастеру, без предоплаты
    digest_time: time = time(20, 0)
    reminder_hours: tuple[int, int] = (12, 6)   # первое и второе напоминание, часов до визита
    gallery_dir: Path = field(default=BASE_DIR / "assets" / "gallery")

    @property
    def log_path(self) -> Path:
        return self.db_path.parent / "bot.log"

    @property
    def payments_enabled(self) -> bool:
        return bool(self.payment_token)

    @property
    def online_available(self) -> bool:
        # Если оба способа выключены по ошибке, оставляем оплату в студии — запись не должна ломаться
        return self.pay_online

    @property
    def on_site_available(self) -> bool:
        return self.pay_on_site or not self.pay_online


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "Не задан BOT_TOKEN. Скопируйте .env.example в .env и укажите токен от @BotFather."
        )

    tz_name = os.getenv("TIMEZONE", "Europe/Moscow").strip() or "Europe/Moscow"
    db_path = Path(os.getenv("DB_PATH", str(BASE_DIR / "data" / "studio.db")))
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path

    return Settings(
        bot_token=token,
        admin_ids=_parse_ids(os.getenv("ADMIN_ID", "")),
        payment_token=os.getenv("PAYMENT_TOKEN", "").strip(),
        timezone=ZoneInfo(tz_name),
        db_path=db_path,
        studio_name=os.getenv("STUDIO_NAME", Settings.studio_name),
        studio_address=os.getenv("STUDIO_ADDRESS", Settings.studio_address),
        studio_phone=os.getenv("STUDIO_PHONE", Settings.studio_phone),
        studio_instagram=os.getenv("STUDIO_INSTAGRAM", "").strip(),
        studio_map_url=os.getenv("STUDIO_MAP_URL", "").strip(),
        work_start=_parse_time(os.getenv("WORK_START", "09:00"), time(9, 0)),
        work_end=_parse_time(os.getenv("WORK_END", "20:00"), time(20, 0)),
        booking_days=_parse_int(os.getenv("BOOKING_DAYS"), 30, 1, 60),
        digest_time=_parse_time(os.getenv("DIGEST_TIME", "20:00"), time(20, 0)),
        pay_online=_parse_bool(os.getenv("PAY_ONLINE"), False),
        reminder_hours=_parse_reminders(os.getenv("REMINDER_HOURS")),
        prepay_percent=_parse_int(os.getenv("PREPAY_PERCENT"), 30, 1, 100),
        pay_on_site=_parse_bool(os.getenv("PAY_ON_SITE"), True),
    )
