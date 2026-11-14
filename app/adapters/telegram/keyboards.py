"""Reply and inline keyboards, in the user's language."""

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.engine.templates import LANGUAGES, render
from app.models import User
from app.services.http import PlaceCandidate


def main_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=render("btn_where", lang)), KeyboardButton(text=render("btn_time", lang))],
            [KeyboardButton(text=render("btn_nearby", lang)), KeyboardButton(text=render("btn_stop", lang))],
            [KeyboardButton(text=render("btn_send_location", lang), request_location=True)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=name, callback_data=f"lang:{code}") for code, name in LANGUAGES.items()]]
    )


def destination_keyboard(candidates: list[PlaceCandidate], lang: str) -> InlineKeyboardMarkup:
    rows = []
    for i, c in enumerate(candidates):
        label = f"📍 {c.name}" + (f" · {c.detail}" if c.detail else "")
        rows.append([InlineKeyboardButton(text=label[:64], callback_data=f"dest:{i}")])
    rows.append([InlineKeyboardButton(text=render("none_of_these", lang), callback_data="dest:none")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_keyboard(user: User) -> InlineKeyboardMarkup:
    lang = user.language
    state = render("on" if user.voice_on else "off", lang)
    level = render(f"level_{user.alert_level}", lang)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{name}{' ✓' if code == lang else ''}", callback_data=f"set:lang:{code}") for code, name in LANGUAGES.items()],
            [InlineKeyboardButton(text=render("btn_voice", lang, state=state), callback_data="set:voice")],
            [InlineKeyboardButton(text=render("btn_level", lang, level=level), callback_data="set:level")],
        ]
    )


def pins_keyboard(places: list) -> InlineKeyboardMarkup | None:
    if not places:
        return None
    buttons = [
        InlineKeyboardButton(text=f"📍 {i}", callback_data=f"pin:{i - 1}") for i, _ in enumerate(places, 1)
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons])
