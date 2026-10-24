"""Paths, ports and API-key loading."""

from __future__ import annotations

import os
from pathlib import Path

HOST = "127.0.0.1"
PORT = 47823

DATA_DIR = Path.home() / "Library" / "Application Support" / "ais-screensaver"
ENV_FILE = Path.home() / ".config" / "ais-screensaver" / "env"
WEB_DIR = (Path(__file__).resolve().parent.parent.parent / "web").resolve()

RETENTION_S = 12 * 3600  # how much track history we keep
FRESH_S = 15 * 60  # a vessel is "live" if heard from within this window

AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"


def load_api_key() -> str | None:
    key = os.environ.get("AISSTREAM_API_KEY", "").strip()
    if key:
        return key
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith("AISSTREAM_API_KEY="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value:
                    return value
    return None


def db_path(mock: bool) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / ("ais-mock.sqlite" if mock else "ais.sqlite")
