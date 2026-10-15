"""Тексты бота. Разметка — HTML."""
from __future__ import annotations

from html import escape

from bot.config import Settings
from bot.database.models import CONFIRMED, PENDING, Booking, Option, Service
from bot.demo_data import category_title
from bot.utils.timeutil import MONTHS_NOM, WEEKDAYS_FULL, human_date, human_dt, human_duration, money


def welcome(settings: Settings, name: str) -> str:
    return (
        f"🌸 <b>{escape(settings.studio_name)}</b>\n\n"
        f"Здравствуйте, {escape(name)}! Рады видеть вас 💗\n\n"
        "Здесь можно за минуту записаться на маникюр, педикюр, брови или ресницы, "
        "посмотреть цены и наши работы.\n\n"
        "Чем могу помочь?"
    )


def main_menu(settings: Settings) -> str:
    return f"🌸 <b>{escape(settings.studio_name)}</b>\n\nВыберите, что вас интересует ✨"


SESSION_EXPIRED = "🌙 Кажется, страница устарела. Давайте начнём запись заново ✨"
SLOT_TAKEN = "😔 Ой, это время только что заняли. Пожалуйста, выберите другое."
def no_slots(days: int) -> str:
    return (
        f"😔 В ближайшие {days} дней у мастера нет свободного времени под эту процедуру.\n"
        "Попробуйте выбрать другого мастера или напишите нам."
    )


def choose_category() -> str:
    return "✨ <b>Запись</b>\n\nВыберите направление:"


def choose_service(category: str) -> str:
    return f"✨ <b>{category_title(category)}</b>\n\nВыберите услугу:"


def choose_options(service: Service, selected: list[Option]) -> str:
    lines = [
        f"✨ <b>{escape(service.name)}</b>",
        "",
        "Дополнительные опции",
        "Отметьте нужные (можно несколько) и нажмите «Далее».",
    ]
    if selected:
        lines += ["", "Выбрано: " + ", ".join(escape(o.name) for o in selected)]
    return "\n".join(lines)


def choose_master() -> str:
    return "👩‍🎨 Выберите мастера:"


def choose_date(master_name: str, duration: int) -> str:
    return (
        f"📅 Выберите дату\n\n"
        f"Мастер: <b>{escape(master_name)}</b>\n"
        f"Длительность: <b>{human_duration(duration)}</b>\n\n"
        "<i>✕ — нет свободного времени</i>"
    )


def choose_time(day, duration: int) -> str:
    return (
        f"🕐 Выберите время\n\n"
        f"<b>{human_date(day).capitalize()}</b>\n"
        f"Процедура займёт {human_duration(duration)}, "
        "показываю только то время, куда она помещается целиком."
    )


def summary(
    service: Service, options: list[Option], master_name: str, start, duration: int,
    price: int, prepay: int, settings: Settings,
) -> str:
    lines = [
        "💗 <b>Проверьте, пожалуйста, запись</b>",
        "",
        f"💅 Услуга: <b>{escape(service.name)}</b> — {money(service.price)}",
    ]
    for o in options:
        lines.append(f"   + {escape(o.name)} — {money(o.price)}")
    lines += [
        f"👩‍🎨 Мастер: <b>{escape(master_name)}</b>",
        f"📅 Когда: <b>{human_dt(start)}</b>",
        f"⏳ Длительность: <b>{human_duration(duration)}</b>",
        "",
        f"💰 Итого: <b>{money(price)}</b>",
        f"💳 Предоплата {settings.prepay_percent}%: <b>{money(prepay)}</b>",
        "",
        f"<i>После подтверждения время закрепится за вами на {settings.hold_minutes} минут — "
        "за это время нужно внести предоплату.</i>",
    ]
    return "\n".join(lines)


def booking_card(b: Booking, settings: Settings, with_status: bool = True) -> str:
    lines = [
        f"💅 <b>{escape(b.service_name)}</b>",
    ]
    if b.options_text:
        lines.append(f"   + {escape(b.options_text)}")
    lines += [
        f"👩‍🎨 Мастер: {escape(b.master_name)}",
        f"📅 {human_dt(b.start_dt)}",
        f"⏳ {human_duration(b.duration)} · {money(b.price)}",
    ]
    if with_status:
        if b.status == CONFIRMED:
            lines.append(f"✅ Предоплата {money(b.prepay)} внесена")
        elif b.status == PENDING:
            lines.append(f"⏳ Ожидает предоплаты {money(b.prepay)} до {b.expires_at[-5:]}")
    return "\n".join(lines)


