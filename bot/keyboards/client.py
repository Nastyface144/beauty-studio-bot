"""Клавиатуры клиента."""
from __future__ import annotations

from datetime import date, datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import Settings
from bot.database.models import CONFIRMED, PENDING, Booking, Master, Option, Service
from bot.demo_data import CATEGORIES, category_title
from bot.keyboards.calendar import calendar_rows, day_code
from bot.keyboards.callbacks import BookCb, GalleryCb, MenuCb, MyCb, RateCb
from bot.utils.timeutil import WEEKDAYS_SHORT, money


def _btn(text: str, cb) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=cb.pack() if hasattr(cb, "pack") else cb)


def back_btn(cb, text: str = "◀️ Назад") -> InlineKeyboardButton:
    return _btn(text, cb)


def menu_btn() -> InlineKeyboardButton:
    return _btn("🏠 В меню", MenuCb(action="main"))


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("💅 Записаться", MenuCb(action="book"))],
        [_btn("📋 Мои записи", MenuCb(action="my")), _btn("💰 Услуги и цены", MenuCb(action="prices"))],
        [_btn("📸 Наши работы", MenuCb(action="gallery")), _btn("📍 Контакты", MenuCb(action="contacts"))],
    ])


def only_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[menu_btn()]])


def prices() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("💅 Записаться", MenuCb(action="book"))],
        [back_btn(MenuCb(action="main"))],
    ])


def contacts(settings: Settings) -> InlineKeyboardMarkup:
    rows = []
    if settings.studio_map_url:
        rows.append([InlineKeyboardButton(text="🗺 Открыть на карте", url=settings.studio_map_url)])
    rows.append([_btn("💅 Записаться", MenuCb(action="book"))])
    rows.append([back_btn(MenuCb(action="main"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------- запись ----------

def categories() -> InlineKeyboardMarkup:
    rows = [[_btn(category_title(key), BookCb(action="cat", value=key))] for key in CATEGORIES]
    rows.append([back_btn(MenuCb(action="main"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def services(items: list[Service]) -> InlineKeyboardMarkup:
    rows = [
        [_btn(f"{s.name} · {money(s.price)}", BookCb(action="srv", value=str(s.id)))]
        for s in items
    ]
    rows.append([back_btn(BookCb(action="back", value="cats"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def options(items: list[Option], selected: set[int]) -> InlineKeyboardMarkup:
    rows = []
    for o in items:
        mark = "✅" if o.id in selected else "▫️"
        rows.append([_btn(f"{mark} {o.name} · +{money(o.price)}", BookCb(action="opt", value=str(o.id)))])
    rows.append([_btn("Далее ▶️" if selected else "Без опций ▶️", BookCb(action="opts_done"))])
    rows.append([back_btn(BookCb(action="back", value="services"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def masters(items: list[Master], back_to: str) -> InlineKeyboardMarkup:
    rows = [[_btn(f"👩‍🎨 {m.name}", BookCb(action="mst", value=str(m.id)))] for m in items]
    rows.append([back_btn(BookCb(action="back", value=back_to))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def booking_calendar(days: list[date], available: set[date]) -> InlineKeyboardMarkup:
    rows = calendar_rows(
        days,
        label=lambda d: str(d.day) if d in available else None,
        callback=lambda d: BookCb(action="day", value=day_code(d)).pack(),
    )
    rows.append([back_btn(BookCb(action="back", value="masters"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def times(starts: list[datetime]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for s in starts:
        kb.button(text=s.strftime("%H:%M"), callback_data=BookCb(action="time", value=s.strftime("%H%M")))
    kb.adjust(4)
    kb.row(back_btn(BookCb(action="back", value="calendar")))
    return kb.as_markup()


def summary() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("💳 Подтвердить и оплатить", BookCb(action="confirm"))],
        [back_btn(BookCb(action="back", value="times"))],
        [_btn("✖️ Отменить запись", MenuCb(action="main"))],
    ])


def slot_taken() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🕐 Выбрать другое время", BookCb(action="back", value="times"))],
        [menu_btn()],
    ])


def restart_booking() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("💅 Записаться", MenuCb(action="book"))],
        [menu_btn()],
    ])


# ---------- оплата ----------

def invoice(booking: Booking) -> InlineKeyboardMarkup:
    # Кнопка оплаты обязана быть первой
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💳 Оплатить {money(booking.prepay)}", pay=True)],
        [_btn("✖️ Отменить бронь", MyCb(action="drop", booking_id=booking.id))],
    ])


def demo_payment(booking: Booking) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn(f"💳 Оплатить {money(booking.prepay)} (демо)", MyCb(action="demo_pay", booking_id=booking.id))],
        [_btn("✖️ Отменить бронь", MyCb(action="drop", booking_id=booking.id))],
    ])


# ---------- мои записи ----------

def my_bookings(items: list[Booking]) -> InlineKeyboardMarkup:
    rows = []
    for b in items:
        dt = b.start_dt
        icon = "✅" if b.status == CONFIRMED else "⏳"
        text = f"{icon} {dt:%d.%m} {WEEKDAYS_SHORT[dt.weekday()]} {dt:%H:%M} · {b.service_name}"
        rows.append([_btn(text[:60], MyCb(action="view", booking_id=b.id))])
    if not items:
        rows.append([_btn("💅 Записаться", MenuCb(action="book"))])
    rows.append([back_btn(MenuCb(action="main"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def my_booking(b: Booking, can_cancel: bool) -> InlineKeyboardMarkup:
    rows = []
    if b.status == PENDING:
        rows.append([_btn(f"💳 Оплатить {money(b.prepay)}", MyCb(action="pay", booking_id=b.id))])
    if can_cancel:
        rows.append([_btn("✖️ Отменить запись", MyCb(action="cancel", booking_id=b.id))])
    rows.append([back_btn(MenuCb(action="my"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cancel_confirm(b: Booking) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("Да, отменить", MyCb(action="cancel_ok", booking_id=b.id))],
        [back_btn(MyCb(action="view", booking_id=b.id), "◀️ Нет, оставить")],
    ])


def after_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("📋 Мои записи", MenuCb(action="my"))],
        [menu_btn()],
    ])


def after_payment() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("📋 Мои записи", MenuCb(action="my"))],
        [menu_btn()],
    ])


# ---------- галерея ----------

def gallery_categories() -> InlineKeyboardMarkup:
    rows = [
        [_btn(category_title(key), GalleryCb(action="show", category=key, index=0))]
        for key in CATEGORIES
    ]
    rows.append([back_btn(MenuCb(action="main"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def gallery_nav(category: str, index: int, total: int, item_id: int, is_admin: bool) -> InlineKeyboardMarkup:
    rows = []
    if total > 1:
        prev_i = (index - 1) % total
        next_i = (index + 1) % total
        rows.append([
            _btn("◀️", GalleryCb(action="show", category=category, index=prev_i)),
            _btn(f"{index + 1} / {total}", "noop"),
            _btn("▶️", GalleryCb(action="show", category=category, index=next_i)),
        ])
    rows.append([_btn("💅 Хочу так же", MenuCb(action="book"))])
    if is_admin:
        rows.append([_btn("🗑 Удалить фото", GalleryCb(action="del", category=category, index=index, item_id=item_id))])
    rows.append([back_btn(GalleryCb(action="cats"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def gallery_empty() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[back_btn(GalleryCb(action="cats"))]])


# ---------- отзыв ----------

def rating(booking_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn(f"{n} ⭐", RateCb(booking_id=booking_id, stars=n)) for n in range(1, 6)],
    ])
