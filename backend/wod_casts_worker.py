# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""WOD23 cast import — its own process under deploy/wod-casts.service (MemoryMax=1.2G).

Daily timer; exits in seconds unless files are pending, the LOD cells are due, a refresh was requested, an
interrupted import can be resumed, or the quarterly source check is due (listing + HEAD at most every 91 days).
⛔ Never imported by main.py: the API process does not run this. The admin force-sync only records
`refresh_requested_at` (`domains.wod_casts.request_refresh`); this worker picks it up on its next timer tick.

    .venv/bin/python -m wod_casts_worker [--budget-s N] [--check]

(same environment as the unit: `set -a; . .env`, WOD_DOWNLOAD_DIR, WOD_TILE_CACHE_DIR). `--check`
forces the quarterly listing now (it still honours `running` and a back-off). The first import is just this
command repeated until nothing is pending: every run loads files largest first within RUN_BUDGET_S.

Decisions (`_decide`), all read from `wod_casts_source`, `wod_files` and `sync_log` (no network):

- `running`   a "started" marker in sync_log younger than STARTED_STALE AND another connection with
              application_name `wod_casts_worker` is open: another import is live. A killed worker (systemctl stop,
              OOM) leaves its marker but its connections vanish, so the stale marker blocks nothing.
- `resume`    the last run was killed (the pessimistic stamp) less than 7 days ago, files are pending (or the LOD
              is due) and it has not died twice at the same file. NO back-off: the next run continues.
- `backoff`   the last import failed (`blocked` / `error` / `schema` / `disk`, or died twice at one file) less than
              7 days ago. An explicit refresh request made AFTER the failure bypasses it.
- `requested` `refresh_requested_at` is set: list + HEAD now, then import what is pending.
- `never`     `loaded_at` is null and there is something to do (the first import, over several runs).
- `pending`   any wod_files row is due (status 'pending', or 'failed' for more than a day).
- `lod due`   (P3) no file pending, but a file was loaded after the LOD cells were built (or never built): only the
              rebuild runs. A failed rebuild is therefore retried on the next tick.
- `bake due`  a tile version exists whose pre-bake never succeeded (no `wod-tiles` success or `skipped:` row since
              `tile_built_at`): only the bake runs.
- `fresh`     checked within the last CHECK_EVERY (91 days): no network call.
- `check`     the quarterly check is due: `discover_and_mark` -> `changed` when it left files to import, else
              `unchanged`. A failing listing is `head failed` (retried tomorrow, nothing marked).
- `busy`      (after the decision, before the import) the shared advisory lock stayed taken for the whole wait
              budget (LOCK_WAIT_S, 2 h). Writes NOTHING: no sync_log row, no failure stamp, no back-off.
- `low memory` / `disk`  deferred, written with log_sync_skipped; never start a back-off.

## Interruptions (the pessimistic stamp)

Before each file is downloaded the worker stamps `last_failure = 'interrupted'` and `interrupted_file = <file_id>`
(inside the loader's `fetch` hook; the LOD rebuild stamps the marker -1). A run that is killed never reaches the
clean-up and leaves that stamp. The same file stamped a second time in a row sets `interrupt_count = 2`: if THAT
attempt dies too, the next start sees count 2, alerts `interrupted twice at file <url>` and backs off 7 days
instead of retrying one bad file (OOM) for ever. A different file restarts the count at 1; every finished run
clears the stamp.

## What goes where (the healthy-skip convention — the same as socat_points_worker.py)

Decisions that import nothing because nothing is due (`running`, `backoff`, `busy`, `fresh`, `unchanged`) write
NOTHING to sync_log. Every run stamps `wod_casts_source.last_run_at` / `last_decision`. A deferral that DID
leave work due (`low memory:`, `disk above`, `head failed:`) is written with log_sync_skipped; the next healthy
decision clears it. A `started` marker is written when an import begins; the loader's own sync_log write
replaces it, a killed run leaves it (so `running` holds until STARTED_STALE).

The import takes advisory lock 4242001, shared with obis_sync_worker, vme_bake_worker, plankton_obis_worker,
glodap_bottles_worker, socat_points_worker and argo-doxy. It is POLLED (pg_try_advisory_lock) for at most
LOCK_WAIT_S, never waited on blockingly: a blocking wait counts against TimeoutStartSec and a late run would be
killed MID-IMPORT. TimeoutStartSec (8 h) = the 2 h wait + RUN_BUDGET_S 3.5 h + LOD rebuild and the 45 min
pre-bake + margin; `wod_casts_rules.STARTED_STALE` equals it.

## Tile pre-bake

After a run that swapped a new tile version, still holding the lock: `wod_tiles.prebake`. It NEVER changes the
import's outcome: its result is logged under sync_log source `wod-tiles` (`skipped: N tiles timed out` is a
WARN) and a failed bake just means tiles are rendered on demand.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import asyncpg
from dotenv import load_dotenv

