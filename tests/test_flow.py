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

    def last_admin(self):
        for c in reversed(self.session.calls):
            if isinstance(c, (SendMessage, EditMessageText)) and c.chat_id == ADMIN:
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
    today = now_local(TZ).date()
    last_day = today + timedelta(days=29)
    # календарь показывает один месяц; остальные — стрелкой ▶️
    days = [b for b in h.buttons() if b.startswith("b:day:")]
    assert all(b[6:12] == f"{today:%Y%m}" for b in days)
    seen = set(days)
    if last_day.month != today.month:
        nxt = f"b:month:{last_day:%Y%m}"
        assert nxt in h.buttons()
        await h.click(nxt)
        days = [b for b in h.buttons() if b.startswith("b:day:")]
        assert all(b[6:12] == f"{last_day:%Y%m}" for b in days)
        assert f"b:month:{today:%Y%m}" in h.buttons()  # стрелка назад
        seen |= set(days)
    assert f"b:day:{day_code(last_day)}" in seen
    assert f"b:day:{day_code(last_day + timedelta(days=1))}" not in seen
    assert len(seen) >= 29  # сегодня может быть уже закрыто по времени
    # после выбора дня и возврата календарь открывается на месяце выбранного дня
    await h.click(f"b:day:{day_code(last_day)}")
    await h.click("b:back:calendar")
    assert f"b:day:{day_code(last_day)}" in h.buttons()
    assert not h.errors, h.errors


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
    admin_screen = [c.text for c in h.session.of(EditMessageText) if c.chat_id == ADMIN][-1]
    assert "отменена" in admin_screen and "Админ-панель" in admin_screen
    assert "вернуть предоплату" in admin_screen
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


async def test_finished_actions_return_to_main_menu(harness: Harness):
    h = harness
    await book_nails(h)
    booking = (await h.db.user_upcoming(CLIENT, now_local(TZ)))[0]
    # отказ от неоплаченной брони → главное меню
    await h.click(f"my:drop:{booking.id}")
    assert "m:book" in h.buttons() and "m:my" in h.buttons()
    assert "отменена" in h.last_screen()

    # оплата → меню
    await book_nails(h)
    booking = (await h.db.user_upcoming(CLIENT, now_local(TZ)))[0]
    await h.click(f"my:demo_pay:{booking.id}")
    assert "m:book" in h.buttons() and "Вы записаны" in h.last_screen()

    # отмена клиентом → меню
    await h.click("m:my")
    await h.click(f"my:view:{booking.id}")
    await h.click(f"my:cancel_ok:{booking.id}")
    assert "m:book" in h.buttons() and "отменена" in h.last_screen()

    # у админа в главном меню есть вход в админку
    await h.message("/start", uid=ADMIN)
    assert "a:home:" in h.buttons()
    await h.message("/start")
    assert "a:home:" not in h.buttons()
    assert not h.errors, h.errors


async def test_admin_calendars_have_month_arrows(harness: Harness):
    h = harness
    today = now_local(TZ).date()
    nxt = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    await h.message("/admin", uid=ADMIN)
    await h.click("a:view:", uid=ADMIN)
    assert f"a:view:{nxt:%Y%m}" in h.buttons()
    await h.click(f"a:view:{nxt:%Y%m}", uid=ADMIN)
    assert f"a:vday:{day_code(nxt)}" in h.buttons()
    await h.click("a:close:", uid=ADMIN)
    assert f"a:close:{nxt:%Y%m}" in h.buttons()
    await h.click(f"a:close:{nxt:%Y%m}", uid=ADMIN)
    await h.click(f"a:day:{day_code(nxt)}", uid=ADMIN)
    assert f"a:close:{nxt:%Y%m}" in h.buttons()  # «Назад» возвращает в тот же месяц
    assert not h.errors, h.errors


async def test_vacation_period(harness: Harness):
    h = harness
    await book_nails(h)  # запись на завтра 12:00
    booking = (await h.db.user_upcoming(CLIENT, now_local(TZ)))[0]
    await h.click(f"my:demo_pay:{booking.id}")

    today = now_local(TZ).date()
    start, end = today + timedelta(days=1), today + timedelta(days=40)  # период через границу месяца
    await h.message("/admin", uid=ADMIN)
    await h.click("a:vac:", uid=ADMIN)
    assert "Закрытых дней впереди нет" in h.last_admin()
    await h.click("a:vac_new:", uid=ADMIN)
    await h.click(f"a:vac_s:{day_code(start)}", uid=ADMIN)
    assert f"a:vac_e:{day_code(start)}{day_code(start)}" in h.buttons()   # можно закрыть один день
    assert f"a:vac_e:{day_code(start)}{day_code(today)}" not in h.buttons()  # раньше начала нельзя
    await h.click(f"a:vac_s:{day_code(start)}{end:%Y%m}", uid=ADMIN)       # стрелка к месяцу конца
    await h.click(f"a:vac_e:{day_code(start)}{day_code(end)}", uid=ADMIN)
    confirm = h.last_admin()
    assert "40 дней" in confirm and "уже есть записи (1)" in confirm
    await h.click(f"a:vac_ok:{day_code(start)}{day_code(end)}", uid=ADMIN)
    assert "✅ Закрыто" in h.last_admin()
    assert f"a:vac_open:{day_code(start)}{day_code(end)}" in h.buttons()

    # клиенту эти дни недоступны, существующая запись не отменена
    assert (await h.db.get_booking(booking.id)).status == CONFIRMED
    await h.click("m:book", uid=2002)
    await h.click("b:cat:brows", uid=2002)
    await h.click("b:srv:5", uid=2002)
    await h.click("b:mst:1", uid=2002)
    await h.click(f"b:day:{day_code(start + timedelta(days=3))}", uid=2002)
    assert not [b for b in h.buttons() if b.startswith("b:time:")]

    await h.click(f"a:vac_open:{day_code(start)}{day_code(end)}", uid=ADMIN)
    assert "🔓 Открыто" in h.last_admin()
    assert await h.db.closed_days(start, end, "09:00", "20:00") == set()
    assert not h.errors, h.errors


