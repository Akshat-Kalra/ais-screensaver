# AIS E-Ink Screensaver — Spec

A macOS screensaver that, when the Mac is idle, shows a minimal **e-ink-style** vessel tracker:
a map on the left showing one ship's recent trajectory, and a "Top Trumps"-style card on the right
with its details. Every ~45s it "full-refreshes" (like an e-ink panel) to a new random vessel.

## Architecture

```
aisstream.io (WebSocket, free API key)
        │  curated bounding boxes only
        ▼
collector/  (Python, uv, runs 24/7 as a launchd LaunchAgent)
  - keeps ~12h of downsampled positions + static ship data in SQLite
  - serves HTTP on 127.0.0.1:47823: JSON API + the static web/ app
        │
        ▼
web/  (HTML/CSS/JS, MapLibre GL, e-ink design)  ← loaded from http://127.0.0.1:47823/
        ▲
saver/  (Swift ScreenSaverView bundle, AISSaver.saver, hosts a WKWebView)
```

Why localhost HTTP: modern macOS runs screensavers inside the sandboxed `legacyScreenSaver`
process, which can't read arbitrary files in ~/Library, but can make network connections.
Bonus: the web UI can be developed in a normal browser at http://127.0.0.1:47823/.

## Layout

```
ais-screensaver/
  SPEC.md
  README.md
  collector/        pyproject.toml, src or flat modules, uv-managed
  web/              index.html, style.css, app.js, vendor/, assets/
  saver/            AISSaverView.swift, Info.plist, build.sh
  scripts/          install-agent.sh, uninstall-agent.sh, (collector launchd plist template)
```

## Config

- API key: `AISSTREAM_API_KEY` env var, or file `~/.config/ais-screensaver/env` containing
  `AISSTREAM_API_KEY=...`.
- Data dir: `~/Library/Application Support/ais-screensaver/` (SQLite `ais.sqlite`, logs).
- Port: `47823`, bind `127.0.0.1` only.
- `--mock` flag: no network; synthesize ~150 realistic vessels across the regions with 12h of
  back-filled tracks so the whole stack can be developed/tested without an API key.

## Regions (aisstream bounding boxes: `[[lat_min, lon_min], [lat_max, lon_max]]`)

| id | name | box |
|---|---|---|
| singapore | Singapore Strait | [[1.0, 103.4], [1.5, 104.5]] |
| dover | Strait of Dover | [[50.6, 0.8], [51.3, 2.0]] |
| gibraltar | Strait of Gibraltar | [[35.8, -6.0], [36.2, -5.2]] |
| rotterdam | Rotterdam Approaches | [[51.85, 3.6], [52.1, 4.4]] |
| panama | Panama Canal | [[8.8, -80.0], [9.5, -79.4]] |
| bosphorus | Bosphorus | [[40.95, 28.9], [41.25, 29.15]] |
| salish | Salish Sea | [[48.9, -123.6], [49.4, -122.8]] |
| hongkong | Hong Kong | [[22.15, 113.8], [22.45, 114.35]] |
| suez | Suez Canal | [[29.8, 32.2], [31.4, 32.7]] |
| sanpedro | San Pedro Bay | [[33.6, -118.4], [33.8, -118.1]] |
| tokyo | Tokyo Bay | [[35.2, 139.6], [35.7, 140.1]] |

## HTTP API (collector → web). All JSON. CORS `*` is fine (localhost only).

### `GET /api/health`
```json
{"ok": true, "mode": "live|mock", "connected": true, "vessels": 1834, "positions": 412003,
 "last_message_at": "2026-10-23T18:02:11Z", "msgs_per_min": 2400}
```

### `GET /api/pick?exclude=MMSI,MMSI,...`
Returns one "featured" vessel (same shape as `/api/vessel/{mmsi}`), or `404 {"error":"no_candidates"}`.
Selection: pick a region uniformly among regions that have candidates, then a weighted-random
vessel in it. Candidate = has a name, last position < 15 min old, track spans ≥ 1.5 h with ≥ 15
points. Weight up moving vessels (sog > 3 kn ×3), longer tracks, and categories not shown recently
(the `exclude` list is the recently-shown MMSIs; never return those).

