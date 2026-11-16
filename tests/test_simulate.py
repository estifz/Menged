"""The /simulate replay: the recorded demo trip runs through the real engine
with no network and ends with an arrival, within the anti-overload limits."""

from app.demo import simulate
from app.demo.data import load_demo
from app.geo import haversine
from app.models import Priority, Status
from app.services import nominatim
from tests.helpers import get_trip, make_user, notifications


async def test_demo_replay_arrives(db, channel, monkeypatch):
    demo = load_demo()
    assert demo is not None, "run scripts/record_demo.py first"

    async def reverse(lat, lon, lang="en"):  
        best = None
        for s in demo.streets:
            d = haversine(lat, lon, s["lat"], s["lon"])
            if d < 200 and (best is None or d < best[0]):
                best = (d, s.get(f"name_{lang}") or s.get("name_en"))
        return best[1] if best else None

    monkeypatch.setattr(nominatim, "reverse", reverse)

    tid = await simulate.run(await make_user(), speedup=1, sleep=False)
    trip = await get_trip(tid)
    assert trip.status == Status.ARRIVED and trip.route_provider == "demo" and trip.simulated

    rows = await notifications(tid)
    types = [n.rule for n in rows]
    assert types[:2] == ["trip_routed", "tracking_started"]
    assert types[-1] == "arrived"
    assert "getting_close" in types and "next" in types
    assert any(t in ("new_place", "new_street", "time_left_10") for t in types)

    # Anti-overload: a normal/low message never comes within 45 s of the previous one,
    # and no 5-minute window holds more than 4 non-high messages.
    for prev, cur in zip(rows, rows[1:]):
        if cur.priority != Priority.HIGH:
            assert (cur.sent_at - prev.sent_at).total_seconds() >= 45, (prev.rule, cur.rule)
    normal = [n.sent_at for n in rows if n.priority != Priority.HIGH]
    for t in normal:
        assert sum(1 for u in normal if 0 <= (t - u).total_seconds() < 300) <= 4


async def test_simulated_trip_ignores_live_location(db, channel, monkeypatch):
    from unittest.mock import AsyncMock, MagicMock
    from app.adapters.telegram.handlers import handle_point
    from app.db import session_scope
    from app.engine import trips as engine
    from app.models import User
    from tests.conftest import DEST, T0
    from app.services.http import PlaceCandidate

    user_id = await make_user()
    async with session_scope() as s:
        user = await s.get(User, user_id)
        trip = await engine.create_trip(s, user, PlaceCandidate("Bole Medhanialem", *DEST), now=T0, simulated=True)
        tid = trip.id
        await engine.add_location(s, trip, DEST[0] + 0.01, DEST[1] + 0.01, 10.0, recorded_at=T0, now=T0)

    trip = await get_trip(tid)
    assert trip.simulated
    saved_lat = trip.last_lat

    msg = MagicMock()
    msg.from_user.id = 1
    msg.from_user.language_code = "en"
    msg.chat.id = 1
    msg.location.latitude = 8.12345
    msg.location.longitude = 39.12345
    msg.location.horizontal_accuracy = 5.0
    msg.edit_date = None
    msg.date = 1000000000
    msg.answer = AsyncMock()

    state = AsyncMock()
    await handle_point(msg, state, live=True)

    trip_after = await get_trip(tid)
    assert trip_after.last_lat == saved_lat
    assert trip_after.last_lat != 8.12345

