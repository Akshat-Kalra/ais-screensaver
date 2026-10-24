"""Offline mock feed: synthetic vessels moving along real shipping lanes.

Every vessel's position is a pure function of time, so the same code back-fills
12 hours of history at startup and then keeps positions advancing live.

- transit lanes: ships enter at one end, travel to the other, then the slot
  respawns as a new ship (new MMSI) after a short gap, like traffic leaving coverage.
- ferry lanes: one ship shuttles back and forth with a dwell at each terminal.
- anchorages: ships swing slowly around an anchor point.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import time
import zlib
from dataclasses import dataclass

from .config import RETENTION_S
from .store import Store, haversine_nm

log = logging.getLogger("mock")

BACKFILL_STEP_S = 90
TICK_S = 5

# (lon, lat) waypoints along real channels.
LANES: dict[str, list[tuple[str, str, list[tuple[float, float]]]]] = {
    "singapore": [
        ("transit", "east", [(103.42, 1.13), (103.62, 1.135), (103.75, 1.165), (103.90, 1.185),
                              (104.05, 1.215), (104.25, 1.255), (104.48, 1.30)]),
        ("transit", "west", [(104.48, 1.335), (104.25, 1.29), (104.05, 1.245), (103.90, 1.21),
                              (103.75, 1.19), (103.62, 1.16), (103.42, 1.155)]),
    ],
    "dover": [
        ("transit", "ne", [(0.85, 50.62), (1.10, 50.75), (1.38, 50.88), (1.62, 51.02), (1.85, 51.15),
                            (1.98, 51.27)]),
        ("transit", "sw", [(1.95, 51.30), (1.72, 51.13), (1.47, 51.02), (1.22, 50.90), (0.95, 50.76),
                            (0.82, 50.66)]),
        ("ferry", "dover-calais", [(1.335, 51.115), (1.42, 51.08), (1.60, 51.02), (1.80, 50.975),
                                    (1.855, 50.968)]),
    ],
    "gibraltar": [
        ("transit", "east", [(-5.98, 35.88), (-5.75, 35.90), (-5.55, 35.925), (-5.40, 35.955),
                              (-5.22, 35.985)]),
        ("transit", "west", [(-5.22, 36.03), (-5.42, 36.00), (-5.60, 35.97), (-5.80, 35.96),
                              (-5.98, 35.97)]),
        ("ferry", "algeciras-tangermed", [(-5.425, 36.12), (-5.40, 36.06), (-5.44, 35.99),
                                           (-5.49, 35.92), (-5.50, 35.895)]),
    ],
    "rotterdam": [
        ("transit", "inbound", [(3.62, 52.02), (3.80, 52.005), (3.95, 51.99), (4.03, 51.985),
                                 (4.06, 51.975)]),
        ("transit", "coastal", [(3.75, 51.88), (3.92, 51.95), (4.05, 52.03), (4.18, 52.09)]),
    ],
    "panama": [
        ("transit", "southbound", [(-79.92, 9.45), (-79.915, 9.37), (-79.92, 9.29), (-79.88, 9.22),
                                    (-79.82, 9.18), (-79.76, 9.14), (-79.71, 9.12), (-79.68, 9.09),
                                    (-79.655, 9.05), (-79.625, 9.02), (-79.595, 8.995), (-79.575, 8.96),
                                    (-79.555, 8.935), (-79.53, 8.89), (-79.52, 8.84)]),
        ("transit", "northbound", [(-79.51, 8.83), (-79.525, 8.885), (-79.55, 8.93), (-79.572, 8.958),
                                    (-79.592, 8.993), (-79.622, 9.018), (-79.652, 9.048),
                                    (-79.676, 9.088), (-79.706, 9.118), (-79.758, 9.138),
                                    (-79.818, 9.178), (-79.878, 9.218), (-79.917, 9.29),
                                    (-79.91, 9.37), (-79.905, 9.46)]),
    ],
    "bosphorus": [
        ("transit", "northbound", [(28.99, 40.97), (29.005, 41.02), (29.033, 41.05), (29.054, 41.077),
                                    (29.06, 41.092), (29.062, 41.12), (29.07, 41.15), (29.08, 41.18),
                                    (29.11, 41.22), (29.13, 41.25)]),
        ("transit", "southbound", [(29.135, 41.245), (29.115, 41.215), (29.085, 41.178),
                                    (29.074, 41.148), (29.066, 41.118), (29.064, 41.09),
                                    (29.058, 41.075), (29.038, 41.048), (29.01, 41.018),
                                    (28.995, 40.965)]),
        ("ferry", "eminonu-kadikoy", [(28.976, 41.018), (28.99, 41.008), (29.01, 40.995),
                                       (29.022, 40.993)]),
    ],
    "salish": [
        ("transit", "georgia-south", [(-123.58, 49.36), (-123.42, 49.22), (-123.30, 49.06),
                                       (-123.20, 48.93)]),
        ("transit", "burrard-inbound", [(-123.42, 49.24), (-123.28, 49.28), (-123.19, 49.305),
                                         (-123.145, 49.317), (-123.11, 49.306), (-123.05, 49.297)]),
        ("ferry", "horseshoe-nanaimo", [(-123.274, 49.373), (-123.29, 49.35), (-123.33, 49.32),
                                         (-123.46, 49.28), (-123.59, 49.235)]),
        ("ferry", "tsawwassen-swartz", [(-123.135, 49.005), (-123.22, 48.96), (-123.32, 48.91)]),
    ],
    "hongkong": [
        ("transit", "harbour-east", [(114.10, 22.296), (114.135, 22.293), (114.165, 22.292),
                                      (114.20, 22.297), (114.235, 22.286), (114.27, 22.27)]),
        ("transit", "urmston", [(113.82, 22.38), (113.90, 22.356), (113.98, 22.345), (114.04, 22.348)]),
        ("transit", "south", [(114.34, 22.19), (114.20, 22.17), (114.05, 22.175), (113.90, 22.19),
                               (113.82, 22.21)]),
    ],
    "suez": [
        ("transit", "southbound", [(32.36, 31.38), (32.315, 31.27), (32.31, 31.05), (32.32, 30.85),
                                    (32.30, 30.65), (32.30, 30.57), (32.34, 30.45), (32.40, 30.33),
                                    (32.47, 30.22), (32.55, 30.10), (32.56, 29.96), (32.55, 29.85)]),
        ("transit", "northbound", [(32.545, 29.86), (32.555, 29.97), (32.545, 30.10), (32.465, 30.22),
                                    (32.395, 30.33), (32.335, 30.45), (32.295, 30.57),
                                    (32.295, 30.65), (32.315, 30.85), (32.305, 31.05),
                                    (32.31, 31.27), (32.35, 31.39)]),
    ],
    "sanpedro": [
        ("transit", "la-approach", [(-118.39, 33.62), (-118.32, 33.66), (-118.27, 33.69),
                                     (-118.25, 33.706)]),
        ("transit", "lb-approach", [(-118.11, 33.62), (-118.14, 33.66), (-118.17, 33.70),
                                     (-118.185, 33.72)]),
    ],
    "tokyo": [
        ("transit", "uraga-north", [(139.74, 35.21), (139.755, 35.25), (139.77, 35.29), (139.785, 35.36),
                                     (139.82, 35.46), (139.85, 35.54), (139.83, 35.60)]),
        ("transit", "uraga-south", [(139.81, 35.595), (139.835, 35.535), (139.805, 35.455),
                                     (139.775, 35.36), (139.762, 35.29), (139.748, 35.25),
                                     (139.735, 35.21)]),
        ("transit", "yokohama", [(139.75, 35.22), (139.77, 35.30), (139.775, 35.38), (139.70, 35.43),
                                  (139.66, 35.445)]),
    ],
}

ANCHORAGES: dict[str, list[tuple[float, float]]] = {
    "singapore": [(103.88, 1.235), (104.10, 1.27), (103.70, 1.21)],
    "dover": [(1.42, 51.20)],
    "gibraltar": [(-5.33, 36.10), (-5.38, 36.08)],
    "rotterdam": [(3.75, 51.96), (3.85, 52.05)],
    "panama": [(-79.88, 9.42), (-79.50, 8.87)],
    "bosphorus": [(28.97, 40.98)],
    "salish": [(-123.20, 49.28), (-123.17, 49.27)],
    "hongkong": [(114.05, 22.25)],
    "suez": [(32.38, 31.36), (32.55, 29.88)],
    "sanpedro": [(-118.22, 33.67), (-118.18, 33.66)],
    "tokyo": [(139.78, 35.50)],
}

# Typical traffic mix per region: category -> weight.
MIX = {
    "default": {"cargo": 5, "tanker": 3, "passenger": 1, "tug": 1, "fishing": 1, "special": 0.5},
    "salish": {"cargo": 3, "tanker": 1.5, "tug": 2, "sailing": 1.5, "pleasure": 1.5, "fishing": 1},
    "gibraltar": {"cargo": 4, "tanker": 3, "sailing": 1, "fishing": 1, "military": 0.5},
    "bosphorus": {"cargo": 4, "tanker": 3, "passenger": 1, "fishing": 1},
    "hongkong": {"cargo": 5, "highspeed": 1.5, "passenger": 1, "tug": 1, "fishing": 1},
    "rotterdam": {"cargo": 4, "tanker": 3, "tug": 1.5, "special": 1},
    "panama": {"cargo": 5, "tanker": 3, "passenger": 0.5},
    "suez": {"cargo": 5, "tanker": 3, "military": 0.3},
    "dover": {"cargo": 5, "tanker": 3, "sailing": 0.5, "fishing": 1, "military": 0.3},
}

SHIP_TYPE = {
    "cargo": [70, 70, 70, 71, 79], "tanker": [80, 80, 81, 82, 89], "passenger": [60, 69],
    "tug": [52, 52, 31], "fishing": [30], "sailing": [36], "pleasure": [37], "highspeed": [40],
    "military": [35], "special": [50, 33, 51, 55],
}

SPEED_KN = {
    "cargo": (11, 19), "tanker": (9, 14), "passenger": (14, 21), "tug": (6, 10), "fishing": (4, 8),
    "sailing": (4, 7.5), "pleasure": (7, 16), "highspeed": (24, 32), "military": (10, 18),
    "special": (6, 12),
}

DIMS = {  # (length range, beam ratio, draught range)
    "cargo": ((140, 400), 0.15, (8, 16)), "tanker": ((120, 330), 0.18, (8, 21)),
    "passenger": ((80, 200), 0.17, (4, 8)), "tug": ((25, 40), 0.33, (3, 6)),
    "fishing": ((15, 60), 0.28, (3, 6)), "sailing": ((9, 20), 0.3, (1.5, 3)),
    "pleasure": ((10, 40), 0.25, (1, 3)), "highspeed": ((30, 50), 0.28, (1.5, 2.5)),
    "military": ((80, 180), 0.13, (4, 7)), "special": ((20, 60), 0.3, (2, 5)),
}

FLAG_MIDS = [
    351, 352, 353, 354, 355, 356, 357, 370, 371, 372, 636, 636, 636, 538, 538, 538, 215, 229, 248,
    256, 477, 477, 563, 563, 564, 565, 566, 311, 308, 209, 212, 240, 241, 244, 245, 218, 211,
    219, 257, 259, 232, 235, 271, 273, 412, 413, 414, 431, 440, 441, 533, 525, 548, 574, 316,
    366, 367, 338, 226, 247, 224, 265, 230, 255, 341, 375, 620, 572, 470,
]
REGION_MIDS = {  # local flags show up more often for small craft
    "salish": [316, 316, 316, 367, 338], "dover": [232, 235, 226, 227], "gibraltar": [224, 225, 236, 242],
    "rotterdam": [244, 245, 246], "panama": [351, 352, 370], "bosphorus": [271, 271, 271],
    "hongkong": [477, 477, 413], "suez": [622, 622], "sanpedro": [366, 367, 338], "tokyo": [431, 432],
    "singapore": [563, 564, 533, 525],
}

PREFIX = {
    "cargo": ["MAERSK", "MSC", "CMA CGM", "EVER", "ONE", "HMM", "COSCO", "YM", "OOCL", "HAPAG",
              "ZIM", "WAN HAI", "NORDIC", "SEASPAN", "STAR", "GOLDEN", "PACIFIC", "ATLANTIC"],
    "tanker": ["FRONT", "BW", "STENA", "NAVIG8", "TORM", "SEAWAYS", "MINERVA", "NORDIC", "OCEAN",
               "DHT", "ARDMORE", "EAGLE", "MARAN", "GULF"],
    "passenger": ["SPIRIT OF", "PRIDE OF", "QUEEN OF", "COASTAL", "ISLAND", "STAR"],
    "tug": ["SVITZER", "SMIT", "KOTUG", "SEASPAN", "BOLUDA", "FAIRPLAY", "TITAN"],
    "fishing": ["ATLANTIC", "NORTHERN", "SEA", "OCEAN", "BLUE", "LUCKY"],
    "sailing": ["", "", "SV"],
    "pleasure": ["", "", "MY"],
    "highspeed": ["COTAI WATER JET", "TURBOJET", "FIRST FERRY"],
    "military": ["HMS", "USS", "HNLMS", "ESPS", "TCG", "HMCS"],
    "special": ["PILOT", "SAR", "DREDGER", "PATROL"],
}
WORDS = ["AURORA", "HORIZON", "MERIDIAN", "ALBATROSS", "KESTREL", "CORMORANT", "ORION", "VEGA",
         "POLARIS", "CASSIOPEIA", "SERENITY", "TRADER", "NAVIGATOR", "VOYAGER", "PIONEER",
         "ENDEAVOUR", "RESOLUTE", "TENACITY", "HARMONY", "LIBERTY", "SPIRIT", "FORTUNE",
         "KENSINGTON", "AMSTERDAM", "HAMBURG", "SHANGHAI", "VALENCIA", "GENOA", "BUSAN", "TOKYO",
         "SANTOS", "DURBAN", "LISBON", "OSLO", "ANNA", "SOPHIA", "MARINA", "ISABELLA", "LUNA",
         "CORAL", "PEARL", "JADE", "AMBER", "SAPPHIRE", "TIDE", "BREEZE", "WAVE", "DAWN", "ATLAS",
         "TITAN", "HERCULES", "NEPTUNE", "TRITON", "POSEIDON", "SELENE", "HELIOS", "ZEPHYR"]

DESTINATIONS = {
    "singapore": ["SG SIN", "SGSIN", "MY PKG", "CN SHA", "NL RTM", "AE JEA", "IN NSA", "HK HKG"],
    "dover": ["NL RTM", "BE ANR", "DE HAM", "GB LGP", "FR LEH", "US NYC", "ES ALG", "GB FXT"],
    "gibraltar": ["ES ALG", "MA TNG", "IT GOA", "GR PIR", "NL RTM", "EG PSD", "TR IST", "GI GIB"],
    "rotterdam": ["NL RTM", "GB FXT", "DE HAM", "NO OSL", "SE GOT", "BE ANR"],
    "panama": ["PA BLB", "PA CTB", "US LAX", "CN SHA", "CL VAP", "US HOU", "JP YOK", "PE CLL"],
    "bosphorus": ["RU NVS", "UA ODS", "TR IST", "RO CND", "GE BUS", "EG ALY", "GR PIR"],
    "salish": ["CA VAN", "CA NAN", "CA VIC", "US SEA", "CN SHA", "JP TYO", "KR PUS", "CA PRR"],
    "hongkong": ["HK HKG", "CN SZX", "MO MFM", "SG SIN", "TW KHH", "CN SHA"],
    "suez": ["EG SUZ", "EG PSD", "SA JED", "SG SIN", "NL RTM", "IN BOM", "OM SLL"],
    "sanpedro": ["US LAX", "US LGB", "CN SHA", "JP TYO", "KR PUS", "MX ZLO"],
    "tokyo": ["JP TYO", "JP YOK", "JP CHB", "CN SHA", "KR PUS", "US LAX", "TW KEL"],
}


@dataclass
class Path:
    pts: list[tuple[float, float]]
    cum: list[float]  # cumulative distance in nm

    @classmethod
    def of(cls, pts: list[tuple[float, float]]) -> "Path":
        cum = [0.0]
        for (lo1, la1), (lo2, la2) in zip(pts, pts[1:]):
            cum.append(cum[-1] + haversine_nm(la1, lo1, la2, lo2))
        return cls(pts, cum)

    @property
    def length(self) -> float:
        return self.cum[-1]

    def at(self, s: float) -> tuple[float, float, float]:
        """(lon, lat, bearing) at distance s nm along the path."""
        s = max(0.0, min(s, self.length))
        i = 1
        while i < len(self.cum) - 1 and self.cum[i] < s:
            i += 1
        (lo1, la1), (lo2, la2) = self.pts[i - 1], self.pts[i]
        seg = self.cum[i] - self.cum[i - 1] or 1e-9
        f = (s - self.cum[i - 1]) / seg
        return lo1 + (lo2 - lo1) * f, la1 + (la2 - la1) * f, bearing(la1, lo1, la2, lo2)


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _offset(lon: float, lat: float, brg: float, metres: float) -> tuple[float, float]:
    """Shift a point perpendicular (to starboard) of bearing `brg`."""
    perp = math.radians(brg + 90)
    dlat = metres * math.cos(perp) / 111_320
    dlon = metres * math.sin(perp) / (111_320 * math.cos(math.radians(lat)))
    return lon + dlon, lat + dlat


def _rng(*key: object) -> random.Random:
    return random.Random(zlib.crc32(":".join(map(str, key)).encode()))


@dataclass
class Identity:
    mmsi: int
    name: str
    callsign: str
    imo: int | None
    ship_type: int
    category: str
    length: float
    beam: float
    draught: float
    destination: str
    eta: int
    speed: float


def make_identity(region: str, key: str, now: float, category: str | None = None) -> Identity:
    r = _rng(region, key)
    mix = MIX.get(region, MIX["default"])
    rolled = r.choices(list(mix), weights=list(mix.values()))[0]
    category = category or rolled
    mids = REGION_MIDS.get(region, []) if category in ("tug", "fishing", "sailing", "pleasure", "special",
                                                        "military", "passenger") else []
    mid = r.choice(mids or FLAG_MIDS)
    mmsi = mid * 1_000_000 + r.randrange(0, 1_000_000)
    prefix = r.choice(PREFIX[category])
    word = r.choice(WORDS)
    if category in ("sailing", "pleasure"):
        name = f"{prefix} {word}".strip()
    elif category == "highspeed":
        name = f"{prefix} {r.randint(1, 30)}"
    elif category == "cargo" and prefix == "EVER":
        name = f"EVER {word}"
    else:
        name = f"{prefix} {word}"
    (lmin, lmax), beam_ratio, (dmin, dmax) = DIMS[category]
    length = round(r.uniform(lmin, lmax))
    smin, smax = SPEED_KN[category]
    big = category in ("cargo", "tanker", "passenger")
    return Identity(
        mmsi=mmsi,
        name=name.upper(),
        callsign="".join(r.choice("ABCDEFGHJKLMNPRSTUVWXYZ") for _ in range(2)) + str(r.randint(10, 9999)),
        imo=r.randint(9_100_000, 9_990_000) if big or r.random() < 0.3 else None,
        ship_type=r.choice(SHIP_TYPE[category]),
        category=category,
        length=length,
        beam=round(length * beam_ratio * r.uniform(0.85, 1.1)),
        draught=round(r.uniform(dmin, dmax), 1),
        destination=r.choice(DESTINATIONS[region]),
        eta=int(now // 3600 * 3600 + r.randint(4, 96) * 3600),
        speed=round(r.uniform(smin, smax), 1),
    )


class Slot:
    """One traffic slot; subclasses compute state at time t."""

    region: str

    def state(self, t: float) -> tuple[Identity, float, float, float, float, int] | None:
        raise NotImplementedError

    def start_time(self, t: float) -> float:
        """When the identity active at t first appeared."""
        raise NotImplementedError


class TransitSlot(Slot):
    def __init__(self, region: str, key: str, path: Path, epoch: float):
        self.region, self.key, self.path = region, key, path
        r = _rng(region, key, "slot")
        self.phase = r.uniform(0, 1)
        self.lateral = r.uniform(-350, 350)
        self.gap_s = r.uniform(5, 40) * 60
        self.epoch = epoch
        self._ids: dict[int, Identity] = {}

    def _identity(self, gen: int) -> Identity:
        if gen not in self._ids:
            self._ids[gen] = make_identity(self.region, f"{self.key}:{gen}", self.epoch)
        return self._ids[gen]

    def _period(self, gen: int) -> float:
        return self.path.length / self._identity(gen).speed * 3600 + self.gap_s

    def _gen_at(self, t: float) -> tuple[int, float]:
        # Walk generations from the epoch; periods differ per generation (speed varies).
        base = self.epoch - RETENTION_S * 2 - self.phase * self._period(0)
        gen, start = 0, base
        while start + self._period(gen) <= t:
            start += self._period(gen)
            gen += 1
        return gen, start

    def start_time(self, t: float) -> float:
        return self._gen_at(t)[1]

    def state(self, t: float):
        gen, start = self._gen_at(t)
        ident = self._identity(gen)
        s = (t - start) / 3600 * ident.speed
        if s > self.path.length:
            return None  # in the gap between ships
        lon, lat, brg = self.path.at(s)
        wobble = 120 * math.sin((t - start) / 1700 + self.phase * 6)
        lon, lat = _offset(lon, lat, brg, self.lateral + wobble)
        sog = ident.speed + 0.4 * math.sin(t / 900 + self.phase * 10)
        nav = 8 if ident.category == "sailing" else 7 if ident.category == "fishing" else 0
        return ident, lon, lat, round(sog, 1), brg, nav


class FerrySlot(Slot):
    DWELL_S = 15 * 60

    def __init__(self, region: str, key: str, path: Path, epoch: float):
        self.region, self.path = region, path
        self.ident = make_identity(region, key, epoch, category="passenger")
        self.ident.ship_type = 60
        self.leg_s = path.length / self.ident.speed * 3600
        self.cycle = 2 * (self.leg_s + self.DWELL_S)
        self.offset = _rng(region, key, "ferry").uniform(0, self.cycle)
        self.epoch = epoch

    def start_time(self, t: float) -> float:
        return t - RETENTION_S  # ferries have always been here

    def state(self, t: float):
        p = (t + self.offset) % self.cycle
        if p < self.DWELL_S:
            lon, lat, brg = self.path.at(0)
            return self.ident, lon, lat, 0.0, (brg + 180) % 360, 5
        p -= self.DWELL_S
        if p < self.leg_s:
            lon, lat, brg = self.path.at(p / self.leg_s * self.path.length)
            lon, lat = _offset(lon, lat, brg, 60)
            return self.ident, lon, lat, self.ident.speed, brg, 0
        p -= self.leg_s
        if p < self.DWELL_S:
            lon, lat, brg = self.path.at(self.path.length)
            return self.ident, lon, lat, 0.0, brg, 5
        p -= self.DWELL_S
        lon, lat, brg = self.path.at((1 - p / self.leg_s) * self.path.length)
        brg = (brg + 180) % 360
        lon, lat = _offset(lon, lat, brg, 60)
        return self.ident, lon, lat, self.ident.speed, brg, 0


class AnchorSlot(Slot):
    def __init__(self, region: str, key: str, point: tuple[float, float], epoch: float):
        self.region, self.point = region, point
        cat = _rng(region, key, "cat").choice(["cargo", "tanker"])
        self.ident = make_identity(region, key, epoch, category=cat)
        r = _rng(region, key, "anchor")
        self.jitter = (r.uniform(-0.01, 0.01), r.uniform(-0.008, 0.008))
        self.phase = r.uniform(0, 6.28)

    def start_time(self, t: float) -> float:
        return t - RETENTION_S

    def state(self, t: float):
        a = t / 7200 + self.phase  # swing around the anchor over ~12h
        lon = self.point[0] + self.jitter[0] + 0.0012 * math.cos(a)
        lat = self.point[1] + self.jitter[1] + 0.0009 * math.sin(a)
        return self.ident, lon, lat, 0.1, (math.degrees(a) + 90) % 360, 1


class MockFeed:
    mode = "mock"

    def __init__(self, store: Store, ships_per_lane: int = 5):
        self.store = store
        self.connected = True
        self.last_message_at: float | None = None
        self.message_count = 0
        self._seen_static: set[int] = set()
        epoch = time.time()
        self.slots: list[Slot] = []
        for region, lanes in LANES.items():
            for kind, name, pts in lanes:
                path = Path.of(pts)
                if kind == "ferry":
                    self.slots.append(FerrySlot(region, name, path, epoch))
                else:
                    for i in range(ships_per_lane):
                        self.slots.append(TransitSlot(region, f"{name}{i}", path, epoch))
            for i, pt in enumerate(ANCHORAGES.get(region, [])):
                self.slots.append(AnchorSlot(region, f"anchor{i}", pt, epoch))

    def _emit(self, slot: Slot, t: float) -> None:
        st = slot.state(t)
        if st is None:
            return
        ident, lon, lat, sog, cog, nav = st
        if ident.mmsi not in self._seen_static:
            self._seen_static.add(ident.mmsi)
            self.store.update_static(
                ident.mmsi, name=ident.name, callsign=ident.callsign, imo=ident.imo,
                ship_type=ident.ship_type, length=ident.length, beam=ident.beam,
                draught=ident.draught, destination=ident.destination, eta=ident.eta,
            )
        heading = round((cog + math.sin(t / 300) * 2) % 360)
        self.store.update_position(ident.mmsi, lat, lon, sog, round(cog, 1), heading, t, nav_status=nav)
        self.message_count += 1
        self.last_message_at = time.time()

    def backfill(self) -> None:
        now = time.time()
        for slot in self.slots:
            t = max(now - RETENTION_S, slot.start_time(now))
            while t < now:
                self._emit(slot, t)
                t += BACKFILL_STEP_S
        self.store.flush()
        log.info("mock: %d slots, %d vessels, %d track points", len(self.slots),
                 len(self.store.vessels), self.store.positions_count)

    async def run(self) -> None:
        self.backfill()
        while True:
            now = time.time()
            for slot in self.slots:
                self._emit(slot, now)
            await asyncio.sleep(TICK_S)
