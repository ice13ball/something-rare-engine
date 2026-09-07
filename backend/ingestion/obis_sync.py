# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""OBIS biodiversity sync — shared module.

Used by both abyssal-api (admin force-sync) and obis-sync.service (scheduled
weekly run). Neither process imports the other; both import this module.

Source: s3://obis-open-data/occurrence/*.parquet (AWS Open Data Sponsorship,
no egress fees). ~6,880 parquet files scanned locally via DuckDB in batches.
Filter strategy: curated species list derived from existing biodiversity_hotspots
rows — no depth cutoff (shallow records of deep-sea species are relevant for
offshore-claim areas on the continental shelf).
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from datetime import datetime, timezone

import asyncpg

from ingestion.obis_parquet import fetch_deep_occurrences_for_species

_hotspot_grid_lock = asyncio.Lock()
_log = logging.getLogger("obis_sync")

_INSERT_SQL = """
    INSERT INTO biodiversity_hotspots
           (obis_id, scientific_name, phylum, class_name, order_name,
            family, depth, geom, dataset_id, occurrence_id)
    VALUES ($1, $2, $3, $4, $5, $6, $7,
            ST_SetSRID(ST_MakePoint($8, $9), 4326), $10, $11)
    ON CONFLICT (obis_id) DO UPDATE
       SET dataset_id    = EXCLUDED.dataset_id,
           occurrence_id = EXCLUDED.occurrence_id
     WHERE biodiversity_hotspots.dataset_id    IS DISTINCT FROM EXCLUDED.dataset_id
        OR biodiversity_hotspots.occurrence_id IS DISTINCT FROM EXCLUDED.occurrence_id
"""

# Which rows the snapshot still carries is recorded in a side table rather than a
# `last_seen_at` column on the rows themselves. Under MVCC an UPDATE writes a new
# row version, so stamping a column every pass would rewrite all ~33M rows weekly
# — gigabytes of WAL and heap bloat to record something the pass already knows.
# An UNLOGGED side table costs no WAL and leaves the main table untouched except
# where something genuinely changed.
# obis_id is TEXT on biodiversity_hotspots, so this column is TEXT too: PostgreSQL
# has no implicit uuid=text cast, and a UUID column here would make the anti-join
# below fail outright with "operator does not exist".
_SEEN_DDL = """
    DROP TABLE IF EXISTS obis_seen;
    CREATE UNLOGGED TABLE obis_seen (obis_id TEXT);
"""

# Rows absent from the current snapshot are deleted, not flagged. OBIS regenerates
# `_id` whenever a contributor republishes a dataset, so a republication orphans a
# whole generation of rows: they duplicate the records that replaced them, and
# their obis.org/occurrence/<id> links no longer resolve. Presence in the current
# snapshot is the only thing that distinguishes a live row from an orphan, and it
# cannot be derived from our own table.
_PURGE_SQL = """
    DELETE FROM biodiversity_hotspots bh
     WHERE NOT EXISTS (SELECT 1 FROM obis_seen s WHERE s.obis_id = bh.obis_id)
"""

# A pass that dies halfway records only part of the snapshot, and purging against
# that would delete most of the table. Refuse unless the pass observed at least
# this share of what was there beforehand.
_PURGE_MIN_STAMPED_RATIO = 0.5

# `_coverage_complete` (files_ok == files_total) cannot detect a *short* S3
# listing: files_total is derived from the same listing, so if DuckDB's glob
# returns a truncated set, every listed file reads fine and coverage looks total.
# The independent signal is history — the largest catalogue listing we have ever
# seen. Refuse to purge when this run's listing dropped below this fraction of
# that high-water mark. Fail-safe in the right direction: a false trip only skips
# a purge (orphans linger), it never deletes. Stored in sync_log under a
# dedicated pseudo-source so no new table/migration is needed; total_records
# holds the file count. A genuine, sustained OBIS shrinkage below the ratio keeps
# skipping purges (visible in the logs) until an operator resets the HWM row.
_CATALOGUE_MIN_RATIO = 0.9
_CATALOGUE_HWM_SOURCE = "obis-parquet-files-hwm"


