# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""GLODAPv3 bottle import — its own process under deploy/glodap-bottles.service (MemoryMax=1.5G).

Daily timer; exits in seconds unless the layer was never loaded, a refresh was requested, or the
source changed (HEAD at most once per 30 days). ⛔ Never imported by main.py: the API process does
not run this. The admin force-sync only records `refresh_requested_at`
(`domains.glodap_points.request_refresh`); this worker picks it up on its next timer tick.

Decisions (`_decide`), all read from `glodap_bottle_source` and `sync_log`:

- `running`   a "started" marker in sync_log younger than 6 h (STARTED_STALE): another import is live.
- `backoff`   the last import failed (`blocked` / `error` / `schema`, or the process died mid-run) less than
              7 days ago. An explicit refresh request made AFTER the failure bypasses it. `low memory`,
              `disk` and `head failed` never start a back-off: nothing was downloaded.
- `requested` `refresh_requested_at` is set.
- `never`     `loaded_at` is null.
- `busy`      (after the decision, before the import) the shared advisory lock stayed taken for the whole
              wait budget (LOCK_WAIT_S, 2 h). Writes NOTHING: no sync_log row, no failure stamp, no back-off, no
              scratch or staging yet; the import is still due and the next timer tick tries again.
- `fresh`     checked within the last 30 days: no network call.
- `unchanged` the monthly HEAD found the same release.
- `changed`   the monthly HEAD found a different release.

## What goes where (the healthy-skip convention)

Decisions that import nothing because nothing is due (`running`, `backoff`, `busy`, `fresh`, `unchanged`) write NOTHING
to sync_log: the same convention as the scheduler's cadence gate (scheduling.py `_slow_sources_sync_task`:
`should_sync` is logged to the journal only, ingestion/cadence.py) and as plankton_obis_worker.py (`fresh` /
`backoff` / `running` "write nothing"). A skip row there is read as "the last run failed" (domains/plankton.py
`_classify`), and a daily one would also erase the loader's "swapped, but <rejects>" note. Instead every run
stamps `glodap_bottle_source.last_run_at` / `last_decision`, so "ran, found nothing" is distinguishable from
"never ran". A deferral that DID leave an import due (`low memory:`, `disk above`, `head failed:`) is written
with log_sync_skipped, like plankton's low-memory skip; those prefixes are not failures, and the next healthy
decision clears them. The last load's reject counts live in `glodap_bottle_source.last_rejects` (+ `_at`),
the failure stamp in `last_failed_at` / `last_failure`.

