"""Тексты бота. Разметка — HTML."""
from __future__ import annotations

from html import escape

from bot.config import Settings
from bot.database.models import CONFIRMED, PENDING, Booking, Master, Option, Service
from bot.demo_data import category_title
from bot.utils.timeutil import (
    MONTHS_GEN, MONTHS_NOM, WEEKDAYS_FULL, WEEKDAYS_SHORT, human_date, human_dt, human_duration, money,
)

ANY_MASTER_TITLE = "любой свободный мастер"


def short_date(d) -> str:
    """17 октября, сб"""
    return f"{d.day} {MONTHS_GEN[d.month - 1]}, {WEEKDAYS_SHORT[d.weekday()].lower()}"


# ---------- главное меню ----------

def welcome(settings: Settings, name: str) -> str:
    return (
        f"<b>{escape(settings.studio_name)}</b>\n"
        "Маникюр · педикюр · брови · ресницы\n\n"
        f"Здравствуйте, {escape(name)}!\n"
        "Здесь можно записаться к мастеру, посмотреть цены и примеры работ.\n\n"
        f"🕘 Ежедневно {settings.work_start:%H:%M}–{settings.work_end:%H:%M}\n"
        f"📍 {escape(settings.studio_address)}"
    )


def main_menu(settings: Settings) -> str:
    return (
        f"<b>{escape(settings.studio_name)}</b>\n"
        f"🕘 Ежедневно {settings.work_start:%H:%M}–{settings.work_end:%H:%M}\n\n"
        "Выберите раздел:"
    )


SESSION_EXPIRED = "Сессия записи устарела. Начните, пожалуйста, заново."
SLOT_TAKEN = "Это время только что заняли. Выберите, пожалуйста, другое."
DAY_FULL = "На этот день свободного времени не осталось."
DATE_UNAVAILABLE = "Эта дата недоступна для записи."


def no_slots(days: int, any_master: bool) -> str:
    who = "у мастеров" if any_master else "у мастера"
    tail = "" if any_master else " Попробуйте другого мастера или вариант «Любой свободный»."
    return f"😔 В ближайшие {days} дней {who} нет свободного времени под эту процедуру.{tail}"


# ---------- шаги записи ----------

def step_header(n: int, total: int, recap: list[tuple[str, str]]) -> str:
    lines = [f"<b>Запись</b> · шаг {n} из {total}"]
    for label, value in recap:
        lines.append(f"{label}: <b>{escape(value)}</b>")
    return "\n".join(lines) + "\n\n"


def choose_category() -> str:
    return "Выберите направление:"


def choose_service(category: str) -> str:
    return f"{category_title(category)}\nВыберите услугу:"


def choose_options(selected: list[Option], price: int) -> str:
    lines = ["Добавьте дополнительные услуги, если нужно.", "Можно выбрать несколько или пропустить этот шаг."]
    if selected:
        lines += ["", f"Стоимость с дополнениями: <b>{money(price)}</b>"]
    return "\n".join(lines)


def choose_master(masters: list[Master], duration: int, price: int) -> str:
    lines = [f"Длительность: {human_duration(duration)} · {money(price)}", "", "Выберите мастера:"]
    for m in masters:
        if m.about:
            lines.append(f"• <b>{escape(m.name)}</b> — {escape(m.about)}")
    lines += ["", "<i>«Любой свободный» — покажем всё доступное время у всех мастеров.</i>"]
    return "\n".join(lines)


def choose_date() -> str:
    return "Выберите дату:\n<i>✕ — всё занято · бледные числа — выходные дни</i>"


def choose_time(duration: int) -> str:
    return f"Выберите время (процедура займёт {human_duration(duration)}):\n<i>✕ — время занято</i>"


def _payment_hint(settings: Settings, price: int, prepay: int) -> list[str]:
    online, on_site = settings.online_available, settings.on_site_available
    full = prepay >= price
    card = (
        f"💳 <b>Картой онлайн</b> — {money(prepay)} сейчас"
        + ("" if full else f", остальное ({money(price - prepay)}) в салоне")
        + f". Время держится {settings.hold_minutes} мин, пока вы оплачиваете."
    )
    salon = f"🏠 <b>В салоне</b> — {money(price)} после процедуры, наличными или картой."
    if online and on_site:
        return ["<b>Способ оплаты</b>", card, salon]
    if online:
        return ["<b>Оплата</b>", card]
    return ["<b>Оплата</b>", salon]


