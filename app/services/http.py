"""Shared HTTP client and small helpers for the free map services."""

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings

_client: httpx.AsyncClient | None = None


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            headers={"User-Agent": get_settings().user_agent},
            timeout=httpx.Timeout(20.0, connect=10.0),
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


class ServiceError(Exception):
    """An external map service failed or returned nothing usable."""


class RateLimiter:
    """Allows one call per `interval` seconds across the whole app."""

    def __init__(self, interval: float) -> None:
        self.interval = interval
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def __aenter__(self) -> None:
        await self._lock.acquire()
        wait = self._last + self.interval - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)

    async def __aexit__(self, *exc: object) -> None:
        self._last = time.monotonic()
        self._lock.release()


class TTLCache:
    """Small in-memory LRU cache with expiry."""

    def __init__(self, max_items: int = 2000, ttl_s: float = 24 * 3600) -> None:
        self.max_items = max_items
        self.ttl_s = ttl_s
        self._data: OrderedDict[Any, tuple[float, Any]] = OrderedDict()

    def get(self, key: Any) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires, value = item
        if expires < time.monotonic():
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return value

    def set(self, key: Any, value: Any) -> None:
        self._data[key] = (time.monotonic() + self.ttl_s, value)
        self._data.move_to_end(key)
        while len(self._data) > self.max_items:
            self._data.popitem(last=False)


@dataclass
class PlaceCandidate:
    """A destination search result from any source."""

    name: str
    lat: float
    lon: float
    detail: str = ""  # area / kind shown under the name
    source: str = ""
    score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "lat": self.lat,
            "lon": self.lon,
            "detail": self.detail,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PlaceCandidate":
        return cls(d["name"], d["lat"], d["lon"], d.get("detail", ""), d.get("source", ""))
