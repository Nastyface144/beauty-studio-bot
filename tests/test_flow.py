"""Сквозные сценарии через настоящий Dispatcher и поддельный Telegram API."""
from __future__ import annotations

import itertools
import logging
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.methods import (
    AnswerCallbackQuery, AnswerPreCheckoutQuery, EditMessageMedia, EditMessageText,
    SendInvoice, SendMessage, SendPhoto, TelegramMethod,
)
from aiogram.types import Message, Update

from bot.config import BASE_DIR, Settings
from bot.database.models import CANCELLED, CONFIRMED, PENDING
from bot.keyboards.calendar import day_code
from bot.main import build_dispatcher
from bot.scheduler import jobs
from bot.utils.timeutil import now_local

TZ = ZoneInfo("Europe/Moscow")
CLIENT, ADMIN = 1001, 999
BOT_ID = 42


class FakeSession(BaseSession):
    """Возвращает правдоподобные ответы и запоминает все вызовы API."""

    def __init__(self):
        super().__init__()
        self.calls: list[TelegramMethod] = []
        self._ids = itertools.count(500)

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, (SendMessage, SendPhoto, SendInvoice, EditMessageText, EditMessageMedia)):
            mid = getattr(method, "message_id", None) or next(self._ids)
            data = {
                "message_id": mid, "date": 0,
                "chat": {"id": method.chat_id or CLIENT, "type": "private"},
                "from": {"id": BOT_ID, "is_bot": True, "first_name": "Bot"},
            }
            if isinstance(method, (SendPhoto, EditMessageMedia)):
                data["photo"] = [{"file_id": f"photo{mid}", "file_unique_id": f"u{mid}", "width": 900, "height": 900}]
                data["caption"] = getattr(method, "caption", None) or getattr(method.media, "caption", "")
            elif isinstance(method, SendInvoice):
                data["invoice"] = {"title": method.title, "description": method.description,
                                   "start_parameter": "", "currency": "RUB", "total_amount": 1}
            else:
                data["text"] = method.text
            return Message.model_validate(data, context={"bot": bot})
        return True  # answerCallbackQuery, deleteMessage, answerPreCheckoutQuery и т.п.

    def of(self, kind):
        return [c for c in self.calls if isinstance(c, kind)]

    def texts(self):
        return [c.text for c in self.calls if isinstance(c, (SendMessage, EditMessageText))]