def summary(
    service: Service, options: list[Option], master_name: str, start, duration: int,
    price: int, prepay: int, settings: Settings,
) -> str:
    lines = [
        "<b>Проверьте запись</b>",
        "",
        f"Услуга: <b>{escape(service.name)}</b> — {money(service.price)}",
    ]
    for o in options:
        lines.append(f"   + {escape(o.name)} — {money(o.price)}")
    lines += [
        f"Мастер: <b>{escape(master_name)}</b>",
        f"Дата и время: <b>{human_dt(start)}</b>",
        f"Длительность: {human_duration(duration)}",
        "",
        f"Итого: <b>{money(price)}</b>",
        "",
    ]
    lines += _payment_hint(settings, price, prepay)
    return "\n".join(lines)


def _payment_status(b: Booking) -> str:
    if b.status == PENDING:
        return f"⏳ Ожидает оплаты {money(b.prepay)} до {b.expires_at[-5:]}"
    if b.pay_on_site:
        return f"🏠 Оплата в салоне: {money(b.price)}"
    if b.prepay >= b.price:
        return f"✅ Оплачено картой: {money(b.prepay)}"
    return f"✅ Оплачено картой {money(b.prepay)} · в салоне {money(b.price - b.prepay)}"


def booking_card(b: Booking, settings: Settings, with_status: bool = True) -> str:
    service = escape(b.service_name) + (f" + {escape(b.options_text)}" if b.options_text else "")
    lines = [
        f"📅 <b>{human_dt(b.start_dt)}</b>",
        f"💅 {service}",
        f"👤 Мастер: {escape(b.master_name)}",
        f"⏳ {human_duration(b.duration)} · {money(b.price)}",
    ]
    if with_status and b.status in (PENDING, CONFIRMED):
        lines.append(_payment_status(b))
    return "\n".join(lines)


def invoice_description(b: Booking) -> str:
    text = f"{b.service_name}"
    if b.options_text:
        text += f" + {b.options_text}"
    text += f". Мастер {b.master_name}, {human_dt(b.start_dt)}."
    if b.prepay < b.price:
        text += f" Остаток {b.price - b.prepay} ₽ оплачивается в салоне."
    return text[:255]


def payment_success(b: Booking, settings: Settings) -> str:
    return (
        "✅ <b>Вы записаны</b>\n\n"
        + booking_card(b, settings)
        + f"\n\n📍 {escape(settings.studio_address)}\n"
        f"📞 {escape(settings.studio_phone)}\n\n"
        "Напомним о визите за сутки и за 2 часа. Запись можно посмотреть или отменить в разделе «Мои записи»."
    )


def payment_conflict() -> str:
    return (
        "Оплата прошла, но пока она обрабатывалась, это время успели занять.\n\n"
        "Администратор уже в курсе и свяжется с вами, чтобы подобрать другое время или вернуть деньги."
    )


def hold_expired(b: Booking) -> str:
    return (
        f"⌛️ Время на оплату вышло, бронь на {human_dt(b.start_dt)} снята.\n"
        "Вы можете записаться заново — в том числе с оплатой в салоне."
    )


def my_bookings(has_any: bool) -> str:
    if not has_any:
        return "<b>Мои записи</b>\n\nПредстоящих записей нет."
    return "<b>Мои записи</b>\n\nВыберите запись:"


def cancel_confirm(b: Booking, settings: Settings) -> str:
    refund = (
        f"\n\nОплаченные {money(b.prepay)} вернём — администратор свяжется с вами."
        if b.refund_due else ""
    )
    return "<b>Отменить запись?</b>\n\n" + booking_card(b, settings, with_status=False) + refund


def cancel_too_late(settings: Settings) -> str:
    return (
        f"\n\n<i>Отменить запись в боте можно не позднее чем за {settings.cancel_hours} ч до визита. "
        f"Если планы изменились, позвоните нам: {escape(settings.studio_phone)}</i>"
    )


CANCELLED_OK = "Запись отменена."


# ---------- информация ----------

def prices(services_by_cat: dict[str, list[Service]], options: list[Option]) -> str:
    lines = ["<b>Услуги и цены</b>"]
    for cat, items in services_by_cat.items():
        lines += ["", f"<b>{category_title(cat)}</b>"]
        for s in items:
            lines.append(f"{escape(s.name)} — <b>{money(s.price)}</b> · {human_duration(s.duration)}")
    if options:
        lines += ["", "<b>Дополнительно к ногтевому сервису</b>"]
        for o in options:
            lines.append(f"{escape(o.name)} — +{money(o.price)} · +{human_duration(o.duration)}")
    return "\n".join(lines)


