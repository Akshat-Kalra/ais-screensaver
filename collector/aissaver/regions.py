"""The curated waterways we subscribe to."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Region:
    id: str
    name: str
    lat_min: float
    lon_min: float
    lat_max: float
    lon_max: float
    tz: str  # IANA zone, so the UI can show local time

    def contains(self, lat: float, lon: float) -> bool:
        return self.lat_min <= lat <= self.lat_max and self.lon_min <= lon <= self.lon_max

    def box(self) -> list[list[float]]:
        """aisstream.io bounding box format: [[lat1, lon1], [lat2, lon2]]."""
        return [[self.lat_min, self.lon_min], [self.lat_max, self.lon_max]]

    def as_json(self) -> dict:
        return {"id": self.id, "name": self.name, "tz": self.tz}


REGIONS: list[Region] = [
    Region("singapore", "Singapore Strait", 1.0, 103.4, 1.5, 104.5, "Asia/Singapore"),
    Region("dover", "Strait of Dover", 50.6, 0.8, 51.3, 2.0, "Europe/London"),
    Region("gibraltar", "Strait of Gibraltar", 35.8, -6.0, 36.2, -5.2, "Europe/Madrid"),
    Region("rotterdam", "Rotterdam Approaches", 51.85, 3.6, 52.1, 4.4, "Europe/Amsterdam"),
    Region("panama", "Panama Canal", 8.8, -80.0, 9.5, -79.4, "America/Panama"),
    Region("bosphorus", "Bosphorus", 40.95, 28.9, 41.25, 29.15, "Europe/Istanbul"),
    Region("salish", "Salish Sea", 48.9, -123.6, 49.4, -122.8, "America/Vancouver"),
    Region("hongkong", "Hong Kong", 22.15, 113.8, 22.45, 114.35, "Asia/Hong_Kong"),
    Region("suez", "Suez Canal", 29.8, 32.2, 31.4, 32.7, "Africa/Cairo"),
    Region("sanpedro", "San Pedro Bay", 33.6, -118.4, 33.8, -118.1, "America/Los_Angeles"),
    Region("tokyo", "Tokyo Bay", 35.2, 139.6, 35.7, 140.1, "Asia/Tokyo"),
]

BY_ID = {r.id: r for r in REGIONS}


def region_for(lat: float, lon: float) -> Region | None:
    for r in REGIONS:
        if r.contains(lat, lon):
            return r
    return None