The import takes advisory lock 4242001, the one obis_sync_worker, vme_bake_worker and plankton_obis_worker
share, so the heavy jobs never run concurrently. Unlike them it does NOT wait blockingly: plankton may hold the
lock for up to 12 h, and a blocking wait counts against the unit's TimeoutStartSec, so a run that queued late
would be killed MID-IMPORT (an 'interrupted' stamp = a 7-day back-off, ~1 GB of scratch and a half-built
glodap_casts_new left behind). The lock is polled with pg_try_advisory_lock for at most LOCK_WAIT_S; past that
the run exits as `busy` before anything exists to clean up. TimeoutStartSec (6 h) = the 2 h wait + a full
import (the real file's import time is measured at the first run) with margin; STARTED_STALE equals it.
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
from ingestion.glodap_bottles import SCRATCH_DIR, head_fingerprint, sync_glodap_bottles
from ingestion.glodap_bottles_rules import (  # noqa: F401  (re-exported: tests and callers read them here)
    DISK_PREFIX, FAILED_OUTCOMES, HEAD_FAILED_PREFIX, LOW_MEMORY_PREFIX, SOURCE, STARTED_PREFIX, STARTED_STALE,
    TRANSIENT_PREFIXES)
from sync_log import log_sync_skipped

log = logging.getLogger("glodap_bottles_worker")
LOCK_KEY = 4242001                       # shared with obis_sync_worker, vme_bake_worker, plankton_obis_worker
CHECK_EVERY = timedelta(days=30)
MIN_AVAIL_KIB = 3 * 1024 * 1024
MAX_DISK_USED = 0.80                     # disk-guard warns at 85 %, stops services at 90 %
LOCK_WAIT_S = 2 * 3600                   # poll budget for the shared lock; see the module docstring
LOCK_POLL_S = 30.0
BACKOFF = timedelta(days=7)              # after a failed import, like plankton_obis_worker.BACKOFF_DAYS


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


async def _decide(conn, *, head=None) -> str:
    """-> 'running' | 'backoff' | 'requested' | 'never' | 'changed' | 'unchanged' | 'fresh', or 'head failed'
    when the monthly HEAD itself raised (a network error is a skipped check, not a crash)."""
    head = head or head_fingerprint
    s = await conn.fetchrow("SELECT * FROM glodap_bottle_source WHERE id=1")
    started = await conn.fetchval(
        "SELECT skipped_at FROM sync_log WHERE source=$1 AND skipped_reason LIKE $2", SOURCE, STARTED_PREFIX + "%")
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
    if s["last_checked_at"] and now - s["last_checked_at"] < CHECK_EVERY:
        return "fresh"
    try:
        fp = await asyncio.to_thread(head)
    except Exception as e:
        log.warning("glodap-bottles: HEAD failed: %s: %s", type(e).__name__, e)
        return "head failed"
    if _same(s, fp):
        await conn.execute("UPDATE glodap_bottle_source SET last_checked_at=now() WHERE id=1")
        return "unchanged"
    return "changed"


async def _stamp(conn, sql: str, *args) -> None:
    """Bookkeeping in glodap_bottle_source must never mask the run's real outcome."""
    try:
        await conn.execute(sql, *args)
    except Exception:
        log.exception("glodap-bottles: could not update glodap_bottle_source")


async def _clear_transient_skip(conn) -> None:
    """A healthy decision means the earlier deferral (low memory / disk / head failed) is over: clear its
    marker so it does not read as a standing problem. Failure markers (blocked / error ...) are left alone."""
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


async def run_once(pool, *, head=None, lock_wait_s: float | None = None, lock_poll_s: float | None = None) -> str:
    """Returns the decision when nothing was imported, else the import's outcome
    ('swapped' | 'blocked' | 'lock_timeout' | 'error' | 'schema'), or 'low memory' | 'disk' | 'busy'.
    Every run stamps glodap_bottle_source.last_run_at / last_decision. lock_wait_s / lock_poll_s default to
    LOCK_WAIT_S / LOCK_POLL_S (tests pass short ones)."""
    db.pool = pool                       # sync_log and the loader read db.pool (see plankton_obis_worker)
    result = "error"
    try:
        result = await _run(pool, head, LOCK_WAIT_S if lock_wait_s is None else lock_wait_s,
                            LOCK_POLL_S if lock_poll_s is None else lock_poll_s)
        return result
    finally:
        async with pool.acquire() as conn:
            await _stamp(conn, "UPDATE glodap_bottle_source SET last_run_at = now(), last_decision = $1 WHERE id = 1",
                         result)


async def _run(pool, head, lock_wait_s: float, lock_poll_s: float) -> str:
    # ONE connection for the whole critical section: session-level advisory locks are released
    # when a pooled connection goes back (see vme_bake_worker.py).
    async with pool.acquire() as lock_conn:
        decision = await _decide(lock_conn, head=head)
        if decision in ("running", "backoff"):
            log.info("glodap-bottles: %s — nothing to do", decision)
            return decision
        if decision in ("fresh", "unchanged"):
            log.info("glodap-bottles: %s — nothing to do", decision)
            await _clear_transient_skip(lock_conn)
            return decision
        if decision == "head failed":
            await log_sync_skipped(SOURCE, f"{HEAD_FAILED_PREFIX}: monthly check skipped, will retry on the next timer run")
            return decision
        if _mem_available_kib() < MIN_AVAIL_KIB:
            await log_sync_skipped(SOURCE, f"{LOW_MEMORY_PREFIX}: deferred to the next timer run")
            return "low memory"
        if _disk_used_fraction() > MAX_DISK_USED:
            await log_sync_skipped(SOURCE, f"{DISK_PREFIX} {int(MAX_DISK_USED * 100)} %: refused")
            return "disk"
        log.info("glodap-bottles: %s — polling advisory lock %d for up to %.0f s", decision, LOCK_KEY, lock_wait_s)
        if not await _acquire_lock(lock_conn, lock_wait_s, lock_poll_s):
            # Nothing is stamped or logged: the import is still due, tomorrow's tick tries again.
            log.warning("glodap-bottles: advisory lock %d still held after %.0f s — exiting busy", LOCK_KEY,
                        lock_wait_s)
            return "busy"
        try:
            # Re-decide now that we hold the lock: a run that waited behind another import must see
            # that import's result instead of importing a second time.
            decision = await _decide(lock_conn, head=head)
            if decision in ("running", "backoff", "head failed"):
                log.info("glodap-bottles: %s after waiting for the lock — nothing to do", decision)
                return decision
            if decision in ("fresh", "unchanged"):
                log.info("glodap-bottles: %s after waiting for the lock — nothing to do", decision)
                await _clear_transient_skip(lock_conn)
                return decision
            await log_sync_skipped(SOURCE, f"{STARTED_PREFIX} ({decision})")
            # Pessimistic stamp: a run that is killed (OOM, TimeoutStartSec) never reaches the stamp below, and
            # must still start the back-off. Any completed outcome overwrites it; a swap clears it.
            await _stamp(lock_conn, "UPDATE glodap_bottle_source SET last_failed_at = now(), "
                         "last_failure = 'interrupted' WHERE id = 1")
            out = await sync_glodap_bottles()
            log.info("glodap-bottles: %s", out)
            outcome = out["outcome"]
            if outcome in FAILED_OUTCOMES:
                await _stamp(lock_conn, "UPDATE glodap_bottle_source SET last_failed_at = now(), last_failure = $1 "
                             "WHERE id = 1", outcome)
            else:                           # swapped (the loader cleared it too) or lock_timeout (transient)
                await _stamp(lock_conn, "UPDATE glodap_bottle_source SET last_failed_at = NULL, last_failure = NULL "
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
    # Own process, own logging setup — see backend/log_redaction.py.
    log_redaction.install()
    asyncio.run(main())
