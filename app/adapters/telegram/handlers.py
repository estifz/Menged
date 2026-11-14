"""Telegram bot handlers: the conversation, live location and buttons.

Handlers only translate Telegram updates into trip-engine calls and send the
replies; every rule lives in the engine so the app behaves the same.
"""

import html
import logging
import time
from datetime import UTC, datetime

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.adapters import base as channels
from app.adapters.telegram.keyboards import (
    destination_keyboard,
    language_keyboard,
    main_keyboard,
    pins_keyboard,
    settings_keyboard,
)
from app.config import get_settings
from app.db import session_scope
from app.demo import simulate
from app.engine import trips as engine
from app.engine.templates import LANGUAGES, all_variants, render
from app.models import Status, Trip, User
from app.services.http import PlaceCandidate, ServiceError

log = logging.getLogger(__name__)
router = Router(name="menged")

LIVE_POS_MAX_AGE_S = 120
STATIC_POS_MAX_AGE_S = 600
LEVEL_CYCLE = ["normal", "chatty", "quiet"]


# --- Helpers -----------------------------------------------------------------------
async def load_user(session, message_or_cb) -> User:
    chat = message_or_cb.message.chat if isinstance(message_or_cb, CallbackQuery) else message_or_cb.chat
    lang = message_or_cb.from_user.language_code if message_or_cb.from_user else None
    user, _ = await engine.get_or_create_telegram_user(session, chat.id, lang)
    return user


async def voice_reply(user: User, text: str) -> None:
    """Replies to button taps are voiced too when voice is on."""
    ch = channels.get("telegram")
    if user.voice_on and hasattr(ch, "send_voice"):
        await ch.send_voice(user, text)


def recorded_at(message: Message) -> datetime:
    ts = message.edit_date or message.date
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    return datetime.fromtimestamp(ts, UTC)


async def current_position(state: FSMContext, trip: Trip | None) -> tuple[float, float] | None:
    if trip and trip.status in Status.TRACKING and trip.last_lat is not None:
        return trip.last_lat, trip.last_lon
    data = await state.get_data()
    for key, max_age in (("live_pos", LIVE_POS_MAX_AGE_S), ("static_pos", STATIC_POS_MAX_AGE_S)):
        pos = data.get(key)
        if pos and time.time() - pos[2] <= max_age:
            return pos[0], pos[1]
    return None


# --- /start, /help, language --------------------------------------------------------
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    async with session_scope() as session:
        user = await load_user(session, message)
    await message.answer(render("welcome", user.language), reply_markup=language_keyboard())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    async with session_scope() as session:
        user = await load_user(session, message)
    await message.answer(render("help", user.language), reply_markup=main_keyboard(user.language))


@router.callback_query(F.data.startswith("lang:"))
async def cb_language(cb: CallbackQuery) -> None:
    code = cb.data.split(":", 1)[1]
    async with session_scope() as session:
        user = await load_user(session, cb)
        if code in LANGUAGES:
            user.language = code
    await cb.answer()
    if cb.message:
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.message.answer(render("ready", user.language), reply_markup=main_keyboard(user.language))


# --- /settings ------------------------------------------------------------------------
def settings_text(user: User) -> str:
    lang = user.language
    return render(
        "settings_title",
        lang,
        language=LANGUAGES[lang],
        voice=render("on" if user.voice_on else "off", lang),
        level=render(f"level_{user.alert_level}", lang),
    )


@router.message(Command("settings"))
async def cmd_settings(message: Message) -> None:
    async with session_scope() as session:
        user = await load_user(session, message)
    await message.answer(settings_text(user), reply_markup=settings_keyboard(user))


