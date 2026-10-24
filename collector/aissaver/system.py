"""Host status for the UI's e-reader chrome (WebKit has no battery API)."""

from __future__ import annotations

import asyncio
import re
import time

CACHE_S = 30
_cache: tuple[float, dict | None] = (0.0, None)


def parse_pmset(text: str) -> dict | None:
    """`pmset -g batt` output -> {percent, charging, plugged}; None on Macs without a battery."""
    m = re.search(r"InternalBattery.*?(\d+)%;\s*([^;]+);", text)
    if not m:
        return None
    state = m.group(2).strip()
    return {
        "percent": int(m.group(1)),
        "charging": state == "charging",
        "plugged": "AC Power" in text,
    }


async def battery() -> dict | None:
    global _cache
    at, value = _cache
    if time.time() - at < CACHE_S:
        return value
    try:
        proc = await asyncio.create_subprocess_exec(
            "pmset", "-g", "batt", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), 5)
        value = parse_pmset(out.decode(errors="replace"))
    except (OSError, asyncio.TimeoutError):
        value = None
    _cache = (time.time(), value)
    return value
