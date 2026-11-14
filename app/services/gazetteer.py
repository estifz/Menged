"""Offline list of named places in Addis Ababa with fuzzy search.

Built once by `scripts/build_gazetteer.py` from OpenStreetMap. Searching it is
instant, works without internet, tolerates typos (rapidfuzz) and folds Amharic
spelling variants (app.text.amharic).
"""

import json
import logging
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz, process

from app.services.http import PlaceCandidate
from app.text.amharic import normalize

log = logging.getLogger(__name__)

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "addis_places.json"
MIN_SCORE = 70.0  # below this, a match is not shown
STRONG_SCORE = 88.0  # at or above this, we skip the online geocoders

KIND_LABELS = {
    "en": {
        "place_of_worship": "Church / mosque",
        "restaurant": "Restaurant",
        "cafe": "Café",
        "fast_food": "Fast food",
        "hotel": "Hotel",
        "mall": "Mall",
        "hospital": "Hospital",
        "university": "University",
        "bus_station": "Bus station",
        "square": "Square",
        "park": "Park",
        "stadium": "Stadium",
        "neighbourhood": "Area",
        "suburb": "Area",
        "museum": "Museum",
        "marketplace": "Market",
    },
    "am": {
        "place_of_worship": "ቤተ እምነት",
        "restaurant": "ምግብ ቤት",
        "cafe": "ካፌ",
        "fast_food": "ፈጣን ምግብ",
        "hotel": "ሆቴል",
        "mall": "የገበያ ማዕከል",
        "hospital": "ሆስፒታል",
        "university": "ዩኒቨርሲቲ",
        "bus_station": "አውቶቡስ ጣቢያ",
        "square": "አደባባይ",
        "park": "መናፈሻ",
        "stadium": "ስታዲየም",
        "neighbourhood": "ሰፈር",
        "suburb": "ሰፈር",
        "museum": "ሙዚየም",
        "marketplace": "ገበያ",
    },
}


@lru_cache
def _load() -> tuple[list[dict], list[str], list[int]]:
    """Returns (places, normalised search keys, key -> place index)."""
    if not DATA_FILE.exists():
        log.info("gazetteer file not found at %s; offline search disabled", DATA_FILE)
        return [], [], []
    places = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    keys: list[str] = []
    owners: list[int] = []
    for i, p in enumerate(places):
        for field in ("name", "name_am", "name_en"):
            if p.get(field):
                keys.append(normalize(p[field]))
                owners.append(i)
    return places, keys, owners


def display_name(place: dict, lang: str) -> str:
    return place.get(f"name_{lang}") or place["name"]


def nearest(lat: float, lon: float, max_m: float = 300, exclude_kinds: tuple[str, ...] = ()) -> tuple[dict, float] | None:
    """Closest named place to a point (used for "Where am I?" outside a trip)."""
    from app.geo import haversine

    places, _, _ = _load()
    best: tuple[dict, float] | None = None
    # Cheap bounding-box prefilter (~0.005° ≈ 550 m) before exact distance.
    for p in places:
        if abs(p["lat"] - lat) > 0.005 or abs(p["lon"] - lon) > 0.005:
            continue
        if p.get("kind") in exclude_kinds:
            continue
        d = haversine(lat, lon, p["lat"], p["lon"])
        if d <= max_m and (best is None or d < best[1]):
            best = (p, d)
    return best


LANDMARK_KINDS = {
    "place_of_worship", "square", "mall", "hospital", "university", "college", "station", "bus_station",
    "stadium", "neighbourhood", "suburb", "quarter", "historic", "attraction", "museum", "monument",
    "hotel", "park", "government", "marketplace", "townhall", "embassy", "cinema", "theatre",
}
MINOR_KINDS = {"bank", "fuel", "police", "school", "clinic", "guest_house"}
FOOD_KINDS = {"restaurant", "cafe", "fast_food"}
# Areas are stored as one point in the middle, so "passing" them is meaningless.
AREA_KINDS = {"neighbourhood", "suburb", "quarter"}