import db
import log_redaction
from api_access.notify import notify_telegram
from ingestion import wod_casts as L
from ingestion import wod_casts_rules as R
from sync_log import log_sync, log_sync_skipped

log = logging.getLogger("wod_casts_worker")
SOURCE = R.SOURCE
TILES_SOURCE = R.TILES_SOURCE
ALERT_TITLE = "Abyssal WOD casts import"
LOCK_KEY = R.LOCK_KEY                    # 4242001: shared with obis_sync, vme_bake, plankton, glodap, socat, argo-doxy
LOCK_WAIT_S = R.LOCK_WAIT_S
LOCK_POLL_S = 30.0
CHECK_EVERY = R.CHECK_EVERY
MIN_AVAIL_KIB = 1024 * 1024
MAX_DISK_USED = R.DISK_STOP_PROJECTED    # the loader refuses per file; this only skips a start on a full disk
BACKOFF = timedelta(days=7)
LOD_MARKER = -1                          # interrupted_file value of the LOD rebuild (no wod_files row)
HEAD_FAILED_PREFIX = "head failed"
LOW_MEMORY_PREFIX = "low memory"
DISK_PREFIX = "disk above"
TRANSIENT_PREFIXES = (HEAD_FAILED_PREFIX, LOW_MEMORY_PREFIX, DISK_PREFIX)
FAILED_OUTCOMES = ("blocked", "error", "schema", "disk")      # -> 7-day back-off
ALERT_OUTCOMES = FAILED_OUTCOMES + ("lock_timeout",)


def _mem_available_kib() -> int:
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1])
    return 0


def _was_interrupted(failure: str | None) -> bool:
    """A killed run (the pessimistic stamp). Everything else (blocked, error, schema, disk, 'interrupted twice')
    is a back-off."""
    return failure == "interrupted"


APP_NAME = "wod_casts_worker"            # application_name of the worker's connections (see main)


async def _worker_alive(conn) -> bool:
    """Another worker process holds a database connection. A killed process (systemctl stop, OOM) loses its
    connections, so the `started` marker it left behind no longer reads as a live run."""
    # ⛔ The decision must run before any second pool connection opens: an idle one of this pool would make a stale marker read as "running".
    return bool(await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE application_name = $1 AND pid <> pg_backend_pid())",
        APP_NAME))


async def _bake_due(conn) -> bool:
    """A tile version exists whose pre-bake never succeeded: the last good bake (`last_synced_at`) or the last
    timed-out one (`skipped:` marker, accepted as done so it is not retried daily) predates `tile_built_at`."""
    return bool(await conn.fetchval(
        """SELECT s.tile_version IS NOT NULL AND s.tile_built_at IS NOT NULL AND coalesce(
             (SELECT greatest(l.last_synced_at, CASE WHEN l.skipped_reason LIKE 'skipped:%' THEN l.skipped_at END)
                FROM sync_log l WHERE l.source = $1), '-infinity') < s.tile_built_at
           FROM wod_casts_source s WHERE s.id = 1""", TILES_SOURCE))


async def _counts(conn) -> tuple[int, bool]:
    """(files due, LOD rebuild due) — the loader's own SQL, so the worker and the loader cannot disagree."""
    pending = await conn.fetchval(f"SELECT count(*) FROM ({L._PENDING_SQL}) p")
    lod_due = bool(await conn.fetchval(L._LOD_DUE_SQL))
    return int(pending), lod_due


