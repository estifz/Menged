"""Trip engine: the only code that changes `trips.status`.

created → routed → active ⇄ stale → approaching → arrived
                     └──────────── ended (user stop / 10 min without location)

Both the Telegram adapter and the REST API call these functions, so the bot
and the app always behave the same.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import base as channels
from app.config import get_settings
from app.db import after_commit
from app.demo.data import load_demo
from app.engine import notifications as notif
from app.engine.notifications import Ctx, make
from app.engine.templates import fmt_km, fmt_minutes, render
from app.geo import Route, encode, haversine, kalman_step
from app.models import LocationPoint, Priority, Status, Trip, TripPlace, User, utcnow
from app.services import gazetteer, nominatim, overpass, photon, routing
from app.services.http import PlaceCandidate, ServiceError

log = logging.getLogger(__name__)

_locks: dict[int, asyncio.Lock] = {}
_routes: dict[int, tuple[str, Route]] = {}
_card_last: dict[int, float] = {}

DEFAULT_SPEED_MPS = 6.0  # ~22 km/h, city traffic


def trip_lock(trip_id: int) -> asyncio.Lock:
    return _locks.setdefault(trip_id, asyncio.Lock())


def route_of(trip: Trip) -> Route | None:
    if not trip.route_line:
        return None
    cached = _routes.get(trip.id)
    if cached and cached[0] == trip.route_line:
        return cached[1]
    route = Route.from_polyline(trip.route_line)
    _routes[trip.id] = (trip.route_line, route)
    return route


async def get_or_create_telegram_user(session: AsyncSession, chat_id: int, lang_hint: str | None = None) -> tuple[User, bool]:
    user = await session.scalar(select(User).where(User.telegram_chat_id == chat_id))
    if user:
        return user, False
    lang = "am" if (lang_hint or "").startswith("am") else "en"
    user = User(channel="telegram", telegram_chat_id=chat_id, language=lang, voice_on=True, alert_level="normal")
    session.add(user)
    await session.flush()
    return user, True


async def open_trip(session: AsyncSession, user_id: int) -> Trip | None:
    return await session.scalar(
        select(Trip)
        .where(Trip.user_id == user_id, Trip.status.in_(Status.OPEN))
        .order_by(Trip.created_at.desc())
        .limit(1)
    )


async def search_destination(query: str, lang: str = "en", limit: int = 3) -> list[PlaceCandidate]:
    """Offline gazetteer (instant, typo-tolerant) → Nominatim → Photon.

    A strong offline match is returned straight away. Otherwise the online
    results come first and weaker offline matches fill the remaining slots.
    """
    offline = gazetteer.search(query, lang, limit)
    if offline and offline[0].score >= gazetteer.STRONG_SCORE:
        return offline
    online: list[PlaceCandidate] = []
    errors = 0
    for source in (lambda: nominatim.search(query, lang, limit), lambda: photon.search(query, limit)):
        try:
            online = await source()
        except ServiceError as e:
            log.warning("%s", e)
            errors += 1
            continue
        if online:
            break
    if not online and not offline and errors == 2:
        raise ServiceError("all geocoders failed")
    merged: list[PlaceCandidate] = []
    for c in online + offline:
        if all(haversine(c.lat, c.lon, m.lat, m.lon) > 100 for m in merged):
            merged.append(c)
    return merged[:limit]


async def create_trip(
    session: AsyncSession,
    user: User,
    dest: PlaceCandidate,
    start: tuple[float, float] | None = None,
    now: datetime | None = None,
    simulated: bool = False,
) -> Trip:
    """Create a trip. If the start is known (app, or a location the bot already
    has) the trip is routed right away; otherwise the first live point routes it."""
    now = now or utcnow()
    previous = await open_trip(session, user.id)
    if previous:
        await end_trip(session, previous, "replaced", now=now, notify=False)
    trip = Trip(
        user_id=user.id,
        status=Status.CREATED,
        dest_name=dest.name,
        dest_lat=dest.lat,
        dest_lon=dest.lon,
        simulated=simulated,
        created_at=now,
    )
    session.add(trip)
    await session.flush()
    if start is not None:
        await route_trip(session, trip, user, start[0], start[1], now)
    return trip


_background: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)


async def drain_background() -> None:
    """Wait for background work (used by tests and the simulator)."""
    while _background:
        await asyncio.gather(*list(_background), return_exceptions=True)


def _add_places(session: AsyncSession, trip: Trip, line: Route | None, places, existing: list[TripPlace] = ()) -> int:
    added = 0
    known = list(existing)
    for p in places:
        if any(k.osm_id == p.osm_id or (k.name == p.name and haversine(k.lat, k.lon, p.lat, p.lon) < 80) for k in known):
            continue
        proj = line.project(p.lat, p.lon) if line else None
        row = TripPlace(
            trip_id=trip.id,
            osm_id=p.osm_id,
            name=p.name,
            name_am=p.name_am,
            name_en=p.name_en,
            kind=p.kind,
            lat=p.lat,
            lon=p.lon,
            distance_from_route_m=proj.offset_m if proj else None,
            along_route_m=proj.along_m if proj else None,
        )
        session.add(row)
        known.append(row)
        added += 1
    return added


async def _enrich_places(trip_id: int, points: list[tuple[float, float]]) -> None:
    """Add Overpass places the offline list doesn't have. Best effort."""
    try:
        found = await overpass.places_along(points, get_settings().route_corridor_m)
    except ServiceError as e:
        log.info("Overpass top-up skipped for trip %s: %s", trip_id, e)
        return
    from app.db import session_scope

    try:
        async with session_scope() as session:
            async with trip_lock(trip_id):
                trip = await session.get(Trip, trip_id)
                if trip is None or trip.status not in Status.OPEN:
                    return
                added = _add_places(session, trip, route_of(trip), found, await _places(session, trip))
        log.info("Overpass added %d places to trip %s", added, trip_id)
    except Exception:
        log.exception("saving Overpass places failed for trip %s", trip_id)


