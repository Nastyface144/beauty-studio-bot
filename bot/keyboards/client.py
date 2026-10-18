"""Клавиатуры клиента.

Кнопки без смайликов. Главные действия выделены цветом Telegram:
синий (primary) — основное действие, зелёный (success) — подтвердить,
красный (danger) — отменить. Старые версии Telegram показывают их обычными.
"""
from __future__ import annotations

from datetime import date, datetime

from aiogram.types import DisabledButton, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import Settings
from bot.database.models import PENDING, Booking, Master, Option, Service
from bot.demo_data import CATEGORIES
from bot.keyboards.calendar import calendar_rows, day_code, month_code
from bot.keyboards.callbacks import AdminCb, BookCb, GalleryCb, MenuCb, MyCb, RateCb
from bot.utils.timeutil import WEEKDAYS_SHORT, money

PRIMARY, SUCCESS, DANGER = "primary", "success", "danger"


def _btn(text: str, cb, style: str | None = None) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text, callback_data=cb.pack() if hasattr(cb, "pack") else cb, style=style,
    )


def back_btn(cb, text: str = "‹ Назад") -> InlineKeyboardButton:
    return _btn(text, cb)


def menu_btn() -> InlineKeyboardButton:
    return _btn("Главное меню", MenuCb(action="main"))


def book_btn() -> InlineKeyboardButton:
    return _btn("Записаться", MenuCb(action="book"), PRIMARY)


def _cat_name(key: str) -> str:
    return CATEGORIES.get(key, (key, ""))[0]


def main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [book_btn()],
        [_btn("Мои записи", MenuCb(action="my")), _btn("Услуги и цены", MenuCb(action="prices"))],
        [_btn("Портфолио", MenuCb(action="gallery")), _btn("Контакты", MenuCb(action="contacts"))],
    ]
    if is_admin:
        rows.append([_btn("Админ-панель", AdminCb(action="home"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def only_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[menu_btn()]])


def prices() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[book_btn()], [back_btn(MenuCb(action="main"))]])


