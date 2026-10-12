from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from bot.utils.timeutil import from_str

# Статусы записи
PENDING = "pending"        # ждёт предоплаты, слот удерживается
CONFIRMED = "confirmed"    # оплачена
CANCELLED = "cancelled"    # отменена клиентом
EXPIRED = "expired"        # не оплачена вовремя
COMPLETED = "completed"    # визит состоялся


@dataclass(slots=True)
class Master:
    id: int
    name: str
    about: str
    categories: list[str]


@dataclass(slots=True)
class Service:
    id: int
    category: str
    name: str
    price: int
    duration: int
    description: str


@dataclass(slots=True)
class Option:
    id: int
    category: str
    name: str
    price: int
    duration: int


@dataclass(slots=True)
class Booking:
    id: int
    user_id: int
    master_id: int
    master_name: str
    service_id: int
    service_name: str
    options_text: str
    start: str
    end: str
    price: int
    prepay: int
    status: str
    expires_at: str | None
    invoice_message_id: int | None
    rating: int | None
    client_name: str = ""
    client_username: str | None = None

    @property
    def start_dt(self) -> datetime:
        return from_str(self.start)

    @property
    def end_dt(self) -> datetime:
        return from_str(self.end)

    @property
    def duration(self) -> int:
        return int((self.end_dt - self.start_dt).total_seconds() // 60)


@dataclass(slots=True)
class GalleryItem:
    id: int
    category: str
    file_id: str | None
    file_path: str | None
    caption: str


@dataclass(slots=True)
class Block:
    id: int
    start: str
    end: str
