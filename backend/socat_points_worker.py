# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""SOCATv2026 observation-point import — its own process under deploy/socat-points.service (MemoryMax=1.2G).

Daily timer; exits in seconds unless the layer was never loaded, a refresh was requested, an interrupted import
can be resumed, or the source changed (HEAD at most once per 30 days). ⛔ Never imported by main.py: the API
process does not run this. The admin force-sync only records `refresh_requested_at`
(`domains.socat_points.request_refresh`); this worker picks it up on its next timer tick.

First import (the zip is already on the VPS, sha256 from the phase-0 download):

    .venv/bin/python -m socat_points_worker --zip /var/tmp/socat-phase0/SOCATv2026_synthesis_file.zip --sha256 <hex>

(same environment as the unit: `set -a; . .env`, SOCAT_SCRATCH_DIR, TMPDIR, SOCAT_TILE_CACHE_DIR). The sha256 is
handed to the loader as `expected_sha256` (C3): a different file is refused before anything is staged.

Decisions (`_decide`), all read from `socat_points_source` and `sync_log`:

- `running`   a "started" marker in sync_log younger than STARTED_STALE: another import is live.
- `resume`    the last run was interrupted (killed, OOM, or a failure after progress) and the staging holds
              committed cruises for the current zip (same sha256), and it has not died twice at the same
              expocode. NO back-off: the next run continues from the last committed cruise.
- `backoff`   the last import failed (`blocked` / `error` / `schema` / `disk`, or a process that died with no
              progress to resume, or died twice at the same expocode) less than 7 days ago. An explicit refresh
              request made AFTER the failure bypasses it. `low memory`, `disk` and `head failed` never start a
              back-off: nothing was staged.
- `requested` `refresh_requested_at` is set (or --zip was given).
- `never`     `loaded_at` is null.
- `busy`      (after the decision, before the import) the shared advisory lock stayed taken for the whole
              wait budget (LOCK_WAIT_S, 2 h). Writes NOTHING: no sync_log row, no failure stamp, no back-off.
- `fresh`     checked within the last 30 days: no network call.
- `unchanged` the monthly HEAD found the same release.
- `changed`   the monthly HEAD found a different release.

## Interruptions (the pessimistic stamp)

Before the import the worker stamps `last_failure = 'interrupted'` and `interrupted_expocode =
staging_last_expocode` (the point this run resumes from). A run that is killed never reaches the clean-up and
leaves that stamp. If the NEXT start finds the same `staging_last_expocode`, the previous run died without
committing a single batch past it: `interrupt_count` becomes 2, the worker alerts `interrupted twice at
<expocode>` and backs off for 7 days instead of retrying one bad cruise (OOM) for ever. Progress beyond the
stamp (a different expocode) restarts the count at 1. The loader is called with `count_resume=False` so a
resume is not counted twice.

## What goes where (the healthy-skip convention — the same as glodap_bottles_worker.py)

Decisions that import nothing because nothing is due (`running`, `backoff`, `busy`, `fresh`, `unchanged`) write
NOTHING to sync_log. Every run stamps `socat_points_source.last_run_at` / `last_decision`. A deferral that DID
leave an import due (`low memory:`, `disk above`, `head failed:`) is written with log_sync_skipped; the next
healthy decision clears it. The reject counts of the last load live in `socat_points_source.last_rejects`
(`/v1/socat/meta` reads the "swapped with rejects" note from there), the failure stamp in `last_failed_at` /
`last_failure`.

The import takes advisory lock 4242001, shared with obis_sync_worker, vme_bake_worker, plankton_obis_worker and
glodap_bottles_worker. It is POLLED (pg_try_advisory_lock) for at most LOCK_WAIT_S, never waited on blockingly:
plankton may hold the lock for 12 h and a blocking wait counts against TimeoutStartSec, so a late run would be
killed MID-IMPORT. TimeoutStartSec (6 h) = the 2 h wait + the import + the 45 min tile bake;
`socat_points_rules.STARTED_STALE` equals it.

## Tile pre-bake

After `swapped`, still holding the lock: `socat_tiles.prebake` (z0-6 plus every z7-z10 tile with >= 100,000
drawable observations, counted right after the swap; each tile under a 60 s statement timeout; 45 min deadline;
stops on 20 consecutive timeouts). It NEVER changes the import's outcome: a failed bake is logged under
sync_log source `socat-tiles` and the tiles are then rendered on demand.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import pathlib
import shutil
import time
from datetime import datetime, timedelta, timezone

