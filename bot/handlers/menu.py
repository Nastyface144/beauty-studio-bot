"""/start, главное меню, цены и контакты."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot import texts
from bot.config import Settings
from bot.database.db import Database
from bot.demo_data import CATEGORIES
from bot.keyboards import client as kb
from bot.keyboards.callbacks import NOOP, MenuCb
from bot.utils.ui import safe_delete, show

router = Router(name="menu")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    await state.clear()
    user = message.from_user
    await db.upsert_user(user.id, user.full_name, user.username)
    await show(message, db, texts.welcome(settings, user.first_name or user.full_name), kb.main_menu())
    await safe_delete(message.bot, message.chat.id, message.message_id)


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    await state.clear()
    await show(message, db, texts.main_menu(settings), kb.main_menu())
    await safe_delete(message.bot, message.chat.id, message.message_id)


@router.callback_query(MenuCb.filter(F.action == "main"))
async def main_menu(cb: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    await cb.answer()
    await state.clear()
    await show(cb, db, texts.main_menu(settings), kb.main_menu())


@router.callback_query(MenuCb.filter(F.action == "prices"))
async def prices(cb: CallbackQuery, db: Database) -> None:
    await cb.answer()
    by_cat = {cat: await db.services(cat) for cat in CATEGORIES}
    options = []
    for cat in CATEGORIES:
        options += await db.options(cat)
    await show(cb, db, texts.prices(by_cat, options), kb.prices())


@router.callback_query(MenuCb.filter(F.action == "contacts"))
async def contacts(cb: CallbackQuery, db: Database, settings: Settings) -> None:
    await cb.answer()
    await show(cb, db, texts.contacts(settings), kb.contacts(settings))


@router.callback_query(F.data == NOOP)
async def noop(cb: CallbackQuery) -> None:
    await cb.answer()