def _straight_line(start: tuple[float, float], dest: tuple[float, float]) -> routing.RouteResult:
    d = haversine(*start, *dest) * 1.3  # streets are longer than a straight line
    return routing.RouteResult(encode([start, dest]), d, d / DEFAULT_SPEED_MPS, "straight")


async def route_trip(session: AsyncSession, trip: Trip, user: User, lat: float, lon: float, now: datetime) -> None:
    """created → routed: route line, distance, time, and places along it (once)."""
    s = get_settings()
    start, dest = (lat, lon), (trip.dest_lat, trip.dest_lon)
    trip.start_lat, trip.start_lon = lat, lon
    demo = load_demo()
    use_demo = demo is not None and (trip.simulated or False) and demo.matches(None, dest)

    route: routing.RouteResult | None = None
    if use_demo:
        route = routing.RouteResult(demo.route["line"], demo.route["distance_m"], demo.route["duration_s"], "demo")
        trip.start_name = demo.start["name"]
    else:
        trip.start_name = await nominatim.reverse(lat, lon, user.language) or None
        try:
            route = await routing.get_route(start, dest)
        except ServiceError:
            if demo is not None and demo.matches(start, dest):
                route = routing.RouteResult(demo.route["line"], demo.route["distance_m"], demo.route["duration_s"], "demo")
    route_failed = route is None
    if route is None:
        route = _straight_line(start, dest)

    trip.route_line = route.line
    trip.route_provider = route.provider
    trip.distance_m = route.distance_m
    trip.duration_s = route.duration_s
    trip.distance_left_m = route.distance_m
    trip.time_left_s = route.duration_s
    trip.status = Status.ROUTED

    # Places along the corridor, cached in trip_places. The offline list answers
    # instantly; Overpass only tops it up in the background, because the public
    # servers are often slow or blocked from cloud hosts and must never hold up
    # a trip (or a Telegram webhook call).
    line = route_of(trip)
    if route.provider == "demo" and demo is not None:
        _add_places(session, trip, line, [overpass.OsmPlace(**p) for p in demo.places])
    elif line is not None:
        points = line.simplified()
        _add_places(session, trip, line, gazetteer.along_route(points, s.route_corridor_m))
        if route.provider != "straight":
            trip_id = trip.id
            after_commit(session, lambda: _spawn(_enrich_places(trip_id, points)))
    await session.flush()

    if route_failed:
        await notif.deliver(session, user, trip, make("route_failed", user, Priority.HIGH, key="routed"), now)
    else:
        await notif.deliver(
            session,
            user,
            trip,
            make(
                "trip_routed",
                user,
                Priority.HIGH,
                key="routed",
                dest=trip.dest_name,
                km=fmt_km(route.distance_m),
                minutes=fmt_minutes(route.duration_s),
            ),
            now,
        )


async def end_trip(session: AsyncSession, trip: Trip, reason: str, now: datetime | None = None, notify: bool = True) -> None:
    now = now or utcnow()
    if trip.status in (Status.ENDED, Status.ARRIVED):
        return
    user = await session.get(User, trip.user_id)
    trip.status = Status.ENDED
    trip.ended_at = now
    trip.end_reason = reason
    if user is None:
        return
    if notify:
        key = "trip_ended_timeout" if reason == "timeout" else "trip_ended"
        await notif.deliver(session, user, trip, make(key, user, Priority.HIGH, key="ended"), now)
    await _close_card(user, trip)
    _forget(trip.id)