def contacts(settings: Settings) -> InlineKeyboardMarkup:
    rows = []
    if settings.studio_map_url:
        rows.append([InlineKeyboardButton(text="Открыть на карте", url=settings.studio_map_url)])
    rows.append([book_btn()])
    rows.append([back_btn(MenuCb(action="main"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------- запись ----------

def categories() -> InlineKeyboardMarkup:
    rows = [[_btn(_cat_name(key), BookCb(action="cat", value=key))] for key in CATEGORIES]
    rows.append([back_btn(MenuCb(action="main"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def services(items: list[Service]) -> InlineKeyboardMarkup:
    rows = [[_btn(f"{s.name} — {money(s.price)}", BookCb(action="srv", value=str(s.id)))] for s in items]
    rows.append([back_btn(BookCb(action="back", value="cats"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def options(items: list[Option], selected: set[int]) -> InlineKeyboardMarkup:
    rows = []
    for o in items:
        on = o.id in selected
        text = f"{'✓ ' if on else ''}{o.name} — +{money(o.price)}"
        rows.append([_btn(text, BookCb(action="opt", value=str(o.id)), SUCCESS if on else None)])
    rows.append([_btn("Продолжить" if selected else "Пропустить", BookCb(action="opts_done"), PRIMARY)])
    rows.append([back_btn(BookCb(action="back", value="services"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def masters(items: list[Master], back_to: str) -> InlineKeyboardMarkup:
    rows = [[_btn(m.name, BookCb(action="mst", value=str(m.id)))] for m in items]
    if len(items) > 1:
        rows.insert(0, [_btn("Любой свободный мастер", BookCb(action="mst", value="0"), PRIMARY)])
    rows.append([back_btn(BookCb(action="back", value=back_to))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def booking_calendar(
    days: list[date], available: set[date], month: tuple[int, int] | None,
    day_off: set[date] = frozenset(), selected: date | None = None,
) -> InlineKeyboardMarkup:
    rows = calendar_rows(
        days,
        inactive=lambda d: d in day_off,
        label=lambda d: str(d.day) if d in available else None,
        callback=lambda d: BookCb(action="day", value=day_code(d)).pack(),
        month=month,
        nav=lambda m: BookCb(action="month", value=month_code(*m)).pack(),
        selected=selected,
    )
    rows.append([back_btn(BookCb(action="back", value="masters"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def times(grid: list[tuple[datetime, bool]]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for start, free in grid:
        if free:
            kb.button(text=start.strftime("%H:%M"), callback_data=BookCb(action="time", value=start.strftime("%H%M")))
        else:
            kb.add(InlineKeyboardButton(text="✕", disabled=DisabledButton()))  # занято — нажать нельзя
    kb.adjust(4)
    kb.row(back_btn(BookCb(action="back", value="calendar"), "‹ Другая дата"))
    return kb.as_markup()


def summary(settings: Settings, price: int, prepay: int) -> InlineKeyboardMarkup:
    rows = []
    online, on_site = settings.online_available, settings.on_site_available
    if online:
        rows.append([_btn(f"Оплатить картой — {money(prepay)}", BookCb(action="confirm", value="online"), PRIMARY)])
    if on_site:
        text = "Оплачу в салоне" if online else "Подтвердить запись"
        rows.append([_btn(text, BookCb(action="confirm", value="cash"), None if online else SUCCESS)])
    rows.append([back_btn(BookCb(action="back", value="times"), "‹ Изменить время")])
    rows.append([_btn("Отменить", MenuCb(action="main"), DANGER)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def slot_taken() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("Выбрать другое время", BookCb(action="back", value="times"), PRIMARY)],
        [menu_btn()],
    ])


def restart_booking() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[book_btn()], [menu_btn()]])


# ---------- оплата (если включена) ----------

def _cash_row(booking: Booking, allow_cash: bool) -> list[list[InlineKeyboardButton]]:
    return [[_btn("Лучше оплачу в салоне", MyCb(action="to_cash", booking_id=booking.id))]] if allow_cash else []


def invoice(booking: Booking, allow_cash: bool = True) -> InlineKeyboardMarkup:
    # Кнопка оплаты обязана быть первой
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Оплатить картой — {money(booking.prepay)}", pay=True)],
        *_cash_row(booking, allow_cash),
        [_btn("Отменить бронь", MyCb(action="drop", booking_id=booking.id), DANGER)],
    ])


def demo_payment(booking: Booking, allow_cash: bool = True) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn(f"Оплатить картой — {money(booking.prepay)} (демо)",
              MyCb(action="demo_pay", booking_id=booking.id), PRIMARY)],
        *_cash_row(booking, allow_cash),
        [_btn("Отменить бронь", MyCb(action="drop", booking_id=booking.id), DANGER)],
    ])


# ---------- мои записи ----------

def my_bookings(items: list[Booking], reminders_on: bool = True) -> InlineKeyboardMarkup:
    rows = []
    for b in items:
        dt = b.start_dt
        text = f"{dt:%d.%m}, {WEEKDAYS_SHORT[dt.weekday()].lower()} {dt:%H:%M} — {b.service_name}"
        rows.append([_btn(text[:60], MyCb(action="view", booking_id=b.id))])
    if not items:
        rows.append([book_btn()])
    rows.append([_btn(
        "Напоминания: включены" if reminders_on else "Напоминания: выключены",
        MenuCb(action="rem_toggle"), None if reminders_on else DANGER,
    )])
    rows.append([back_btn(MenuCb(action="main"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def my_booking(b: Booking, can_cancel: bool, allow_cash: bool = True) -> InlineKeyboardMarkup:
    rows = []
    if b.status == PENDING:
        rows.append([_btn(f"Оплатить картой — {money(b.prepay)}", MyCb(action="pay", booking_id=b.id), PRIMARY)])
        rows += _cash_row(b, allow_cash)
    if can_cancel:
        rows.append([_btn("Отменить запись", MyCb(action="cancel", booking_id=b.id), DANGER)])
    rows.append([back_btn(MenuCb(action="my"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cancel_confirm(b: Booking) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("Да, отменить", MyCb(action="cancel_ok", booking_id=b.id), DANGER)],
        [back_btn(MyCb(action="view", booking_id=b.id), "Нет, оставить")],
    ])


def reminder(reminders_on: bool = True) -> InlineKeyboardMarkup:
    """Под напоминанием: отключить их одной кнопкой (или включить обратно)."""
    if reminders_on:
        toggle = _btn("Отключить напоминания", MenuCb(action="rem_off"))
    else:
        toggle = _btn("Включить напоминания", MenuCb(action="rem_on"), PRIMARY)
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("Мои записи", MenuCb(action="my"))], [toggle]])


# ---------- галерея ----------

def gallery_categories() -> InlineKeyboardMarkup:
    rows = [[_btn(_cat_name(key), GalleryCb(action="show", category=key, index=0))] for key in CATEGORIES]
    rows.append([back_btn(MenuCb(action="main"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def gallery_nav(category: str, index: int, total: int, item_id: int, is_admin: bool) -> InlineKeyboardMarkup:
    rows = []
    if total > 1:
        prev_i = (index - 1) % total
        next_i = (index + 1) % total
        rows.append([
            _btn("‹", GalleryCb(action="show", category=category, index=prev_i)),
            InlineKeyboardButton(text=f"{index + 1} из {total}", disabled=DisabledButton()),
            _btn("›", GalleryCb(action="show", category=category, index=next_i)),
        ])
    rows.append([book_btn()])
    if is_admin:
        rows.append([_btn("Удалить фото", GalleryCb(action="del", category=category, index=index, item_id=item_id),
                          DANGER)])
    rows.append([back_btn(GalleryCb(action="cats"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def gallery_empty() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[back_btn(GalleryCb(action="cats"))]])


# ---------- отзыв ----------

def rating(booking_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn(str(n), RateCb(booking_id=booking_id, stars=n)) for n in range(1, 6)],
    ])
