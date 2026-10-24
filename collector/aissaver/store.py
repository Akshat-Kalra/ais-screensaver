"""Vessel state: latest positions in memory, downsampled tracks in SQLite.

Writes happen on the event loop thread in small batches (see `flush`). Read-heavy
queries run in worker threads via `asyncio.to_thread`, each with its own connection;
WAL mode lets them run concurrently with the writer.
"""

from __future__ import annotations

import math
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import regions
from .config import RETENTION_S

# Downsampling rules for stored track points.
MIN_INTERVAL_S = 90
STATIONARY_INTERVAL_S = 600
STATIONARY_SOG = 0.5
COG_CHANGE_DEG = 15
SOG_CHANGE_KN = 3

# Implied speeds above this between consecutive points are treated as GPS glitches.
MAX_PLAUSIBLE_KN = 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS vessels (
    mmsi INTEGER PRIMARY KEY,
    name TEXT, callsign TEXT, imo INTEGER, ship_type INTEGER,
    length REAL, beam REAL, draught REAL, destination TEXT, eta INTEGER,
    nav_status INTEGER,
    lat REAL, lon REAL, sog REAL, cog REAL, heading REAL, ts REAL,
    region TEXT
);
CREATE TABLE IF NOT EXISTS positions (
    mmsi INTEGER NOT NULL, ts INTEGER NOT NULL,
    lat REAL NOT NULL, lon REAL NOT NULL, sog REAL, cog REAL
);
CREATE INDEX IF NOT EXISTS positions_mmsi_ts ON positions (mmsi, ts);
CREATE INDEX IF NOT EXISTS positions_ts ON positions (ts);
"""

_VESSEL_COLS = (
    "mmsi", "name", "callsign", "imo", "ship_type", "length", "beam", "draught",
    "destination", "eta", "nav_status", "lat", "lon", "sog", "cog", "heading", "ts", "region",
)


@dataclass
class Vessel:
    mmsi: int
    name: str | None = None
    callsign: str | None = None
    imo: int | None = None
    ship_type: int | None = None
    length: float | None = None
    beam: float | None = None
    draught: float | None = None
    destination: str | None = None
    eta: int | None = None
    nav_status: int | None = None
    lat: float | None = None
    lon: float | None = None
    sog: float | None = None
    cog: float | None = None
    heading: float | None = None
    ts: float | None = None
    region: str | None = None
    # Downsampling state (not persisted as columns).
    stored_ts: float = field(default=0.0, repr=False)
    stored_sog: float | None = field(default=None, repr=False)
    stored_cog: float | None = field(default=None, repr=False)

    def row(self) -> tuple:
        return tuple(getattr(self, c) for c in _VESSEL_COLS)


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r_nm = 3440.065
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r_nm * math.asin(min(1.0, math.sqrt(a)))


def angle_diff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def _connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


class Store:
    def __init__(self, path: Path | str):
        self.path = path
        self.db = _connect(path)
        self.db.executescript(SCHEMA)
        self.vessels: dict[int, Vessel] = {}
        self._pending_positions: list[tuple] = []
        self._dirty: set[int] = set()
        self._local = threading.local()
        self.positions_count = 0
        self._load()

    # --- persistence -------------------------------------------------------------

    def _load(self) -> None:
        cutoff = time.time() - RETENTION_S
        cur = self.db.execute(
            f"SELECT {', '.join(_VESSEL_COLS)} FROM vessels WHERE ts IS NULL OR ts > ?", (cutoff,)
        )
        for row in cur:
            v = Vessel(**dict(zip(_VESSEL_COLS, row)))
            self.vessels[v.mmsi] = v
        # Resume downsampling from each vessel's last stored point.
        for mmsi, ts, sog, cog in self.db.execute(
            "SELECT mmsi, MAX(ts), sog, cog FROM positions GROUP BY mmsi"
        ):
            v = self.vessels.get(mmsi)
            if v:
                v.stored_ts, v.stored_sog, v.stored_cog = ts, sog, cog
        self.positions_count = self.db.execute("SELECT COUNT(*) FROM positions").fetchone()[0]

    def _reader(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = _connect(self.path)
            self._local.conn = conn
        return conn

    def flush(self) -> None:
        if not self._pending_positions and not self._dirty:
            return
        rows = [self.vessels[m].row() for m in self._dirty if m in self.vessels]
        with self.db:
            if self._pending_positions:
                self.db.executemany(
                    "INSERT INTO positions (mmsi, ts, lat, lon, sog, cog) VALUES (?, ?, ?, ?, ?, ?)",
                    self._pending_positions,
                )
            if rows:
                self.db.executemany(
                    f"INSERT OR REPLACE INTO vessels ({', '.join(_VESSEL_COLS)}) "
                    f"VALUES ({', '.join('?' * len(_VESSEL_COLS))})",
                    rows,
                )
        self.positions_count += len(self._pending_positions)
        self._pending_positions.clear()
        self._dirty.clear()

    def prune(self, now: float | None = None) -> int:
        cutoff = (now or time.time()) - RETENTION_S
        with self.db:
            n = self.db.execute("DELETE FROM positions WHERE ts < ?", (cutoff,)).rowcount
            self.db.execute("DELETE FROM vessels WHERE ts < ?", (cutoff,))
        for mmsi in [m for m, v in self.vessels.items() if v.ts is not None and v.ts < cutoff]:
            del self.vessels[mmsi]
        self.positions_count = max(0, self.positions_count - n)
        return n

    def close(self) -> None:
        self.flush()
        self.db.close()

    # --- ingest ------------------------------------------------------------------

    def _vessel(self, mmsi: int) -> Vessel:
        v = self.vessels.get(mmsi)
        if v is None:
            v = self.vessels[mmsi] = Vessel(mmsi)
        return v

    def update_position(
        self,
        mmsi: int,
        lat: float,
        lon: float,
        sog: float | None,
        cog: float | None,
        heading: float | None,
        ts: float,
        nav_status: int | None = None,
    ) -> bool:
        """Record a position report. Returns True if a track point was stored."""
        v = self._vessel(mmsi)
        if v.ts is not None and ts < v.ts:
            return False  # out-of-order report
        v.lat, v.lon, v.sog, v.cog, v.heading, v.ts = lat, lon, sog, cog, heading, ts
        if nav_status is not None:
            v.nav_status = nav_status
        region = regions.region_for(lat, lon)
        if region:
            v.region = region.id
        self._dirty.add(mmsi)

        if not self._should_store(v, ts):
            return False
        v.stored_ts, v.stored_sog, v.stored_cog = ts, sog, cog
        self._pending_positions.append((mmsi, int(ts), lat, lon, sog, cog))
        return True

    @staticmethod
    def _should_store(v: Vessel, ts: float) -> bool:
        elapsed = ts - v.stored_ts
        stationary = v.sog is not None and v.sog < STATIONARY_SOG
        if stationary:
            return elapsed >= STATIONARY_INTERVAL_S
        if elapsed >= MIN_INTERVAL_S:
            return True
        if elapsed < 10:
            return False  # never store points closer than 10s apart
        if v.cog is not None and v.stored_cog is not None and angle_diff(v.cog, v.stored_cog) > COG_CHANGE_DEG:
            return True
        if v.sog is not None and v.stored_sog is not None and abs(v.sog - v.stored_sog) > SOG_CHANGE_KN:
            return True
        return False

    def update_static(self, mmsi: int, **fields) -> None:
        v = self._vessel(mmsi)
        changed = False
        for k, val in fields.items():
            if val is None or val == "":
                continue
            if getattr(v, k) != val:
                setattr(v, k, val)
                changed = True
        if changed:
            self._dirty.add(mmsi)

    # --- queries (safe to call from worker threads) ------------------------------

    def track_stats(self, since: float) -> dict[int, tuple[int, int, int]]:
        """mmsi -> (count, first_ts, last_ts) for points newer than `since`."""
        cur = self._reader().execute(
            "SELECT mmsi, COUNT(*), MIN(ts), MAX(ts) FROM positions WHERE ts > ? GROUP BY mmsi",
            (int(since),),
        )
        return {m: (n, a, b) for m, n, a, b in cur}

    def track(self, mmsi: int, since: float) -> list[tuple[float, float, int, float | None]]:
        """[(lon, lat, ts, sog)] oldest -> newest, with GPS glitches removed."""
        cur = self._reader().execute(
            "SELECT lon, lat, ts, sog FROM positions WHERE mmsi = ? AND ts > ? ORDER BY ts",
            (mmsi, int(since)),
        )
        out: list[tuple[float, float, int, float | None]] = []
        for lon, lat, ts, sog in cur:
            if out:
                plon, plat, pts, _ = out[-1]
                dt_h = max(ts - pts, 1) / 3600
                if haversine_nm(plat, plon, lat, lon) / dt_h > MAX_PLAUSIBLE_KN:
                    continue
            out.append((lon, lat, ts, sog))
        return out
