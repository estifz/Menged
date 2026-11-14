"""Geometry helpers: distances, route projection and GPS smoothing.

Distances use a local equirectangular projection, which is accurate to well
under 1 % at city scale and far cheaper than geodesic maths per point.
"""

import math
from dataclasses import dataclass, field

import polyline as polyline_codec

EARTH_R = 6_371_000.0


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def encode(points: list[tuple[float, float]]) -> str:
    return polyline_codec.encode(points, 5)


def decode(line: str) -> list[tuple[float, float]]:
    return [(float(a), float(b)) for a, b in polyline_codec.decode(line, 5)]


@dataclass
class Projection:
    along_m: float  # distance from the route start to the projected point
    offset_m: float  # distance from the point to the route
    lat: float
    lon: float


@dataclass
class Route:
    """A decoded route line with cumulative lengths for fast projection."""

    points: list[tuple[float, float]]
    cum: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.points:
            raise ValueError("empty route")
        self._lat0 = math.radians(self.points[0][0])
        self._xy = [self._to_xy(lat, lon) for lat, lon in self.points]
        self.cum = [0.0]
        for (x1, y1), (x2, y2) in zip(self._xy, self._xy[1:]):
            self.cum.append(self.cum[-1] + math.hypot(x2 - x1, y2 - y1))

    @classmethod
    def from_polyline(cls, line: str) -> "Route":
        return cls(decode(line))

    @property
    def length_m(self) -> float:
        return self.cum[-1]

    def _to_xy(self, lat: float, lon: float) -> tuple[float, float]:
        return (
            math.radians(lon) * math.cos(self._lat0) * EARTH_R,
            math.radians(lat) * EARTH_R,
        )

    def _from_xy(self, x: float, y: float) -> tuple[float, float]:
        return math.degrees(y / EARTH_R), math.degrees(x / (math.cos(self._lat0) * EARTH_R))

    def project(self, lat: float, lon: float, min_along: float | None = None) -> Projection:
        """Nearest point on the route.

        `min_along` lets the caller prefer segments at or after the previous
        progress, so a route that loops back near itself doesn't make the
        traveller jump backwards.
        """
        px, py = self._to_xy(lat, lon)
        if len(self._xy) == 1:
            x, y = self._xy[0]
            return Projection(0.0, math.hypot(px - x, py - y), *self.points[0])

        best: tuple[float, float, float, float] | None = None  # (score, along, offset, t-seg)
        best_xy = self._xy[0]
        for i in range(len(self._xy) - 1):
            (x1, y1), (x2, y2) = self._xy[i], self._xy[i + 1]
            dx, dy = x2 - x1, y2 - y1
            seg2 = dx * dx + dy * dy
            t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / seg2))
            qx, qy = x1 + t * dx, y1 + t * dy
            offset = math.hypot(px - qx, py - qy)
            along = self.cum[i] + t * math.sqrt(seg2)
            score = offset
            if min_along is not None and along < min_along - 50:
                score += 200  # penalise going backwards along the route
            if best is None or score < best[0]:
                best = (score, along, offset, t)
                best_xy = (qx, qy)
        assert best is not None
        qlat, qlon = self._from_xy(*best_xy)
        return Projection(best[1], best[2], qlat, qlon)

    def point_at(self, along_m: float) -> tuple[float, float]:
        """Point at a given distance along the route (used by the simulator)."""
        along_m = max(0.0, min(self.length_m, along_m))
        for i in range(len(self.cum) - 1):
            if self.cum[i + 1] >= along_m:
                seg = self.cum[i + 1] - self.cum[i]
                t = 0.0 if seg == 0 else (along_m - self.cum[i]) / seg
                (lat1, lon1), (lat2, lon2) = self.points[i], self.points[i + 1]
                return lat1 + t * (lat2 - lat1), lon1 + t * (lon2 - lon1)
        return self.points[-1]

    def simplified(self, max_points: int = 80) -> list[tuple[float, float]]:
        """Evenly spaced subset of points (for the Overpass corridor query)."""
        if len(self.points) <= max_points:
            return list(self.points)
        step = self.length_m / (max_points - 1)
        return [self.point_at(i * step) for i in range(max_points)]


PROCESS_NOISE_MPS = 3.0  # how fast we let the estimate move, in m/s


def kalman_step(
    prev_lat: float | None,
    prev_lon: float | None,
    prev_var: float | None,
    dt_s: float,
    lat: float,
    lon: float,
    accuracy_m: float | None,
    speed_mps: float | None = None,
) -> tuple[float, float, float]:
    """One step of a simple position Kalman filter.

    Returns the smoothed (lat, lon) and the new variance in m². Accurate
    points move the estimate almost all the way; noisy points move it less.
    """
    acc = max(accuracy_m or 15.0, 3.0)
    meas_var = acc * acc
    if prev_lat is None or prev_lon is None or prev_var is None:
        return lat, lon, meas_var
    # Expected movement since the last point: a moving bus must not lag behind,
    # while a stationary user's jitter gets averaged out.
    move = max(dt_s, 0.0) * max(PROCESS_NOISE_MPS, speed_mps or 0.0)
    var = prev_var + move * move
    k = var / (var + meas_var)
    new_lat = prev_lat + k * (lat - prev_lat)
    new_lon = prev_lon + k * (lon - prev_lon)
    return new_lat, new_lon, (1 - k) * var