def invoice_description(b: Booking) -> str:
    text = f"{b.service_name}"
    if b.options_text:
        text += f" + {b.options_text}"
    text += f". Мастер {b.master_name}, {human_dt(b.start_dt)}. Остаток оплачивается в студии."
    return text[:255]


def payment_success(b: Booking, settings: Settings) -> str:
    return (
        "🎉 <b>Вы записаны!</b>\n\n"
        + booking_card(b, settings)
        + f"\n\n📍 {escape(settings.studio_address)}\n\n"
        "Мы напомним о визите за сутки и за 2 часа. До встречи 💗"
    )


def payment_conflict() -> str:
    return (
        "😔 Оплата прошла, но, к сожалению, пока она обрабатывалась, это время успели занять.\n\n"
        "Администратор уже знает об этом и свяжется с вами, чтобы подобрать другое время "
        "или вернуть предоплату."
    )


def hold_expired(b: Booking) -> str:
    return (
        "⌛️ Время на оплату вышло, и бронь на "
        f"{human_dt(b.start_dt)} снята.\n\n"
        "Ничего страшного — можно записаться заново в пару касаний 🌸"
    )


def my_bookings(has_any: bool) -> str:
    if not has_any:
        return "📋 <b>Мои записи</b>\n\nУ вас пока нет предстоящих записей. Самое время себя порадовать ✨"
    return "📋 <b>Мои записи</b>\n\nВыберите запись, чтобы посмотреть подробности:"


def cancel_confirm(b: Booking, settings: Settings) -> str:
    refund = (
        f"\n\nПредоплата {money(b.prepay)} будет возвращена — администратор свяжется с вами."
        if b.status == CONFIRMED else ""
    )
    return "Точно отменить запись?\n\n" + booking_card(b, settings, with_status=False) + refund


def cancel_too_late(settings: Settings) -> str:
    return (
        f"\n\n<i>Отменить запись через бота можно не позднее чем за {settings.cancel_hours} часов. "
        f"Если планы изменились, позвоните нам: {escape(settings.studio_phone)}</i>"
    )


CANCELLED_OK = "🌸 Запись отменена. Будем рады видеть вас в другой раз!"


def prices(services_by_cat: dict[str, list[Service]], options: list[Option]) -> str:
    lines = ["💰 <b>Услуги и цены</b>"]
    for cat, items in services_by_cat.items():
        lines += ["", f"<b>{category_title(cat)}</b>"]
        for s in items:
            lines.append(f"• {escape(s.name)} — {money(s.price)} · {human_duration(s.duration)}")
    if options:
        lines += ["", "<b>✨ Дополнительно к ногтевым услугам</b>"]
        for o in options:
            lines.append(f"• {escape(o.name)} — +{money(o.price)} · +{human_duration(o.duration)}")
    return "\n".join(lines)


def contacts(settings: Settings) -> str:
    lines = [
        f"📍 <b>{escape(settings.studio_name)}</b>",
        "",
        f"🏠 {escape(settings.studio_address)}",
        f"📞 {escape(settings.studio_phone)}",
        f"🕘 Ежедневно {settings.work_start:%H:%M}–{settings.work_end:%H:%M}",
    ]
    if settings.studio_instagram:
        lines.append(f"📸 {escape(settings.studio_instagram)}")
    lines += ["", "Ждём вас в гости 💗"]
    return "\n".join(lines)


def gallery_categories() -> str:
    return "📸 <b>Наши работы</b>\n\nВыберите направление:"


def gallery_photo(category: str, idx: int, total: int, caption: str) -> str:
    text = f"{category_title(category)} · {idx + 1} из {total}"
    if caption:
        text += f"\n\n{escape(caption)}"
    return text


def gallery_empty(category: str) -> str:
    return f"{category_title(category)}\n\nСкоро здесь появятся фотографии наших работ 🌸"


