# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Standalone, cgroup-capped OBIS plankton import worker.

Runs as its OWN systemd unit (plankton-obis.service) — never inside abyssal-api.
Triggered every 6 h by plankton-obis.timer. Whether to import is decided from
`sync_log` (the database is the memory, no local state file):

- last success younger than STALE_DAYS            -> "fresh"   (exit, nothing written)
- last run failed less than BACKOFF_DAYS ago      -> "backoff" (exit, nothing written)
- "started" marker younger than 8 h               -> "running" (another import is live; exit)
- "started" marker older than 8 h                 -> a killed run: counts as failed -> "backoff"
- otherwise the import runs.

"fresh" and "backoff" are decisions, not syncs: they write nothing to `sync_log`,
so a 6-hourly tick cannot move `skipped_at` (which would restart the back-off
clock forever) or spam the monitor. A low-memory deferral DOES write a skip, with
the reason, because a due import did not happen — but it is not a failure and
never starts a back-off.

The import takes advisory lock 4242001 with a BLOCKING wait, like obis_sync_worker
and vme_bake_worker, so the three heavy jobs never run concurrently. The wait is
unbounded here by design; the unit's TimeoutStartSec is the bound.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

import asyncpg
from dotenv import load_dotenv

import db
import log_redaction
from ingestion.plankton_obis import SOURCE, STARTED_PREFIX, STARTED_STALE_HOURS, sync_plankton_obis
from schema.plankton import SWAPPED_PARTIAL_PREFIX
from sync_log import log_sync_skipped

LOCK_KEY = 4242001            # shared with obis_sync_worker and vme_bake_worker
STALE_DAYS = 30
BACKOFF_DAYS = 7              # wait after a failed run before trying again
MIN_AVAIL_KIB = 3 * 1024 * 1024  # 3 GiB
LOW_MEMORY_PREFIX = "low memory"  # a skip with this prefix is NOT a failed run
STARTED_STALE = timedelta(hours=STARTED_STALE_HOURS)   # = the unit's TimeoutStartSec
log = logging.getLogger("plankton_obis_worker")


def _mem_available_kib():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1])
    except OSError:
        pass
    return None


def _memory_ok() -> bool:
    avail = _mem_available_kib()
    return avail is None or avail >= MIN_AVAIL_KIB


async def _decide(conn) -> str | None:
    """'fresh' | 'backoff' | 'running' | None (= import is due), from the sync_log row alone.

    A "started" marker (written when an import begins, replaced by every normal exit) younger
    than STARTED_STALE means a run is in progress -> 'running'. An older one means the process
    was killed (OOM / TimeoutStartSec / SIGTERM wrote nothing) -> a FAILED run: the usual
    back-off counted from the start, and /v1/plankton/meta shows it as "error"."""
    row = await conn.fetchrow(
        "SELECT last_synced_at, skipped_reason, skipped_at FROM sync_log WHERE source = $1", SOURCE)
    if row is None:
        return None
    now = datetime.now(timezone.utc)
    reason, skipped_at = row["skipped_reason"], row["skipped_at"]
    if reason and skipped_at and reason.startswith(STARTED_PREFIX) and now - skipped_at < STARTED_STALE:
        return "running"
    # log_sync clears the skip marker on success, so a marker means the LAST run failed
    # (except a partial swap: it succeeded, its marker only carries the failed-dataset count).
    if reason and skipped_at and not reason.startswith((LOW_MEMORY_PREFIX, SWAPPED_PARTIAL_PREFIX)) \
            and now - skipped_at < timedelta(days=BACKOFF_DAYS):
        return "backoff"
    last = row["last_synced_at"]
    if last is not None and now - last < timedelta(days=STALE_DAYS):
        return "fresh"
    return None


async def run_once(pool) -> str:
    """Returns "ran" | "fresh" | "backoff" | "running" | "low-memory"."""
    db.pool = pool
    # ONE connection for the whole critical section: session-level advisory locks are
    # released when a pooled connection goes back (see vme_bake_worker.py).
    async with pool.acquire() as lock_conn:
        decision = await _decide(lock_conn)
        if decision:
            log.info("plankton-obis: %s — nothing to do", decision)
            return decision
        if not _memory_ok():
            avail = _mem_available_kib()
            reason = f"{LOW_MEMORY_PREFIX} — MemAvailable {avail} KiB below {MIN_AVAIL_KIB} KiB, import deferred"
            log.warning("plankton-obis: %s", reason)
            await log_sync_skipped(SOURCE, reason)
            return "low-memory"
        log.info("plankton-obis: waiting for advisory lock %d", LOCK_KEY)
        await lock_conn.execute("SELECT pg_advisory_lock($1)", LOCK_KEY)
        try:
            # Re-decide now that we hold the lock: a run that waited behind another import must see
            # that import's fresh success (or marker) instead of importing a second time.
            decision = await _decide(lock_conn)
            if decision:
                log.info("plankton-obis: %s after waiting for the lock — nothing to do", decision)
                return decision
            res = await sync_plankton_obis()
            log.info("plankton-obis: %s", res)
            return "ran"
        finally:
            await lock_conn.execute("SELECT pg_advisory_unlock($1)", LOCK_KEY)


async def main():
    load_dotenv()
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=3)
    try:
        await run_once(pool)
    finally:
        await pool.close()


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Own process, own logging setup — see backend/log_redaction.py.
    log_redaction.install()
    asyncio.run(main())