def contacts(settings: Settings) -> str:
    lines = [
        f"<b>{escape(settings.studio_name)}</b>",
        "",
        f"📍 {escape(settings.studio_address)}",
        f"📞 {escape(settings.studio_phone)}",
        f"🕘 Ежедневно {settings.work_start:%H:%M}–{settings.work_end:%H:%M}",
    ]
    if settings.studio_instagram:
        lines.append(f"📸 {escape(settings.studio_instagram)}")
    return "\n".join(lines)


def gallery_categories() -> str:
    return "<b>Портфолио</b>\n\nВыберите направление:"


def gallery_photo(category: str, idx: int, total: int, caption: str) -> str:
    text = f"{category_title(category)} · {idx + 1} из {total}"
    if caption:
        text += f"\n\n{escape(caption)}"
    return text


def gallery_empty(category: str) -> str:
    return f"{category_title(category)}\n\nФотографии работ скоро появятся."


def reminder(b: Booking, settings: Settings, hours: int) -> str:
    when = "завтра" if hours == 24 else "через 2 часа"
    return (
        f"🔔 <b>Напоминание: {when} у вас запись</b>\n\n"
        + booking_card(b, settings)
        + f"\n\n📍 {escape(settings.studio_address)}\n"
        f"📞 {escape(settings.studio_phone)}"
    )


def review_request(b: Booking) -> str:
    return (
        "Спасибо, что выбрали нас!\n\n"
        f"Оцените, пожалуйста, визит: «{escape(b.service_name)}», мастер {escape(b.master_name)}."
    )


def review_thanks(rating: int) -> str:
    if rating >= 4:
        return f"{'⭐' * rating}\nСпасибо за оценку! Будем рады видеть вас снова."
    return (
        f"{'⭐' * rating}\nСпасибо за отзыв. Нам жаль, что визит не оправдал ожиданий — "
        "администратор свяжется с вами."
    )


# ---------- админ ----------

def _client(b: Booking) -> str:
    name = escape(b.client_name or "Клиент")
    if b.client_username:
        return f'{name} (@{escape(b.client_username)})'
    return f'<a href="tg://user?id={b.user_id}">{name}</a>'


def admin_new_booking(b: Booking) -> str:
    if b.pay_on_site:
        return "🆕 <b>Новая запись</b> · 🏠 оплата в салоне\n\n" + _admin_card(b)
    return "🆕 <b>Новая бронь (ждёт оплаты картой)</b>\n\n" + _admin_card(b)


def admin_paid(b: Booking) -> str:
    return f"💳 <b>Оплачена предоплата {money(b.prepay)}</b>\n\n" + _admin_card(b)


def admin_conflict(b: Booking) -> str:
    return (
        "⚠️ <b>Оплата пришла после снятия брони, а слот уже занят</b>\n"
        "Свяжитесь с клиентом: перенос или возврат.\n\n" + _admin_card(b)
    )


def admin_cancelled(b: Booking) -> str:
    refund = f"\n\n💸 Нужно вернуть предоплату {money(b.prepay)}" if b.refund_due else ""
    return "❌ <b>Клиент отменил запись</b>\n\n" + _admin_card(b) + refund


def admin_rating(b: Booking, rating: int) -> str:
    return f"{'⭐' * rating} <b>Оценка {rating}/5</b>\n\n" + _admin_card(b)


def _admin_card(b: Booking) -> str:
    opts = f" + {escape(b.options_text)}" if b.options_text else ""
    return (
        f"👤 {_client(b)}\n"
        f"💅 {escape(b.service_name)}{opts}\n"
        f"👩‍🎨 {escape(b.master_name)}\n"
        f"📅 {human_dt(b.start_dt)} ({human_duration(b.duration)})\n"
        f"💰 {money(b.price)}, " + ("оплата в салоне" if b.pay_on_site else f"предоплата {money(b.prepay)}") + "\n"
        f"#запись{b.id}"
    )


def admin_home(settings: Settings, notice: str = "") -> str:
    text = f"🛠 <b>Админ-панель · {escape(settings.studio_name)}</b>\n\nВыберите действие:"
    return f"{notice}\n\n{text}" if notice else text


STATUS_TITLES = {
    "pending": "⏳ ждёт оплаты",
    "confirmed": "✅ подтверждена",
    "completed": "🌸 визит состоялся",
    "cancelled": "❌ отменена",
    "expired": "⌛️ не оплачена, снята",
}