class Harness:
    def __init__(self, dp, db, settings):
        self.dp, self.db, self.settings = dp, db, settings
        self.session = FakeSession()
        self.bot = Bot("42:TEST", session=self.session, default=DefaultBotProperties(parse_mode="HTML"))
        self.errors: list[BaseException] = []
        self._uid = itertools.count(1)
        # Все ошибки хендлеров проходят через on_error → логируются; собираем их
        errors = self.errors

        class Collector(logging.Handler):
            def emit(self, record):
                if record.exc_info:
                    errors.append(record.exc_info[1])

        logging.getLogger("bot.handlers.common").addHandler(Collector(level=logging.ERROR))

    async def _feed(self, data):
        data["update_id"] = next(self._uid)
        update = Update.model_validate(data, context={"bot": self.bot})
        await self.dp.feed_update(self.bot, update, db=self.db, settings=self.settings)

    def _user(self, uid):
        return {"id": uid, "is_bot": False, "first_name": "Алиса" if uid == CLIENT else "Админ", "username": "alice"}

    async def message(self, text, uid=CLIENT, **extra):
        msg = {"message_id": next(self.session._ids), "date": 0, "chat": {"id": uid, "type": "private"},
               "from": self._user(uid), "text": text, **extra}
        if text.startswith("/"):
            msg["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        await self._feed({"message": msg})

    async def click(self, data, uid=CLIENT):
        mid = await self.db.get_ui_message(uid) or 1
        await self._feed({"callback_query": {
            "id": str(next(self._uid)), "from": self._user(uid), "chat_instance": "x", "data": data,
            "message": {"message_id": mid, "date": 0, "chat": {"id": uid, "type": "private"},
                        "from": {"id": BOT_ID, "is_bot": True, "first_name": "Bot"}, "text": "screen"},
        }})

    def last_screen(self):
        for c in reversed(self.session.calls):
            if isinstance(c, (SendMessage, EditMessageText)) and c.chat_id == CLIENT:
                return c.text
        return ""

    def buttons(self):
        """callback_data всех кнопок последнего экрана."""
        for c in reversed(self.session.calls):
            markup = getattr(c, "reply_markup", None)
            if markup is not None and not isinstance(c, AnswerCallbackQuery):
                return [b.callback_data for row in markup.inline_keyboard for b in row if b.callback_data]
        return []


_DP = None


def _dispatcher(db, settings):
    global _DP
    if _DP is None:
        _DP = build_dispatcher(db, settings)  # роутеры — синглтоны, диспетчер собираем один раз
    return _DP


def make_settings(tmp_path, payment_token=""):
    return Settings(
        bot_token="42:TEST", admin_ids=frozenset({ADMIN}), payment_token=payment_token,
        timezone=TZ, db_path=tmp_path / "db.sqlite", gallery_dir=BASE_DIR / "assets" / "gallery",
    )


@pytest.fixture
def harness(db, tmp_path):
    settings = make_settings(tmp_path)
    return Harness(_dispatcher(db, settings), db, settings)


def tomorrow_code():
    return day_code(now_local(TZ).date() + timedelta(days=1))


async def book_nails(h: Harness):
    await h.message("/start")
    await h.click("m:book")
    await h.click("b:cat:nails")
    await h.click("b:srv:2")          # Маникюр + гель-лак, 90 мин
    await h.click("b:opt:1")          # Дизайн +30 мин
    await h.click("b:opt:2")          # Снятие +15 мин
    await h.click("b:opts_done:")
    await h.click("b:mst:1")
    await h.click(f"b:day:{tomorrow_code()}")
    await h.click("b:time:1200")
    await h.click("b:confirm:")


async def test_full_booking_with_demo_payment(harness: Harness):
    h = harness
    await book_nails(h)
    assert not h.errors, h.errors

    summary = [t for t in h.session.texts() if "Проверьте" in t][-1]
    assert "3 000 ₽" in summary          # 2200 + 500 + 300
    assert "2 ч 15 мин" in summary
    assert "900 ₽" in summary            # 30%

    pending = await h.db.user_upcoming(CLIENT, now_local(TZ))
    assert len(pending) == 1 and pending[0].status == PENDING
    booking = pending[0]
    assert booking.end_dt - booking.start_dt == timedelta(minutes=135)

    admin_msgs = [c.text for c in h.session.of(SendMessage) if c.chat_id == ADMIN]
    assert any("Новая бронь" in t for t in admin_msgs)

    await h.click(f"my:demo_pay:{booking.id}")
    assert not h.errors, h.errors
    assert (await h.db.get_booking(booking.id)).status == CONFIRMED
    assert any("Вы записаны" in t for t in h.session.texts())
    assert any("Оплачена предоплата" in c.text for c in h.session.of(SendMessage) if c.chat_id == ADMIN)


async def test_back_buttons_and_times_fit_duration(harness: Harness):
    h = harness
    await h.message("/start")
    await h.click("m:book")
    await h.click("b:cat:lashes")
    await h.click("b:srv:7")          # 120 мин, без опций → сразу мастер
    assert "b:back:services" in h.buttons()
    await h.click("b:mst:2")
    await h.click(f"b:day:{tomorrow_code()}")
    times = [b for b in h.buttons() if b.startswith("b:time:")]
    assert times[0] == "b:time:0900" and times[-1] == "b:time:1800"
    await h.click("b:back:calendar")
    await h.click("b:back:masters")
    await h.click("b:back:services")
    await h.click("b:back:cats")
    assert not h.errors, h.errors
    # Анна не делает ресницы — её нельзя подставить вручную
    await h.click("b:mst:1")
    assert "устарела" in h.last_screen()


async def test_taken_slot_is_hidden_for_other_client(harness: Harness):
    h = harness
    await book_nails(h)
    await h.click("m:book", uid=2002)
    await h.click("b:cat:nails", uid=2002)
    await h.click("b:srv:1", uid=2002)
    await h.click("b:opts_done:", uid=2002)
    await h.click("b:mst:1", uid=2002)
    await h.click(f"b:day:{tomorrow_code()}", uid=2002)
    times = [b for b in h.buttons() if b.startswith("b:time:")]
    # занято 12:00–14:15, часовая процедура не может начаться с 11:30 до 14:00
    assert "b:time:1100" in times and "b:time:1130" not in times
    assert "b:time:1400" not in times and "b:time:1430" in times
    # прямой клик по занятому времени не проходит
    await h.click("b:time:1200", uid=2002)
    assert not h.errors, h.errors
    assert not [t for t in h.session.texts() if "Проверьте" in t and "Маникюр классический" in t]


async def test_cancel_rules(harness: Harness):
    h = harness
    await book_nails(h)
    booking = (await h.db.user_upcoming(CLIENT, now_local(TZ)))[0]
    await h.click(f"my:demo_pay:{booking.id}")
    await h.click("m:my")
    await h.click(f"my:view:{booking.id}")
    start = booking.start_dt
    can_cancel = start - now_local(TZ) >= timedelta(hours=12)
    assert (f"my:cancel:{booking.id}" in h.buttons()) == can_cancel
    await h.click(f"my:cancel_ok:{booking.id}")
    status = (await h.db.get_booking(booking.id)).status
    assert status == (CANCELLED if can_cancel else CONFIRMED)
    assert not h.errors, h.errors


async def test_scheduler_jobs(harness: Harness):
    h = harness
    await book_nails(h)
    booking = (await h.db.user_upcoming(CLIENT, now_local(TZ)))[0]
    # бронь не оплачена — сдвигаем срок и запускаем задачу
    await h.db.conn.execute("UPDATE bookings SET expires_at = '2000-01-01 00:00' WHERE id = ?", (booking.id,))
    await jobs.expire_unpaid(h.bot, h.db, h.settings)
    assert (await h.db.get_booking(booking.id)).status == "expired"
    assert any("Время на оплату вышло" in t for t in h.session.texts())

    # оплаченная запись: напоминание и запрос оценки
    await book_nails(h)
    booking = (await h.db.user_upcoming(CLIENT, now_local(TZ)))[0]
    await h.click(f"my:demo_pay:{booking.id}")
    await h.db.conn.execute("UPDATE bookings SET reminded_24 = 0 WHERE id = ?", (booking.id,))
    await jobs.send_reminders(h.bot, h.db, h.settings)
    reminders = [c.text for c in h.session.of(SendMessage) if "Напоминаем" in c.text]
    assert len(reminders) <= 1
    await h.db.conn.execute(
        "UPDATE bookings SET start = '2000-01-01 10:00', end = '2000-01-01 11:00' WHERE id = ?", (booking.id,)
    )
    await jobs.request_reviews(h.bot, h.db, h.settings)
    assert any("оценку" in c.text for c in h.session.of(SendMessage))
    await h.click(f"r:{booking.id}:5")
    assert (await h.db.get_booking(booking.id)).rating == 5
    assert not h.errors, h.errors


async def test_gallery_and_menu(harness: Harness):
    h = harness
    await h.message("/start")
    for action in ("prices", "contacts", "gallery", "my"):
        await h.click(f"m:{action}")
    await h.click("g:show:nails:0:0")
    await h.click("g:show:nails:1:0")
    await h.click("g:show:nails:2:0")
    await h.click("g:cats::0:0")
    assert h.session.of(SendPhoto) or h.session.of(EditMessageMedia)
    items = await h.db.gallery("nails")
    assert items[0].file_id  # file_id закэширован после первой отправки
    await h.message("привет")  # свободный текст → меню
    await h.click("unknown:data")  # устаревшая кнопка
    assert not h.errors, h.errors


async def test_admin_panel(harness: Harness):
    h = harness
    await book_nails(h)
    await h.message("/admin", uid=ADMIN)
    await h.click("a:today:", uid=ADMIN)
    await h.click("a:tomorrow:", uid=ADMIN)
    assert any("Маникюр + гель-лак" in t for t in h.session.texts())
    await h.click("a:close:", uid=ADMIN)
    day = tomorrow_code()
    await h.click(f"a:day:{day}", uid=ADMIN)
    await h.click(f"a:slot:{day}1600", uid=ADMIN)
    blocks = await h.db.blocks_for_day(now_local(TZ).date() + timedelta(days=1))
    assert len(blocks) == 1
    await h.click(f"a:day_toggle:{day}", uid=ADMIN)
    await h.click(f"a:slot:{day}1000", uid=ADMIN)  # открыть 10:00 внутри закрытого дня
    blocks = await h.db.blocks_for_day(now_local(TZ).date() + timedelta(days=1))
    assert [(b.start[-5:], b.end[-5:]) for b in blocks] == [("09:00", "10:00"), ("10:30", "20:00")]
    await h.click(f"a:day_toggle:{day}", uid=ADMIN)  # теперь закрыт не весь день → закрыть целиком
    await h.click(f"a:day_toggle:{day}", uid=ADMIN)  # и открыть
    assert await h.db.blocks_for_day(now_local(TZ).date() + timedelta(days=1)) == []

    await h.click("a:photo:", uid=ADMIN)
    await h.click("a:photo_cat:brows", uid=ADMIN)
    await h.message("не фото", uid=ADMIN)
    await h.message("", uid=ADMIN, photo=[{"file_id": "NEW", "file_unique_id": "n", "width": 1, "height": 1}],
                    caption="Новая работа")
    assert any(i.file_id == "NEW" for i in await h.db.gallery("brows"))

    # клиенту админка недоступна
    await h.message("/admin")
    await h.click("a:today:")
    assert not h.errors, h.errors


async def test_real_invoice_flow(db, tmp_path):
    settings = make_settings(tmp_path, payment_token="TEST:123")
    h = Harness(_dispatcher(db, settings), db, settings)
    await book_nails(h)
    invoices = h.session.of(SendInvoice)
    assert invoices and invoices[-1].prices[0].amount == 90000
    assert invoices[-1].reply_markup.inline_keyboard[0][0].pay
    booking = (await db.user_upcoming(CLIENT, now_local(TZ)))[0]

    await h._feed({"pre_checkout_query": {
        "id": "pc1", "from": h._user(CLIENT), "currency": "RUB", "total_amount": 90000,
        "invoice_payload": f"booking:{booking.id}",
    }})
    answer = h.session.of(AnswerPreCheckoutQuery)[-1]
    assert answer.ok, answer.error_message

    await h._feed({"message": {
        "message_id": 9999, "date": 0, "chat": {"id": CLIENT, "type": "private"}, "from": h._user(CLIENT),
        "successful_payment": {"currency": "RUB", "total_amount": 90000, "invoice_payload": f"booking:{booking.id}",
                               "telegram_payment_charge_id": "tg1", "provider_payment_charge_id": "yk1"},
    }})
    assert (await db.get_booking(booking.id)).status == CONFIRMED
    assert not h.errors, h.errors

    # чужая/неверная сумма отклоняется
    await h._feed({"pre_checkout_query": {
        "id": "pc2", "from": h._user(CLIENT), "currency": "RUB", "total_amount": 100,
        "invoice_payload": f"booking:{booking.id}",
    }})
    assert not h.session.of(AnswerPreCheckoutQuery)[-1].ok


async def test_booking_window_is_30_days(harness: Harness):
    h = harness
    await h.message("/start")
    await h.click("m:book")
    await h.click("b:cat:brows")
    await h.click("b:srv:5")
    await h.click("b:mst:1")
    days = [b for b in h.buttons() if b.startswith("b:day:")]
    last = day_code(now_local(TZ).date() + timedelta(days=29))
    assert f"b:day:{last}" in days
    assert len(days) >= 29  # сегодня может быть уже закрыто по времени


async def test_weekly_day_off(harness: Harness):
    h = harness
    tomorrow = now_local(TZ).date() + timedelta(days=1)
    await h.message("/admin", uid=ADMIN)
    await h.click("a:weekly:", uid=ADMIN)
    await h.click(f"a:wk:{tomorrow.weekday()}", uid=ADMIN)
    assert await h.db.get_weekly_off() == {tomorrow.weekday()}

    await h.message("/start")
    await h.click("m:book")
    await h.click("b:cat:brows")
    await h.click("b:srv:5")
    await h.click("b:mst:1")
    assert f"b:day:{day_code(tomorrow)}" not in h.buttons()
    # даже прямой клик по дню не даёт выбрать время
    await h.click(f"b:day:{day_code(tomorrow)}")
    assert not [b for b in h.buttons() if b.startswith("b:time:")]

    await h.click(f"a:wk:{tomorrow.weekday()}", uid=ADMIN)
    assert await h.db.get_weekly_off() == set()
    assert not h.errors, h.errors


async def test_admin_views_and_cancels_booking(harness: Harness):
    h = harness
    await book_nails(h)
    booking = (await h.db.user_upcoming(CLIENT, now_local(TZ)))[0]
    await h.click(f"my:demo_pay:{booking.id}")

    await h.message("/admin", uid=ADMIN)
    await h.click("a:view:", uid=ADMIN)
    assert f"a:vday:{tomorrow_code()}" in h.buttons()
    await h.click(f"a:vday:{tomorrow_code()}", uid=ADMIN)
    assert f"a:bk:{booking.id}" in h.buttons()
    await h.click(f"a:bk:{booking.id}", uid=ADMIN)
    await h.click(f"a:bk_cancel:{booking.id}", uid=ADMIN)
    await h.click(f"a:bk_cancel_ok:{booking.id}", uid=ADMIN)

    assert (await h.db.get_booking(booking.id)).status == CANCELLED
    to_client = [c.text for c in h.session.of(SendMessage) if c.chat_id == CLIENT]
    assert any("пришлось отменить" in t for t in to_client)
    # слот снова свободен
    assert await h.db.busy_intervals(1, booking.start_dt.date(), booking.start_dt.date(), now_local(TZ)) == []
    assert not h.errors, h.errors


async def test_admin_stats_logs_and_digest(harness: Harness):
    h = harness
    await book_nails(h)
    booking = (await h.db.user_upcoming(CLIENT, now_local(TZ)))[0]
    await h.click(f"my:demo_pay:{booking.id}")

    await h.message("/admin", uid=ADMIN)
    await h.click("a:stats:", uid=ADMIN)
    stats_text = h.session.calls[-1].text
    assert "Предстоящих оплаченных записей: <b>1</b>" in stats_text

    h.settings.log_path.write_text(
        "15.10 12:00:00 INFO bot.handlers.booking: Новая бронь #1\n"
        "15.10 12:00:01 INFO aiogram.dispatcher: шум библиотеки\n"
        "15.10 12:00:02 ERROR bot.handlers.common: Ошибка <b>\n"
        "Traceback (most recent call last):\n",
        encoding="utf-8",
    )
    await h.click("a:logs:all", uid=ADMIN)
    text = h.session.calls[-1].text
    assert "Новая бронь #1" in text and "шум" not in text and "&lt;b&gt;" in text
    await h.click("a:logs:err", uid=ADMIN)
    text = h.session.calls[-1].text
    assert "Ошибка" in text and "Новая бронь" not in text

    await jobs.admin_digest(h.bot, h.db, h.settings)
    digest = [c.text for c in h.session.of(SendMessage) if c.chat_id == ADMIN][-1]
    assert "Записи на завтра" in digest and "Маникюр + гель-лак" in digest
    assert not h.errors, h.errors