def _catalogue_short(files_total: int, hwm: int | None,
                     ratio: float = _CATALOGUE_MIN_RATIO) -> bool:
    """True if this pass's parquet-file listing is suspiciously smaller than the
    largest we've ever recorded — the fingerprint of a truncated listing that
    `_coverage_complete` would otherwise wave through. No history yet (first
    pass) → cannot compare, so returns False and the row-count ratio guards."""
    if not hwm:
        return False  # no history to compare against; 0.5 row-ratio still guards
    return files_total < hwm * ratio


async def _catalogue_hwm(pool: asyncpg.Pool) -> int | None:
    """Largest parquet-file count seen on a prior coverage-complete pass."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT total_records FROM sync_log WHERE source = $1",
            _CATALOGUE_HWM_SOURCE,
        )


async def _record_catalogue_hwm(pool: asyncpg.Pool, files_total: int) -> None:
    """Raise the high-water mark to `files_total` (never lowers it — GREATEST)."""
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO sync_log (source, last_synced_at, records_added, total_records)
               VALUES ($1, NOW(), $2, $2)
               ON CONFLICT (source) DO UPDATE
               SET last_synced_at = NOW(),
                   records_added = EXCLUDED.records_added,
                   total_records = GREATEST(sync_log.total_records, EXCLUDED.total_records)""",
            _CATALOGUE_HWM_SOURCE, files_total,
        )


