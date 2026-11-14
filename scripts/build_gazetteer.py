"""Build the offline Addis Ababa place list (app/data/addis_places.json).

Run once (and again whenever you want fresher data):
    .venv/bin/python -m scripts.build_gazetteer

One Overpass query for named places in the Addis bounding box.
"""

import asyncio
import json

from app.config import get_settings
from app.services.gazetteer import DATA_FILE
from app.services.overpass import MIRRORS
from app.services.http import client, close_client

BBOX = "8.83,38.65,9.10,38.92"  # south, west, north, east

QUERY = f"""
[out:json][timeout:120];
(
  nwr["name"]["amenity"~"^(place_of_worship|hospital|clinic|university|college|bus_station|marketplace|restaurant|cafe|fast_food|bank|theatre|cinema|townhall|embassy|school|police|fuel)$"]({BBOX});
  nwr["name"]["tourism"~"^(attraction|museum|hotel|monument|viewpoint|guest_house)$"]({BBOX});
  nwr["name"]["shop"~"^(mall|supermarket|department_store)$"]({BBOX});
  nwr["name"]["leisure"~"^(park|stadium)$"]({BBOX});
  nwr["name"]["place"~"^(square|neighbourhood|suburb|quarter)$"]({BBOX});
  nwr["name"]["highway"="pedestrian"]["area"="yes"]({BBOX});
  nwr["name"]["historic"]({BBOX});
  nwr["name"]["railway"="station"]({BBOX});
  nwr["name"]["public_transport"="station"]({BBOX});
  nwr["name"]["office"="government"]({BBOX});
);
out center tags;
"""


def kind_of(tags: dict) -> str:
    for key in ("amenity", "tourism", "shop", "leisure", "place"):
        if key in tags:
            return tags[key]
    if "historic" in tags:
        return "historic"
    if tags.get("railway") == "station" or tags.get("public_transport") == "station":
        return "station"
    if tags.get("highway") == "pedestrian":
        return "square"
    if tags.get("office") == "government":
        return "government"
    return "landmark"


async def main() -> None:
    elements = None
    for url in [get_settings().overpass_url] + MIRRORS:
        try:
            r = await client().post(url, data={"data": QUERY}, timeout=180.0)
            r.raise_for_status()
            elements = r.json()["elements"]
            break
        except Exception as e:
            print(f"{url} failed: {e}")
    if elements is None:
        raise SystemExit("all Overpass servers failed; try again later")
    places = []
    seen = set()
    for el in elements:
        tags = el.get("tags", {})
        if "lat" in el:
            lat, lon = el["lat"], el["lon"]
        elif "center" in el:
            lat, lon = el["center"]["lat"], el["center"]["lon"]
        else:
            continue
        key = (tags["name"], round(lat, 3), round(lon, 3))
        if key in seen:
            continue
        seen.add(key)
        place = {"name": tags["name"], "lat": round(lat, 6), "lon": round(lon, 6), "kind": kind_of(tags)}
        if tags.get("name:am"):
            place["name_am"] = tags["name:am"]
        if tags.get("name:en"):
            place["name_en"] = tags["name:en"]
        places.append(place)
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(places, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(places)} places to {DATA_FILE}")
    await close_client()


if __name__ == "__main__":
    asyncio.run(main())
