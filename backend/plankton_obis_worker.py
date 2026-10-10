# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Standalone, cgroup-capped OBIS plankton import worker.

Runs as its OWN systemd unit (plankton-obis.service) — never inside abyssal-api.
Triggered every 6 h by plankton-obis.timer. Whether to import is decided from
`sync_log` (the database is the memory, no local state file):

- last success younger than STALE_DAYS            -> "fresh"   (exit, nothing written)
- last run failed less than BACKOFF_DAYS ago      -> "backoff" (exit, nothing written)
- "started" marker younger than 12 h              -> "running" (another import is live; exit)
- "started" marker older than 12 h                -> a killed run: counts as failed -> "backoff"
- otherwise the import runs.

"fresh" and "backoff" are decisions, not syncs: they write nothing to `sync_log`,
so a 6-hourly tick cannot move `skipped_at` (which would restart the back-off
clock forever) or spam the monitor. A low-memory deferral DOES write a skip, with
the reason, because a due import did not happen — but it is not a failure and
never starts a back-off.

RERUN AFTER A KILL (OOM, TimeoutStartSec, SIGTERM, a manual stop). A killed run leaves its "started"
marker in sync_log; for 12 h the worker reads that as "running" and skips, afterwards as a failed run
("backoff", 7 days). To import right now, on the VPS as the service user:

    cd /home/ice13ball/something-rare/backend
    sudo systemctl start plankton-obis.service          # normal tick, honours marker / due / back-off
    .venv/bin/python -m plankton_obis_worker --force    # same environment as the unit (set -a; . .env)

`--force` skips the 30-day "fresh" check and ignores a stale OR fresh "started" marker and the
failure back-off. It still takes advisory lock 4242001 (so it cannot overlap obis-sync / vme-bake
or another import), still defers on low memory, and writes its own "started" marker and outcome.
Never run it while another import is alive: it would not know (the lock only protects the
same-lock holders), so check `systemctl status plankton-obis` first. Leftover `plankton_*_new`
tables of the killed run are dropped by the next run's build_staging.
Without `--force` nothing changes.

RESUME. `--resume` (implies --force) continues an interrupted run on the staging tables it left, instead
of starting from zero: it does NOT call build_staging (that would DROP the loaded rows). It needs
plankton_occurrences_new and plankton_datasets_new; without them it logs a warning and does a normal full
run. The done set is the ledger plankton_progress_new (one row per fully loaded dataset, written in the
same transaction as its load, so it is exact). A run that predates the ledger has none: then the done set
is the distinct dataset_id in plankton_occurrences_new, and the ledger is created and seeded from those
counts. ⚠️ That fallback assumes the stop happened while NO COPY was running: the old code loaded in
50k-row autocommitted batches, so a dataset cut off mid-load would count as done with a partial set of
rows. Before stopping such a run, check pg_stat_activity of the import's backend (no COPY running,
state idle/`active` on a non-COPY statement) — the check is the operator's. Failed datasets are never
in the ledger, so a resume retries them. Datasets already loaded keep their rows and licence as loaded.
A resumed run that fails keeps its staging (hours of work) for the next --resume; the following full run
drops it.

AGGREGATES-ONLY. `--aggregates-only` runs NO import: under the same advisory lock it rebuilds the stage-2 map
aggregates (plankton_sites / _site_facets / _grid_facets / _tile_version) from the LIVE plankton_occurrences,
swaps only them in, and pre-bakes the default tiles. Used once when the map layer is first deployed, and for
repairs. It writes no plankton-obis sync_log row (the import's freshness is unchanged).

PARALLELISM. Extract children run up to PLANKTON_PARALLEL (default 3; 1 = strictly sequential) at once,
admitted by S3 object size and a live memory guard (plankton_obis.ExtractStream); loads into Postgres stay
one at a time on one connection.

The import takes advisory lock 4242001 with a BLOCKING wait, like obis_sync_worker
and vme_bake_worker, so the three heavy jobs never run concurrently. The wait is
unbounded here by design; the unit's TimeoutStartSec is the bound.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

import asyncpg
from dotenv import load_dotenv

import db
import log_redaction
from ingestion.plankton_obis import (SOURCE, STARTED_PREFIX, STARTED_STALE_HOURS, bake_tiles,
                                     rebuild_aggregates_from_live, sync_plankton_obis)
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


async def run_once(pool, force: bool = False, resume: bool = False) -> str:
    """Returns "ran" | "fresh" | "backoff" | "running" | "low-memory".
    `force` skips both `_decide` checks (due / marker / back-off); lock, memory check and the
    run's own marker are unchanged. `resume` (the CLI makes it imply `force`) continues the staging
    tables a stopped run left; see the module docstring."""
    force = force or resume
    db.pool = pool
    # ONE connection for the whole critical section: session-level advisory locks are
    # released when a pooled connection goes back (see vme_bake_worker.py).
    async with pool.acquire() as lock_conn:
        decision = None if force else await _decide(lock_conn)
        if decision:
            log.info("plankton-obis: %s — nothing to do", decision)
            return decision
        if force:
            log.warning("plankton-obis: --force — ignoring the due check, the started marker and the back-off")
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
            decision = None if force else await _decide(lock_conn)
            if decision:
                log.info("plankton-obis: %s after waiting for the lock — nothing to do", decision)
                return decision
            res = await sync_plankton_obis(resume=True) if resume else await sync_plankton_obis()
            log.info("plankton-obis: %s", res)
            return "ran"
        finally:
            await lock_conn.execute("SELECT pg_advisory_unlock($1)", LOCK_KEY)


async def rebuild_map(pool) -> str:
    """--aggregates-only: under advisory lock LOCK_KEY (so it never overlaps an import, obis-sync or
    vme-bake), rebuild the stage-2 aggregates from the live table. Returns "aggregates"."""
    db.pool = pool
    async with pool.acquire() as lock_conn:
        log.info("plankton-obis: --aggregates-only, waiting for advisory lock %d", LOCK_KEY)
        await lock_conn.execute("SELECT pg_advisory_lock($1)", LOCK_KEY)
        try:
            version = await rebuild_aggregates_from_live(lock_conn)
            log.info("plankton-obis: aggregates rebuilt from the live table, version %s", version)
            await bake_tiles()          # still under the lock: no import can swap underneath the bake
        finally:
            await lock_conn.execute("SELECT pg_advisory_unlock($1)", LOCK_KEY)
    return "aggregates"


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--force", action="store_true",
                    help="import now: skip the due check and any started marker (lock and memory check stay)")
    ap.add_argument("--resume", action="store_true",
                    help="continue the staging tables of a stopped run (implies --force); see the docstring")
    ap.add_argument("--aggregates-only", action="store_true",
                    help="no import: rebuild the map aggregates from the live table and pre-bake the tiles")
    ns = ap.parse_args(argv)
    if ns.aggregates_only and (ns.force or ns.resume):
        ap.error("--aggregates-only runs no import: it cannot be combined with --force or --resume")
    ns.force = ns.force or ns.resume
    return ns


async def main(force: bool = False, resume: bool = False, aggregates_only: bool = False):
    load_dotenv()
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=3)
    try:
        if aggregates_only:
            await rebuild_map(pool)
        else:
            await run_once(pool, force=force, resume=resume)
    finally:
        await pool.close()


if __name__ == "__main__":
    cli = parse_args()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Own process, own logging setup — see backend/log_redaction.py.
    log_redaction.install()
    asyncio.run(main(force=cli.force, resume=cli.resume, aggregates_only=cli.aggregates_only))
