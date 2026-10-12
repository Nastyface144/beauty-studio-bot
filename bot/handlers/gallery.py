"""«Наши работы»: галерея фото по категориям с листанием."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, FSInputFile

from bot import texts
from bot.config import Settings
from bot.database.db import Database
from bot.demo_data import CATEGORIES
from bot.keyboards import client as kb
from bot.keyboards.callbacks import GalleryCb, MenuCb
from bot.utils.ui import show

log = logging.getLogger(__name__)
router = Router(name="gallery")


async def render_categories(cb: CallbackQuery, db: Database) -> None:
    await show(cb, db, texts.gallery_categories(), kb.gallery_categories())


async def render_photo(cb: CallbackQuery, db: Database, settings: Settings, category: str, index: int) -> None:
    items = await db.gallery(category)
    # Пропускаем демо-фото, файлы которых удалили с диска
    items = [i for i in items if i.file_id or (i.file_path and (settings.gallery_dir / i.file_path).exists())]
    if not items:
        return await show(cb, db, texts.gallery_empty(category), kb.gallery_empty())

    index %= len(items)
    item = items[index]
    is_admin = cb.from_user.id in settings.admin_ids
    caption = texts.gallery_photo(category, index, len(items), item.caption)
    markup = kb.gallery_nav(category, index, len(items), item.id, is_admin)
    photo = item.file_id or FSInputFile(settings.gallery_dir / item.file_path)

    msg = await show(cb, db, caption, markup, photo=photo)
    # После первой загрузки с диска запоминаем file_id — дальше Telegram отдаёт фото мгновенно
    if not item.file_id and msg.photo:
        await db.cache_photo_file_id(item.id, msg.photo[-1].file_id)


@router.callback_query(MenuCb.filter(F.action == "gallery"))
async def open_gallery(cb: CallbackQuery, db: Database) -> None:
    await cb.answer()
    await render_categories(cb, db)


@router.callback_query(GalleryCb.filter(F.action == "cats"))
async def back_to_categories(cb: CallbackQuery, db: Database) -> None:
    await cb.answer()
    await render_categories(cb, db)


@router.callback_query(GalleryCb.filter(F.action == "show"))
async def show_photo(cb: CallbackQuery, callback_data: GalleryCb, db: Database, settings: Settings) -> None:
    await cb.answer()
    if callback_data.category not in CATEGORIES:
        return await render_categories(cb, db)
    await render_photo(cb, db, settings, callback_data.category, callback_data.index)


@router.callback_query(GalleryCb.filter(F.action == "del"))
async def delete_photo(cb: CallbackQuery, callback_data: GalleryCb, db: Database, settings: Settings) -> None:
    if cb.from_user.id not in settings.admin_ids:
        await cb.answer()
        return
    await db.delete_photo(callback_data.item_id)
    await cb.answer("Фото удалено")
    await render_photo(cb, db, settings, callback_data.category, max(callback_data.index - 1, 0))