def reminder(b: Booking, settings: Settings, hours: int) -> str:
    when = "завтра" if hours == 24 else "через 2 часа"
    return (
        f"🔔 <b>Напоминаем: {when} у вас запись</b>\n\n"
        + booking_card(b, settings, with_status=False)
        + f"\n\n📍 {escape(settings.studio_address)}\n"
        f"📞 {escape(settings.studio_phone)}\n\nЖдём вас 💗"
    )


def review_request(b: Booking) -> str:
    return (
        f"🌸 Спасибо, что были у нас сегодня!\n\n"
        f"Как вам «{escape(b.service_name)}» у мастера {escape(b.master_name)}? "
        "Поставьте, пожалуйста, оценку — это очень помогает нам становиться лучше."
    )


def review_thanks(rating: int) -> str:
    if rating >= 4:
        return f"{'⭐' * rating}\n\nСпасибо за высокую оценку! Будем рады видеть вас снова 💗"
    return (
        f"{'⭐' * rating}\n\nСпасибо за честность. Нам жаль, что что-то пошло не так — "
        "администратор свяжется с вами, чтобы во всём разобраться 🌸"
    )


# ---------- админ ----------

def _client(b: Booking) -> str:
    name = escape(b.client_name or "Клиент")
    if b.client_username:
        return f'{name} (@{escape(b.client_username)})'
    return f'<a href="tg://user?id={b.user_id}">{name}</a>'


def admin_new_booking(b: Booking) -> str:
    return "🆕 <b>Новая бронь (ждёт оплаты)</b>\n\n" + _admin_card(b)


def admin_paid(b: Booking) -> str:
    return f"💳 <b>Оплачена предоплата {money(b.prepay)}</b>\n\n" + _admin_card(b)


def admin_conflict(b: Booking) -> str:
    return (
        "⚠️ <b>Оплата пришла после снятия брони, а слот уже занят</b>\n"
        "Свяжитесь с клиентом: перенос или возврат.\n\n" + _admin_card(b)
    )


def admin_cancelled(b: Booking) -> str:
    refund = f"\n\n💸 Нужно вернуть предоплату {money(b.prepay)}" if b.status == CONFIRMED else ""
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
        f"💰 {money(b.price)}, предоплата {money(b.prepay)}\n"
        f"#запись{b.id}"
    )


def admin_home(settings: Settings, notice: str = "") -> str:
    text = f"🛠 <b>Админ-панель · {escape(settings.studio_name)}</b>\n\nВыберите действие:"
    return f"{notice}\n\n{text}" if notice else text


STATUS_TITLES = {
    "pending": "⏳ ждёт оплаты",
    "confirmed": "✅ оплачена",
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
        mark = "✅" if b.status in (CONFIRMED, "completed") else "⏳"
        opts = f" + {escape(b.options_text)}" if b.options_text else ""
        total += b.price
        lines.append(
            f"{mark} <b>{b.start[-5:]}–{b.end[-5:]}</b> · {escape(b.master_name)}\n"
            f"    {escape(b.service_name)}{opts}\n"
            f"    {_client(b)}"
        )
    if bookings:
        lines += ["", f"Записей: {len(bookings)} · на сумму {money(total)}"]
        lines += ["<i>✅ оплачено · ⏳ ждёт оплаты · нажмите на запись, чтобы открыть</i>"]
    return "\n".join(lines)


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
    if b.rating:
        lines.append(f"Оценка: {'⭐' * b.rating}")
    return "\n".join(lines)


def admin_cancel_confirm(b: Booking) -> str:
    refund = (
        f"\n\n💸 Клиент уже внёс предоплату {money(b.prepay)} — её нужно будет вернуть."
        if b.status == CONFIRMED else ""
    )
    return (
        "Отменить эту запись? Клиент получит сообщение об отмене.\n\n" + _admin_card(b) + refund
    )


def admin_cancelled_by_studio(b: Booking) -> str:
    refund = f"\n\n💸 Не забудьте вернуть предоплату {money(b.prepay)}" if b.status == CONFIRMED else ""
    return "❌ <b>Запись отменена администратором</b>\n\n" + _admin_card(b) + refund


def client_cancelled_by_studio(b: Booking, settings: Settings) -> str:
    refund = (
        f"\nПредоплату {money(b.prepay)} мы вернём — администратор свяжется с вами."
        if b.status == CONFIRMED else ""
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
        f"Получено предоплат: <b>{money(st['month_prepay'])}</b>",
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