### `GET /api/vessel/{mmsi}`
```json
{
  "mmsi": 563012345,
  "name": "EVER GIVEN",
  "callsign": "H3RC",
  "imo": 9811000,
  "ship_type": 70,
  "ship_type_label": "Cargo",
  "category": "cargo",          // cargo|tanker|passenger|fishing|tug|pleasure|sailing|highspeed|military|special|other
  "flag": {"code": "PA", "name": "Panama"},   // from MMSI MID (first 3 digits); null if unknown
  "length_m": 400, "beam_m": 59, "draught_m": 14.5,     // null when unknown / zero
  "destination": "ROTTERDAM", "eta": "2026-10-25T06:00:00Z",   // null when unknown
  "nav_status": "Under way using engine",
  "region": {"id": "dover", "name": "Strait of Dover"},
  "last": {"lat": 51.01, "lon": 1.52, "sog": 14.2, "cog": 47.0, "heading": 46, "ts": 1761242531},
  "track": [[1.31, 50.88, 1761199331], [1.33, 50.89, 1761199451]],   // [lon, lat, unix_ts], oldest→newest
  "stats": {"distance_nm": 82.4, "track_hours": 11.9, "max_sog": 15.1, "avg_sog": 12.7}
}
```

### `GET /api/nearby?lat=..&lon=..&radius_km=25`
Other recent vessels (< 15 min) for context dots on the map, max 300:
```json
[{"mmsi": 1, "lat": 51.0, "lon": 1.4, "cog": 220.0, "sog": 11.2, "category": "tanker", "name": "X"}]
```

### Static
`GET /` and any non-`/api` path serve files from `../web/` (index.html at `/`).

## Collector details

- aisstream.io: connect `wss://stream.aisstream.io/v0/stream`, send subscription within 3s:
  `{"APIKey": KEY, "BoundingBoxes": [...all regions...], "FilterMessageTypes": ["PositionReport",
  "StandardClassBPositionReport", "ExtendedClassBPositionReport", "ShipStaticData", "StaticDataReport"]}`.
  Messages: `{"MessageType": "...", "MetaData": {"MMSI", "ShipName", "latitude", "longitude",
  "time_utc"}, "Message": {"<MessageType>": {...}}}`. Reconnect with exponential backoff (cap 60s).
- Downsample: store a position for a vessel only if ≥ 90s since its last stored point, or COG changed
  > 15°, or SOG changed > 3 kn. Stationary vessels (sog < 0.5): at most every 10 min. Always keep
  the latest position in a `vessels` table (updated in memory, flushed in batches).
- Batch DB writes (e.g. every 2s, one transaction). WAL mode. Prune positions older than 12h every 10 min.
- Ignore invalid positions (lat 91 / lon 181 sentinel, 0/0), SOG 102.3 = unknown, COG 360 = unknown,
  heading 511 = unknown.
- Static: ShipStaticData gives Name, CallSign, ImoNumber, Type, Dimension{A,B,C,D} (length = A+B,
  beam = C+D), MaximumStaticDraught, Destination, Eta{Month,Day,Hour,Minute}. StaticDataReport (class B)
  gives name/type/callsign in parts A/B. Strip `@` padding and whitespace.
- Lookup tables: MID → ISO country code + name (full ITU MID table); AIS ship type code → label +
  category; nav status code → label.
- Deps: keep minimal — `aiohttp` (WS client + HTTP server) and stdlib `sqlite3`.
- Entry: `uv run --project collector aissaver-collector [--mock] [--port 47823]`
  (or `uv run collector/main.py` — either is fine, document it).

## Web / visual design — "e-ink"

Goal: it should look like a Kindle / Kobo / reMarkable screen showing a tracker. Minimal, calm, crisp.

- **Palette:** paper `#E9E7E0` (warm grey-white), ink `#111`, at most two intermediate greys
  (`#9a9890`, `#c9c7bf`), and prefer **dither / dot patterns** over flat grey fills. No colour anywhere.
- **Paper texture:** very subtle monochrome noise over everything (SVG feTurbulence or a tiny tiled
  PNG generated on a canvas), plus faint vignette. Should feel like matte e-paper, not a webpage.
- **Typography:** e-reader feel. A bookish serif for the ship name and headings (e.g. Literata or
  Source Serif), a monospace for data (e.g. IBM Plex Mono / JetBrains Mono). Load from Google Fonts
  with system fallbacks. Small caps / letter-spaced labels.
- **Layout (16:10 and 16:9):** left ~62% map, right ~38% card, with generous margins. A thin e-reader
  "status bar" across the top: `AIS · STRAIT OF DOVER` left, UTC clock + local time of the vessel's
  region + vessels-tracked count + a little battery-style glyph right. Everything sized in vw/vh / clamp().
