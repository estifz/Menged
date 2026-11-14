"""The saved demo trip: route, places and street names, recorded once by
`scripts/record_demo.py`. Used by /simulate and as a fallback when the public
map services are slow or down during the demo."""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.geo import haversine

DEMO_FILE = Path(__file__).resolve().parent / "demo_trip.json"


@dataclass
class DemoTrip:
    raw: dict

    @property
    def start(self) -> dict:
        return self.raw["start"]

    @property
    def dest(self) -> dict:
        return self.raw["dest"]

    @property
    def route(self) -> dict:
        return self.raw["route"]

    @property
    def places(self) -> list[dict]:
        return self.raw.get("places", [])

    @property
    def streets(self) -> list[dict]:
        return self.raw.get("streets", [])

    def matches(self, start: tuple[float, float] | None, dest: tuple[float, float]) -> bool:
        """True if a trip is (roughly) the demo trip."""
        if haversine(dest[0], dest[1], self.dest["lat"], self.dest["lon"]) > 250:
            return False
        if start is None:
            return True
        return haversine(start[0], start[1], self.start["lat"], self.start["lon"]) < 1500


@lru_cache
def load_demo() -> DemoTrip | None:
    if not DEMO_FILE.exists():
        return None
    return DemoTrip(json.loads(DEMO_FILE.read_text(encoding="utf-8")))
