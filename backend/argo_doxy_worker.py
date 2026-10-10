# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""BGC-Argo DOXY import — its own process under deploy/argo-doxy.service (MemoryMax=1.5G).

Daily timer, weekly work. ⛔ Never imported by main.py: the API process does not ingest. The admin force-sync
only records `refresh_requested_at` (domains.argo_oxygen_points.request_refresh).

Decisions (`_decide`), read from argo_doxy_source and sync_log:
- `running`   a "started" marker younger than STARTED_STALE (6 h 30 min, = the unit's TimeoutStartSec).
- `backoff`   the last import failed (blocked / error / schema, or the process died: 'interrupted') < 7 days ago;
              a refresh requested AFTER the failure bypasses it.
- `requested` refresh_requested_at is set.
- `never`     loaded_at is null.
- `pending`   a previous run stopped at its time budget or the disk line and left floats to do.
- `due`       the last complete run is CADENCE (6 d 12 h) old (or there is none).
- `fresh`     otherwise: no network call, nothing written to sync_log (healthy-skip convention, as glodap).
- `busy`      the shared advisory lock 4242001 stayed taken for LOCK_WAIT_S: exit, write nothing; the next tick
              tries again. The lock is POLLED, never awaited, so a queued run is never killed by TimeoutStartSec.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from datetime import datetime, timedelta, timezone

import asyncpg
from dotenv import load_dotenv

import db
import log_redaction
from ingestion.argo_doxy import SCRATCH_DIR, sync_argo_doxy
from ingestion.argo_doxy_rules import (DISK_PREFIX, FAILED_OUTCOMES, LOW_MEMORY_PREFIX, SOURCE,  # noqa: F401
                                       STARTED_PREFIX, STARTED_STALE, TRANSIENT_PREFIXES)
from sync_log import log_sync_skipped

log = logging.getLogger("argo_doxy_worker")
LOCK_KEY = 4242001                       # shared with obis_sync_worker, vme_bake_worker, plankton, glodap
# Weekly work on a DAILY tick. A bare 7 days would miss the tick of day 7: last_complete_at is stamped when the run
# ENDS (hours after its tick began) and the tick itself jitters (RandomizedDelaySec 20 min), so the check on day 7 sees
# 6 d 23 h and the import slides to day 8 — about eight days in practice. A full-budget run ends up to ~4.5 h after
# its tick (3.5 h budget + index + the float in flight + jitter), so 6 d 20 h still missed day 7 for it. With a daily
# tick every cadence between 6 d and (7 d - run length) gives the same weekly rhythm; 6 d 12 h sits in the middle.
CADENCE = timedelta(days=6, hours=12)
BACKOFF = timedelta(days=7)
MIN_AVAIL_KIB = 3 * 1024 * 1024
MAX_DISK_USED = 0.80                     # disk-guard warns at 85 %, stops services at 90 %
LOCK_WAIT_S = 2 * 3600
LOCK_POLL_S = 30.0


def _mem_available_kib() -> int:
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1])
    return 0


def _disk_used_fraction() -> float:
    u = shutil.disk_usage(SCRATCH_DIR if SCRATCH_DIR.exists() else "/")
    return u.used / u.total


async def _decide(conn) -> str:
    s = await conn.fetchrow("SELECT * FROM argo_doxy_source WHERE id = 1")
    started = await conn.fetchval("SELECT skipped_at FROM sync_log WHERE source=$1 AND skipped_reason LIKE $2",
                                  SOURCE, STARTED_PREFIX + "%")
    now = datetime.now(timezone.utc)
    if started and now - started < STARTED_STALE:
        return "running"
    failed, requested = s["last_failed_at"], s["refresh_requested_at"]
    if failed and now - failed < BACKOFF and not (requested and requested > failed):
        return "backoff"
    if requested:
        return "requested"
    if s["loaded_at"] is None:
        return "never"
    if s["pending_floats"]:
        return "pending"
    if s["last_complete_at"] is None or now - s["last_complete_at"] >= CADENCE:
        return "due"
    return "fresh"


