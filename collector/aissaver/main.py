"""Entry point: run the AIS feed (live or mock) and the HTTP server."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

from aiohttp import web

from . import config
from .aisstream import AisStreamClient
from .api import Api
from .mock import MockFeed
from .store import Store

log = logging.getLogger("collector")

FLUSH_S = 2
PRUNE_S = 600
STATS_S = 60


async def _every(seconds: float, fn) -> None:
    while True:
        await asyncio.sleep(seconds)
        try:
            fn()
        except Exception:
            log.exception("periodic task %s failed", getattr(fn, "__name__", fn))


async def serve(args: argparse.Namespace) -> None:
    if args.mock:
        path = config.db_path(mock=True)
        for p in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
            p.unlink(missing_ok=True)  # mock data is regenerated from scratch every run
        store = Store(path)
        feed = MockFeed(store)
    else:
        key = config.load_api_key()
        if not key:
            sys.exit(
                "No aisstream.io API key found.\n"
                f"Set AISSTREAM_API_KEY or run scripts/set-key.sh <KEY> (writes {config.ENV_FILE}).\n"
                "Get a free key at https://aisstream.io, or run with --mock."
            )
        store = Store(config.db_path(mock=False))
        feed = AisStreamClient(store, key)

    api = Api(store, feed)
    runner = web.AppRunner(api.app(), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, args.host, args.port).start()
    log.info("serving http://%s:%d/ (%s mode, web dir %s)", args.host, args.port, feed.mode, config.WEB_DIR)

    def log_stats() -> None:
        log.info(
            "stats: %d msgs/min, %d vessels, %d positions, connected=%s",
            api.msgs_per_min(), len(store.vessels), store.positions_count, feed.connected,
        )

    def prune() -> None:
        n = store.prune()
        if n:
            log.info("pruned %d old positions", n)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    tasks = [
        asyncio.create_task(feed.run(), name="feed"),
        asyncio.create_task(_every(FLUSH_S, store.flush), name="flush"),
        asyncio.create_task(_every(PRUNE_S, prune), name="prune"),
        asyncio.create_task(_every(5, api.sample_rate), name="rate"),
        asyncio.create_task(_every(STATS_S, log_stats), name="stats"),
    ]
    stop_task = asyncio.create_task(stop.wait())
    done, _ = await asyncio.wait([stop_task, *tasks], return_when=asyncio.FIRST_COMPLETED)
    for t in done:
        if t is not stop_task and t.exception():
            log.error("task %s crashed: %r", t.get_name(), t.exception())
    log.info("shutting down")
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await runner.cleanup()
    store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="AIS e-ink screensaver collector")
    parser.add_argument("--mock", action="store_true", help="synthesise vessels instead of using aisstream.io")
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(serve(args))


if __name__ == "__main__":
    main()
