"""Overpass: landmarks and food places along a route, fetched once per trip."""

import logging
from dataclasses import dataclass

from app.config import get_settings
from app.services.http import ServiceError, TTLCache, client

log = logging.getLogger(__name__)

FOOD = {"restaurant", "cafe", "fast_food"}

# Overpass filters for things worth announcing or suggesting.
_FILTERS = [
    '["amenity"~"^(restaurant|cafe|fast_food|place_of_worship|bus_station|hospital|university|marketplace|theatre|cinema)$"]',
    '["tourism"~"^(attraction|museum|hotel|monument|viewpoint)$"]',
    '["historic"]',
    '["shop"="mall"]',
    '["leisure"~"^(park|stadium)$"]',
    '["place"="square"]',
    '["railway"="station"]',
]

# Free public Overpass servers, tried in order.
MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

_nearby_cache = TTLCache(max_items=500, ttl_s=6 * 3600)


@dataclass
class OsmPlace:
    osm_id: str
    name: str
    name_am: str | None
    name_en: str | None
    kind: str
    lat: float
    lon: float


def _kind(tags: dict) -> str:
    amenity = tags.get("amenity")
    if amenity in FOOD:
        return amenity
    return "landmark"


def _parse(elements: list[dict]) -> list[OsmPlace]:
    seen: set[str] = set()
    out: list[OsmPlace] = []
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue
        if "lat" in el:
            lat, lon = el["lat"], el["lon"]
        elif "center" in el:
            lat, lon = el["center"]["lat"], el["center"]["lon"]
        else:
            continue
        osm_id = f"{el['type'][0]}{el['id']}"
        if osm_id in seen:
            continue
        seen.add(osm_id)
        out.append(
            OsmPlace(osm_id, name, tags.get("name:am"), tags.get("name:en"), _kind(tags), float(lat), float(lon))
        )
    return out


def _servers() -> list[str]:
    primary = get_settings().overpass_url
    return [primary] + [m for m in MIRRORS if m != primary]


async def _run(query: str) -> list[OsmPlace]:
    """Try the main public server, then a mirror (public servers often 502/429)."""
    errors = []
    for url in _servers():
        try:
            r = await client().post(url, data={"data": query}, timeout=70.0)
            r.raise_for_status()
            data = r.json()
            # Overpass reports timeouts and overload as a "remark" with HTTP 200.
            remark = data.get("remark", "")
            if "error" in remark.lower():
                raise ServiceError(remark[:200])
            return _parse(data.get("elements", []))
        except Exception as e:
            log.warning("overpass %s failed: %s", url, e)
            errors.append(f"{url}: {e}")
    raise ServiceError("overpass failed: " + " | ".join(errors))


async def places_along(points: list[tuple[float, float]], radius_m: int) -> list[OsmPlace]:
    """One query per trip: a bounding box around the route (cheap for Overpass),
    then keep only places within `radius_m` of the route line."""
    from app.geo import Route

    pad = radius_m / 111_000 * 1.2
    south = min(p[0] for p in points) - pad
    north = max(p[0] for p in points) + pad
    west = min(p[1] for p in points) - pad
    east = max(p[1] for p in points) + pad
    bbox = f"{south:.5f},{west:.5f},{north:.5f},{east:.5f}"
    parts = "".join(f"nwr{f}[\"name\"]({bbox});" for f in _FILTERS)
    query = f"[out:json][timeout:60];({parts});out center tags;"
    places = await _run(query)
    route = Route(points)
    return [p for p in places if route.project(p.lat, p.lon).offset_m <= radius_m]


async def food_near(lat: float, lon: float, radius_m: int = 500) -> list[OsmPlace]:
    """Restaurants and cafés around one point (used outside a trip)."""
    key = (round(lat, 3), round(lon, 3), radius_m)  # ~100 m grid
    cached = _nearby_cache.get(key)
    if cached is not None:
        return cached
    query = (
        f'[out:json][timeout:20];nwr(around:{radius_m},{lat:.5f},{lon:.5f})'
        f'["amenity"~"^(restaurant|cafe|fast_food)$"]["name"];out center tags 60;'
    )
    places = await _run(query)
    _nearby_cache.set(key, places)
    return places
