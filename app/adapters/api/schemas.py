"""Request and response bodies for the mobile app API (/v1)."""

from datetime import datetime

from pydantic import BaseModel, Field


class DeviceIn(BaseModel):
    device_token: str | None = Field(None, description="FCM registration token, if push is used")
    language: str = "en"


class DeviceOut(BaseModel):
    user_id: int
    token: str


class Point(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    name: str | None = None


class TripIn(BaseModel):
    destination: Point | None = Field(None, description="A place picked from /v1/places/search")
    destination_query: str | None = Field(None, description="Free text; the best search match is used")
    start: Point | None = Field(None, description="Current position; routes the trip immediately")


class TripOut(BaseModel):
    id: int
    status: str
    dest_name: str
    dest_lat: float
    dest_lon: float
    start_name: str | None
    distance_m: float | None
    duration_s: float | None
    distance_left_m: float | None
    time_left_s: float | None
    current_street: str | None
    route_line: str | None
    started_at: datetime | None
    ended_at: datetime | None


class LocationIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    accuracy_m: float | None = None
    recorded_at: datetime | None = None


class LocationsIn(BaseModel):
    points: list[LocationIn] = Field(min_length=1, max_length=100)


class MessageOut(BaseModel):
    id: int
    type: str
    priority: str
    text: str
    params: dict
    sent_at: datetime


class LocationsOut(BaseModel):
    trip: TripOut
    messages: list[MessageOut]


class PlaceOut(BaseModel):
    name: str
    lat: float
    lon: float
    detail: str = ""
    kind: str | None = None
    meters: int | None = None


class Settings(BaseModel):
    language: str = Field("en", pattern="^(en|am)$")
    voice_on: bool = True
    alert_level: str = Field("normal", pattern="^(quiet|normal|chatty)$")


class WhereOut(BaseModel):
    text: str
