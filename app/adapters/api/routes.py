"""REST API for the mobile app. Same trip engine as the bot; only this adapter
differs. The app speaks messages with its own on-device text-to-speech, so
the server sends text only."""

import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.api import schemas
from app.adapters.base import OutMessage
from app.db import get_session
from app.engine import trips as engine
from app.models import Notification, Trip, User
from app.services import push
from app.services.http import PlaceCandidate, ServiceError

router = APIRouter(prefix="/v1", tags=["app"])
_bearer = HTTPBearer(auto_error=False)


class AppChannel:
    """Messages are already logged in `notifications` (the app pulls them);
    push only wakes the app sooner."""

    async def send(self, user: User, msg: OutMessage) -> bool:
        await push.send(user.device_token, "Menged", msg.text, {"type": msg.type, "priority": msg.priority})
        return False

    async def update_card(self, user, trip, text) -> int | None:
        return None

    async def close_card(self, user, trip, text) -> None:
        return None


async def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    if creds is None:
        raise HTTPException(401, "missing bearer token")
    user = await session.scalar(select(User).where(User.api_token == creds.credentials))
    if user is None:
        raise HTTPException(401, "invalid token")
    return user


async def own_trip(trip_id: int, user: User, session: AsyncSession) -> Trip:
    trip = await session.get(Trip, trip_id)
    if trip is None or trip.user_id != user.id:
        raise HTTPException(404, "trip not found")
    return trip


def trip_out(trip: Trip) -> schemas.TripOut:
    return schemas.TripOut.model_validate(trip, from_attributes=True)


def message_out(n: Notification) -> schemas.MessageOut:
    return schemas.MessageOut(
        id=n.id, type=n.rule, priority=n.priority, text=n.text, params=n.params or {}, sent_at=n.sent_at
    )


@router.post("/devices", response_model=schemas.DeviceOut)
async def register_device(body: schemas.DeviceIn, session: AsyncSession = Depends(get_session)):
    token = secrets.token_urlsafe(32)
    user = User(
        channel="app",
        device_token=body.device_token,
        api_token=token,
        language=body.language if body.language in ("en", "am") else "en",
        voice_on=True,
    )
    session.add(user)
    await session.flush()
    return schemas.DeviceOut(user_id=user.id, token=token)


@router.get("/me/settings", response_model=schemas.Settings)
async def get_settings_(user: User = Depends(current_user)):
    return schemas.Settings(language=user.language, voice_on=user.voice_on, alert_level=user.alert_level)


@router.put("/me/settings", response_model=schemas.Settings)
async def put_settings(body: schemas.Settings, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    user = await session.merge(user)
    user.language, user.voice_on, user.alert_level = body.language, body.voice_on, body.alert_level
    return body


@router.get("/places/search", response_model=list[schemas.PlaceOut])
async def search_places(q: str = Query(min_length=2), user: User = Depends(current_user)):
    try:
        results = await engine.search_destination(q, user.language, limit=5)
    except ServiceError:
        raise HTTPException(503, "map search unavailable")
    return [schemas.PlaceOut(name=c.name, lat=c.lat, lon=c.lon, detail=c.detail) for c in results]


@router.get("/places/nearby", response_model=list[schemas.PlaceOut])
async def nearby_places(
    lat: float,
    lon: float,
    kind: str = "restaurant",
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    if kind not in ("restaurant", "food", "cafe"):
        raise HTTPException(400, "supported kinds: restaurant, cafe, food")
    trip = await engine.open_trip(session, user.id)
    places = await engine.nearby_food(session, user, lat, lon, trip)
    return [schemas.PlaceOut(name=p.name, lat=p.lat, lon=p.lon, kind=p.kind, meters=p.meters) for p in places]


@router.get("/where", response_model=schemas.WhereOut)
async def where(lat: float, lon: float, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    trip = await engine.open_trip(session, user.id)
    return schemas.WhereOut(text=await engine.where_am_i(session, user, lat, lon, trip))


@router.post("/trips", response_model=schemas.TripOut, status_code=201)
async def create_trip(body: schemas.TripIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    user = await session.merge(user)
    if body.destination is not None:
        dest = PlaceCandidate(body.destination.name or "Destination", body.destination.lat, body.destination.lon)
    elif body.destination_query:
        try:
            found = await engine.search_destination(body.destination_query, user.language, limit=1)
        except ServiceError:
            raise HTTPException(503, "map search unavailable")
        if not found:
            raise HTTPException(404, "destination not found")
        dest = found[0]
    else:
        raise HTTPException(422, "destination or destination_query is required")
    start = (body.start.lat, body.start.lon) if body.start else None
    trip = await engine.create_trip(session, user, dest, start=start)
    return trip_out(trip)


@router.get("/trips/{trip_id}", response_model=schemas.TripOut)
async def get_trip(trip_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return trip_out(await own_trip(trip_id, user, session))


@router.post("/trips/{trip_id}/locations", response_model=schemas.LocationsOut)
async def post_locations(
    trip_id: int, body: schemas.LocationsIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    trip = await own_trip(trip_id, user, session)
    if trip.simulated:
        return schemas.LocationsOut(notifications=[])
    before = await session.scalar(select(func.max(Notification.id)).where(Notification.trip_id == trip.id)) or 0
    async with engine.trip_lock(trip.id):
        for p in body.points:  # the app sends them oldest first
            await engine.add_location(session, trip, p.lat, p.lon, p.accuracy_m, recorded_at=p.recorded_at)
    rows = await session.scalars(
        select(Notification).where(Notification.trip_id == trip.id, Notification.id > before).order_by(Notification.id)
    )
    return schemas.LocationsOut(trip=trip_out(trip), messages=[message_out(n) for n in rows])


@router.get("/trips/{trip_id}/messages", response_model=list[schemas.MessageOut])
async def get_messages(
    trip_id: int,
    since: int = Query(0, description="Return messages with id greater than this"),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    trip = await own_trip(trip_id, user, session)
    rows = await session.scalars(
        select(Notification).where(Notification.trip_id == trip.id, Notification.id > since).order_by(Notification.id)
    )
    return [message_out(n) for n in rows]


@router.post("/trips/{trip_id}/end", response_model=schemas.TripOut)
async def end_trip(trip_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    trip = await own_trip(trip_id, user, session)
    async with engine.trip_lock(trip.id):
        await engine.end_trip(session, trip, "user")
    return trip_out(trip)
