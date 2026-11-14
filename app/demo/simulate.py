"""/simulate: replay the saved demo trip through the real trip engine.

The trip runs on a virtual clock that moves `speedup` times faster than real
time, so a 15-minute ride plays in about 90 seconds while every rule (45 s
gaps, 15/10-minute marks, "still here"...) behaves exactly as on a real ride.
No GPS and no internet needed: the route, places and street names come from
`demo_trip.json`.
"""

import asyncio
import logging
import random
from datetime import timedelta

from app.db import session_scope
from app.demo.data import load_demo
from app.engine import trips as engine
from app.geo import Route
from app.models import Status, Trip, User, utcnow
from app.services.http import PlaceCandidate

log = logging.getLogger(__name__)

_tasks: dict[int, asyncio.Task] = {}

STEP_S = 5.0  # virtual seconds between points
SPEED_MPS = 7.0  # minibus pace


def cancel(user_id: int) -> None:
    task = _tasks.pop(user_id, None)
    if task and not task.done():
        task.cancel()


def start(user_id: int, speedup: float = 10.0) -> str | None:
    """Start a replay in the background. Returns the destination name."""
    demo = load_demo()
    if demo is None:
        return None
    cancel(user_id)
    _tasks[user_id] = asyncio.create_task(run(user_id, max(1.0, min(speedup, 60.0))))
    return demo.dest["name"]


async def run(user_id: int, speedup: float, jitter_m: float = 6.0, sleep: bool = True) -> int | None:
    demo = load_demo()
    if demo is None:
        return None
    route = Route.from_polyline(demo.route["line"])
    t0 = utcnow()

    async with session_scope() as session:
        user = await session.get(User, user_id)
        if user is None:
            return None
        dest = PlaceCandidate(demo.dest["name"], demo.dest["lat"], demo.dest["lon"], source="demo")
        trip = await engine.create_trip(session, user, dest, now=t0, simulated=True)
        trip_id = trip.id

    elapsed = 0.0
    along = 0.0
    rng = random.Random(42)
    extra = 0
    try:
        while True:
            done = along >= route.length_m
            if done:
                extra += 1
                if extra > 5:  # safety: arrival should have triggered already
                    break
            lat, lon = route.point_at(along) if not done else (demo.dest["lat"], demo.dest["lon"])
            if not done:  # a little GPS noise
                lat += rng.gauss(0, jitter_m) / 111_000
                lon += rng.gauss(0, jitter_m) / 111_000
            virtual_now = t0 + timedelta(seconds=elapsed)
            async with session_scope() as session:
                trip = await session.get(Trip, trip_id)
                if trip is None or trip.status not in Status.OPEN:
                    break
                async with engine.trip_lock(trip_id):
                    await engine.add_location(session, trip, lat, lon, 8.0, recorded_at=virtual_now, now=virtual_now)
            elapsed += STEP_S
            along += SPEED_MPS * STEP_S
            if sleep:
                await asyncio.sleep(STEP_S / speedup)
    except asyncio.CancelledError:
        log.info("simulation for user %s cancelled", user_id)
        raise
    except Exception:
        log.exception("simulation failed for user %s", user_id)
    finally:
        _tasks.pop(user_id, None)
    return trip_id