def _to_osm_place(i: int, p: dict):
    from app.services.overpass import OsmPlace

    kind = p.get("kind", "")
    return OsmPlace(
        osm_id=f"g{i}",
        name=p["name"],
        name_am=p.get("name_am"),
        name_en=p.get("name_en"),
        kind=kind if kind in FOOD_KINDS else "landmark",
        lat=p["lat"],
        lon=p["lon"],
    )


def along_route(points: list[tuple[float, float]], radius_m: float) -> list:
    """Landmarks and food places within `radius_m` of a route, from the offline
    list. Instant and independent of the public Overpass servers."""
    from app.geo import Route

    places, _, _ = _load()
    if not places or not points:
        return []
    pad = radius_m / 111_000 * 1.2
    south, north = min(p[0] for p in points) - pad, max(p[0] for p in points) + pad
    west, east = min(p[1] for p in points) - pad, max(p[1] for p in points) + pad
    route = Route(points)
    out = []
    for i, p in enumerate(places):
        kind = p.get("kind", "")
        if kind not in FOOD_KINDS and (kind not in LANDMARK_KINDS or kind in AREA_KINDS):
            continue
        if not (south <= p["lat"] <= north and west <= p["lon"] <= east):
            continue
        if route.project(p["lat"], p["lon"]).offset_m <= radius_m:
            out.append(_to_osm_place(i, p))
    return out


def food_near(lat: float, lon: float, radius_m: float = 500) -> list:
    """Restaurants and cafés around a point, from the offline list."""
    from app.geo import haversine

    places, _, _ = _load()
    box = radius_m / 111_000 * 1.2
    return [
        _to_osm_place(i, p)
        for i, p in enumerate(places)
        if p.get("kind") in FOOD_KINDS
        and abs(p["lat"] - lat) <= box
        and abs(p["lon"] - lon) <= box
        and haversine(lat, lon, p["lat"], p["lon"]) <= radius_m
    ]


def _token_coverage(a: list[str], b: list[str]) -> float:
    """Share of tokens in `a` that fuzzy-match some token in `b`."""
    if not a:
        return 0.0
    hits = sum(1 for t in a if any(fuzz.ratio(t, u) >= 80 for u in b))
    return hits / len(a)


def _rescore(q: str, key: str, wratio: float, kind: str) -> float:
    """0-100. Rewards matching *all* typed words, not just a short fragment,
    and prefers landmarks over banks and offices."""
    qt, kt = q.split(), key.split()
    coverage = 0.7 * _token_coverage(qt, kt) + 0.3 * _token_coverage(kt, qt)
    score = 60 * coverage + 0.4 * wratio
    if kind in LANDMARK_KINDS:
        score += 5
    elif kind in MINOR_KINDS:
        score -= 8
    return score


def search(query: str, lang: str = "en", limit: int = 3) -> list[PlaceCandidate]:
    places, keys, owners = _load()
    q = normalize(query)
    if not q or not keys:
        return []
    matches = process.extract(q, keys, scorer=fuzz.WRatio, limit=80, score_cutoff=70)
    best: dict[int, float] = {}
    for key, wratio, idx in matches:
        pi = owners[idx]
        score = _rescore(q, key, wratio, places[pi].get("kind", ""))
        if score > best.get(pi, 0):
            best[pi] = score
    out: list[PlaceCandidate] = []
    seen_names: set[str] = set()
    for pi, score in sorted(best.items(), key=lambda kv: -kv[1]):
        if score < MIN_SCORE:
            break
        p = places[pi]
        name = display_name(p, lang)
        if name.lower() in seen_names:  # chains with many branches: keep the best one
            continue
        seen_names.add(name.lower())
        label = KIND_LABELS.get(lang, KIND_LABELS["en"]).get(p.get("kind", ""), "")
        out.append(PlaceCandidate(name, p["lat"], p["lon"], label, "gazetteer", round(score, 1)))
        if len(out) >= limit:
            break
    return out