def _forget(trip_id: int) -> None:
    _routes.pop(trip_id, None)
    _card_last.pop(trip_id, None)


@dataclass
class Progress:
    along_m: float | None
    distance_left: float
    time_left_s: float
    d_dest: float


def _effective_speed(trip: Trip) -> float:
    avg = (trip.distance_m / trip.duration_s) if trip.distance_m and trip.duration_s else DEFAULT_SPEED_MPS
    if trip.speed_ema_mps is None:
        return avg
    # Lean on the real speed (minibuses are slower than car routing), but don't
    # let a red light make the estimate explode.
    return max(0.5 * avg, 0.6 * trip.speed_ema_mps + 0.4 * avg)


def compute_progress(trip: Trip, lat: float, lon: float) -> Progress:
    d_dest = haversine(lat, lon, trip.dest_lat, trip.dest_lon)
    route = route_of(trip)
    along = None
    if route is not None and route.length_m > 0:
        prev_along = route.length_m - trip.distance_left_m if trip.distance_left_m is not None else None
        proj = route.project(lat, lon, min_along=prev_along)
        along = proj.along_m
        if proj.offset_m > 300:  # off the route: fall back to straight-line distance
            distance_left = d_dest * 1.3
        else:
            scale = (trip.distance_m / route.length_m) if trip.distance_m else 1.0
            distance_left = max((route.length_m - proj.along_m) * scale, d_dest)
    else:
        distance_left = d_dest * 1.3
    return Progress(along, distance_left, distance_left / _effective_speed(trip), d_dest)


def _candidate_status(trip: Trip, p: Progress) -> str:
    s = get_settings()
    if p.d_dest <= s.arrived_m:
        return Status.ARRIVED
    if p.distance_left <= s.approaching_m or p.time_left_s <= s.approaching_s:
        return Status.APPROACHING
    if trip.status == Status.APPROACHING and p.distance_left <= s.approaching_m * 2:
        return Status.APPROACHING  # hysteresis: don't flap at the boundary
    return Status.ACTIVE


async def _places(session: AsyncSession, trip: Trip) -> list[TripPlace]:
    return list(await session.scalars(select(TripPlace).where(TripPlace.trip_id == trip.id)))


async def add_location(
    session: AsyncSession,
    trip: Trip,
    lat: float,
    lon: float,
    accuracy_m: float | None = None,
    recorded_at: datetime | None = None,
    now: datetime | None = None,
) -> list:
    """Handle one location point. Returns the notifications sent."""
    s = get_settings()
    now = now or utcnow()
    recorded_at = recorded_at or now
    if trip.status not in Status.OPEN:
        return []
    user = await session.get(User, trip.user_id)
    if user is None:
        return []

    sent: list = []
    # Noisy point (indoors, between buildings): it proves sharing is alive, but
    # we don't use the position.
    if accuracy_m is not None and accuracy_m > s.max_accuracy_m:
        if trip.status in Status.TRACKING:
            trip.last_seen_at = recorded_at
        return []

    if trip.last_seen_at and recorded_at < trip.last_seen_at:
        return []  # arrived out of order; a newer point was already used

    if trip.status == Status.CREATED:
        await route_trip(session, trip, user, lat, lon, now)

    dt = (recorded_at - trip.last_seen_at).total_seconds() if trip.last_seen_at else 0.0
    slat, slon, var = kalman_step(trip.last_lat, trip.last_lon, trip.smooth_var, dt, lat, lon, accuracy_m, trip.speed_ema_mps)
    speed = None
    if trip.last_lat is not None and dt >= 1:
        speed = haversine(trip.last_lat, trip.last_lon, slat, slon) / dt
        if speed < 45:  # ignore GPS jumps
            trip.speed_ema_mps = speed if trip.speed_ema_mps is None else 0.7 * trip.speed_ema_mps + 0.3 * speed
    session.add(
        LocationPoint(trip_id=trip.id, lat=lat, lon=lon, accuracy_m=accuracy_m, speed_mps=speed, recorded_at=recorded_at)
    )

    if trip.status == Status.ROUTED:
        trip.status = Status.ACTIVE
        trip.started_at = now
        msg = make("tracking_started", user, Priority.HIGH, key="started")
        msg.voice = False
        await notif.deliver(session, user, trip, msg, now)
    elif trip.status == Status.STALE:
        trip.status = Status.ACTIVE
        trip.pending_state, trip.pending_count = None, 0
        await notif.deliver(session, user, trip, make("tracking_resumed", user, Priority.HIGH), now)

    progress = compute_progress(trip, slat, slon)

    # State changes need 2 points in a row (noisy GPS must not trigger "arrived").
    became = None
    cand = _candidate_status(trip, progress)
    if cand == trip.status:
        trip.pending_state, trip.pending_count = None, 0
    else:
        if trip.pending_state == cand:
            trip.pending_count += 1
        else:
            trip.pending_state, trip.pending_count = cand, 1
        if trip.pending_count >= 2:
            trip.status = cand
            became = cand
            trip.pending_state, trip.pending_count = None, 0

    # Street name: reverse-geocode at most once per 30 s per trip.
    street_changed = False
    if trip.last_reverse_at is None or (now - trip.last_reverse_at).total_seconds() >= s.reverse_geocode_every_s:
        trip.last_reverse_at = now
        street = await nominatim.reverse(slat, slon, user.language)
        if street:
            if trip.first_street is None:
                trip.first_street = street
            if street != trip.current_street:
                street_changed = True
                trip.current_street = street

    trip.last_lat, trip.last_lon, trip.smooth_var = slat, slon, var
    trip.last_seen_at = recorded_at
    trip.distance_left_m = progress.distance_left
    trip.time_left_s = progress.time_left_s

    ctx = Ctx(
        now=now,
        lat=slat,
        lon=slon,
        along_m=progress.along_m,
        distance_left=progress.distance_left,
        time_left_s=progress.time_left_s,
        street=trip.current_street,
        street_changed=street_changed,
        became=became,
        moving=(trip.speed_ema_mps or 0) > 1.0,
        places=await _places(session, trip),
    )
    sent += await notif.evaluate(session, user, trip, ctx)

    if became == Status.ARRIVED:
        trip.ended_at = now
        trip.end_reason = "arrived"
        await _close_card(user, trip)
        _forget(trip.id)
    else:
        await refresh_card(user, trip)
    return sent