async def _decide(conn, *, forced_check: bool = False) -> str:
    """-> 'running' | 'resume' | 'backoff' | 'requested' | 'never' | 'pending' | 'lod due' | 'bake due' | 'fresh' | 'check'.
    Pure database reads: the network (discovery) happens in `_run`. `forced_check` (--check) turns 'fresh' into
    'check'."""
    s = await conn.fetchrow("SELECT * FROM wod_casts_source WHERE id=1")
    started = await conn.fetchval(
        "SELECT skipped_at FROM sync_log WHERE source=$1 AND skipped_reason LIKE $2", SOURCE, R.STARTED_PREFIX + "%")
    now = datetime.now(timezone.utc)
    if started and now - started < R.STARTED_STALE and await _worker_alive(conn):
        return "running"
    pending, lod_due = await _counts(conn)
    failed, requested = s["last_failed_at"], s["refresh_requested_at"]
    if failed and now - failed < BACKOFF and not (requested and requested > failed):
        if (_was_interrupted(s["last_failure"]) and (pending or lod_due)
                and (s["interrupt_count"] or 0) < R.MAX_SAME_FILE_INTERRUPTS):
            return "resume"
        return "backoff"
    if requested:
        return "requested"
    if s["loaded_at"] is None and (pending or lod_due or s["last_checked_at"] is None):
        return "never"
    if pending:
        return "pending"
    if lod_due:
        return "lod due"
    if await _bake_due(conn):
        return "bake due"                # the pre-bake of the current version failed: only the bake runs
    if forced_check:
        return "check"
    if s["last_checked_at"] and now - s["last_checked_at"] < CHECK_EVERY:
        return "fresh"
    return "check"


async def _stamp(conn, sql: str, *args) -> None:
    """Bookkeeping in wod_casts_source must never mask the run's real outcome."""
    try:
        await conn.execute(sql, *args)
    except Exception:
        log.exception("wod-casts: could not update wod_casts_source")


async def _stamp_interrupt(conn, marker: int) -> int:
    """The pessimistic stamp for one file (or LOD_MARKER). Returns interrupt_count after it: 1 for a new marker,
    +1 when the previous stamp was this same marker and was never cleared (that attempt was killed)."""
    return await conn.fetchval(
        """UPDATE wod_casts_source SET
             interrupt_count = CASE WHEN last_failure = 'interrupted' AND interrupted_file IS NOT DISTINCT FROM $1
                                    THEN COALESCE(interrupt_count, 0) + 1 ELSE 1 END,
             interrupted_file = $1, last_failed_at = now(), last_failure = 'interrupted'
           WHERE id = 1 RETURNING interrupt_count""", marker)


async def _settle_double_interrupt(conn) -> None:
    """A back-off decision whose cause is a file killed twice: alert ONCE and turn the stamp into a plain
    7-day back-off (`interrupted twice at file <url>`), so the next ticks stay silent."""
    s = await conn.fetchrow("SELECT last_failure, interrupted_file, interrupt_count FROM wod_casts_source WHERE id=1")
    if not (_was_interrupted(s["last_failure"]) and (s["interrupt_count"] or 0) >= R.MAX_SAME_FILE_INTERRUPTS):
        return
    fid = s["interrupted_file"]
    what = "the LOD rebuild"
    if fid is not None and fid != LOD_MARKER:
        url = await conn.fetchval("SELECT url FROM wod_files WHERE file_id = $1", fid)
        what = f"file {url or fid}"
    msg = f"interrupted twice at {what}"
    log.error("wod-casts: %s — backing off 7 days", msg)
    await _stamp(conn, "UPDATE wod_casts_source SET last_failed_at = now(), last_failure = $1, "
                 "interrupted_file = NULL, interrupt_count = NULL WHERE id = 1", msg[:200])
    await notify_telegram(f"wod-casts: {msg}; 7-day back-off", ALERT_TITLE)


