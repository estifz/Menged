"""Test setup: a fresh SQLite database per test, a recording channel instead of
Telegram, and fake map services (no network)."""

import os
from datetime import UTC, datetime
from types import SimpleNamespace

os.environ.update(
    {"ENABLE_BOT": "true", "TELEGRAM_BOT_TOKEN": "", "ENABLE_SCHEDULER": "false", "TTS_ENABLED": "false", "ADMIN_TELEGRAM_IDS": ""}
)

import pytest
import pytest_asyncio

from app.config import get_settings

get_settings.cache_clear()

from app import db as dbmod  # noqa: E402
from app.adapters import base as channels  # noqa: E402
from app.adapters.base import NullChannel  # noqa: E402
from app.geo import encode  # noqa: E402
from app.models import Base  # noqa: E402
from app.services import nominatim, overpass, routing  # noqa: E402
from app.services.http import ServiceError  # noqa: E402

T0 = datetime(2026, 11, 14, 8, 0, tzinfo=UTC)
START = (10.000, 38.760)  # outside Addis, so the offline place list adds nothing
DEST = (10.054, 38.760)  # ~6 km due north


def lat_at(meters: float) -> float:
    return START[0] + meters / 111_000


@pytest_asyncio.fixture
async def db(tmp_path):
    engine = dbmod.make_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    dbmod.init_engine(engine)
    yield engine
    await engine.dispose()


@pytest.fixture
def channel():
    ch = NullChannel()
    channels.register("telegram", ch)
    channels.register("app", ch)
    return ch


@pytest.fixture
def fake_services(monkeypatch):
    """Replace Nominatim, routing and Overpass with in-memory fakes."""
    state = SimpleNamespace(
        streets=[],  # (lat_min, lat_max, name)
        route={"distance_m": 6000.0, "duration_s": 1200.0, "fail": False},
        places=[],
        reverse_calls=0,
    )

    async def reverse(lat, lon, lang="en"):
        state.reverse_calls += 1
        for lo, hi, name in state.streets:
            if lo <= lat < hi:
                return name
        return None

    async def get_route(start, dest):
        if state.route["fail"]:
            raise ServiceError("routing down")
        return routing.RouteResult(encode([start, dest]), state.route["distance_m"], state.route["duration_s"], "fake")

    async def places_along(points, radius_m):
        return list(state.places)

    async def food_near(lat, lon, radius_m=500):
        return [p for p in state.places if p.kind in overpass.FOOD]

    monkeypatch.setattr(nominatim, "reverse", reverse)
    monkeypatch.setattr(routing, "get_route", get_route)
    monkeypatch.setattr(overpass, "places_along", places_along)
    monkeypatch.setattr(overpass, "food_near", food_near)
    return state


@pytest.fixture
def scenario(fake_services):
    """Two streets, one landmark 2.1 km in, no food."""
    fake_services.streets[:] = [(0.0, lat_at(3000), "Churchill Avenue"), (lat_at(3000), 99.0, "Bole Road")]
    fake_services.places[:] = [
        overpass.OsmPlace("n1", "Lion of Judah", "የይሁዳ አንበሳ", None, "landmark", lat_at(2100), START[1] + 0.0003)
    ]
    return fake_services
