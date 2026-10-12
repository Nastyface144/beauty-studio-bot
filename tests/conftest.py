import pytest_asyncio

from bot.config import BASE_DIR
from bot.database.db import Database


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.connect()
    await database.seed_demo_data(BASE_DIR / "assets" / "gallery")
    yield database
    await database.close()
