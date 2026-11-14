"""Application settings, read from environment variables and `.env`.

Every distance and time threshold from the plan lives here so it can be tuned
during testing without touching the engine code.
"""

from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Infrastructure -----------------------------------------------------
    database_url: str = "sqlite+aiosqlite:///./var/menged.db"
    database_url_pooled: str | None = None

    telegram_bot_token: str = ""
    telegram_mode: str = "polling"  # "polling" (local) or "webhook" (production)
    webhook_base_url: str = ""  # e.g. https://menged.onrender.com
    webhook_secret: str = "change-me"
    admin_telegram_ids: str = ""  # comma-separated user ids allowed to use /simulate

    ors_api_key: str = ""
    user_agent: str = "MengedBot/1.0"
    nominatim_url: str = "https://nominatim.openstreetmap.org"
    photon_url: str = "https://photon.komoot.io"
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    osrm_url: str = "https://router.project-osrm.org"
    ors_url: str = "https://api.openrouteservice.org"
    routing_profile: str = "driving-car"

    tts_enabled: bool = True
    tts_cache_dir: str = "var/tts"
    firebase_credentials_file: str = ""

    enable_scheduler: bool = True
    enable_bot: bool = True

    # --- Map search bias (Ethiopia / Addis Ababa) -------------------------
    country_codes: str = "et"
    # left, top, right, bottom (lon/lat) roughly around Addis Ababa
    viewbox: str = "38.60,9.10,38.95,8.83"

    # --- Trip engine thresholds (starting values, tune in testing) --------
    max_accuracy_m: float = 100.0
    approaching_m: float = 500.0
    approaching_s: float = 300.0
    next_m: float = 150.0
    next_s: float = 60.0
    arrived_m: float = 50.0
    stale_after_s: int = 120
    end_after_s: int = 600
    purge_points_after_h: int = 24
    route_corridor_m: int = 200
    reverse_geocode_every_s: int = 30

    # --- Notification engine ----------------------------------------------
    min_gap_s: int = 45
    window_s: int = 300
    window_max: int = 4
    still_here_after_s: int = 180
    landmark_radius_m: float = 100.0
    time_left_marks_min: str = "15,10,5"
    food_radius_m: float = 500.0
    food_min_places: int = 2
    food_offer_every_s: int = 600
    food_min_trip_s: int = 600
    trip_card_every_s: int = 15
    tick_seconds: int = 30

    # --- Derived helpers ----------------------------------------------------
    @property
    def time_left_marks(self) -> list[int]:
        return sorted((int(x) for x in self.time_left_marks_min.split(",") if x.strip()), reverse=True)

    @property
    def admin_ids(self) -> set[int]:
        return {int(x) for x in self.admin_telegram_ids.split(",") if x.strip()}

    @property
    def app_database_url(self) -> str:
        """URL the running app uses (pooled when available)."""
        return to_async_url(self.database_url_pooled or self.database_url)

    @property
    def migration_database_url(self) -> str:
        """Direct (non-pooled) URL for Alembic migrations."""
        return to_async_url(self.database_url)

    @property
    def uses_pgbouncer(self) -> bool:
        return bool(self.database_url_pooled) or "-pooler" in self.database_url


# libpq-only query options that asyncpg does not understand.
_LIBPQ_ONLY = {"sslmode", "channel_binding", "sslrootcert", "sslcert", "sslkey", "options"}


def to_async_url(url: str) -> str:
    """Turn a plain `postgresql://` URL (as Neon gives it) into an asyncpg URL.

    libpq options such as `sslmode` and `channel_binding` are removed; SSL is
    passed to asyncpg through `connect_args` instead (see `app.db`).
    """
    if url.startswith("sqlite"):
        return url
    parts = urlsplit(url)
    scheme = "postgresql+asyncpg"
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if k not in _LIBPQ_ONLY])
    return urlunsplit((scheme, parts.netloc, parts.path, query, parts.fragment))


def needs_ssl(url: str) -> bool:
    return "sslmode=require" in url or "neon.tech" in url


@lru_cache
def get_settings() -> Settings:
    return Settings()
