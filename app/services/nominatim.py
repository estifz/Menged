"""Nominatim: place names to coordinates and coordinates to street names.

Public server policy: at most 1 request per second for the whole app and an
identifying User-Agent. Every result is cached.
"""

import logging

from app.config import get_settings
from app.services.http import PlaceCandidate, RateLimiter, ServiceError, TTLCache, client

log = logging.getLogger(__name__)

_limiter = RateLimiter(1.05)
_search_cache = TTLCache(max_items=2000, ttl_s=7 * 24 * 3600)
_reverse_cache = TTLCache(max_items=5000, ttl_s=7 * 24 * 3600)

# Street samples from the saved demo trip, so the demo works offline.
_seeded_streets: list[tuple[float, float, str, str]] = []  # lat, lon, lang, name


def seed_streets(samples: list[dict]) -> None:
    for s in samples:
        for lang in ("en", "am"):
            name = s.get(f"name_{lang}") or s.get("name")
            if name:
                _seeded_streets.append((s["lat"], s["lon"], lang, name))


def _area(address: dict) -> str:
    for key in ("neighbourhood", "suburb", "quarter", "city_district", "city", "town"):
        if address.get(key):
            return address[key]
    return ""


async def search(query: str, lang: str = "en", limit: int = 3) -> list[PlaceCandidate]:
    key = (query.strip().lower(), lang, limit)
    cached = _search_cache.get(key)
    if cached is not None:
        return cached
    s = get_settings()
    params = {
        "q": query,
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": limit,
        "countrycodes": s.country_codes,
        "viewbox": s.viewbox,
        "accept-language": f"{lang},en",
    }
    try:
        async with _limiter:
            r = await client().get(f"{s.nominatim_url}/search", params=params)
        r.raise_for_status()
        data = r.json()
    except Exception as e:  # network, HTTP, JSON
        raise ServiceError(f"nominatim search failed: {e}") from e
    results = []
    for item in data:
        name = item.get("name") or item.get("display_name", "").split(",")[0]
        if not name:
            continue
        results.append(
            PlaceCandidate(
                name=name,
                lat=float(item["lat"]),
                lon=float(item["lon"]),
                detail=_area(item.get("address", {})),
                source="nominatim",
            )
        )
    _search_cache.set(key, results)
    return results


async def reverse(lat: float, lon: float, lang: str = "en") -> str | None:
    """Street (or neighbourhood) name at a point."""
    from app.geo import haversine

    for slat, slon, slang, name in _seeded_streets:
        if slang == lang and haversine(lat, lon, slat, slon) < 120:
            return name

    key = (round(lat, 4), round(lon, 4), lang)  # ~11 m grid
    cached = _reverse_cache.get(key)
    if cached is not None:
        return cached or None
    s = get_settings()
    params = {
        "lat": lat,
        "lon": lon,
        "format": "jsonv2",
        "zoom": 17,
        "addressdetails": 1,
        "accept-language": f"{lang},en",
    }
    try:
        async with _limiter:
            r = await client().get(f"{s.nominatim_url}/reverse", params=params)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.warning("nominatim reverse failed: %s", e)
        return None
    addr = data.get("address", {}) if isinstance(data, dict) else {}
    name = addr.get("road") or addr.get("pedestrian") or _area(addr) or ""
    _reverse_cache.set(key, name)
    return name or None