def admin_day(day, bookings: list[Booking], day_off: bool = False, header: str = "") -> str:
    lines = [header or f"📅 <b>{human_date(day).capitalize()}</b>", ""]
    if day_off:
        lines += ["💤 Выходной по графику", ""]
    if not bookings:
        lines.append("Записей нет 🌿")
    total = 0
    for b in bookings:
        mark = _mark(b)
        opts = f" + {escape(b.options_text)}" if b.options_text else ""
        total += b.price
        lines.append(
            f"{mark} <b>{b.start[-5:]}–{b.end[-5:]}</b> · {escape(b.master_name)}\n"
            f"    {escape(b.service_name)}{opts}\n"
            f"    {_client(b)}"
        )
    if bookings:
        lines += ["", f"Записей: {len(bookings)} · на сумму {money(total)}"]
        lines += ["<i>✅ предоплата внесена · 🏠 оплата в салоне · ⏳ ждёт предоплаты\nНажмите на запись, чтобы открыть</i>"]
    return "\n".join(lines)


def _mark(b: Booking) -> str:
    if b.status == PENDING:
        return "⏳"
    return "🏠" if b.pay_on_site else "✅"


def admin_digest(day, bookings: list[Booking]) -> str:
    return admin_day(day, bookings, header=f"🌙 <b>Записи на завтра, {human_date(day)}</b>")


def admin_view_pick_day() -> str:
    return (
        "📋 <b>Все записи</b>\n\nВыберите дату.\n"
        "<i>Точка рядом с числом (12•) — в этот день есть записи. 💤 — выходной по графику.</i>"
    )


def admin_booking(b: Booking) -> str:
    lines = [f"🧾 <b>Запись #{b.id}</b>", "", _admin_card(b), ""]
    lines.append(f"Статус: {STATUS_TITLES.get(b.status, b.status)}")
    if b.status in (CONFIRMED, "completed"):
        lines.append("Оплата: 🏠 в салоне" if b.pay_on_site else f"Оплата: ✅ картой {money(b.prepay)}")
    if b.rating:
        lines.append(f"Оценка: {'⭐' * b.rating}")
    return "\n".join(lines)


def admin_cancel_confirm(b: Booking) -> str:
    refund = (
        f"\n\n💸 Клиент уже внёс предоплату {money(b.prepay)} — её нужно будет вернуть."
        if b.refund_due else ""
    )
    return (
        "Отменить эту запись? Клиент получит сообщение об отмене.\n\n" + _admin_card(b) + refund
    )


def admin_cancelled_by_studio(b: Booking) -> str:
    refund = f"\n\n💸 Не забудьте вернуть предоплату {money(b.prepay)}" if b.refund_due else ""
    return "❌ <b>Запись отменена администратором</b>\n\n" + _admin_card(b) + refund


def client_cancelled_by_studio(b: Booking, settings: Settings) -> str:
    refund = (
        f"\nПредоплату {money(b.prepay)} мы вернём — администратор свяжется с вами."
        if b.refund_due else ""
    )
    return (
        "😔 <b>К сожалению, нам пришлось отменить вашу запись</b>\n\n"
        + booking_card(b, settings, with_status=False)
        + f"\n{refund}\n\nПросим прощения! Подобрать другое время можно в боте "
        f"или по телефону {escape(settings.studio_phone)} 🌸"
    )


def admin_stats(st: dict, now) -> str:
    avg = f"{st['avg_rating']:.1f} ⭐ ({st['ratings']} оценок)" if st["ratings"] else "пока нет"
    month = MONTHS_NOM[now.month - 1].lower()
    return "\n".join([
        "📊 <b>Статистика</b>",
        "",
        f"Предстоящих оплаченных записей: <b>{st['upcoming']}</b>",
        f"Сейчас ждут оплаты: <b>{st['pending']}</b>",
        "",
        f"<b>За {month}</b>",
        f"Визитов (оплаченных): <b>{st['month_visits']}</b>",
        f"Сумма услуг: <b>{money(st['month_revenue'])}</b>",
        f"Оплачено картой: <b>{money(st['month_prepay'])}</b>",
        f"Отмен после оплаты: <b>{st['month_cancelled']}</b>",
        f"Броней без оплаты (снялись): <b>{st['month_expired']}</b>",
        "",
        f"Средняя оценка: <b>{avg}</b>",
        f"Клиентов в боте: <b>{st['clients']}</b>",
    ])


def admin_logs(lines: list[str], errors_only: bool) -> str:
    title = "⚠️ <b>Журнал: ошибки и предупреждения</b>" if errors_only else "🧾 <b>Журнал событий</b>"
    if not lines:
        return title + "\n\nЗаписей пока нет 🌿"
    body = escape("\n".join(lines))
    return f"{title}\n<i>последние события, новые внизу</i>\n\n<pre>{body}</pre>"