async def _stamp(conn, sql: str, *args) -> None:
    try:
        await conn.execute(sql, *args)
    except Exception:
        log.exception("argo-doxy: could not update argo_doxy_source")


async def _clear_transient_skip(conn) -> None:
    await _stamp(conn, "UPDATE sync_log SET skipped_reason = NULL, skipped_at = NULL WHERE source = $1 AND ("
                 + " OR ".join(f"skipped_reason LIKE ${i + 2}" for i in range(len(TRANSIENT_PREFIXES))) + ")",
                 SOURCE, *[p + "%" for p in TRANSIENT_PREFIXES])


async def _clear_started_marker(conn) -> None:
    """The loader's own sync_log writes replace the marker, except where it writes none (an injected sync, an
    exit that logs nothing): without this /meta would read `running` for STARTED_STALE after a finished run."""
    await _stamp(conn, "UPDATE sync_log SET skipped_reason = NULL, skipped_at = NULL "
                 "WHERE source = $1 AND skipped_reason LIKE $2", SOURCE, STARTED_PREFIX + "%")


async def _acquire_lock(conn, wait_s: float, poll_s: float) -> bool:
    deadline = time.monotonic() + wait_s
    while True:
        if await conn.fetchval("SELECT pg_try_advisory_lock($1)", LOCK_KEY):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        await asyncio.sleep(min(poll_s, remaining))


async def run_once(pool, *, sync=None, lock_wait_s: float | None = None, lock_poll_s: float | None = None) -> str:
    db.pool = pool
    result = "error"
    try:
        result = await _run(pool, sync or sync_argo_doxy, LOCK_WAIT_S if lock_wait_s is None else lock_wait_s,
                            LOCK_POLL_S if lock_poll_s is None else lock_poll_s)
        return result
    finally:
        async with pool.acquire() as conn:
            await _stamp(conn, "UPDATE argo_doxy_source SET last_run_at = now(), last_decision = $1 WHERE id = 1",
                         result)


async def _run(pool, sync, lock_wait_s: float, lock_poll_s: float) -> str:
    async with pool.acquire() as lock_conn:              # ONE connection: session-level advisory lock
        decision = await _decide(lock_conn)
        if decision in ("running", "backoff"):
            return decision
        if decision == "fresh":
            await _clear_transient_skip(lock_conn)
            return decision
        if _mem_available_kib() < MIN_AVAIL_KIB:
            await log_sync_skipped(SOURCE, f"{LOW_MEMORY_PREFIX}: deferred to the next timer run")
            return "low memory"
        if _disk_used_fraction() > MAX_DISK_USED:
            await log_sync_skipped(SOURCE, f"{DISK_PREFIX} {int(MAX_DISK_USED * 100)} %: refused")
            return "disk"
        if not await _acquire_lock(lock_conn, lock_wait_s, lock_poll_s):
            log.warning("argo-doxy: advisory lock %d still held after %.0f s — exiting busy", LOCK_KEY, lock_wait_s)
            return "busy"
        try:
            decision = await _decide(lock_conn)          # re-decide: we may have waited behind another import
            if decision in ("running", "backoff"):
                return decision
            if decision == "fresh":
                await _clear_transient_skip(lock_conn)
                return decision
            await log_sync_skipped(SOURCE, f"{STARTED_PREFIX} ({decision})")
            await _stamp(lock_conn, "UPDATE argo_doxy_source SET last_failed_at = now(), "
                         "last_failure = 'interrupted' WHERE id = 1")
            out = await sync()
            outcome = out.get("outcome") or "error"      # early exits return a short dict without float counts
            log.info("argo-doxy: %s", out)
            await _clear_started_marker(lock_conn)       # a run that RETURNED is not "running"; a killed one stays
            if outcome in FAILED_OUTCOMES:
                await _stamp(lock_conn, "UPDATE argo_doxy_source SET last_failed_at = now(), last_failure = $1 "
                             "WHERE id = 1", outcome)
            else:
                await _stamp(lock_conn, "UPDATE argo_doxy_source SET last_failed_at = NULL, last_failure = NULL "
                             "WHERE id = 1")
            return outcome
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
    log_redaction.install()
    asyncio.run(main())