async def _log_sync(pool: asyncpg.Pool, source: str, added: int, total: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO sync_log (source, last_synced_at, records_added, total_records)
               VALUES ($1, NOW(), $2, $3)
               ON CONFLICT (source) DO UPDATE
               SET last_synced_at = NOW(), records_added = $2, total_records = $3""",
            source, added, total,
        )


async def is_obis_paused(pool: asyncpg.Pool) -> bool:
    async with pool.acquire() as conn:
        return bool(await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM paused_syncs WHERE action = 'obis')"
        ))


# Mutual exclusion between OBIS passes. Deliberately NOT 4242001: that one
# serializes obis against vme-bake and is already held by `obis_sync_worker` on a
# connection of its own, so re-taking it here from a different pool connection
# would block the worker on itself forever.
#
# Two passes can genuinely overlap — the weekly worker and an admin force-sync via
# /admin/sync/obis, which calls straight into this module from inside abyssal-api.
# They would share one `obis_seen` table and the later DROP would discard the ids
# the earlier pass had already recorded, leaving a purge to run against a set that
# never described any single pass.
_OBIS_SELF_LOCK = 4242002


async def sync_obis(pool: asyncpg.Pool) -> int:
    """Run one OBIS pass, refusing to start if another is already running."""
    # The lock is held for the whole pass — hours. It gets a connection of its own
    # rather than one from the pool: both pools are `max_size=4`, and the API's
    # serves the entire site, so parking one of those four for the duration of an
    # admin force-sync would starve it.
    lock_conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        if not await lock_conn.fetchval("SELECT pg_try_advisory_lock($1)", _OBIS_SELF_LOCK):
            _log.warning(
                "biodiversity_hotspots: another OBIS pass holds the lock — skipping this run"
            )
            return 0
        try:
            return await _sync_obis_inner(pool, lock_conn)
        finally:
            await lock_conn.execute("SELECT pg_advisory_unlock($1)", _OBIS_SELF_LOCK)
    finally:
        await lock_conn.close()  # closing would release the lock anyway


async def _sync_obis_inner(pool: asyncpg.Pool, lock_conn: asyncpg.Connection) -> int:
    """Full OBIS sync via S3 parquet (DuckDB).

    Downloads parquet files in batches of 200, queries with DuckDB against
    our curated species list, and upserts into biodiversity_hotspots.
    Full catalog pass in ~20-40 min vs 7+ h for the REST path.

    Skips if last sync was within 20 h — prevents crash-restart tight loops.
    """
    async with pool.acquire() as conn:
        last_sync = await conn.fetchval(
            "SELECT last_synced_at FROM sync_log WHERE source = 'biodiversity_hotspots'"
        )
        if last_sync is not None:
            age_hours = (datetime.now(tz=timezone.utc) - last_sync).total_seconds() / 3600
            if age_hours < 20:
                _log.info(
                    "biodiversity_hotspots: skipping sync — last run %.1fh ago (< 20h)",
                    age_hours,
                )
                return 0

        species: list[str] = [
            r["scientific_name"]
            for r in await conn.fetch(
                "SELECT DISTINCT scientific_name FROM biodiversity_hotspots "
                "WHERE scientific_name IS NOT NULL"
            )
        ]

    if not species:
        _log.warning("biodiversity_hotspots: no species in DB — nothing to filter parquet by; skipping")
        return 0

    _log.info("biodiversity_hotspots: starting parquet sync for %d species", len(species))

    async with pool.acquire() as conn:
        total_before = await conn.fetchval("SELECT COUNT(*) FROM biodiversity_hotspots")
        await conn.execute(_SEEN_DDL)

    # A purge is only safe after a pass that ran to completion over every parquet
    # file. `drained`/`producer_failed` catch an aborted run; `parquet_stats`
    # catches the subtler case where the run finished normally but individual
    # batches were skipped (failed download or failed query) — the generator warns
    # and continues, so reaching the end proves nothing about coverage.
    drained = False
    producer_failed = False
    parquet_stats: dict[str, int] = {}

    loop = asyncio.get_running_loop()
    chunk_queue: asyncio.Queue[list | None] = asyncio.Queue(maxsize=4)
    stop_producing = threading.Event()

    def _produce() -> None:
        """Run DuckDB iteration in a thread; push chunks to asyncio queue.

        Checks ``stop_producing`` each batch so that if the consumer exits
        early (error/cancel) we break out — closing the generator, which runs
        its per-batch ``finally`` tempdir cleanup — instead of stranding the
        thread blocked on a full queue with a live multi-GB scratch dir.
        """
        try:
            for chunk in fetch_deep_occurrences_for_species(species, stats=parquet_stats):
                if stop_producing.is_set():
                    break
                asyncio.run_coroutine_threadsafe(chunk_queue.put(chunk), loop).result()
        finally:
            asyncio.run_coroutine_threadsafe(chunk_queue.put(None), loop).result()

    producer = loop.run_in_executor(None, _produce)

    inserted = 0
    try:
        while True:
            chunk = await chunk_queue.get()
            if chunk is None:
                drained = True
                break
            rows = [
                (
                    r["obis_id"],
                    r["scientific_name"],
                    r["phylum"],
                    r["class_name"],
                    r["order_name"],
                    r["family"],
                    r["depth"],
                    float(r["lon"]),
                    float(r["lat"]),
                    r.get("dataset_id"),
                    r.get("occurrence_id"),
                )
                for r in chunk
                if r.get("obis_id") and r.get("lat") is not None and r.get("lon") is not None
            ]
            if not rows:
                continue
            async with pool.acquire() as conn:
                for i in range(0, len(rows), 500):
                    await conn.executemany(_INSERT_SQL, rows[i:i + 500])
                # COPY, not executemany: this is one column over tens of millions
                # of rows and the only thing asked of it is bulk throughput.
                await conn.copy_records_to_table(
                    "obis_seen", records=[(r[0],) for r in rows], columns=["obis_id"],
                )
            inserted += len(rows)
            if inserted % 500_000 == 0:
                _log.info("biodiversity_hotspots: %d rows inserted so far…", inserted)
    finally:
        # Guarantee the producer thread unwinds so the generator's per-batch
        # tempdir cleanup runs even if the consumer errored or was cancelled.
        stop_producing.set()
        while not producer.done():
            try:
                chunk_queue.get_nowait()
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.05)
        try:
            await asyncio.wrap_future(producer)
        except Exception:
            producer_failed = True
            _log.exception("obis producer thread errored during shutdown")

    covered = _coverage_complete(parquet_stats)
    if not covered:
        _log.warning(
            "biodiversity_hotspots: read %d of %d parquet files — coverage incomplete",
            parquet_stats.get("files_ok", 0), parquet_stats.get("files_total", 0),
        )

    # Independent guard against a *short* listing that `covered` cannot see
    # (files_total comes from the same listing). Compare against the largest
    # catalogue we have ever recorded.
    files_total = parquet_stats.get("files_total", 0)
    hwm = await _catalogue_hwm(pool)
    catalogue_short = _catalogue_short(files_total, hwm)
    if catalogue_short:
        _log.error(
            "biodiversity_hotspots: parquet listing returned %d files vs high-water "
            "mark %d (< %.0f%%) — listing looks truncated; refusing to purge",
            files_total, hwm or 0, _CATALOGUE_MIN_RATIO * 100,
        )
    elif covered:
        # Only a trustworthy full listing may raise the bar the next run is held to.
        await _record_catalogue_hwm(pool, files_total)

    purged = await _purge_stale(
        pool, total_before, lock_conn,
        complete=drained and not producer_failed and covered and not catalogue_short,
    )

    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM biodiversity_hotspots")
    await _log_sync(pool, "biodiversity_hotspots", inserted, total)
    _log.info(
        "biodiversity_hotspots: parquet sync complete — %d rows upserted, "
        "%d stale purged / %d total",
        inserted, purged, total,
    )
    return inserted


def _coverage_complete(stats: dict[str, int]) -> bool:
    """Did the pass read every parquet file in the catalogue?

    Unpopulated stats mean the generator never reported — treat that as NOT
    covered. Defaulting the other way would make an empty dict silently authorise
    a purge, which is precisely the failure this guard exists to prevent.
    """
    total = stats.get("files_total", 0)
    return bool(total) and stats.get("files_ok", 0) == total


async def _purge_stale(
    pool: asyncpg.Pool,
    total_before: int,
    lock_conn: asyncpg.Connection,
    *,
    complete: bool,
) -> int:
    """Delete rows the just-finished pass did not observe in the OBIS snapshot.

    Three independent conditions must all hold, because each catches a different
    way a pass can look finished without being trustworthy:

    * `complete` — the run drained its queue AND read every parquet file;
    * the advisory lock is still ours, so `obis_seen` describes only this pass;
    * the pass observed at least half of what was already stored, which is the
      backstop for the case the other two cannot see: a catalogue listing that
      came back short, making partial coverage look total.
    """
    if not complete:
        _log.warning(
            "biodiversity_hotspots: pass incomplete — skipping stale purge "
            "(orphaned rows stay until a full pass succeeds)"
        )
        return 0

    # An advisory lock dies with its session. If the pool connection holding ours
    # was reset during a multi-hour pass, another run could have started and
    # rewritten `obis_seen` underneath us — so re-verify rather than assume.
    still_locked = await lock_conn.fetchval(
        "SELECT count(*) FROM pg_locks "
        " WHERE locktype = 'advisory' AND pid = pg_backend_pid() AND granted"
    )
    if not still_locked:
        _log.error(
            "biodiversity_hotspots: advisory lock no longer held — refusing to purge "
            "(obis_seen may describe a different pass)"
        )
        return 0

    async with pool.acquire() as conn:
        seen = await conn.fetchval("SELECT COUNT(*) FROM obis_seen")
        if total_before and seen < total_before * _PURGE_MIN_STAMPED_RATIO:
            _log.error(
                "biodiversity_hotspots: pass observed only %d rows against %d already "
                "stored (< %.0f%%) — refusing to purge; investigate before re-running",
                seen, total_before, _PURGE_MIN_STAMPED_RATIO * 100,
            )
            return 0

        await conn.execute("CREATE INDEX ON obis_seen (obis_id)")
        await conn.execute("ANALYZE obis_seen")
        status = await conn.execute(_PURGE_SQL)
        await conn.execute("DROP TABLE IF EXISTS obis_seen")

    deleted = int(status.split()[-1]) if status.startswith("DELETE") else 0
    if deleted:
        _log.info(
            "biodiversity_hotspots: purged %d rows absent from the current OBIS "
            "snapshot (retired or republished ids)", deleted,
        )
    return deleted


async def rebuild_hotspot_grid(pool: asyncpg.Pool) -> int:
    """Rebuild the pre-computed hotspot_grid table for map rendering at low zoom.

    Two resolutions:
    - coarse (2.0°): ~500-800 cells, for zoom 3-5
    - fine (0.5°): ~5,000-8,000 cells, for zoom 6-7

    Single-pass CTE touches biodiversity_hotspots exactly once.
    """
    if _hotspot_grid_lock.locked():
        _log.info("hotspot_grid: rebuild already in progress, skipping duplicate call")
        return 0
    async with _hotspot_grid_lock:
        total = 0
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SET LOCAL statement_timeout = '20min'")
                await conn.execute("SET LOCAL max_parallel_workers_per_gather = 0")
                await conn.execute("TRUNCATE hotspot_grid")
                for res, step in [("coarse", 2.0), ("fine", 0.5)]:
                    await conn.execute(f"""
                    WITH cell_species AS (
                        SELECT
                            ST_SnapToGrid(geom, {step})    AS cell,
                            scientific_name,
                            COALESCE(iucn_category, 'NE')  AS iucn_cat,
                            count(*)                        AS records
                        FROM biodiversity_hotspots
                        WHERE geom IS NOT NULL
                        GROUP BY 1, scientific_name, iucn_category
                    ),
                    cell_stats AS (
                        SELECT
                            cell,
                            sum(records)                                                                      AS total_count,
                            count(DISTINCT scientific_name)                                                   AS species_count,
                            count(DISTINCT CASE WHEN iucn_cat IN ('CR','EN','VU') THEN scientific_name END)  AS endangered_count,
                            count(DISTINCT CASE WHEN iucn_cat IN ('CR','EN')      THEN scientific_name END)  AS cr_en_count
                        FROM cell_species
                        GROUP BY cell
                    ),
                    ranked AS (
                        SELECT *,
                               row_number() OVER (
                                   PARTITION BY cell
                                   ORDER BY CASE iucn_cat
                                                WHEN 'CR' THEN 1 WHEN 'EN' THEN 2 WHEN 'VU' THEN 3
                                                WHEN 'NT' THEN 4 WHEN 'LC' THEN 5 ELSE 6 END,
                                            records DESC
                               ) AS rn
                        FROM cell_species
                    ),
                    cell_top AS (
                        SELECT cell,
                               jsonb_agg(
                                   jsonb_build_object('name', scientific_name, 'iucn', iucn_cat, 'records', records)
                                   ORDER BY CASE iucn_cat
                                                WHEN 'CR' THEN 1 WHEN 'EN' THEN 2 WHEN 'VU' THEN 3
                                                WHEN 'NT' THEN 4 WHEN 'LC' THEN 5 ELSE 6 END,
                                            records DESC
                               ) AS top_species
                        FROM ranked
                        WHERE rn <= 5
                        GROUP BY cell
                    )
                    INSERT INTO hotspot_grid
                        (resolution, cell_lon, cell_lat, total_count, species_count,
                         endangered_count, cr_en_count, top_species, geom)
                    SELECT
                        $1,
                        ST_X(s.cell),
                        ST_Y(s.cell),
                        s.total_count,
                        s.species_count,
                        s.endangered_count,
                        s.cr_en_count,
                        t.top_species,
                        ST_SetSRID(ST_MakePoint(ST_X(s.cell), ST_Y(s.cell)), 4326)
                    FROM cell_stats s
                    LEFT JOIN cell_top t ON t.cell = s.cell
                    """, res)
                    cnt = await conn.fetchval(
                        "SELECT count(*) FROM hotspot_grid WHERE resolution = $1", res
                    )
                    _log.info("hotspot_grid: %s — %d cells", res, cnt)
                    total += cnt

        _log.info("hotspot_grid: rebuild complete — %d total cells", total)
        return total