import asyncpg
from dotenv import load_dotenv

import db
import log_redaction
from api_access.notify import notify_telegram
from ingestion import socat_points_rules as R
from ingestion.socat_points import (
    SCRATCH_DIR, ZIP_NAME, discard_staging, head_fingerprint, sha256_of, sync_socat_points)
from sync_log import log_sync, log_sync_skipped

log = logging.getLogger("socat_points_worker")
SOURCE = R.SOURCE
TILES_SOURCE = R.TILES_SOURCE
ALERT_TITLE = "Abyssal SOCAT points import"
LOCK_KEY = 4242001                       # shared with obis_sync_worker, vme_bake_worker, plankton, glodap
CHECK_EVERY = timedelta(days=30)
MIN_AVAIL_KIB = 1024 * 1024
MAX_DISK_USED = 0.80                     # disk-guard warns at 85 %, stops services at 90 %
LOCK_WAIT_S = 2 * 3600                   # poll budget for the shared lock; see the module docstring
LOCK_POLL_S = 30.0
BACKOFF = timedelta(days=7)


def _mem_available_kib() -> int:
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1])
    return 0


def _disk_used_fraction() -> float:
    u = shutil.disk_usage(SCRATCH_DIR if SCRATCH_DIR.exists() else "/")
    return u.used / u.total


def _same(stored, head: dict) -> bool:
    if head.get("etag") and stored["etag"]:
        return head["etag"] == stored["etag"]
    return (head.get("content_length"), head.get("last_modified")) == (stored["content_length"], stored["last_modified"])


def _can_resume(s, current_sha: str | None) -> bool:
    """Staging holds committed cruises of the current file (current_sha None = not known yet: the loader
    compares the real sha itself and starts over if it differs)."""
    return (s["staging_last_expocode"] is not None and s["staging_sha256"] is not None
            and (current_sha is None or current_sha == s["staging_sha256"]))


def _was_interrupted(failure: str | None) -> bool:
    """A failure that leaves a staging worth continuing: a killed run (the pessimistic stamp) or a loader
    'resumable' outcome. Everything else (blocked, error, schema, disk) is a back-off."""
    return failure is not None and (failure == "interrupted" or failure.startswith("resumable"))


LOCK_TIMEOUT_FAILURE = "lock_timeout"     # last_failure after a complete staging whose swap lost the lock race


def _swap_pending(failure: str | None) -> bool:
    """The last run staged everything and only the swap failed (loader outcome 'lock_timeout')."""
    return failure is not None and failure.startswith(LOCK_TIMEOUT_FAILURE)


async def _decide(conn, *, head=None, current_sha: str | None = None, forced: bool = False) -> str:
    """-> 'running' | 'resume' | 'backoff' | 'requested' | 'never' | 'changed' | 'unchanged' | 'fresh', or
    'head failed' when the monthly HEAD itself raised (a network error is a skipped check, not a crash).
    `forced` (--zip): an operator-supplied file is imported whatever the monthly check or a back-off would say."""
    head = head or head_fingerprint
    s = await conn.fetchrow("SELECT * FROM socat_points_source WHERE id=1")
    started = await conn.fetchval(
        "SELECT skipped_at FROM sync_log WHERE source=$1 AND skipped_reason LIKE $2", SOURCE, R.STARTED_PREFIX + "%")
    now = datetime.now(timezone.utc)
    if started and now - started < R.STARTED_STALE:
        return "running"
    failed, requested = s["last_failed_at"], s["refresh_requested_at"]
    if failed and _swap_pending(s["last_failure"]) and _can_resume(s, current_sha):
        return "resume"                  # no back-off and no age limit: hours of staging only await their swap
    if failed and now - failed < BACKOFF and not forced and not (requested and requested > failed):
        if (_was_interrupted(s["last_failure"]) and _can_resume(s, current_sha)
                and (s["interrupt_count"] or 0) < R.MAX_SAME_POINT_INTERRUPTS):
            return "resume"
        return "backoff"
    if requested:
        return "requested"
    if s["loaded_at"] is None:
        return "never"
    if forced:
        return "requested"
    if s["last_checked_at"] and now - s["last_checked_at"] < CHECK_EVERY:
        return "fresh"
    try:
        fp = await asyncio.to_thread(head)
    except Exception as e:
        log.warning("socat-points: HEAD failed: %s: %s", type(e).__name__, e)
        return "head failed"
    if _same(s, fp):
        await conn.execute("UPDATE socat_points_source SET last_checked_at=now() WHERE id=1")
        return "unchanged"
    return "changed"