def admin_weekly(off: set[int]) -> str:
    names = ", ".join(WEEKDAYS_FULL[d] for d in sorted(off)) if off else "нет"
    return (
        "💤 <b>Выходные по дням недели</b>\n\n"
        "Нажмите на день, чтобы сделать его выходным или рабочим. "
        "В выходные дни клиенты не смогут записаться.\n\n"
        f"Сейчас выходные: <b>{names}</b>\n\n"
        "<i>Уже существующие записи на эти дни не отменяются.</i>"
    )


def admin_close_pick_day() -> str:
    return (
        "🔒 <b>Закрыть день или время</b>\n\nВыберите дату:\n"
        "<i>🔒 — день закрыт целиком · 💤 — выходной по графику</i>"
    )


def admin_close_day(day, day_closed: bool, active: int, day_off: bool = False) -> str:
    lines = [
        f"🔒 <b>{human_date(day).capitalize()}</b>",
        "",
    ]
    if day_off:
        lines += ["💤 Это выходной по графику — запись закрыта. Изменить: «Выходные по дням недели».", ""]
    lines += [
        "Нажмите на время, чтобы закрыть или открыть его (интервалы по 30 минут). "
        "🔒 — закрыто.",
    ]
    if day_closed:
        lines += ["", "<b>День закрыт целиком.</b>"]
    if active:
        lines += ["", f"⚠️ На этот день есть активные записи: {active}. Закрытие их не отменяет."]
    return "\n".join(lines)


def admin_photo_pick() -> str:
    return "📸 <b>Добавить фото в галерею</b>\n\nВыберите раздел:"


def admin_photo_wait(category: str) -> str:
    return (
        f"📸 Раздел: <b>{category_title(category)}</b>\n\n"
        "Отправьте фото одним сообщением. Подпись к фото станет описанием работы."
    )


def admin_photo_saved(category: str) -> str:
    return f"✅ Фото добавлено в раздел «{category_title(category)}». Можно отправить ещё одно."


def admin_expired(b: Booking) -> str:
    return "⌛️ <b>Бронь снята: не оплачена вовремя</b>\n\n" + _admin_card(b)


def period_label(start, end) -> str:
    if start == end:
        return f"{start:%d.%m}"
    return f"{start:%d.%m}–{end:%d.%m}"


def _days_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "день"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "дня"
    return "дней"


def admin_vacations(periods: list, notice: str = "") -> str:
    lines = []
    if notice:
        lines += [notice, ""]
    lines += ["🏖 <b>Отпуск и закрытые периоды</b>", ""]
    if periods:
        lines.append("Сейчас закрыто (запись в эти дни недоступна):")
        for start, end in periods:
            n = (end - start).days + 1
            lines.append(f"• {period_label(start, end)} — {n} {_days_word(n)}")
        lines += ["", "<i>Нажмите «🔓 Открыть», чтобы вернуть запись на эти дни.</i>"]
    else:
        lines.append("Закрытых дней впереди нет 🌿")
    return "\n".join(lines)


def admin_vac_pick_start() -> str:
    return (
        "🏖 <b>Закрыть период</b>\n\n"
        "Шаг 1 из 2: выберите <b>первый</b> нерабочий день.\n"
        "<i>🔒 — уже закрыто · 💤 — выходной по графику</i>"
    )


def admin_vac_pick_end(start) -> str:
    return (
        "🏖 <b>Закрыть период</b>\n\n"
        f"Начало: <b>{human_date(start)}</b>\n"
        "Шаг 2 из 2: выберите <b>последний</b> нерабочий день "
        "(если закрываете один день — нажмите на него же)."
    )


def admin_vac_confirm(start, end, bookings: list[Booking]) -> str:
    n = (end - start).days + 1
    lines = [
        "🏖 <b>Закрыть период?</b>",
        "",
        f"С <b>{human_date(start)}</b>",
        f"по <b>{human_date(end)}</b>",
        f"Всего: {n} {_days_word(n)}. Клиенты не смогут записаться на эти дни.",
    ]
    if bookings:
        lines += ["", f"⚠️ На эти дни уже есть записи ({len(bookings)}) — закрытие их <b>не отменяет</b>:"]
        for b in bookings[:10]:
            lines.append(f"• {b.start_dt:%d.%m %H:%M} · {escape(b.master_name)} · {escape(b.client_name or 'Клиент')}")
        if len(bookings) > 10:
            lines.append(f"… и ещё {len(bookings) - 10}")
        lines.append("Перенесите или отмените их в «📋 Все записи по датам».")
    return "\n".join(lines)


def admin_switched_to_cash(b: Booking) -> str:
    return "🔁 <b>Клиент выбрал оплату в салоне</b> (вместо карты)\n\n" + _admin_card(b)
