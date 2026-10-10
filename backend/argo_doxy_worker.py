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

Map tiles (design 2026-10-10): after a run, and on a `fresh` tick, when the data moved past the last tile build and no
float is pending, or when the last pre-bake of the current tile version failed (`_tile_work`), the worker rebuilds the
tile tables and/or pre-bakes z0-4 (`build_tiles`), holding the lock. The tiles never change the decision or the
outcome; their result goes to sync_log under `argo-tiles`, and only when tile work was done.
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
from api_access.notify import notify_telegram
from ingestion import argo_doxy_tiles
from ingestion.argo_doxy import SCRATCH_DIR, sync_argo_doxy
from ingestion.argo_doxy_rules import (DISK_PREFIX, FAILED_OUTCOMES, LOW_MEMORY_PREFIX, SOURCE,  # noqa: F401
                                       STARTED_PREFIX, STARTED_STALE, TILES_SOURCE, TRANSIENT_PREFIXES)
from sync_log import log_sync, log_sync_skipped

log = logging.getLogger("argo_doxy_worker")
ALERT_TITLE = "Abyssal Argo DOXY import"
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


NO_DRAWABLE = "skipped: no drawable profile"
# $1 TILES_SOURCE, $2 NO_DRAWABLE. `rebuild`: a complete import changed the data after the last tile build (or tiles were
# never built), unless the last attempt on exactly this data found nothing to draw (a purged layer is not retried daily).
# `rebake`: the data has NOT moved but the last pre-bake of this tile version neither succeeded (last_synced_at) nor ended
# in a `skipped:` outcome (timeouts, version changed: accepted as done, not retried daily) -- an `error:` outcome retries.
# The bake outcome is read from sync_log, so a healthy tick has nothing to write.
_TILE_WORK_SQL = """
SELECT s.loaded_at IS NOT NULL AND s.pending_floats = 0
         AND (s.tile_built_at IS NULL OR s.tile_built_at < s.loaded_at)
         AND NOT coalesce(l.skipped_reason = $2 AND l.skipped_at >= s.loaded_at, false) AS rebuild,
       s.tile_version IS NOT NULL AND s.tile_built_at IS NOT NULL
         AND (s.loaded_at IS NULL OR s.tile_built_at >= s.loaded_at)
         AND coalesce(greatest(l.last_synced_at, CASE WHEN l.skipped_reason LIKE 'skipped:%' THEN l.skipped_at END),
                      '-infinity') < s.tile_built_at AS rebake
FROM argo_doxy_source s LEFT JOIN sync_log l ON l.source = $1
WHERE s.id = 1"""


async def _tile_work(conn) -> tuple[bool, bool]:
    """(rebuild, rebake) -- see _TILE_WORK_SQL. Never mid-week: pending floats mean the live table is between two
    import weeks, so nothing is rebuilt then."""
    try:
        row = await conn.fetchrow(_TILE_WORK_SQL, TILES_SOURCE, NO_DRAWABLE)
    except (asyncpg.UndefinedColumnError, asyncpg.UndefinedTableError):
        log.warning("argo-tiles: argo_doxy_source has no tile columns yet (API not restarted on the new schema)")
        return False, False
    return (False, False) if row is None else (bool(row["rebuild"]), bool(row["rebake"]))


async def _tiles_due(conn) -> bool:
    rebuild, rebake = await _tile_work(conn)
    return rebuild or rebake


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


async def _log_tiles(reason: str) -> None:
    try:
        await log_sync_skipped(TILES_SOURCE, reason)
    except Exception:
        log.exception("argo-tiles: could not write sync_log")


async def _tiles_failed(reason: str) -> None:
    """Record an `error:` outcome and send ONE Telegram alert per streak. WOD alerts once per failed pre-bake because
    its bake is not retried; here a failed build or bake is retried by every daily tick (`_TILE_WORK_SQL`), so an alert
    per failure would repeat daily until the cause is fixed. The streak is read from sync_log BEFORE it is overwritten:
    the previous outcome already an `error:` = the alert went out; a success (log_sync) or a `skipped:` clears it."""
    previous = None
    try:
        async with db.pool.acquire() as c:
            previous = await c.fetchval("SELECT skipped_reason FROM sync_log WHERE source = $1", TILES_SOURCE)
    except Exception:
        log.exception("argo-tiles: could not read the previous outcome")
    await _log_tiles(reason)
    if not (previous or "").startswith("error:"):
        await notify_telegram(f"argo-tiles: tile work failed ({reason}); the next tick retries", ALERT_TITLE)