async def _stamp(conn, sql: str, *args) -> None:
    """Bookkeeping in socat_points_source must never mask the run's real outcome."""
    try:
        await conn.execute(sql, *args)
    except Exception:
        log.exception("socat-points: could not update socat_points_source")


async def _stamp_start(conn) -> int:
    """The pessimistic stamp (see the docstring): a run that is killed never reaches the clean-up and leaves
    last_failure = 'interrupted' and the point it started from. Returns interrupt_count after the stamp:
    1 the first time a resume point is stamped, +1 each time the SAME point is stamped again (the previous
    run committed nothing past it), 0 for a fresh start (no staging progress)."""
    return await conn.fetchval(
        """UPDATE socat_points_source SET
             interrupt_count = CASE WHEN staging_last_expocode IS NULL THEN NULL
                                    WHEN interrupted_expocode IS NOT DISTINCT FROM staging_last_expocode
                                         THEN COALESCE(interrupt_count, 0) + 1
                                    ELSE 1 END,
             interrupted_expocode = staging_last_expocode,
             last_failed_at = now(), last_failure = 'interrupted'
           WHERE id = 1 RETURNING COALESCE(interrupt_count, 0)""")


async def _drop_exhausted_staging(conn) -> bool:
    """Start FRESH: drop any leftover staging and reset the interrupt count. Called for every decision except
    'resume' (never / changed / requested / forced / an expired back-off window): such a run is a new attempt
    and must not trip the same-cruise cap on its first stamp (a request after one killed run would otherwise
    count 2, alert "interrupted twice" and back off with nothing run), nor back off for ever on an old count.
    The cap applies to 'resume' only. Returns True if there was a staging or a count to clear."""
    row = await conn.fetchrow("SELECT staging_sha256, interrupt_count FROM socat_points_source WHERE id = 1")
    if row["staging_sha256"] is None and not row["interrupt_count"]:
        return False
    log.warning("socat-points: leftover staging / interrupt count %s on a non-resume start — starting over",
                row["interrupt_count"])
    await discard_staging(conn)
    await conn.execute("UPDATE socat_points_source SET interrupted_expocode = NULL, interrupt_count = NULL "
                       "WHERE id = 1")
    return True


async def _stamp_outcome(conn, outcome: str) -> None:
    """What the next run's decision reads after the loader returned `outcome`."""
    if outcome in R.FAILED_OUTCOMES:
        # The loader wrote the reason text; only an untouched 'interrupted' stamp takes the outcome name.
        await _stamp(conn, "UPDATE socat_points_source SET last_failed_at = now(), last_failure = "
                     "CASE WHEN last_failure = 'interrupted' THEN $1 ELSE last_failure END WHERE id = 1", outcome)
    elif outcome == "resumable":
        # Failed after progress: the staging is kept. Leave the stamp (last_failed_at, interrupted_expocode,
        # interrupt_count) so the next run's decision is 'resume', not a back-off.
        await _stamp(conn, "UPDATE socat_points_source SET last_failed_at = now(), last_failure = "
                     "CASE WHEN last_failure = 'interrupted' THEN 'resumable' ELSE last_failure END WHERE id = 1")
    elif outcome == "lock_timeout":
        # Everything is staged, only the swap lost the lock race. Keep the failure marker (the next decision is
        # 'resume': the loader skips every committed cruise, re-validates and retries the swap) but reset the
        # interrupt state: this is not an interruption and must never count toward the same-cruise cap.
        await _stamp(conn, "UPDATE socat_points_source SET last_failed_at = now(), last_failure = "
                     "CASE WHEN last_failure LIKE 'lock_timeout%' THEN last_failure ELSE 'lock_timeout' END, "
                     "interrupted_expocode = NULL, interrupt_count = NULL WHERE id = 1")
    else:                                # swapped (the loader cleared the stamp too)
        await _stamp(conn, "UPDATE socat_points_source SET last_failed_at = NULL, last_failure = NULL, "
                     "interrupted_expocode = NULL, interrupt_count = NULL WHERE id = 1")