def card_text(user: User, trip: Trip) -> str:
    if trip.status in (Status.CREATED, Status.ROUTED) or trip.last_lat is None:
        return render("card_waiting", user.language, dest=trip.dest_name)
    return render(
        "card",
        user.language,
        dest=trip.dest_name,
        km=fmt_km(trip.distance_left_m),
        minutes=fmt_minutes(trip.time_left_s),
        street=trip.current_street or render("card_unknown_street", user.language),
    )


async def refresh_card(user: User, trip: Trip, force: bool = False) -> None:
    gap = 3 if trip.simulated else get_settings().trip_card_every_s
    last = _card_last.get(trip.id)
    if not force and last is not None and time.monotonic() - last < gap:
        return
    _card_last[trip.id] = time.monotonic()
    try:
        mid = await channels.get(user.channel).update_card(user, trip, card_text(user, trip))
        if mid:
            trip.card_message_id = mid
    except Exception:
        log.exception("trip card update failed")


async def _close_card(user: User, trip: Trip) -> None:
    try:
        await channels.get(user.channel).close_card(user, trip, render("card_done", user.language, dest=trip.dest_name))
    except Exception:
        log.exception("closing trip card failed")


async def tick(session: AsyncSession, now: datetime | None = None) -> None:
    """Stale/ended checks and time-based rules for trips with no new points."""
    s = get_settings()
    now = now or utcnow()
    trips = list(
        await session.scalars(select(Trip).where(Trip.status.in_(Status.OPEN), Trip.simulated.is_(False)))
    )
    for trip in trips:
        async with trip_lock(trip.id):
            await session.refresh(trip)
            if trip.status not in Status.OPEN:
                continue
            idle = (now - (trip.last_seen_at or trip.created_at)).total_seconds()
            if trip.status == Status.CREATED:
                if idle > 3600:  # destination chosen but never started
                    await end_trip(session, trip, "expired", now, notify=False)
                continue
            if idle >= s.end_after_s:
                await end_trip(session, trip, "timeout", now)
                continue
            user = await session.get(User, trip.user_id)
            if user is None:
                continue
            if idle >= s.stale_after_s and trip.status in (Status.ACTIVE, Status.APPROACHING):
                trip.status = Status.STALE
                await notif.deliver(session, user, trip, make("location_lost", user, Priority.HIGH), now)
                continue
            if trip.status in (Status.ACTIVE, Status.APPROACHING) and trip.time_left_s is not None:
                since_point = (now - trip.last_seen_at).total_seconds() if trip.last_seen_at else 0
                ctx = Ctx(
                    now=now,
                    lat=trip.last_lat,
                    lon=trip.last_lon,
                    distance_left=trip.distance_left_m,
                    time_left_s=max(0.0, trip.time_left_s - since_point),
                    street=trip.current_street,
                    moving=(trip.speed_ema_mps or 0) > 1.0,
                )
                await notif.evaluate(session, user, trip, ctx)


