"""Record the demo trip (app/demo/demo_trip.json) from the real map services.

    .venv/bin/python -m scripts.record_demo "Merkato" "Bole Medhanialem"

Saves the route, the places along it and street names (English and Amharic)
every ~250 m, so /simulate and the demo fallback work with no internet.
"""

import asyncio
import json
import sys
from dataclasses import asdict

from app.config import get_settings
from app.demo.data import DEMO_FILE
from app.engine.trips import search_destination
from app.geo import Route
from app.services import nominatim, overpass, routing
from app.services.http import close_client


async def pick(query: str):
    results = await search_destination(query, "en", limit=1)
    if not results:
        raise SystemExit(f"could not find {query!r}")
    print(f"  {query!r} -> {results[0].name} ({results[0].lat:.5f}, {results[0].lon:.5f}) via {results[0].source}")
    return results[0]


async def main(start_q: str, dest_q: str) -> None:
    print("Geocoding…")
    start, dest = await pick(start_q), await pick(dest_q)
    print("Routing…")
    r = await routing.get_route((start.lat, start.lon), (dest.lat, dest.lon))
    print(f"  {r.distance_m / 1000:.1f} km, {r.duration_s / 60:.0f} min via {r.provider}")
    route = Route.from_polyline(r.line)

    print("Places along the route…")
    places = await overpass.places_along(route.simplified(), get_settings().route_corridor_m)
    print(f"  {len(places)} places ({sum(p.kind != 'landmark' for p in places)} food)")

    print("Street names (1 request per second)…")
    streets = []
    along = 0.0
    while along <= route.length_m:
        lat, lon = route.point_at(along)
        en = await nominatim.reverse(lat, lon, "en")
        am = await nominatim.reverse(lat, lon, "am")
        if en or am:
            streets.append({"lat": round(lat, 6), "lon": round(lon, 6), "name_en": en, "name_am": am or en})
        along += 250
    print(f"  {len(streets)} street samples")

    data = {
        "start": {"name": start.name, "lat": start.lat, "lon": start.lon},
        "dest": {"name": dest.name, "lat": dest.lat, "lon": dest.lon},
        "route": {"line": r.line, "distance_m": r.distance_m, "duration_s": r.duration_s, "provider": r.provider},
        "places": [asdict(p) for p in places],
        "streets": streets,
    }
    DEMO_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Saved {DEMO_FILE}")
    await close_client()


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "Merkato"
    b = sys.argv[2] if len(sys.argv) > 2 else "Bole Medhanialem"
    asyncio.run(main(a, b))
