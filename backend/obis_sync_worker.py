# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""OBIS biodiversity sync worker.

Runs as its own systemd service (`obis-sync`) separate from abyssal-api so:
  - Phase 2 pagination (multi-hour) does not block API request handling.
  - VPS git-poll restarts of abyssal-api do NOT kill an in-flight sync.

Usage:
    python -m obis_sync_worker

Environment:
    DATABASE_URL    Postgres DSN (same as abyssal-api, from env.conf)
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal

import asyncpg
from dotenv import load_dotenv

import db
from ingestion.obis_sync import is_obis_paused, sync_obis, rebuild_hotspot_grid

INTERVAL = 7 * 24 * 3600  # weekly

log = logging.getLogger("obis_sync_worker")


async def main() -> None:
    load_dotenv()
    dsn = os.environ["DATABASE_URL"]
    db.pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    log.info("obis_sync_worker: started, running first iteration immediately")

    while not stop.is_set():
        try:
            if await is_obis_paused(db.pool):
                log.info("obis: skipped (paused)")
            else:
                async with db.pool.acquire() as lock_conn:
                    await lock_conn.execute("SELECT pg_advisory_lock($1)", 4242001)
                    try:
                        await sync_obis(db.pool)
                        await rebuild_hotspot_grid(db.pool)
                    finally:
                        await lock_conn.execute("SELECT pg_advisory_unlock($1)", 4242001)
        except Exception:
            log.exception("OBIS sync iteration failed")

        # Sleep INTERVAL but wake immediately on SIGTERM/SIGINT
        try:
            await asyncio.wait_for(stop.wait(), timeout=INTERVAL)
        except asyncio.TimeoutError:
            pass

    await db.pool.close()
    log.info("obis_sync_worker: stopped")


if __name__ == "__main__":
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(main())