async def purge_old_points(session: AsyncSession, now: datetime | None = None) -> int:
    """Privacy: delete raw location points 24 h after the trip ends."""
    now = now or utcnow()
    cutoff = now - timedelta(hours=get_settings().purge_points_after_h)
    ended = select(Trip.id).where(Trip.status.in_((Status.ENDED, Status.ARRIVED)), Trip.ended_at < cutoff)
    result = await session.execute(delete(LocationPoint).where(LocationPoint.trip_id.in_(ended)))
    return result.rowcount or 0


async def where_am_i(session: AsyncSession, user: User, lat: float, lon: float, trip: Trip | None = None) -> str:
    lang = user.language
    street = None
    if trip and trip.current_street and trip.last_reverse_at and (utcnow() - trip.last_reverse_at).total_seconds() < 90:
        street = trip.current_street
    if not street:
        street = await nominatim.reverse(lat, lon, lang)

    landmark = None
    if trip:
        best = None
        for p in await _places(session, trip):
            if p.is_food:
                continue
            d = haversine(lat, lon, p.lat, p.lon)
            if d <= 300 and (best is None or d < best[0]):
                best = (d, p.display_name(lang))
        landmark = best[1] if best else None
    if not landmark:
        near = gazetteer.nearest(lat, lon, 300, exclude_kinds=("restaurant", "cafe", "fast_food"))
        landmark = gazetteer.display_name(near[0], lang) if near else None

    if street and landmark:
        text = render("where_am_i", lang, street=street, landmark=landmark)
    elif street:
        text = render("where_am_i_street", lang, street=street)
    elif landmark:
        text = render("where_am_i_landmark", lang, landmark=landmark)
    else:
        text = render("where_am_i_unknown", lang)
    if trip and trip.status in Status.TRACKING:
        text += render("dest_suffix", lang, km=fmt_km(trip.distance_left_m), dest=trip.dest_name)
    return text


def time_left_text(user: User, trip: Trip) -> str:
    return render(
        "time_left_status",
        user.language,
        minutes=fmt_minutes(trip.time_left_s),
        km=fmt_km(trip.distance_left_m),
        dest=trip.dest_name,
    )


@dataclass
class NearbyPlace:
    name: str
    kind: str
    lat: float
    lon: float
    meters: int


async def nearby_food(
    session: AsyncSession, user: User, lat: float, lon: float, trip: Trip | None = None, limit: int = 5
) -> list[NearbyPlace]:
    """Up to 5 restaurants/cafés within 500 m, nearest first. Uses the trip's
    cached places first; one Overpass query otherwise."""
    radius = get_settings().food_radius_m
    found: list[NearbyPlace] = []
    if trip:
        for p in await _places(session, trip):
            if p.is_food:
                d = haversine(lat, lon, p.lat, p.lon)
                if d <= radius:
                    found.append(NearbyPlace(p.display_name(user.language), p.kind, p.lat, p.lon, int(d)))
    if len(found) < 2:
        for p in gazetteer.food_near(lat, lon, radius):
            d = haversine(lat, lon, p.lat, p.lon)
            name = (p.name_am if user.language == "am" else p.name_en) or p.name
            if all(f.name != name for f in found):
                found.append(NearbyPlace(name, p.kind, p.lat, p.lon, int(d)))
    if len(found) < 2:
        try:
            for p in await overpass.food_near(lat, lon, int(radius)):
                d = haversine(lat, lon, p.lat, p.lon)
                name = (p.name_am if user.language == "am" else p.name_en) or p.name
                if d <= radius and all(f.name != name for f in found):
                    found.append(NearbyPlace(name, p.kind, p.lat, p.lon, int(d)))
        except ServiceError as e:
            log.warning("%s", e)
    found.sort(key=lambda f: f.meters)
    return found[:limit]


def food_list_text(user: User, places: list[NearbyPlace]) -> str:
    lang = user.language
    if not places:
        return render("food_none", lang)
    labels = gazetteer.KIND_LABELS.get(lang, gazetteer.KIND_LABELS["en"])
    lines = [render("food_list_title", lang)]
    for i, p in enumerate(places, 1):
        lines.append(render("food_item", lang, n=i, name=p.name, kind=labels.get(p.kind, p.kind), meters=p.meters))
    return "\n".join(lines)
