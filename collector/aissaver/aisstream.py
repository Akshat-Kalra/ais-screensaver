"""aisstream.io WebSocket client and message parsing."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

import aiohttp

from . import regions, tables
from .config import AISSTREAM_URL
from .store import Store

log = logging.getLogger("aisstream")

MESSAGE_TYPES = [
    "PositionReport",
    "StandardClassBPositionReport",
    "ExtendedClassBPositionReport",
    "ShipStaticData",
    "StaticDataReport",
]

_POSITION_TYPES = {"PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport"}


def clean_text(s: object) -> str | None:
    """AIS 6-bit text is padded with '@' and spaces."""
    if not isinstance(s, str):
        return None
    s = s.replace("@", " ").strip()
    s = " ".join(s.split())
    return s or None


def _num(v: object) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def valid_latlon(lat: float | None, lon: float | None) -> bool:
    if lat is None or lon is None:
        return False
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return False  # includes the 91/181 "not available" sentinels
    return not (abs(lat) < 1e-6 and abs(lon) < 1e-6)


def clean_sog(v: object) -> float | None:
    sog = _num(v)
    return None if sog is None or sog < 0 or sog >= 102.25 else round(sog, 1)


def clean_cog(v: object) -> float | None:
    cog = _num(v)
    return None if cog is None or cog < 0 or cog >= 360 else round(cog, 1)


def clean_heading(v: object) -> float | None:
    hdg = _num(v)
    return None if hdg is None or hdg < 0 or hdg >= 360 else hdg  # 511 = not available


def _dims(d: object) -> tuple[float | None, float | None]:
    if not isinstance(d, dict):
        return None, None
    a, b, c, dd = (_num(d.get(k)) or 0 for k in ("A", "B", "C", "D"))
    length = a + b
    beam = c + dd
    return (length or None, beam or None)


def eta_to_unix(eta: object, now: float) -> int | None:
    """AIS ETA has no year: pick the year that puts it nearest to now."""
    if not isinstance(eta, dict):
        return None
    month, day = int(eta.get("Month") or 0), int(eta.get("Day") or 0)
    hour, minute = int(eta.get("Hour") or 0), int(eta.get("Minute") or 0)
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    if hour >= 24:
        hour = 0
    if minute >= 60:
        minute = 0
    year = datetime.fromtimestamp(now, timezone.utc).year
    best: int | None = None
    for y in (year - 1, year, year + 1):
        try:
            t = int(datetime(y, month, day, hour, minute, tzinfo=timezone.utc).timestamp())
        except ValueError:
            continue
        if best is None or abs(t - now) < abs(best - now):
            best = t
    return best


def handle_message(store: Store, msg: dict, now: float | None = None) -> str | None:
    """Apply one aisstream message to the store. Returns the message type if used."""
    now = now if now is not None else time.time()
    mtype = msg.get("MessageType")
    meta = msg.get("MetaData") or {}
    body = (msg.get("Message") or {}).get(mtype)
    if not isinstance(body, dict):
        return None
    mmsi = body.get("UserID") or meta.get("MMSI")
    if not isinstance(mmsi, int) or not tables.is_ship_mmsi(mmsi):
        return None
    if body.get("Valid") is False:
        return None

    if mtype in _POSITION_TYPES:
        lat, lon = _num(body.get("Latitude")), _num(body.get("Longitude"))
        if not valid_latlon(lat, lon):
            return None
        nav = body.get("NavigationalStatus") if mtype == "PositionReport" else None
        store.update_position(
            mmsi, lat, lon,
            clean_sog(body.get("Sog")), clean_cog(body.get("Cog")), clean_heading(body.get("TrueHeading")),
            now, nav_status=nav if isinstance(nav, int) and 0 <= nav <= 15 else None,
        )
        if mtype == "ExtendedClassBPositionReport":
            length, beam = _dims(body.get("Dimension"))
            store.update_static(
                mmsi, name=clean_text(body.get("Name")), ship_type=body.get("Type") or None,
                length=length, beam=beam,
            )
        elif clean_text(meta.get("ShipName")) and not store.vessels[mmsi].name:
            store.update_static(mmsi, name=clean_text(meta.get("ShipName")))
        return mtype

    if mtype == "ShipStaticData":
        length, beam = _dims(body.get("Dimension"))
        draught = _num(body.get("MaximumStaticDraught"))
        imo = body.get("ImoNumber")
        store.update_static(
            mmsi,
            name=clean_text(body.get("Name")),
            callsign=clean_text(body.get("CallSign")),
            imo=imo if isinstance(imo, int) and 1000000 <= imo <= 9999999 else None,
            ship_type=body.get("Type") or None,
            length=length,
            beam=beam,
            draught=draught or None,
            destination=clean_text(body.get("Destination")),
            eta=eta_to_unix(body.get("Eta"), now),
        )
        return mtype

    if mtype == "StaticDataReport":
        a = body.get("ReportA") or {}
        b = body.get("ReportB") or {}
        if a.get("Valid"):
            store.update_static(mmsi, name=clean_text(a.get("Name")))
        if b.get("Valid"):
            length, beam = _dims(b.get("Dimension"))
            store.update_static(
                mmsi, callsign=clean_text(b.get("CallSign")), ship_type=b.get("ShipType") or None,
                length=length, beam=beam,
            )
        return mtype
    return None


class AisStreamClient:
    mode = "live"

    def __init__(self, store: Store, api_key: str):
        self.store = store
        self.api_key = api_key
        self.connected = False
        self.last_message_at: float | None = None
        self.message_count = 0

    def subscription(self) -> dict:
        return {
            "APIKey": self.api_key,
            "BoundingBoxes": [r.box() for r in regions.REGIONS],
            "FilterMessageTypes": MESSAGE_TYPES,
        }

    async def run(self) -> None:
        backoff = 1.0
        timeout = aiohttp.ClientTimeout(total=None, connect=15, sock_read=120)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while True:
                try:
                    async with session.ws_connect(AISSTREAM_URL, heartbeat=30, max_msg_size=0) as ws:
                        await ws.send_str(json.dumps(self.subscription()))
                        log.info("connected to aisstream.io (%d regions)", len(regions.REGIONS))
                        self.connected = True
                        got_data = False
                        async for frame in ws:
                            if frame.type in (aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY):
                                self._on_frame(frame.data)
                                if not got_data:
                                    got_data = True
                                    backoff = 1.0
                            elif frame.type == aiohttp.WSMsgType.ERROR:
                                break
                        log.warning("aisstream closed: code=%s %s", ws.close_code, ws.exception() or "")
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # network errors, DNS, TLS, etc.
                    log.warning("aisstream connection error: %r", e)
                self.connected = False
                log.info("reconnecting in %.0fs", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    def _on_frame(self, data: str | bytes) -> None:
        try:
            msg = json.loads(data)
        except ValueError:
            return
        if "error" in msg:
            log.error("aisstream error: %s", msg["error"])
            return
        self.message_count += 1
        self.last_message_at = time.time()
        try:
            handle_message(self.store, msg, self.last_message_at)
        except Exception:
            log.exception("failed to handle message: %.300s", data)
