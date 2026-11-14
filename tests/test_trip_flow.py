"""End-to-end engine tests: a simulated ride through every state and rule."""

from datetime import timedelta

from sqlalchemy import func, select

from app.db import session_scope
from app.engine import trips as engine
from app.engine.notifications import within_limits
from app.models import LocationPoint, Priority, Status
from app.services.overpass import OsmPlace
from tests.conftest import DEST, START, T0, lat_at
from tests.helpers import drive, get_trip, make_user, notifications, point, sent_types, start_trip


async def test_full_trip_sends_rules_in_order(db, channel, scenario):
    tid = await start_trip(await make_user())
    await drive(tid)
    assert await sent_types(tid) == [
        "trip_routed",
        "tracking_started",
        "time_left",
        "new_place",
        "time_left",
        "new_street",
        "getting_close",
        "next",
        "arrived",
    ]
    trip = await get_trip(tid)
    assert trip.status == Status.ARRIVED and trip.end_reason == "arrived" and trip.ended_at
    assert trip.first_street == "Churchill Avenue" and trip.current_street == "Bole Road"
    rows = await notifications(tid)
    by_key = {n.key: n for n in rows}
    assert [n.key for n in rows if n.rule == "time_left"] == ["time_left_15", "time_left_10"]
    assert by_key["place:n1"].text == "📍 You are passing Lion of Judah."
    assert by_key["time_left_15"].text == "⏱ About 15 minutes to your destination."
    assert by_key["getting_close"].priority == Priority.HIGH
    assert len(channel.sent) == len(rows)  # everything logged was delivered


async def test_rename_time_left_uses_real_speed(db, channel, scenario):
    """A slow minibus (half the routed speed) gets 'about 10 minutes' later."""
    tid = await start_trip(await make_user())
    for i in range(12):
        await point(tid, 75 * i, 30 * i)  # 2.5 m/s instead of 5
    trip = await get_trip(tid)
    assert trip.speed_ema_mps and 2.0 < trip.speed_ema_mps < 3.0
    assert trip.time_left_s > (6000 - 75 * 11) / 5 * 1.3  # noticeably longer than the routed estimate
    assert "time_left" not in await sent_types(tid)


async def test_quiet_level_sends_only_high_priority(db, channel, scenario):
    tid = await start_trip(await make_user(level="quiet"))
    await drive(tid)
    assert await sent_types(tid) == ["trip_routed", "tracking_started", "getting_close", "next", "arrived"]


async def test_chatty_level_includes_still_here(db, channel, scenario):
    tid = await start_trip(await make_user(level="chatty"))
    await drive(tid)
    assert "still_here" in await sent_types(tid)


async def test_anti_overload_limits():
    now = T0
    assert within_limits([], now)
    assert not within_limits([now - timedelta(seconds=30)], now)
    assert within_limits([now - timedelta(seconds=60)], now)
    assert not within_limits([now - timedelta(seconds=60 * k) for k in (1, 2, 3, 4)], now)


async def test_food_offer_fires_once_with_buttons(db, channel, scenario):
    scenario.places[:] = [
        OsmPlace(f"n{i}", f"Cafe {i}", None, None, "cafe", lat_at(700 + 100 * i), START[1] + 0.0002) for i in range(3)
    ]
    tid = await start_trip(await make_user())
    await drive(tid)
    types = await sent_types(tid)
    assert types.count("food_offer") == 1
    offer = next(m for _, m in channel.sent if m.type == "food_offer")
    assert offer.silent and not offer.voice and [a.id.split(":")[1] for a in offer.actions] == ["show", "later", "off"]
    assert offer.text == "☕ There are 3 cafés and restaurants within 500 m. Want to see them?"
    async with session_scope() as s:
        trip = await s.get(engine.Trip, tid)
        user = await s.get(engine.User, trip.user_id)
        places = await engine.nearby_food(s, user, lat_at(800), START[1], trip)
        assert [p.name for p in places] == ["Cafe 1", "Cafe 0", "Cafe 2"]  # nearest first
        text = engine.food_list_text(user, places)
        assert text.startswith("🍽 Places to eat nearby:") and "1. Cafe 1 (Café)" in text