async def _clear_transient_skip(conn) -> None:
    """A healthy decision means the earlier deferral (low memory / disk / head failed) is over: clear its
    marker so it does not read as a standing problem. Failure markers (blocked / error ...) are left alone."""
    await _stamp(conn, "UPDATE sync_log SET skipped_reason = NULL, skipped_at = NULL WHERE source = $1 AND ("
                 + " OR ".join(f"skipped_reason LIKE ${i + 2}" for i in range(len(R.TRANSIENT_PREFIXES))) + ")",
                 SOURCE, *[p + "%" for p in R.TRANSIENT_PREFIXES])


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


async def _current_sha(conn, zip_sha: str | None) -> str | None:
    """The sha256 of the file this run would import, when it is known without a download: the --sha256 given
    with --zip, or the scratch zip a resumable run left behind. Hashed only when a staging could be resumed."""
    if zip_sha:
        return zip_sha
    if await conn.fetchval("SELECT staging_last_expocode FROM socat_points_source WHERE id=1") is None:
        return None
    zp = SCRATCH_DIR / ZIP_NAME
    return await asyncio.to_thread(sha256_of, zp) if zp.exists() else None


async def bake_tiles() -> None:
    """After a swap: pre-bake the tile cache and record the outcome in sync_log under TILES_SOURCE. Never
    raises: the data is already live; a failed bake only makes first views slower until tiles are rendered on
    demand. The logged outcome is a fixed vocabulary ("error: <ExceptionType>" / "error: bake deadline" /
    "error: consecutive timeouts" / "error: no tile version" / "skipped: version changed" /
    "skipped: N tiles timed out"), never exception text."""
    from services import socat_tiles as tiles
    started = time.monotonic()
    try:
        n, skipped = await tiles.prebake(db.pool, tiles.cache_root())
    except Exception as e:
        log.exception("socat-tiles: pre-bake failed")
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
            log.exception("socat-tiles: could not write sync_log")
        if alert:
            await notify_telegram(f"socat-tiles: pre-bake failed ({reason})", ALERT_TITLE)
        return
    log.info("socat-tiles: %d tiles baked, %d timed out, in %d s", n, skipped, time.monotonic() - started)
    try:
        if skipped:
            await log_sync_skipped(TILES_SOURCE, f"skipped: {skipped} tiles timed out")
        else:
            await log_sync(TILES_SOURCE, n, n)
            async with db.pool.acquire() as conn:
                await conn.execute("UPDATE socat_points_source SET tile_built_at = now() WHERE id = 1")
    except Exception:
        log.exception("socat-tiles: could not write the bake outcome")


async def run_once(pool, *, head=None, lock_wait_s: float | None = None, lock_poll_s: float | None = None,
                   zip_path=None, sha256: str | None = None) -> str:
    """Returns the decision when nothing was imported, else the import's outcome
    ('swapped' | 'blocked' | 'lock_timeout' | 'error' | 'schema' | 'disk' | 'resumable'), or 'low memory' | 'disk'
    | 'busy'. Every run stamps socat_points_source.last_run_at / last_decision. lock_wait_s / lock_poll_s default
    to LOCK_WAIT_S / LOCK_POLL_S (tests pass short ones). zip_path + sha256: the first import (see the docstring)."""
    db.pool = pool                       # sync_log and the loader read db.pool (see plankton_obis_worker)
    result = "error"
    try:
        result = await _run(pool, head, LOCK_WAIT_S if lock_wait_s is None else lock_wait_s,
                            LOCK_POLL_S if lock_poll_s is None else lock_poll_s, zip_path, sha256)
        return result
    finally:
        async with pool.acquire() as conn:
            await _stamp(conn, "UPDATE socat_points_source SET last_run_at = now(), last_decision = $1 WHERE id = 1",
                         result[:40])


