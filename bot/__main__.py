"""Точка входа: python -m bot"""
import asyncio
import logging
import sys

from bot.main import main

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except RuntimeError as e:  # понятная ошибка конфигурации вместо трейсбека
        logging.getLogger("bot").error("%s", e)
        sys.exit(1)
