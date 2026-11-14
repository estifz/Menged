"""Telegram channel: sends engine messages as text (+ voice note) and keeps the
pinned live trip card up to date."""

import logging
import re

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from app.adapters.base import OutMessage
from app.models import Trip, User
from app.services import tts

log = logging.getLogger(__name__)

_EMOJI = re.compile("[\U0001f000-\U0001ffff☀-➿⬀-⯿️‍]")
_TAGS = re.compile(r"<[^>]+>")


def speakable(text: str) -> str:
    """Text for the voice note: no emoji, no HTML, no arrows."""
    text = _TAGS.sub("", text)
    text = _EMOJI.sub("", text).replace("→", ",")
    return re.sub(r"\s+", " ", text).strip()


def actions_keyboard(msg: OutMessage) -> InlineKeyboardMarkup | None:
    if not msg.actions:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=a.label, callback_data=a.id)] for a in msg.actions]
    )


class TelegramChannel:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def send(self, user: User, msg: OutMessage) -> bool:
        if not user.telegram_chat_id:
            return False
        chat = user.telegram_chat_id
        # Engine notifications contain no markup, so send them as plain text
        # (place names with "&" or "<" must not break HTML parsing).
        await self.bot.send_message(
            chat, msg.text, parse_mode=None, disable_notification=msg.silent, reply_markup=actions_keyboard(msg)
        )
        if msg.location:
            await self.bot.send_location(chat, *msg.location, disable_notification=True)
        if user.voice_on and msg.voice:
            return await self.send_voice(user, msg.text, silent=msg.silent)
        return False

    async def send_voice(self, user: User, text: str, silent: bool = False) -> bool:
        path = await tts.synthesize(speakable(text), user.language)
        if path is None or not user.telegram_chat_id:
            return False
        try:
            await self.bot.send_voice(user.telegram_chat_id, FSInputFile(path), disable_notification=silent)
            return True
        except Exception as e:
            log.warning("voice send failed: %s", e)
            return False

    async def update_card(self, user: User, trip: Trip, text: str) -> int | None:
        chat = user.telegram_chat_id
        if not chat:
            return None
        if trip.card_message_id:
            try:
                await self.bot.edit_message_text(text=text, chat_id=chat, message_id=trip.card_message_id, parse_mode=None)
                return trip.card_message_id
            except TelegramBadRequest as e:
                if "not modified" in str(e):
                    return trip.card_message_id
                log.info("card edit failed (%s); sending a new card", e)
        msg = await self.bot.send_message(chat, text, parse_mode=None, disable_notification=True)
        try:
            await self.bot.pin_chat_message(chat, msg.message_id, disable_notification=True)
        except TelegramBadRequest as e:
            log.info("pin failed: %s", e)
        return msg.message_id

    async def close_card(self, user: User, trip: Trip, text: str) -> None:
        chat = user.telegram_chat_id
        if not chat or not trip.card_message_id:
            return
        try:
            await self.bot.edit_message_text(text=text, chat_id=chat, message_id=trip.card_message_id, parse_mode=None)
        except TelegramBadRequest:
            pass
        try:
            await self.bot.unpin_chat_message(chat, message_id=trip.card_message_id)
        except TelegramBadRequest:
            pass