async def test_pay_on_site(harness: Harness):
    h = harness
    await h.message("/start")
    await h.click("m:book")
    await h.click("b:cat:nails")
    await h.click("b:srv:1")
    await h.click("b:opts_done:")
    await h.click("b:mst:2")
    await h.click(f"b:day:{tomorrow_code()}")
    await h.click("b:time:1500")
    assert "b:confirm:online" in h.buttons() and "b:confirm:cash" in h.buttons()
    assert "Как удобнее оплатить" in h.last_screen()
    await h.click("b:confirm:cash")

    booking = (await h.db.user_upcoming(CLIENT, now_local(TZ)))[0]
    assert booking.status == CONFIRMED and booking.pay_on_site and booking.prepay == 0
    assert "Вы записаны" in h.last_screen() and "Оплата в студии" in h.last_screen()
    assert "m:book" in h.buttons()  # сразу главное меню, без счёта
    assert not h.session.of(SendInvoice)
    admin_msgs = [c.text for c in h.session.of(SendMessage) if c.chat_id == ADMIN]
    assert any("оплата в студии" in t for t in admin_msgs)

    # бронь без предоплаты не снимается планировщиком, напоминания работают
    await jobs.expire_unpaid(h.bot, h.db, h.settings)
    assert (await h.db.get_booking(booking.id)).status == CONFIRMED

    # при отмене не обещаем вернуть деньги
    await h.click("m:my")
    await h.click(f"my:view:{booking.id}")
    await h.click(f"my:cancel:{booking.id}")
    assert "вернут" not in h.last_screen()
    await h.click(f"my:cancel_ok:{booking.id}")
    assert (await h.db.get_booking(booking.id)).status == CANCELLED
    assert not any("вернуть" in c.text for c in h.session.of(SendMessage) if c.chat_id == ADMIN)
    assert not h.errors, h.errors


async def test_payment_methods_settings(db, tmp_path):
    from dataclasses import replace
    base = make_settings(tmp_path)
    only_cash = replace(base, pay_online=False)
    only_online = replace(base, pay_on_site=False)
    for settings, expect in ((only_cash, {"b:confirm:cash"}), (only_online, {"b:confirm:online"})):
        h = Harness(_dispatcher(db, settings), db, settings)
        await h.message("/start")
        await h.click("m:book")
        await h.click("b:cat:brows")
        await h.click("b:srv:5")
        await h.click("b:mst:1")
        await h.click(f"b:day:{tomorrow_code()}")
        await h.click("b:time:1000")
        confirm = {b for b in h.buttons() if b.startswith("b:confirm:")}
        assert confirm == expect
        # подмена кнопки на запрещённый способ не проходит
        forbidden = "b:confirm:online" if settings is only_cash else "b:confirm:cash"
        await h.click(forbidden)
        booking = (await db.user_upcoming(CLIENT, now_local(TZ)))[0]
        assert booking.pay_on_site == (settings is only_cash)
        await db.cancel_booking(booking.id)
        assert not h.errors, h.errors


async def test_migration_adds_payment_method(tmp_path):
    import sqlite3
    from bot.database.db import Database
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE bookings (id INTEGER PRIMARY KEY, user_id INTEGER, master_id INTEGER,
        master_name TEXT, service_id INTEGER, service_name TEXT, option_ids TEXT, options_text TEXT,
        start TEXT, end TEXT, price INTEGER, prepay INTEGER, status TEXT, expires_at TEXT,
        invoice_message_id INTEGER, charge_id TEXT, reminded_24 INTEGER DEFAULT 0, reminded_2 INTEGER DEFAULT 0,
        review_requested INTEGER DEFAULT 0, rating INTEGER, created_at TEXT)""")
    con.execute("""INSERT INTO bookings(user_id, master_id, master_name, service_id, service_name, option_ids,
        options_text, start, end, price, prepay, status, created_at)
        VALUES (1, 1, 'Анна', 1, 'Маникюр', '[]', '', '2030-01-01 10:00', '2030-01-01 11:00', 1200, 360,
        'confirmed', '2029-12-01 10:00')""")
    con.commit()
    con.close()
    database = Database(path)
    await database.connect()
    booking = await database.get_booking(1)
    assert booking.payment_method == "online" and booking.refund_due
    await database.close()