async def _stamp_outcome(conn, outcome: str, loaded: int = 0) -> None:
    """What the next run's decision reads after the loader returned `outcome`. `loaded` = files this run swapped
    in: a run that made progress is not backed off (its failed files are retried by the loader after a day)."""
    if outcome in FAILED_OUTCOMES and not loaded:
        await _stamp(conn, "UPDATE wod_casts_source SET last_failed_at = now(), last_failure = $1, "
                     "interrupted_file = NULL, interrupt_count = NULL WHERE id = 1", outcome)
    else:
        # complete, partial (budget reached: the next tick simply continues) and lock_timeout (the file stays
        # pending; retrying tomorrow is correct, a 7-day back-off is not)
        await _stamp(conn, "UPDATE wod_casts_source SET last_failed_at = NULL, last_failure = NULL, "
                     "interrupted_file = NULL, interrupt_count = NULL WHERE id = 1")


async def _clear_transient_skip(conn) -> None:
    """A healthy decision means the earlier deferral (low memory / disk / head failed) is over."""
    await _stamp(conn, "UPDATE sync_log SET skipped_reason = NULL, skipped_at = NULL WHERE source = $1 AND ("
                 + " OR ".join(f"skipped_reason LIKE ${i + 2}" for i in range(len(TRANSIENT_PREFIXES))) + ")",
                 SOURCE, *[p + "%" for p in TRANSIENT_PREFIXES])


async def _acquire_lock(conn, wait_s: float, poll_s: float) -> bool:
    """Poll the shared advisory lock for at most wait_s seconds. False = still taken when the budget ran out."""
    deadline = time.monotonic() + wait_s
    while True:
        if await conn.fetchval("SELECT pg_try_advisory_lock($1)", LOCK_KEY):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        await asyncio.sleep(min(poll_s, remaining))


async def _discover(conn, discover) -> bool:
    """Run the listing + HEAD sweep. False = it failed (nothing marked); the caller reports `head failed`."""
    try:
        res = await discover(conn)
    except Exception as e:
        log.warning("wod-casts: discovery failed: %s: %s", type(e).__name__, e)
        return False
    log.info("wod-casts: discovery %s", {k: (len(v) if isinstance(v, list) else v) for k, v in res.items()})
    if res.get("heads_failed") or res.get("years_failed"):
        # discover_and_mark stamped last_checked_at; an incomplete sweep must not hide for a quarter: due again in 7 days
        await _stamp(conn, "UPDATE wod_casts_source SET last_checked_at = now() - make_interval(days => $1) "
                     "WHERE id = 1", CHECK_EVERY.days - 7)
        await notify_telegram(f"wod-casts: incomplete source check ({len(res.get('heads_failed') or [])} HEADs, "
                              f"{len(res.get('years_failed') or [])} year listings failed); repeating in 7 days", ALERT_TITLE)
    return True


async def bake_tiles() -> None:
    """After a swap: pre-bake the tile cache and record the outcome in sync_log under TILES_SOURCE. Never
    raises: the data is already live. The logged outcome is a fixed vocabulary ("error: <ExceptionType>" /
    "error: bake deadline" / "error: consecutive timeouts" / "error: no tile version" / "skipped: version changed"
    / "skipped: N tiles timed out"), never exception text."""
    from services import wod_tiles as tiles
    started = time.monotonic()
    try:
        n, skipped = await tiles.prebake(db.pool, tiles.cache_root())
    except Exception as e:
        log.exception("wod-tiles: pre-bake failed")
        alert = True
        if isinstance(e, tiles.BakeVersionChanged):
            reason, alert = "skipped: version changed", False
        elif isinstance(e, tiles.BakeNoVersion):
            reason = "error: no tile version"
        elif isinstance(e, tiles.BakeConsecutiveTimeouts):
            reason = "error: consecutive timeouts"
        elif isinstance(e, tiles.BakeStopped):
            reason = "error: bake deadline"
        else:
            reason = f"error: {type(e).__name__}"
        try:
            await log_sync_skipped(TILES_SOURCE, reason)
        except Exception:
            log.exception("wod-tiles: could not write sync_log")
        if alert:
            await notify_telegram(f"wod-tiles: pre-bake failed ({reason})", ALERT_TITLE)
        return
    log.info("wod-tiles: %d tiles baked, %d timed out, in %d s", n, skipped, time.monotonic() - started)
    try:
        if skipped:
            await log_sync_skipped(TILES_SOURCE, f"skipped: {skipped} tiles timed out")
        else:
            await log_sync(TILES_SOURCE, n, n)
    except Exception:
        log.exception("wod-tiles: could not write the bake outcome")