def _bake_failure(e: Exception) -> str:
    """Fixed vocabulary, never exception text. BakeConsecutiveTimeouts is a BakeStopped: test it first."""
    from services import argo_tiles as tiles       # already imported by build_tiles (which imported schema first)
    if isinstance(e, tiles.BakeVersionChanged):
        return "skipped: version changed"
    if isinstance(e, tiles.BakeNoVersion):
        return "error: no tile version"
    if isinstance(e, tiles.BakeConsecutiveTimeouts):
        return "error: consecutive timeouts"
    if isinstance(e, tiles.BakeStopped):
        return "error: bake deadline"
    return f"error: {type(e).__name__}"


async def build_tiles(conn) -> None:
    """Rebuild the tile tables from the live profiles when the data moved (swap = new version), then pre-bake the
    current version. Never raises: the import's outcome is already decided, and a failed build keeps the previous
    tiles (the next tick retries). The logged outcome is a fixed vocabulary, never exception text."""
    started = time.monotonic()
    try:
        rebuild, rebake = await _tile_work(conn)
        if not (rebuild or rebake):
            return
        if rebuild:
            try:
                built = await argo_doxy_tiles.rebuild_tiles(conn)
            except argo_doxy_tiles.NothingToDraw:
                await _log_tiles(NO_DRAWABLE)
                return
            except Exception as e:
                log.exception("argo-tiles: build failed, the previous tiles stay")
                await _tiles_failed(f"error: {type(e).__name__}")
                return
            log.info("argo-tiles: version %s, %d profiles, cell rows per level %s, in %d s", built["version"],
                     built["n_points"], built["level_rows"], time.monotonic() - started)
            n_points = built["n_points"]
        else:                                                  # only the pre-bake of the current version failed
            n_points = await conn.fetchval("SELECT count(*) FROM argo_doxy_tile_points")
            log.info("argo-tiles: pre-bake of the current version retried (%d profiles)", n_points)
        # Lazy: this pulls the API stack into the process. `schema` FIRST: services.plankton_tiles imports schema.plankton,
        # whose package init imports domains, which import services -- entered cold from services.* that is an import
        # cycle (AttributeError on plankton_tiles.VERSION_RE); entered through schema it resolves (as in the API).
        import schema  # noqa: F401
        from services import argo_tiles as tiles
        try:
            n, timed_out = await tiles.prebake(db.pool, tiles.cache_root())
        except Exception as e:
            log.exception("argo-tiles: pre-bake failed (tiles render on demand)")
            reason = _bake_failure(e)
            if reason.startswith("error:"):
                await _tiles_failed(reason)
            else:
                await _log_tiles(reason)
            return
        log.info("argo-tiles: %d tiles baked, %d timed out, %d s in total", n, timed_out, time.monotonic() - started)
        if timed_out:
            await _log_tiles(f"skipped: {timed_out} tiles timed out")
            return
        await log_sync(TILES_SOURCE, n, n_points)
    except Exception:
        log.exception("argo-tiles: tile work failed (the import outcome stands)")


async def _tiles_if_due(conn) -> None:
    """Under the lock: never raises."""
    try:
        if await _tiles_due(conn):
            await build_tiles(conn)
    except Exception:
        log.exception("argo-tiles: tile check failed (the import outcome stands)")


async def _tiles_on_fresh_tick(conn, lock_wait_s: float, lock_poll_s: float) -> None:
    """A fresh tick whose data has no tiles yet (the first tick after the deploy, or a build / bake that failed): take
    the lock, re-check, build. Busy = the next tick tries again. Never raises."""
    try:
        if not await _tiles_due(conn):
            return
        if not await _acquire_lock(conn, lock_wait_s, lock_poll_s):
            log.warning("argo-tiles: advisory lock %d still held after %.0f s -- tiles wait for the next tick",
                        LOCK_KEY, lock_wait_s)
            return
        try:
            await _tiles_if_due(conn)                # another process may have built them while we waited
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", LOCK_KEY)
    except Exception:
        log.exception("argo-tiles: tile check failed on a fresh tick")


async def _run(pool, sync, lock_wait_s: float, lock_poll_s: float) -> str:
    async with pool.acquire() as lock_conn:              # ONE connection: session-level advisory lock
        decision = await _decide(lock_conn)
        if decision in ("running", "backoff"):
            return decision
        if decision == "fresh":
            await _clear_transient_skip(lock_conn)
            await _tiles_on_fresh_tick(lock_conn, lock_wait_s, lock_poll_s)
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
                await _tiles_if_due(lock_conn)
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
            await _tiles_if_due(lock_conn)               # still holding the lock; never changes the outcome
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
