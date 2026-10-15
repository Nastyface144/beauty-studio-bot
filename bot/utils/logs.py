"""Журнал бота: запись в файл и чтение последних событий для админки."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from zoneinfo import ZoneInfo

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
FILE_DATEFMT = "%d.%m %H:%M:%S"
LINE_RE = re.compile(r"^(\d\d\.\d\d \d\d:\d\d:\d\d) (\w+) ([\w.]+): (.*)$")
SHORT_LEVEL = {"WARNING": "⚠️", "ERROR": "❗", "CRITICAL": "❗"}


def setup_logging(log_path: Path | None = None, tz: ZoneInfo | None = None) -> None:
    """Консоль + файл с ротацией. Время в журнале — по часовому поясу студии."""
    def converter(ts):
        return datetime.fromtimestamp(ts, tz).timetuple() if tz else datetime.fromtimestamp(ts).timetuple()

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler()
    console_fmt = logging.Formatter(LOG_FORMAT)
    console_fmt.converter = converter
    console.setFormatter(console_fmt)
    root.addHandler(console)

    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        file_fmt = logging.Formatter(LOG_FORMAT, datefmt=FILE_DATEFMT)
        file_fmt.converter = converter
        file_handler.setFormatter(file_fmt)
        root.addHandler(file_handler)

    # Служебные библиотеки пишут строку на каждый запуск задачи и каждый апдейт — это шум
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


def read_events(log_path: Path, limit: int = 25, errors_only: bool = False, max_chars: int = 3000) -> list[str]:
    """Последние события из журнала в компактном виде: «15.10 12:50 Текст»."""
    try:
        with open(log_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 200_000))
            raw = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []

    events = []
    for line in raw.splitlines():
        m = LINE_RE.match(line)
        if not m:
            continue  # строки трейсбека и обрывки в начале буфера
        stamp, level, name, message = m.groups()
        is_problem = level in SHORT_LEVEL
        if errors_only and not is_problem:
            continue
        if not is_problem and not name.startswith("bot"):
            continue  # информационные сообщения библиотек админу не нужны
        icon = SHORT_LEVEL.get(level, "•")
        events.append(f"{stamp[:-3]} {icon} {message[:300]}")

    result: list[str] = []
    total = 0
    for event in reversed(events[-limit:]):
        if total + len(event) > max_chars:
            break
        result.append(event)
        total += len(event) + 1
    return list(reversed(result))