def _stamped_fetch(pool, loop, fetch, flags: list):
    """The loader's `fetch(url, dest)` preceded by the pessimistic stamp for that file. It runs in a worker
    thread, so the stamp goes back to the event loop. A file already killed twice is not fetched again: the
    loader marks it failed with the message, the run goes on with the other files."""
    fetch = fetch or L.default_fetch

    async def stamp(url: str) -> tuple[int | None, int]:
        async with pool.acquire() as c:
            fid = await c.fetchval("SELECT file_id FROM wod_files WHERE url = $1", url)
            if fid is None:
                return None, 0
            n = await _stamp_interrupt(c, fid)
        if n > R.MAX_SAME_FILE_INTERRUPTS:
            flags.append(url)
            await notify_telegram(f"wod-casts: interrupted twice at file {url}; skipped for this run", ALERT_TITLE)
        return fid, n

    def wrapped(url, dest):
        _, n = asyncio.run_coroutine_threadsafe(stamp(url), loop).result()
        if n > R.MAX_SAME_FILE_INTERRUPTS:
            raise OSError(f"interrupted twice at file {url}")
        return fetch(url, dest)
    return wrapped


async def run_once(pool, *, discover=None, fetch=None, budget_s: float | None = None, forced_check: bool = False,
                   lock_wait_s: float | None = None, lock_poll_s: float | None = None) -> str:
    """Returns the decision when nothing was imported, else the import's outcome
    ('complete' | 'partial' | 'blocked' | 'lock_timeout' | 'error' | 'schema' | 'disk'), or 'low memory' | 'disk'
    | 'busy'. Every run stamps wod_casts_source.last_run_at / last_decision. lock_wait_s / lock_poll_s default to
    LOCK_WAIT_S / LOCK_POLL_S (tests pass short ones)."""
    db.pool = pool                       # sync_log and the loader read db.pool (see plankton_obis_worker)
    result = "error"
    try:
        result = await _run(pool, discover or L.discover_and_mark, fetch,
                            R.RUN_BUDGET_S if budget_s is None else budget_s, forced_check,
                            LOCK_WAIT_S if lock_wait_s is None else lock_wait_s,
                            LOCK_POLL_S if lock_poll_s is None else lock_poll_s)
        return result
    finally:
        async with pool.acquire() as conn:
            await _stamp(conn, "UPDATE wod_casts_source SET last_run_at = now(), last_decision = $1 WHERE id = 1",
                         result[:40])


