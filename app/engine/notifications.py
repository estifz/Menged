"""Notification engine: decides *when* to speak.

Runs on every location point and on the 30-second timer. Each rule may
propose a message; then alert levels and anti-overload limits decide what is
actually sent:

- At least `min_gap_s` (45 s) between two messages, at most `window_max` (4)
  in any `window_s` (5 min). High-priority messages skip both limits.
- quiet = high only, normal = high + normal, chatty = everything.
- One-shot messages (time marks, landmarks, streets, arrival...) carry a
  `key` and are never sent twice in a trip.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import base as channels
from app.adapters.base import Action, OutMessage
from app.config import get_settings
from app.engine.templates import fmt_minutes, render
from app.geo import haversine
from app.models import Notification, Priority, Status, Trip, TripPlace, User
from app.text.amharic import normalize

log = logging.getLogger(__name__)

LEVELS = {
    "quiet": {Priority.HIGH},
    "normal": {Priority.HIGH, Priority.NORMAL},
    "chatty": {Priority.HIGH, Priority.NORMAL, Priority.LOW},
}


@dataclass
class Ctx:
    """What the trip engine knows at this moment."""

    now: datetime
    lat: float | None = None
    lon: float | None = None
    along_m: float | None = None
    distance_left: float | None = None
    time_left_s: float | None = None
    street: str | None = None
    street_changed: bool = False
    became: str | None = None  # status the trip just changed to
    moving: bool = False
    places: list[TripPlace] = field(default_factory=list)


def make(type_: str, user: User, priority: str = Priority.NORMAL, key: str | None = None, **params) -> OutMessage:
    return OutMessage(
        type=type_,
        text=render(type_, user.language, **params),
        params=params,
        priority=priority,
        key=key,
    )


async def deliver(session: AsyncSession, user: User, trip: Trip | None, msg: OutMessage, now: datetime) -> None:
    """Log the message (for limits and the app's message feed) and send it."""
    row = Notification(
        trip_id=trip.id if trip else None,
        user_id=user.id,
        rule=msg.type,
        key=msg.key,
        priority=msg.priority,
        text=msg.text,
        params={"type": msg.type, **msg.params, "actions": [a.__dict__ for a in msg.actions]},
        sent_at=now,
    )
    session.add(row)
    await session.flush()
    try:
        row.voice_sent = await channels.get(user.channel).send(user, msg)
    except Exception:  # a failed send must not break tracking
        log.exception("send failed for user %s", user.id)


def _rule_arrived(trip: Trip, user: User, ctx: Ctx, sent: set[str]) -> OutMessage | None:
    if ctx.became == Status.ARRIVED and "arrived" not in sent:
        return make("arrived", user, Priority.HIGH, key="arrived", dest=trip.dest_name)
    return None


def _rule_next(trip: Trip, user: User, ctx: Ctx, sent: set[str]) -> OutMessage | None:
    s = get_settings()
    if trip.status != Status.APPROACHING or "next" in sent or ctx.became == Status.ARRIVED:
        return None
    time_close = (
        ctx.distance_left is not None
        and ctx.distance_left <= s.next_m * 1.2
        and ctx.time_left_s is not None
        and ctx.time_left_s <= s.next_s
    )
    close = (ctx.distance_left is not None and ctx.distance_left <= s.next_m) or time_close
    return make("next", user, Priority.HIGH, key="next") if close else None


def _rule_getting_close(trip: Trip, user: User, ctx: Ctx, sent: set[str]) -> OutMessage | None:
    if ctx.became == Status.APPROACHING and "getting_close" not in sent:
        return make("getting_close", user, Priority.HIGH, key="getting_close")
    return None


def _rule_time_left(trip: Trip, user: User, ctx: Ctx, sent: set[str]) -> OutMessage | None:
    s = get_settings()
    if trip.status != Status.ACTIVE or ctx.time_left_s is None:
        return None
    # Marks at or below the "getting close" time would duplicate that alert.
    marks = [m for m in s.time_left_marks if m * 60 > s.approaching_s]
    crossed = [m for m in marks if ctx.time_left_s <= m * 60]
    if not crossed:
        return None
    m = min(crossed)
    # Don't announce a mark the trip started below, or a larger mark after a smaller one.
    if trip.duration_s is not None and trip.duration_s < m * 60 + 60:
        return None
    if any(f"time_left_{x}" in sent for x in marks if x <= m):
        return None
    return make("time_left", user, Priority.NORMAL, key=f"time_left_{m}", minutes=m)


def _rule_new_place(trip: Trip, user: User, ctx: Ctx, sent: set[str]) -> OutMessage | None:
    s = get_settings()
    if ctx.lat is None or trip.status not in (Status.ACTIVE, Status.APPROACHING):
        return None
    best: tuple[float, TripPlace] | None = None
    for p in ctx.places:
        if p.is_food or p.announced_at is not None or f"place:{p.osm_id}" in sent:
            continue
        d = haversine(ctx.lat, ctx.lon, p.lat, p.lon)
        if d <= s.landmark_radius_m and (best is None or d < best[0]):
            best = (d, p)
    if best is None:
        return None
    place = best[1]
    msg = make("new_place", user, Priority.NORMAL, key=f"place:{place.osm_id}", place=place.display_name(user.language))
    msg.params["place_id"] = place.id
    return msg


def _rule_new_street(trip: Trip, user: User, ctx: Ctx, sent: set[str]) -> OutMessage | None:
    """Announce a street once per trip. Not tied to the exact point where it
    changed, so a street isn't lost when another message took that slot."""
    if not ctx.street or trip.status != Status.ACTIVE:
        return None
    if trip.first_street and normalize(ctx.street) == normalize(trip.first_street):
        return None
    key = f"street:{normalize(ctx.street)}"[:128]
    if key in sent:
        return None
    return make("new_street", user, Priority.NORMAL, key=key, street=ctx.street)


def _food_ahead(ctx: Ctx) -> list[TripPlace]:
    s = get_settings()
    if ctx.lat is None:
        return []
    out = []
    for p in ctx.places:
        if not p.is_food:
            continue
        if ctx.along_m is not None and p.along_route_m is not None and p.along_route_m < ctx.along_m - 50:
            continue  # already behind us
        if haversine(ctx.lat, ctx.lon, p.lat, p.lon) <= s.food_radius_m:
            out.append(p)
    return out


def _rule_food_offer(trip: Trip, user: User, ctx: Ctx, sent: set[str]) -> OutMessage | None:
    s = get_settings()
    if trip.food_offers_off or trip.status != Status.ACTIVE or ctx.time_left_s is None:
        return None
    if ctx.time_left_s <= s.approaching_s or (trip.duration_s or 0) < s.food_min_trip_s:
        return None
    if trip.last_food_offer_at and (ctx.now - trip.last_food_offer_at).total_seconds() < s.food_offer_every_s:
        return None
    if trip.started_at and (ctx.now - trip.started_at).total_seconds() < 120:
        return None  # let the trip settle first
    food = _food_ahead(ctx)
    if len(food) < s.food_min_places:
        return None
    msg = make("food_offer", user, Priority.NORMAL, count=len(food))
    msg.silent = True
    msg.voice = False
    msg.actions = [
        Action(f"food:show:{trip.id}", render("btn_show", user.language)),
        Action(f"food:later:{trip.id}", render("btn_later", user.language)),
        Action(f"food:off:{trip.id}", render("btn_no_more", user.language)),
    ]
    return msg


def _rule_still_here(trip: Trip, user: User, ctx: Ctx, sent: set[str], last_sent: datetime | None) -> OutMessage | None:
    s = get_settings()
    if trip.status != Status.ACTIVE or not ctx.moving:
        return None
    since = (ctx.now - (last_sent or trip.started_at or ctx.now)).total_seconds()
    if since < s.still_here_after_s:
        return None
    minutes = fmt_minutes(ctx.time_left_s)
    if ctx.street:
        msg = make("still_here", user, Priority.LOW, street=ctx.street, minutes=minutes)
    else:
        msg = make("still_here_nostreet", user, Priority.LOW, minutes=minutes)
    msg.silent = True
    return msg


async def _sent_keys(session: AsyncSession, trip: Trip) -> set[str]:
    rows = await session.scalars(
        select(Notification.key).where(Notification.trip_id == trip.id, Notification.key.is_not(None))
    )
    return set(rows)


async def _recent_times(session: AsyncSession, trip: Trip, now: datetime) -> list[datetime]:
    s = get_settings()
    rows = await session.scalars(
        select(Notification.sent_at)
        .where(Notification.trip_id == trip.id, Notification.sent_at >= now - timedelta(seconds=s.window_s))
        .order_by(Notification.sent_at.desc())
    )
    return list(rows)


async def _last_sent(session: AsyncSession, trip: Trip) -> datetime | None:
    return await session.scalar(
        select(Notification.sent_at).where(Notification.trip_id == trip.id).order_by(Notification.sent_at.desc()).limit(1)
    )


def within_limits(recent: list[datetime], now: datetime) -> bool:
    s = get_settings()
    if recent and (now - max(recent)).total_seconds() < s.min_gap_s:
        return False
    return len(recent) < s.window_max


async def evaluate(session: AsyncSession, user: User, trip: Trip, ctx: Ctx) -> list[OutMessage]:
    """Run all rules and send what passes. Returns the messages sent."""
    sent = await _sent_keys(session, trip)
    allowed = LEVELS.get(user.alert_level, LEVELS["normal"])
    out: list[OutMessage] = []

    # High priority: always sent, never limited.
    nxt = _rule_next(trip, user, ctx, sent)
    high = [_rule_arrived(trip, user, ctx, sent), nxt]
    if nxt is None:  # "next" already says it; don't stack "getting close" on top
        high.append(_rule_getting_close(trip, user, ctx, sent))
    for msg in filter(None, high):
        await deliver(session, user, trip, msg, ctx.now)
        out.append(msg)
    if ctx.became == Status.ARRIVED:
        return out

    # Everything else: at most one per evaluation, subject to level and limits.
    recent = await _recent_times(session, trip, ctx.now)
    if not within_limits(recent, ctx.now):
        return out
    last = recent[0] if recent else await _last_sent(session, trip)
    candidates = [
        _rule_time_left(trip, user, ctx, sent),
        _rule_new_place(trip, user, ctx, sent),
        _rule_new_street(trip, user, ctx, sent),
        _rule_food_offer(trip, user, ctx, sent),
        _rule_still_here(trip, user, ctx, sent, last),
    ]
    for msg in candidates:
        if msg is None or msg.priority not in allowed:
            continue
        await deliver(session, user, trip, msg, ctx.now)
        if msg.type == "new_place":
            for p in ctx.places:
                if p.id == msg.params.get("place_id"):
                    p.announced_at = ctx.now
        elif msg.type == "food_offer":
            trip.last_food_offer_at = ctx.now
        out.append(msg)
        break
    return out