async def test_noisy_points_are_ignored(db, channel, scenario):
    tid = await start_trip(await make_user())
    await point(tid, 0, 0, accuracy=150)
    assert (await get_trip(tid)).status == Status.CREATED
    async with session_scope() as s:
        assert await s.scalar(select(func.count()).select_from(LocationPoint)) == 0
    await point(tid, 0, 30)
    assert (await get_trip(tid)).status == Status.ACTIVE


async def test_arrival_needs_two_points(db, channel, scenario):
    tid = await start_trip(await make_user())
    for i in range(5):
        await point(tid, 150 * i, 30 * i)
    await point(tid, 6000, 150)  # one GPS jump onto the destination
    await point(tid, 750, 180)
    trip = await get_trip(tid)
    assert trip.status == Status.ACTIVE and "arrived" not in await sent_types(tid)
    assert trip.speed_ema_mps < 10  # the jump did not poison the speed estimate


async def test_stale_resume_and_timeout(db, channel, scenario):
    tid = await start_trip(await make_user())
    for i in range(3):
        await point(tid, 150 * i, 30 * i)  # last point at t=60
    async with session_scope() as s:
        await engine.tick(s, now=T0 + timedelta(seconds=60 + 130))
    assert (await get_trip(tid)).status == Status.STALE
    assert (await sent_types(tid))[-1] == "location_lost"

    await point(tid, 450, 200)
    assert (await get_trip(tid)).status == Status.ACTIVE
    assert "tracking_resumed" in await sent_types(tid)

    async with session_scope() as s:
        await engine.tick(s, now=T0 + timedelta(seconds=200 + 650))
    trip = await get_trip(tid)
    assert trip.status == Status.ENDED and trip.end_reason == "timeout"
    assert (await sent_types(tid))[-1] == "trip_ended_timeout"


async def test_tick_sends_time_based_rules_without_new_points(db, channel, scenario):
    tid = await start_trip(await make_user())
    for i in range(10):
        await point(tid, 150 * i, 30 * i)  # ~15.5 min left at t=270
    async with session_scope() as s:
        await engine.tick(s, now=T0 + timedelta(seconds=270 + 100))  # still under the 2-min stale limit
    assert "time_left" in await sent_types(tid)


async def test_user_stop_and_new_trip_replaces_old(db, channel, scenario):
    uid = await make_user()
    tid = await start_trip(uid)
    await point(tid, 0, 0)
    async with session_scope() as s:
        trip = await s.get(engine.Trip, tid)
        await engine.end_trip(s, trip, "user")
    trip = await get_trip(tid)
    assert trip.status == Status.ENDED and (await sent_types(tid))[-1] == "trip_ended"
    tid2 = await start_trip(uid)
    assert tid2 != tid
    async with session_scope() as s:
        assert (await engine.open_trip(s, uid)).id == tid2


async def test_routing_failure_still_tracks(db, channel, scenario):
    scenario.route["fail"] = True
    tid = await start_trip(await make_user())
    await point(tid, 0, 0)
    trip = await get_trip(tid)
    assert trip.status == Status.ACTIVE and trip.route_provider == "straight"
    assert (await sent_types(tid))[0] == "route_failed"
    await drive(tid)
    assert (await get_trip(tid)).status == Status.ARRIVED


async def test_points_are_purged_after_24h(db, channel, scenario):
    tid = await start_trip(await make_user())
    await drive(tid)
    async with session_scope() as s:
        assert await engine.purge_old_points(s, now=T0 + timedelta(hours=2)) == 0
        assert await engine.purge_old_points(s, now=T0 + timedelta(hours=26)) > 0
        assert await s.scalar(select(func.count()).select_from(LocationPoint)) == 0


async def test_where_am_i_and_time_left_texts(db, channel, scenario):
    tid = await start_trip(await make_user())
    for i in range(15):
        await point(tid, 150 * i, 30 * i)
    async with session_scope() as s:
        trip = await s.get(engine.Trip, tid)
        user = await s.get(engine.User, trip.user_id)
        text = await engine.where_am_i(s, user, lat_at(2100), START[1], trip)
        assert text.startswith("📍 You are on Churchill Avenue, near Lion of Judah.")
        assert "km to Bole Medhanialem" in text
        assert engine.time_left_text(user, trip).startswith("⏱ About ")
        assert "Bole Medhanialem" in engine.card_text(user, trip)
