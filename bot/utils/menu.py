"""Главное меню как «точка возврата» после завершённых действий."""
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from bot import texts
from bot.config import Settings
from bot.keyboards import client as kb


def main_menu_screen(settings: Settings, user_id: int, notice: str = "") -> tuple[str, InlineKeyboardMarkup]:
    """Текст и кнопки главного меню. `notice` — короткое сообщение о том, что только что произошло."""
    text = texts.main_menu(settings)
    if notice:
        text = f"{notice}\n\n{text}"
    return text, kb.main_menu(is_admin=user_id in settings.admin_ids)
