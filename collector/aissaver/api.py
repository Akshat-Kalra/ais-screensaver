"""HTTP API + static file server for the web UI."""

from __future__ import annotations

import asyncio
import random
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import logging

from aiohttp import web

from . import regions, system, tables
from .config import FRESH_S, RETENTION_S, WEB_DIR
from .store import STATIONARY_SOG, Store, Vessel, haversine_nm

log = logging.getLogger("api")

# (min points, min hours) from best to most lenient. Live AIS has no history, so right after
# the collector starts only short tracks exist: use the best tier that has enough ships.
TRACK_TIERS = [(15, 1.5), (6, 0.33), (2, 0.0)]
MIN_TIER_POOL = 3
STATS_CACHE_S = 60
STILL_SHARE = 0.1


class Feed(Protocol):
    mode: str
    connected: bool
    last_message_at: float | None
    message_count: int


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Api:
    def __init__(self, store: Store, feed: Feed, web_dir: Path = WEB_DIR):
        self.store = store
        self.feed = feed
        self.web_dir = web_dir
        self._stats: dict[int, tuple[int, int, int]] = {}
        self._stats_at = 0.0
        self._stats_lock = asyncio.Lock()
        self._rate_samples: deque[tuple[float, int]] = deque(maxlen=12)

    # --- background helpers ---------------------------------------------------

    def sample_rate(self) -> None:
        self._rate_samples.append((time.time(), self.feed.message_count))

    def msgs_per_min(self) -> int:
        if len(self._rate_samples) < 2:
            return 0
        (t0, c0), (t1, c1) = self._rate_samples[0], self._rate_samples[-1]
        return round((c1 - c0) / max(t1 - t0, 1) * 60)

    async def _track_stats(self) -> dict[int, tuple[int, int, int]]:
        async with self._stats_lock:
            if time.time() - self._stats_at > STATS_CACHE_S:
                self._stats = await asyncio.to_thread(self.store.track_stats, time.time() - RETENTION_S)
                self._stats_at = time.time()
            return self._stats

    # --- serialisation --------------------------------------------------------

    async def vessel_json(self, v: Vessel) -> dict:
        now = time.time()
        rows = await asyncio.to_thread(self.store.track, v.mmsi, now - RETENTION_S)
        track = [[round(lon, 5), round(lat, 5), ts] for lon, lat, ts, _ in rows]
        if v.ts is not None and v.lat is not None and (not track or v.ts > track[-1][2] + 5):
            track.append([round(v.lon, 5), round(v.lat, 5), int(v.ts)])

        dist = 0.0
        for (lon1, lat1, _), (lon2, lat2, _) in zip(track, track[1:]):
            dist += haversine_nm(lat1, lon1, lat2, lon2)
        sogs = [s for *_, s in rows if s is not None]
        hours = (track[-1][2] - track[0][2]) / 3600 if len(track) > 1 else 0.0

        label, category = tables.ship_type_info(v.ship_type)
        region = regions.BY_ID.get(v.region or "")
        return {
            "mmsi": v.mmsi,
            "name": v.name,
            "callsign": v.callsign,
            "imo": v.imo,
            "ship_type": v.ship_type,
            "ship_type_label": label,
            "category": category,
            "flag": tables.flag_for(v.mmsi),
            "length_m": v.length,
            "beam_m": v.beam,
            "draught_m": v.draught,
            "destination": v.destination,
            "eta": _iso(v.eta),
            "nav_status": tables.nav_status_label(v.nav_status),
            "region": region.as_json() if region else None,
            "last": {
                "lat": v.lat, "lon": v.lon, "sog": v.sog, "cog": v.cog,
                "heading": v.heading, "ts": int(v.ts) if v.ts else None,
            },
            "track": track,
            "stats": {
                "distance_nm": round(dist, 1),
                "track_hours": round(hours, 2),
                "max_sog": max(sogs) if sogs else None,
                "avg_sog": round(sum(sogs) / len(sogs), 1) if sogs else None,
            },
        }

    # --- handlers ---------------------------------------------------------------

    async def health(self, request: web.Request) -> web.Response:
        now = time.time()
        live = sum(1 for v in self.store.vessels.values() if v.ts and now - v.ts < FRESH_S)
        return web.json_response({
            "ok": True,
            "mode": self.feed.mode,
            "connected": self.feed.connected,
            "vessels": live,
            "positions": self.store.positions_count,
            "last_message_at": _iso(self.feed.last_message_at),
            "msgs_per_min": self.msgs_per_min(),
            "battery": await system.battery(),
        })

    async def pick(self, request: web.Request) -> web.Response:
        exclude_list = [int(x) for x in request.query.get("exclude", "").split(",") if x.strip().isdigit()]
        only_region = request.query.get("region") or None
        exclude = set(exclude_list)
        recent_cats = {
            tables.ship_type_info(self.store.vessels[m].ship_type)[1]
            for m in exclude_list[:4] if m in self.store.vessels
        }
        stats = await self._track_stats()
        now = time.time()

        tiers = [(defaultdict(list), defaultdict(list)) for _ in TRACK_TIERS]  # (moving, still)
        for v in self.store.vessels.values():
            if not v.name or not v.region or v.ts is None or now - v.ts > FRESH_S or v.mmsi in exclude:
                continue
            if only_region and v.region != only_region:
                continue
            st = stats.get(v.mmsi)
            if not st:
                continue
            n, first, last = st
            span_h = (max(last, v.ts) - first) / 3600
            tier = next((i for i, (pts, hrs) in enumerate(TRACK_TIERS) if n >= pts and span_h >= hrs), None)
            if tier is None:
                continue
            sog = v.sog or 0
            w = 1 + min(span_h, 12) / 6
            if sog > 3:
                w *= 3
            if tables.ship_type_info(v.ship_type)[1] in recent_cats:
                w *= 0.35
            moving_t, still_t = tiers[tier]
            (still_t if sog < STATIONARY_SOG else moving_t)[v.region].append((v, w))

        def size(groups: dict) -> int:
            return sum(len(g) for g in groups.values())

        moving, still = next(
            (t for t in tiers if size(t[0]) + size(t[1]) >= MIN_TIER_POOL),
            next((t for t in tiers if size(t[0]) + size(t[1])), tiers[0]),
        )
        # Ships at anchor make dull cards: show one only now and then, or when nothing moves.
        by_region = still if still and (not moving or random.random() < STILL_SHARE) else moving
        if not by_region:
            return web.json_response({"error": "no_candidates"}, status=404)
        pool = by_region[random.choice(list(by_region))]
        vessel = random.choices([v for v, _ in pool], weights=[w for _, w in pool])[0]
        return web.json_response(await self.vessel_json(vessel))

    async def vessel(self, request: web.Request) -> web.Response:
        try:
            mmsi = int(request.match_info["mmsi"])
        except ValueError:
            raise web.HTTPBadRequest(text="bad mmsi")
        v = self.store.vessels.get(mmsi)
        if v is None or v.lat is None:
            return web.json_response({"error": "not_found"}, status=404)
        return web.json_response(await self.vessel_json(v))

    async def search(self, request: web.Request) -> web.Response:
        """Find vessels by name substring or MMSI prefix; live ones first."""
        q = request.query.get("q", "").strip().upper()
        if len(q) < 2:
            return web.json_response([])
        now = time.time()
        hits = []
        for v in self.store.vessels.values():
            if v.lat is None or v.ts is None:
                continue
            name = (v.name or "").upper()
            if q.isdigit() and str(v.mmsi).startswith(q):
                rank = 0
            elif name.startswith(q):
                rank = 1
            elif q in name:
                rank = 2
            else:
                continue
            live = now - v.ts < FRESH_S
            hits.append((not live, rank, name, v))
        hits.sort(key=lambda h: h[:3])
        return web.json_response([
            {
                "mmsi": v.mmsi, "name": v.name, "category": tables.ship_type_info(v.ship_type)[1],
                "region": regions.BY_ID[v.region].name if v.region in regions.BY_ID else None,
                "sog": v.sog, "live": not stale,
            }
            for stale, _, _, v in hits[:8]
        ])

    async def tracks(self, request: web.Request) -> web.Response:
        """All of a region's tracks at once, for the poster view."""
        region = regions.BY_ID.get(request.query.get("region", ""))
        if region is None:
            raise web.HTTPBadRequest(text="unknown region")
        rows = await asyncio.to_thread(self.store.tracks_in, region.id, time.time() - RETENTION_S)
        out = []
        for mmsi, points in rows.items():
            v = self.store.vessels.get(mmsi)
            # Split at reception gaps so a ship that went quiet isn't joined by a straight line.
            segments, seg = [], []
            for lon, lat, ts, _ in points:
                if seg and ts - seg[-1][2] > 30 * 60:
                    segments.append(seg)
                    seg = []
                seg.append((lon, lat, ts))
            segments.append(seg)
            out.append({
                "mmsi": mmsi,
                "category": tables.ship_type_info(v.ship_type if v else None)[1],
                "segments": [[[round(lon, 5), round(lat, 5)] for lon, lat, _ in s] for s in segments if len(s) > 1],
                "last": [round(points[-1][0], 5), round(points[-1][1], 5)],
            })
        return web.json_response({
            "region": region.as_json(),
            "bbox": [region.lon_min, region.lat_min, region.lon_max, region.lat_max],
            "tracks": out,
        })

    async def regions(self, request: web.Request) -> web.Response:
        return web.json_response([r.as_json() for r in regions.REGIONS])

    async def nearby(self, request: web.Request) -> web.Response:
        try:
            lat = float(request.query["lat"])
            lon = float(request.query["lon"])
            radius_km = min(float(request.query.get("radius_km", 25)), 300)
        except (KeyError, ValueError):
            raise web.HTTPBadRequest(text="lat, lon required")
        exclude = request.query.get("exclude", "")
        now = time.time()
        found = []
        for v in self.store.vessels.values():
            if v.lat is None or v.ts is None or now - v.ts > FRESH_S or str(v.mmsi) == exclude:
                continue
            d_km = haversine_nm(lat, lon, v.lat, v.lon) * 1.852
            if d_km <= radius_km:
                found.append((d_km, v))
        found.sort(key=lambda t: t[0])
        return web.json_response([
            {
                "mmsi": v.mmsi, "lat": v.lat, "lon": v.lon, "cog": v.cog, "heading": v.heading,
                "sog": v.sog, "category": tables.ship_type_info(v.ship_type)[1], "name": v.name,
            }
            for _, v in found[:300]
        ])

    async def client_log(self, request: web.Request) -> web.Response:
        """Diagnostics from the web UI (the screensaver has no visible console)."""
        text = (await request.text())[:2000]
        log.info("client: %s", text)
        return web.json_response({"ok": True})

    async def static(self, request: web.Request) -> web.StreamResponse:
        rel = request.match_info.get("tail", "").lstrip("/")
        path = (self.web_dir / rel).resolve()
        if not path.is_relative_to(self.web_dir):
            raise web.HTTPNotFound()
        if path.is_dir():
            path = path / "index.html"
        if not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={"Cache-Control": "no-cache"})

    # --- app ----------------------------------------------------------------------

    def app(self) -> web.Application:
        @web.middleware
        async def cors(request: web.Request, handler):
            resp = await handler(request)
            resp.headers["Access-Control-Allow-Origin"] = "*"
            if request.path.startswith("/api/"):
                resp.headers["Cache-Control"] = "no-store"
            return resp

        app = web.Application(middlewares=[cors])
        app.router.add_get("/api/health", self.health)
        app.router.add_get("/api/pick", self.pick)
        app.router.add_get("/api/vessel/{mmsi}", self.vessel)
        app.router.add_get("/api/nearby", self.nearby)
        app.router.add_get("/api/search", self.search)
        app.router.add_get("/api/regions", self.regions)
        app.router.add_get("/api/tracks", self.tracks)
        app.router.add_post("/api/log", self.client_log)
        app.router.add_get("/{tail:.*}", self.static)
        return app