- **Map (MapLibre GL JS, vendored into web/vendor/ at a pinned version):** vector tiles from
  OpenFreeMap (`https://tiles.openfreemap.org/planet`, OpenMapTiles schema, no key; glyphs at
  `https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf`). Write a custom style:
  water = paper (transparent over the paper texture); land = a fine 1-bit dot/dither fill pattern
  (generate the pattern image on a canvas and `map.addImage` it); coastline = thin ink line; a few
  sparse place labels in small caps; no roads/POIs (maybe faint major roads at high zoom only).
  No map controls, no attribution clutter: put a tiny "© OpenStreetMap · OpenFreeMap" in the status
  bar instead. Non-interactive.
- **Trajectory:** ink line for the track, dashed for older-than-6h part; small hour tick marks with
  labels like `−3h`, `−6h`. Ship = solid ink triangle/arrow rotated by heading (fallback COG). A short
  dashed projection line ahead (10 min of travel at SOG). Other nearby vessels = tiny hollow triangles
  oriented by COG. Fit bounds to track with padding; sensible min/max zoom.
- **Card ("trump card"):** a playing-card-like panel with thin ink border, slightly rounded corners,
  inner border. Contents top→bottom:
  - small header: card number (`No. 07`), category in letter-spaced caps (`CARGO`)
  - a **1-bit pixel-art ship silhouette** per category (inline SVG with `shape-rendering: crispEdges`,
    hand-designed per category: cargo/container, tanker, passenger/ferry, fishing, tug, sailing,
    pleasure/yacht, high-speed, military, special, other)
  - ship name (serif, large), then flag name + callsign + IMO in mono
  - **stat rows** Top-Trumps style, each a label, value, and a segmented bar (10 blocks, filled
    ▮▮▮▮▯▯… drawn as divs/SVG): LENGTH (m, scale to 400), BEAM, DRAUGHT (scale to 20m),
    SPEED (kn, scale to 25), DISTANCE 12H (nm). Unknown values show `—` and an empty bar.
  - voyage: `→ DESTINATION`, ETA, nav status, position in DMS, "last seen 2 min ago"
- **E-ink behaviour (the important part):**
  - No smooth tweens/flyTo. Changes happen as "refreshes".
  - **Full refresh** when switching vessel: the screen goes ink-black (~140ms), then paper-white
    (~140ms), then the new content appears; leave a faint **ghost** of the previous card/map
    (≈6% opacity snapshot) that fades out in 2–3 discrete steps over ~2s. Keep ≤ 3 flashes/second
    (photosensitivity). `?flash=0` disables the black flash (just white).
  - **Partial refresh** every 15s: refetch `/api/vessel/{mmsi}`; update ship position, numbers,
    "last seen" without flashing (optionally a tiny local flicker on changed text).
  - Dwell per vessel: 45s default, `?dwell=N` seconds override.
  - Burn-in safety: shift the whole layout by a random 0–6px each full refresh.
  - Keep a recently-shown list (last 20 MMSIs) and pass as `exclude`.
- **States:** loading / no candidates yet (collector just started) / collector unreachable → an
  e-ink "sleep screen": centered pixel-art ship, short line of text (`Listening for ships… 12
  vessels so far` / `Collector offline — run scripts/install-agent.sh`), retry every 20s.
- `?preview=1` (System Settings thumbnail): static, no flashing, no timers beyond a slow dwell.
- Performance: it's a screensaver — keep CPU low. No requestAnimationFrame loops; MapLibre only
  re-renders on changes. Set `maxFPS`-ish behaviour by avoiding animations entirely.

## Saver (Swift) details

- `@objc(AISSaverView) final class AISSaverView: ScreenSaverView`, hosting a `WKWebView` filling
  bounds, loading `http://127.0.0.1:47823/?saver=1` (+`&preview=1` when `isPreview`).
- Paper-coloured background before load; `drawsBackground = false` on the web view.
- If the load fails (collector down), show bundled offline HTML (inline e-ink style sleep screen)
  and retry every 20s.
- Sonoma+/Sequoia/Tahoe legacyScreenSaver quirks: observe the distributed notification
  `com.apple.screensaver.willstop` to tear down / pause the web view (instances are not reliably
  deallocated and `stopAnimation` isn't always called); avoid duplicate web views across
  `startAnimation` calls; `animateOneFrame` does nothing; `hasConfigureSheet` false.
- Build without Xcode (only Command Line Tools + Swift 6.2 are installed, no xcodebuild):
  `saver/build.sh` uses `swiftc` → `build/AISSaver.saver/Contents/{MacOS/AISSaver,Info.plist}`,
  frameworks ScreenSaver + WebKit + AppKit, arm64 (optionally universal), min macOS 13, ad-hoc
  `codesign --force --deep -s -`. `saver/build.sh --install` copies to `~/Library/Screen Savers/`
  and `killall legacyScreenSaver` (ignore failure).
