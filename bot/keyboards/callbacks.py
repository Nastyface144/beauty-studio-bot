"""Фабрики callback_data (итоговая строка ≤ 64 байт)."""
from aiogram.filters.callback_data import CallbackData

NOOP = "noop"


class MenuCb(CallbackData, prefix="m"):
    action: str  # main | book | my | prices | gallery | contacts


class BookCb(CallbackData, prefix="b"):
    action: str  # cat | srv | opt | opts_done | mst | day | time | confirm | back
    value: str = ""


class GalleryCb(CallbackData, prefix="g"):
    action: str  # cats | show | del
    category: str = ""
    index: int = 0
    item_id: int = 0


class MyCb(CallbackData, prefix="my"):
    action: str  # view | cancel | cancel_ok | pay | drop | demo_pay
    booking_id: int


class RateCb(CallbackData, prefix="r"):
    booking_id: int
    stars: int


class AdminCb(CallbackData, prefix="a"):
    action: str  # home | today | tomorrow | close | day | day_toggle | slot | photo | photo_cat
    value: str = ""