async def _run(pool, discover, fetch, budget_s: float, forced_check: bool, lock_wait_s: float,
               lock_poll_s: float) -> str:
    # ONE connection for the whole critical section: session-level advisory locks are released
    # when a pooled connection goes back (see vme_bake_worker.py).
    async with pool.acquire() as lock_conn:
        decision = await _decide(lock_conn, forced_check=forced_check)
        if decision == "backoff":
            await _settle_double_interrupt(lock_conn)
        if decision in ("running", "backoff"):
            log.info("wod-casts: %s — nothing to do", decision)
            return decision
        if decision == "fresh":
            log.info("wod-casts: fresh — nothing to do")
            await _clear_transient_skip(lock_conn)
            return decision
        if decision in ("check", "requested") or (
                decision == "never" and await lock_conn.fetchval(
                    "SELECT last_checked_at IS NULL FROM wod_casts_source WHERE id=1")):
            # The listing + HEAD sweep: network and wod_files only, no lock needed.
            if not await _discover(lock_conn, discover):
                await log_sync_skipped(SOURCE, f"{HEAD_FAILED_PREFIX}: source check skipped, will retry on the next timer run")
                return "head failed"
            pending, lod_due = await _counts(lock_conn)
            if not pending and not lod_due:
                await _stamp(lock_conn, "UPDATE wod_casts_source SET refresh_requested_at = NULL WHERE id = 1")
                await _clear_transient_skip(lock_conn)
                log.info("wod-casts: unchanged — nothing to do")
                return "unchanged"
            if decision == "check":
                decision = "changed"
        if _mem_available_kib() < MIN_AVAIL_KIB:
            await log_sync_skipped(SOURCE, f"{LOW_MEMORY_PREFIX}: deferred to the next timer run")
            return "low memory"
        if L._db_fraction() > MAX_DISK_USED:
            await log_sync_skipped(SOURCE, f"{DISK_PREFIX} {int(MAX_DISK_USED * 100)} %: refused")
            return "disk"
        log.info("wod-casts: %s — polling advisory lock %d for up to %.0f s", decision, LOCK_KEY, lock_wait_s)
        if not await _acquire_lock(lock_conn, lock_wait_s, lock_poll_s):
            # Nothing is stamped or logged: the work is still due, tomorrow's tick tries again.
            log.warning("wod-casts: advisory lock %d still held after %.0f s — exiting busy", LOCK_KEY, lock_wait_s)
            return "busy"
        try:
            # Re-decide now that we hold the lock: a run that waited behind another import must see its result.
            again = await _decide(lock_conn)
            if again in ("running", "backoff"):
                log.info("wod-casts: %s after waiting for the lock — nothing to do", again)
                return again
            if again in ("fresh", "check"):
                log.info("wod-casts: %s after waiting for the lock — nothing to do", again)
                await _clear_transient_skip(lock_conn)
                return "fresh"
            if decision not in ("changed", "requested", "never"):
                decision = again                  # otherwise keep the reason the run was started for
            if decision == "bake due":
                await bake_tiles()          # no import: only the pre-bake of the current version; never raises
                return decision
            if decision != "resume":
                # a new attempt (expired back-off, request, new work): an old interrupt count must not carry over
                await _stamp(lock_conn, "UPDATE wod_casts_source SET interrupted_file = NULL, interrupt_count = NULL "
                             "WHERE id = 1")
            await _stamp(lock_conn, "UPDATE wod_casts_source SET refresh_requested_at = NULL WHERE id = 1")
            pending, _ = await _counts(lock_conn)
            if pending == 0:
                # Only the LOD rebuild is left: stamp it, so a rebuild that kills the worker twice is not retried for ever.
                if await _stamp_interrupt(lock_conn, LOD_MARKER) > R.MAX_SAME_FILE_INTERRUPTS:
                    await _settle_double_interrupt(lock_conn)
                    return "backoff"
            version_before = await lock_conn.fetchval("SELECT tile_version FROM wod_casts_source WHERE id=1")
            await log_sync_skipped(SOURCE, f"{R.STARTED_PREFIX} ({decision})")
            flags: list[str] = []
            out = await L.sync_wod_casts(budget_s=budget_s,
                                         fetch=_stamped_fetch(pool, asyncio.get_running_loop(), fetch, flags))
            outcome = out["outcome"]
            log.info("wod-casts: %s (%d files, version %s)", outcome, len(out["files"]), out["version"])
            await _stamp_outcome(lock_conn, outcome, sum(1 for x in out["files"] if x.get("outcome") == "loaded"))
            if outcome in ALERT_OUTCOMES and not (outcome == "error" and flags):
                why = "; ".join(out["reasons"])[:400]
                await notify_telegram(f"wod-casts: {outcome}" + (f" — {why}" if why else ""), ALERT_TITLE)
            if (out["version"] and out["version"] != version_before) or await _bake_due(lock_conn):
                await bake_tiles()          # never raises; still holding the lock
            return outcome
        finally:
            await lock_conn.execute("SELECT pg_advisory_unlock($1)", LOCK_KEY)


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="WOD23 cast import worker (one decision per run; see the module docstring)")
    ap.add_argument("--budget-s", type=float, default=None,
                    help=f"no new file starts after this many seconds (default {R.RUN_BUDGET_S})")
    ap.add_argument("--check", action="store_true", help="force the quarterly source listing now")
    return ap.parse_args(argv)


async def main(argv=None):
    args = parse_args(argv)
    load_dotenv()
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=3,
                                     server_settings={"application_name": APP_NAME})
    try:
        await run_once(pool, budget_s=args.budget_s, forced_check=args.check)
    finally:
        await pool.close()


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Own process, own logging setup — see backend/log_redaction.py.
    log_redaction.install()
    asyncio.run(main())
