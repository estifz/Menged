"""Routing: OpenRouteService (free key) with the keyless OSRM server as fallback.

One route request per trip.
"""

import logging
from dataclasses import dataclass

from app.config import get_settings
from app.services.http import ServiceError, client

log = logging.getLogger(__name__)


@dataclass
class RouteResult:
    line: str  # encoded polyline, precision 5
    distance_m: float
    duration_s: float
    provider: str


async def ors_route(start: tuple[float, float], dest: tuple[float, float]) -> RouteResult:
    s = get_settings()
    if not s.ors_api_key:
        raise ServiceError("no ORS key")
    body = {"coordinates": [[start[1], start[0]], [dest[1], dest[0]]]}
    try:
        r = await client().post(
            f"{s.ors_url}/v2/directions/{s.routing_profile}",
            json=body,
            headers={"Authorization": s.ors_api_key, "Accept": "application/json"},
        )
        r.raise_for_status()
        route = r.json()["routes"][0]
    except Exception as e:
        raise ServiceError(f"ORS failed: {e}") from e
    summary = route.get("summary", {})
    return RouteResult(
        line=route["geometry"],
        distance_m=float(summary.get("distance", 0.0)),
        duration_s=float(summary.get("duration", 0.0)),
        provider="ors",
    )


async def osrm_route(start: tuple[float, float], dest: tuple[float, float]) -> RouteResult:
    s = get_settings()
    coords = f"{start[1]},{start[0]};{dest[1]},{dest[0]}"
    try:
        r = await client().get(
            f"{s.osrm_url}/route/v1/driving/{coords}",
            params={"overview": "full", "geometries": "polyline"},
        )
        r.raise_for_status()
        data = r.json()
        if data.get("code") != "Ok":
            raise ServiceError(data.get("message", "no route"))
        route = data["routes"][0]
    except ServiceError:
        raise
    except Exception as e:
        raise ServiceError(f"OSRM failed: {e}") from e
    return RouteResult(route["geometry"], float(route["distance"]), float(route["duration"]), "osrm")


async def get_route(start: tuple[float, float], dest: tuple[float, float]) -> RouteResult:
    errors = []
    for provider in (ors_route, osrm_route):
        try:
            return await provider(start, dest)
        except ServiceError as e:
            log.warning("%s", e)
            errors.append(str(e))
    raise ServiceError("; ".join(errors))
