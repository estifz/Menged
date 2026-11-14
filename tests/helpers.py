"""Shared helpers for engine tests."""

from datetime import timedelta

from sqlalchemy import select

from app.db import session_scope
from app.engine import trips as engine
from app.models import Notification, Trip, User
from app.services.http import PlaceCandidate
from tests.conftest import DEST, START, T0, lat_at


async def make_user(level: str = "normal", channel: str = "telegram") -> int:
    async with session_scope() as s:
        u = User(channel=channel, telegram_chat_id=1, language="en", voice_on=False, alert_level=level)
        s.add(u)
        await s.flush()
        return u.id


async def start_trip(user_id: int) -> int:
    async with session_scope() as s:
        user = await s.get(User, user_id)
        trip = await engine.create_trip(s, user, PlaceCandidate("Bole Medhanialem", *DEST), now=T0)
        return trip.id


async def point(trip_id: int, along_m: float, t_s: float, accuracy: float = 10.0, lat=None, lon=None):
    async with session_scope() as s:
        trip = await s.get(Trip, trip_id)
        now = T0 + timedelta(seconds=t_s)
        return await engine.add_location(
            s,
            trip,
            lat if lat is not None else lat_at(along_m),
            lon if lon is not None else START[1],
            accuracy,
            recorded_at=now,
            now=now,
        )


async def drive(trip_id: int, n: int = 41, step_m: float = 150, step_s: float = 30, extra_at_dest: int = 1):
    for i in range(n):
        await point(trip_id, step_m * i, step_s * i)
    for j in range(extra_at_dest):
        await point(trip_id, step_m * (n - 1), step_s * (n + j))


async def sent_types(trip_id: int) -> list[str]:
    async with session_scope() as s:
        rows = await s.scalars(
            select(Notification.rule).where(Notification.trip_id == trip_id).order_by(Notification.id)
        )
        return list(rows)


async def notifications(trip_id: int) -> list[Notification]:
    async with session_scope() as s:
        rows = await s.scalars(select(Notification).where(Notification.trip_id == trip_id).order_by(Notification.id))
        return list(rows)


async def get_trip(trip_id: int) -> Trip:
    async with session_scope() as s:
        return await s.get(Trip, trip_id)
