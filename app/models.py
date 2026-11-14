"""Database tables.

The five tables from the plan (users, trips, location_points, trip_places,
notifications), plus a few extra trip columns the engine needs (smoothing
state, debounce counters, trip card bookkeeping).
"""

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """Stores timezone-aware UTC datetimes; always returns aware values.

    SQLite drops the timezone, so values read back are re-tagged as UTC.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class Status:
    CREATED = "created"
    ROUTED = "routed"
    ACTIVE = "active"
    STALE = "stale"
    APPROACHING = "approaching"
    ARRIVED = "arrived"
    ENDED = "ended"

    OPEN = (CREATED, ROUTED, ACTIVE, STALE, APPROACHING)
    TRACKING = (ACTIVE, STALE, APPROACHING)


class Priority:
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class User(TimestampMixin, Base):
    __tablename__ = "users"

    channel: Mapped[str] = mapped_column(String(16), default="telegram")  # telegram | app
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    device_token: Mapped[str | None] = mapped_column(String(512), nullable=True)  # FCM token (app)
    api_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)  # app auth
    language: Mapped[str] = mapped_column(String(8), default="en")
    voice_on: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_level: Mapped[str] = mapped_column(String(16), default="normal")  # quiet | normal | chatty

    trips: Mapped[list["Trip"]] = relationship(back_populates="user")


class Trip(TimestampMixin, Base):
    __tablename__ = "trips"
    __table_args__ = (Index("ix_trips_user_status", "user_id", "status"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16), default=Status.CREATED)

    start_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    start_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    dest_name: Mapped[str] = mapped_column(String(255))
    dest_lat: Mapped[float] = mapped_column(Float)
    dest_lon: Mapped[float] = mapped_column(Float)

    route_line: Mapped[str | None] = mapped_column(Text, nullable=True)  # encoded polyline (precision 5)
    route_provider: Mapped[str | None] = mapped_column(String(16), nullable=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)

    last_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    end_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)

    smooth_var: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed_ema_mps: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_left_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_left_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_street: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_street: Mapped[str | None] = mapped_column(String(255), nullable=True)  # never announced
    last_reverse_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    pending_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    pending_count: Mapped[int] = mapped_column(Integer, default=0)

    card_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    food_offers_off: Mapped[bool] = mapped_column(Boolean, default=False)
    last_food_offer_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship(back_populates="trips")


class LocationPoint(TimestampMixin, Base):
    __tablename__ = "location_points"
    __table_args__ = (Index("ix_location_points_trip_recorded", "trip_id", "recorded_at"),)

    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed_mps: Mapped[float | None] = mapped_column(Float, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime())


class TripPlace(TimestampMixin, Base):
    __tablename__ = "trip_places"
    __table_args__ = (Index("ix_trip_places_trip", "trip_id"),)

    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"))
    osm_id: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(255))
    name_am: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    kind: Mapped[str] = mapped_column(String(32))  # landmark | restaurant | cafe | fast_food | ...
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    distance_from_route_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    along_route_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    announced_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    FOOD_KINDS = ("restaurant", "cafe", "fast_food")

    @property
    def is_food(self) -> bool:
        return self.kind in self.FOOD_KINDS

    def display_name(self, lang: str) -> str:
        if lang == "am" and self.name_am:
            return self.name_am
        if lang == "en" and self.name_en:
            return self.name_en
        return self.name


class Notification(TimestampMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_trip_sent", "trip_id", "sent_at"),
        UniqueConstraint("trip_id", "key", name="uq_notifications_trip_key"),
    )

    trip_id: Mapped[int | None] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    rule: Mapped[str] = mapped_column(String(32))
    key: Mapped[str | None] = mapped_column(String(128), nullable=True)  # one-shot dedupe key
    priority: Mapped[str] = mapped_column(String(8))
    text: Mapped[str] = mapped_column(Text)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    sent_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    voice_sent: Mapped[bool] = mapped_column(Boolean, default=False)