@router.callback_query(F.data.startswith("set:"))
async def cb_settings(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    lang_changed = False
    async with session_scope() as session:
        user = await load_user(session, cb)
        if parts[1] == "lang" and len(parts) > 2 and parts[2] in LANGUAGES:
            lang_changed = user.language != parts[2]
            user.language = parts[2]
        elif parts[1] == "voice":
            user.voice_on = not user.voice_on
        elif parts[1] == "level":
            i = LEVEL_CYCLE.index(user.alert_level) if user.alert_level in LEVEL_CYCLE else 0
            user.alert_level = LEVEL_CYCLE[(i + 1) % len(LEVEL_CYCLE)]
    await cb.answer()
    if cb.message:
        await cb.message.edit_text(settings_text(user), reply_markup=settings_keyboard(user))
        if lang_changed:
            await cb.message.answer(render("ask_destination", user.language), reply_markup=main_keyboard(user.language))


# --- Trip: destination ----------------------------------------------------------------
@router.message(Command("trip"))
async def cmd_trip(message: Message) -> None:
    async with session_scope() as session:
        user = await load_user(session, message)
        trip = await engine.open_trip(session, user.id)
    if trip and trip.status != Status.CREATED:
        await message.answer(render("already_on_trip", user.language, dest=html.escape(trip.dest_name)))
        return
    await message.answer(render("ask_destination", user.language), reply_markup=main_keyboard(user.language))


async def search_and_offer(message: Message, state: FSMContext, user: User, query: str) -> None:
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        candidates = await engine.search_destination(query, user.language)
    except ServiceError:
        await message.answer(render("search_failed", user.language))
        return
    if not candidates:
        await message.answer(render("not_found", user.language, query=html.escape(query)))
        return
    await state.update_data(candidates=[c.to_dict() for c in candidates])
    await message.answer(
        render("pick_destination", user.language), reply_markup=destination_keyboard(candidates, user.language)
    )


@router.callback_query(F.data.startswith("dest:"))
async def cb_destination(cb: CallbackQuery, state: FSMContext) -> None:
    choice = cb.data.split(":", 1)[1]
    data = await state.get_data()
    await cb.answer()
    if cb.message:
        await cb.message.edit_reply_markup(reply_markup=None)
    async with session_scope() as session:
        user = await load_user(session, cb)
        if choice == "none" or not data.get("candidates"):
            await cb.message.answer(render("ask_destination", user.language))
            return
        dest = PlaceCandidate.from_dict(data["candidates"][int(choice)])
        live = data.get("live_pos")
        start = (live[0], live[1]) if live and time.time() - live[2] <= LIVE_POS_MAX_AGE_S else None
        if start is None:
            await cb.message.answer(
                render("dest_set_share", user.language, dest=html.escape(dest.name)),
                reply_markup=main_keyboard(user.language),
            )
        else:
            await cb.message.bot.send_chat_action(cb.message.chat.id, ChatAction.TYPING)
        trip = await engine.create_trip(session, user, dest, start=start)
        if start is not None:
            async with engine.trip_lock(trip.id):
                await engine.add_location(session, trip, start[0], start[1])
    await state.update_data(candidates=None)


# --- Location ---------------------------------------------------------------------------
async def handle_point(message: Message, state: FSMContext, live: bool) -> None:
    loc = message.location
    async with session_scope() as session:
        user = await load_user(session, message)
        trip = await engine.open_trip(session, user.id)
        if live:
            await state.update_data(live_pos=[loc.latitude, loc.longitude, time.time()])
            if trip is None:
                if message.edit_date is None:  # first message of a new live share
                    await message.answer(render("need_destination_first", user.language))
                return
            async with engine.trip_lock(trip.id):
                await session.refresh(trip)
                await engine.add_location(
                    session, trip, loc.latitude, loc.longitude, loc.horizontal_accuracy, recorded_at=recorded_at(message)
                )
            return

        # One-time location (e.g. the "Send my location" button).
        await state.update_data(static_pos=[loc.latitude, loc.longitude, time.time()])
        if trip and trip.status == Status.CREATED:
            await message.answer(render("need_live", user.language))
            return
        text = await engine.where_am_i(session, user, loc.latitude, loc.longitude, trip)
        await message.answer(text, parse_mode=None)
        if trip is None:
            places = await engine.nearby_food(session, user, loc.latitude, loc.longitude)
            await state.update_data(nearby=[[p.name, p.lat, p.lon] for p in places])
            await message.answer(engine.food_list_text(user, places), parse_mode=None, reply_markup=pins_keyboard(places))
    await voice_reply(user, text)


@router.message(F.location)
async def on_location(message: Message, state: FSMContext) -> None:
    await handle_point(message, state, live=message.location.live_period is not None)


@router.edited_message(F.location)
async def on_live_update(message: Message, state: FSMContext) -> None:
    await handle_point(message, state, live=True)


# --- Buttons ------------------------------------------------------------------------------
@router.message(F.text.in_(all_variants("btn_where")))
async def btn_where(message: Message, state: FSMContext) -> None:
    async with session_scope() as session:
        user = await load_user(session, message)
        trip = await engine.open_trip(session, user.id)
        pos = await current_position(state, trip)
        if pos is None:
            await message.answer(render("no_position", user.language), reply_markup=main_keyboard(user.language))
            return
        text = await engine.where_am_i(session, user, pos[0], pos[1], trip)
    await message.answer(text, parse_mode=None)
    await voice_reply(user, text)


@router.message(F.text.in_(all_variants("btn_time")))
async def btn_time(message: Message) -> None:
    async with session_scope() as session:
        user = await load_user(session, message)
        trip = await engine.open_trip(session, user.id)
    if trip is None:
        await message.answer(render("no_trip", user.language))
        return
    if trip.status not in Status.TRACKING:
        await message.answer(engine.card_text(user, trip), parse_mode=None)
        return
    text = engine.time_left_text(user, trip)
    await message.answer(text, parse_mode=None)
    await voice_reply(user, text)


async def send_food_list(message: Message, state: FSMContext, user: User, trip: Trip | None, session) -> None:
    pos = await current_position(state, trip)
    if pos is None:
        await message.answer(render("no_position", user.language), reply_markup=main_keyboard(user.language))
        return
    places = await engine.nearby_food(session, user, pos[0], pos[1], trip)
    await state.update_data(nearby=[[p.name, p.lat, p.lon] for p in places])
    await message.answer(engine.food_list_text(user, places), parse_mode=None, reply_markup=pins_keyboard(places))


@router.message(F.text.in_(all_variants("btn_nearby")))
async def btn_nearby(message: Message, state: FSMContext) -> None:
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    async with session_scope() as session:
        user = await load_user(session, message)
        trip = await engine.open_trip(session, user.id)
        await send_food_list(message, state, user, trip, session)


@router.message(F.text.in_(all_variants("btn_stop")))
async def btn_stop(message: Message) -> None:
    async with session_scope() as session:
        user = await load_user(session, message)
        trip = await engine.open_trip(session, user.id)
        if trip is None:
            await message.answer(render("no_trip", user.language))
            return
        simulate.cancel(user.id)
        async with engine.trip_lock(trip.id):
            await engine.end_trip(session, trip, "user")


@router.callback_query(F.data.startswith("pin:"))
async def cb_pin(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    data = await state.get_data()
    nearby = data.get("nearby") or []
    i = int(cb.data.split(":", 1)[1])
    if cb.message and 0 <= i < len(nearby):
        name, lat, lon = nearby[i]
        await cb.message.answer_venue(latitude=lat, longitude=lon, title=name, address="")


@router.callback_query(F.data.startswith("food:"))
async def cb_food(cb: CallbackQuery, state: FSMContext) -> None:
    _, action, trip_id = cb.data.split(":")
    await cb.answer()
    if cb.message:
        await cb.message.edit_reply_markup(reply_markup=None)
    async with session_scope() as session:
        user = await load_user(session, cb)
        trip = await session.get(Trip, int(trip_id))
        if trip is None or trip.user_id != user.id:
            return
        if action == "show":
            await send_food_list(cb.message, state, user, trip, session)
        elif action == "later":
            trip.last_food_offer_at = datetime.now(UTC)
            await cb.message.answer(render("offer_later", user.language))
        elif action == "off":
            trip.food_offers_off = True
            await cb.message.answer(render("offer_off", user.language))


# --- /simulate (demo) -------------------------------------------------------------------
@router.message(Command("simulate"))
async def cmd_simulate(message: Message) -> None:
    admins = get_settings().admin_ids
    async with session_scope() as session:
        user = await load_user(session, message)
    if admins and message.from_user and message.from_user.id not in admins:
        await message.answer(render("simulate_denied", user.language))
        return
    parts = (message.text or "").split()
    speed = float(parts[1]) if len(parts) > 1 and parts[1].replace(".", "", 1).isdigit() else 10.0
    dest = simulate.start(user.id, speedup=speed)
    if dest is None:
        await message.answer(render("simulate_missing", user.language))
        return
    await message.answer(render("simulate_start", user.language, dest=html.escape(dest)), reply_markup=main_keyboard(user.language))


# --- Free text = destination ------------------------------------------------------------
@router.message(F.text & ~F.text.startswith("/"))
async def on_text(message: Message, state: FSMContext) -> None:
    query = message.text.strip()
    async with session_scope() as session:
        user = await load_user(session, message)
        trip = await engine.open_trip(session, user.id)
    if trip and trip.status != Status.CREATED:
        await message.answer(render("already_on_trip", user.language, dest=html.escape(trip.dest_name)))
        return
    await search_and_offer(message, state, user, query)


async def setup_commands(bot: Bot) -> None:
    from aiogram.types import BotCommand

    for lang in LANGUAGES:
        commands = [
            BotCommand(command="trip", description=render("cmd_trip", lang)),
            BotCommand(command="settings", description=render("cmd_settings", lang)),
            BotCommand(command="help", description=render("cmd_help", lang)),
            BotCommand(command="start", description=render("cmd_start", lang)),
        ]
        await bot.set_my_commands(commands, language_code=None if lang == "en" else lang)