async def _run(pool, head, lock_wait_s: float, lock_poll_s: float, zip_path, sha256) -> str:
    forced = zip_path is not None
    # ONE connection for the whole critical section: session-level advisory locks are released
    # when a pooled connection goes back (see vme_bake_worker.py).
    async with pool.acquire() as lock_conn:
        decision = await _decide(lock_conn, head=head, current_sha=await _current_sha(lock_conn, sha256),
                                 forced=forced)
        if decision in ("running", "backoff"):
            log.info("socat-points: %s — nothing to do", decision)
            return decision
        if decision in ("fresh", "unchanged"):
            log.info("socat-points: %s — nothing to do", decision)
            await _clear_transient_skip(lock_conn)
            return decision
        if decision == "head failed":
            await log_sync_skipped(SOURCE, f"{R.HEAD_FAILED_PREFIX}: monthly check skipped, will retry on the next timer run")
            return decision
        if _mem_available_kib() < MIN_AVAIL_KIB:
            await log_sync_skipped(SOURCE, f"{R.LOW_MEMORY_PREFIX}: deferred to the next timer run")
            return "low memory"
        if _disk_used_fraction() > MAX_DISK_USED:
            await log_sync_skipped(SOURCE, f"{R.DISK_PREFIX} {int(MAX_DISK_USED * 100)} %: refused")
            return "disk"
        log.info("socat-points: %s — polling advisory lock %d for up to %.0f s", decision, LOCK_KEY, lock_wait_s)
        if not await _acquire_lock(lock_conn, lock_wait_s, lock_poll_s):
            # Nothing is stamped or logged: the import is still due, tomorrow's tick tries again.
            log.warning("socat-points: advisory lock %d still held after %.0f s — exiting busy", LOCK_KEY, lock_wait_s)
            return "busy"
        try:
            # Re-decide now that we hold the lock: a run that waited behind another import must see
            # that import's result instead of importing a second time.
            decision = await _decide(lock_conn, head=head, current_sha=await _current_sha(lock_conn, sha256),
                                     forced=forced)
            if decision in ("running", "backoff", "head failed"):
                log.info("socat-points: %s after waiting for the lock — nothing to do", decision)
                return decision
            if decision in ("fresh", "unchanged"):
                log.info("socat-points: %s after waiting for the lock — nothing to do", decision)
                await _clear_transient_skip(lock_conn)
                return decision
            # Pessimistic stamp: a run that is killed (OOM, TimeoutStartSec) never reaches the stamp below, and
            # must still start the back-off — or, with progress, be resumed. Any completed outcome overwrites it.
            if decision != "resume":            # only a resume continues a staging; the cap applies to it alone
                await _drop_exhausted_staging(lock_conn)
            n_int = await _stamp_start(lock_conn)
            if n_int >= R.MAX_SAME_POINT_INTERRUPTS:
                at = await lock_conn.fetchval("SELECT interrupted_expocode FROM socat_points_source WHERE id = 1")
                log.error("socat-points: interrupted twice at %s — backing off", at)
                await notify_telegram(f"socat-points: interrupted twice at {at}; 7-day back-off", ALERT_TITLE)
                return "backoff"
            await log_sync_skipped(SOURCE, f"{R.STARTED_PREFIX} ({decision})")
            out = await sync_socat_points(zip_path=zip_path, expected_sha256=sha256, count_resume=False)
            log.info("socat-points: %s", out)
            outcome = out["outcome"]
            await _stamp_outcome(lock_conn, outcome)
            if outcome == "swapped":
                await bake_tiles()          # never raises; still holding the lock
            return outcome
        finally:
            await lock_conn.execute("SELECT pg_advisory_unlock($1)", LOCK_KEY)


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--zip", help="import this local zip instead of downloading (the first import)")
    ap.add_argument("--sha256", help="expected sha256 of --zip (required with it)")
    args = ap.parse_args(argv)
    if bool(args.zip) != bool(args.sha256):
        ap.error("--zip and --sha256 go together")
    if args.sha256:
        args.sha256 = args.sha256.strip().lower()     # sha256sum prints lowercase; the loader compares exactly
    return args


async def main(argv=None):
    args = parse_args(argv)
    load_dotenv()
    if args.zip:
        # A mistyped --sha256 must fail HERE: through the loader it would be a failed outcome and a 7-day back-off.
        actual = await asyncio.to_thread(sha256_of, pathlib.Path(args.zip))
        if actual != args.sha256:
            log.error("socat-points: %s has sha256 %s, not the --sha256 given (%s) — nothing stamped, nothing run",
                      args.zip, actual, args.sha256)
            raise SystemExit(2)
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=3)
    try:
        await run_once(pool, zip_path=args.zip, sha256=args.sha256)
    finally:
        await pool.close()


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Own process, own logging setup — see backend/log_redaction.py.
    log_redaction.install()
    asyncio.run(main())
