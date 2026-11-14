"""Photon: typo-tolerant OpenStreetMap search, used when Nominatim finds nothing."""

from app.config import get_settings
from app.services.http import PlaceCandidate, ServiceError, TTLCache, client

_cache = TTLCache(max_items=1000, ttl_s=7 * 24 * 3600)

# Centre of Addis Ababa, used to bias results.
_BIAS_LAT, _BIAS_LON = 9.0108, 38.7613


async def search(query: str, limit: int = 3) -> list[PlaceCandidate]:
    key = (query.strip().lower(), limit)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    s = get_settings()
    params = {"q": query, "limit": limit * 3, "lat": _BIAS_LAT, "lon": _BIAS_LON}
    try:
        r = await client().get(f"{s.photon_url}/api/", params=params)
        r.raise_for_status()
        features = r.json().get("features", [])
    except Exception as e:
        raise ServiceError(f"photon search failed: {e}") from e
    results = []
    for f in features:
        props = f.get("properties", {})
        if props.get("countrycode", "").lower() not in ("et", ""):
            continue
        lon, lat = f["geometry"]["coordinates"]
        name = props.get("name") or props.get("street")
        if not name:
            continue
        detail = props.get("district") or props.get("locality") or props.get("city") or ""
        results.append(PlaceCandidate(name, float(lat), float(lon), detail, "photon"))
        if len(results) >= limit:
            break
    _cache.set(key, results)
    return results
