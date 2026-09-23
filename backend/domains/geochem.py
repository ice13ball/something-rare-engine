# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Geochem — five frozen-archive marine chemistry/biology sources whose read
paths are mostly MVT tiles served by `backend/routers/spatial_v2.py`, so only
four hex-density endpoints move with them: MEMENTO (dissolved CH4/N2O),
GEOTRACES (dissolved trace metals), SEAFLEA (observed methane seeps), MOSAIC
(sediment core carbon/nitrogen isotopes), and WOD oxygen profiles (no
endpoint of its own — it's tile-only, see below).

Moved verbatim out of backend/main.py (Task 5 of the backend vertical-split
refactor, Phase 2). Only permitted edits applied: `@app.get` -> `@router.get`,
`_pool` -> `db.pool` (both the `.acquire()` and bare-argument forms —
`wod_oxygen_ingest.sync_wod_oxygen(_pool, ...)` passes the pool object
itself, not just `.acquire()`), leading underscore dropped from every moved
top-level function name (`_sync_wod_oxygen` -> `sync_wod_oxygen`,
`_recompute_memento_atmospheric` -> `recompute_memento_atmospheric`,
`_sync_memento` -> `sync_memento`, `_sync_geotraces` -> `sync_geotraces`,
`_sync_mosaic` -> `sync_mosaic`, `_sync_seaflea` -> `sync_seaflea`, and the
two mosaic-only helpers `_mosaic_tiles`/`_fetch_mosaic_analysis` ->
`mosaic_tiles`/`fetch_mosaic_analysis` — same "drop underscore from every
moved function, not just the sync_* ones" rule Task 6/Phase 1 established for
offshore's shared helpers), and imports/docstring. Module-level *constants*
(non-callables) keep their leading underscore, matching acoustic.py's
`_ACOUSTIC_SOURCE_TIMEOUT_S` precedent: `_MOSAIC_GEO_URL`, `_MOSAIC_SAMP_URL`,
`_MEMENTO_ATM_SQL`, `_MEMENTO_SURF_SQL`, and the three cache globals.

## MEMENTO: atmospheric vs dissolved gas — read before touching this data

MEMENTO declares `CH4` as BOTH `Methane_Ocean [nmol/l]` AND
`Methane_Atmosphere [ppb]`, separated by a `parameterType` the CSV export
does not emit — both spheres land in the same `ch4` column (same for `n2o`).
`ch4_is_atmospheric`/`n2o_is_atmospheric` are **platform-derived** flags
(never MEMENTO's own), computed by `recompute_memento_atmospheric()` from a
per-gas, per-value rule: MEMENTO's own `_Air`-suffixed `label` OR (this
cruise's median for that gas >= threshold AND this value >= threshold). The
two SQL constants' raw-string (r-prefixed triple-quoted) requirement — the
backslash-escaped underscore in the `LIKE` pattern matching `_Air` suffixes
must survive Python untouched, or the flagged-sample count silently drops
from 7,461 to 3,531.

## SEAFLEA: survey-biased, not a completeness map

10,385 SEAFLEA records come from 32 `source_ref` bibliographies, and a
single BOEM Gulf-of-Mexico seismic gallery supplies 59% of them. **An absent
seep dot means an absent survey, not an absent seep** — never use this layer
to conclude a region has no natural methane source. There is deliberately no seep-proximity code anywhere in
the backend.

## `_recompute_memento_atmospheric` has two call paths — both preserved here

It is registered under its own admin action key `memento-flags`
(`main.py` `_SOURCE_TO_ACTION`/`_SYNC_SOURCES`, now
`geochem.recompute_memento_atmospheric()`) **and** it is called from inside
`sync_memento` (module-internal call, no `geochem.` prefix needed — both
live in this file). It is idempotent and credential-free; the
`main.py` lambda comment noting exactly that stays put.

## Caches — none swept, all three still registered

`_geotraces_hex_cache`, `_mosaic_hexes_cache`, `_methane_seeps_cache` were
never among the hand-cleared lines in `admin_cache_clear` — no line comes out
of it for this task. All three still live in this module's `clear_caches()`
and the domain is still registered in `CACHE_CLEARING_DOMAINS`, per the
uniform contract `backend/tests/test_domain_cache_clear.py` enforces.

There is no `_memento_hex_cache`: `memento_hexes()` queries `memento_casts`
JOINed against `density_hex_cells` fresh on every request — no cache
variable, and it does not read the shared `response_cache` leaf either (that
leaf is for `geo_context`'s EEZ/protected-sites TTL cache, a different
mechanism entirely).

`_cascade_stations_cache`/`_cascade_meta_cache` were declared immediately
next to the three geochem caches in main.py (same `_geotraces_hex_cache =
None` block) but belong to the CASCADE Arctic sediment-carbon layer, a
different domain not covered by this task — left in main.py, unmoved, at the
time. They have since moved to `domains/arctic.py` (Phase 4).

`wod-oxygen` has no endpoint of its own in this module: its read path is
MVT tiles (`/v2/spatial/tiles/wod-oxygen/{z}/{x}/{y}`) served by
`routers/spatial_v2.py`, which is unaffected by this move — `sync_wod_oxygen`
still calls `clear_layer_tile_cache("wod-oxygen")` from there at the end of
every sync, imported inline exactly as main.py did.
"""

from __future__ import annotations

import asyncio
import json
import logging

import db
from auth import get_api_key
from domains import geochem_sql
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from ingestion import marhys_ingest
from ingestion import seaflea_ingest
from ingestion import wod_oxygen_ingest
from sync_log import log_sync as _log_sync

log = logging.getLogger(__name__)
router = APIRouter()

# ── Caches ──────────────────────────────────────────────────────────────────
_geotraces_hex_cache: str | None = None
_mosaic_hexes_cache: str | None = None
_methane_seeps_cache: str | None = None
_marhys_cache: str | None = None
_marhys_meta_cache: str | None = None


def clear_caches() -> None:
    """Drop this domain's cached responses. Called by /admin/cache/clear."""
    global _geotraces_hex_cache, _mosaic_hexes_cache, _methane_seeps_cache
    global _marhys_cache, _marhys_meta_cache
    _geotraces_hex_cache = None
    _mosaic_hexes_cache = None
    _methane_seeps_cache = None
    _marhys_cache = None
    _marhys_meta_cache = None


async def sync_wod_oxygen(force: bool = False, min_lat: float = -90.0) -> int:
    """WOD global oxygen profiles. Heavy one-time seed — admin-triggered. Guard skips
    if already seeded (unless force). Resumable per-year inside sync_wod_oxygen.

    `min_lat` is passed explicitly: the ingest module defaults to 50.0 (its original
    Arctic scope), but the shipped layer is global, so a force re-sync must not
    silently amputate everything south of 50N.
    """
    if not force:
        async with db.pool.acquire() as conn:
            last = await conn.fetchval("SELECT last_synced_at FROM sync_log WHERE source = 'wod-oxygen'")
        if last is not None:
            await _log_sync("wod-oxygen", 0, 0)
            return 0
    parsed, inserted = await wod_oxygen_ingest.sync_wod_oxygen(db.pool, force=force, min_lat=min_lat)
    # The sync rewrites the whole table, so every cached tile is stale. Without this
    # the disk cache keeps serving dots rendered from the previous data (and any
    # 0-byte timeout tiles stay poisoned indefinitely).
    from routers.spatial_v2 import clear_layer_tile_cache
    clear_layer_tile_cache("wod-oxygen")
    await _log_sync("wod-oxygen", parsed, inserted)
    return inserted


# Per-gas atmospheric flags. Cruise median spans ALL depths (air rows are not
# reliably shallow — FPN-92_Air is recorded at 46 m) and excludes _Air rows.
_MEMENTO_ATM_SQL = r"""
WITH med AS (
    SELECT c.set_name,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY s.ch4) FILTER (WHERE s.ch4 > 0) AS ch4_med,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY s.n2o) FILTER (WHERE s.n2o > 0) AS n2o_med
    FROM memento_samples s
    JOIN memento_casts c USING (cast_id)
    WHERE s.label IS NULL OR s.label NOT LIKE '%\_Air'
    GROUP BY c.set_name
)
UPDATE memento_samples s
SET ch4_is_atmospheric = COALESCE(s.label LIKE '%\_Air', FALSE)
                         OR COALESCE(m.ch4_med >= $1 AND s.ch4 >= $1, FALSE),
    n2o_is_atmospheric = COALESCE(s.label LIKE '%\_Air', FALSE)
                         OR COALESCE(m.n2o_med >= $2 AND s.n2o >= $2, FALSE)
FROM memento_casts c, med m
WHERE c.cast_id = s.cast_id AND m.set_name = c.set_name
"""

# Recompute OUR OWN cast rollup from water-only samples: shallowest positive value
# that is neither atmospheric nor MEMENTO's flag-9 missing-as-zero sentinel.
_MEMENTO_SURF_SQL = r"""
UPDATE memento_casts k
SET ch4_surf = w.ch4_surf,
    n2o_surf = w.n2o_surf
FROM (
    SELECT s.cast_id,
           (ARRAY_AGG(s.ch4 ORDER BY s.depth_m NULLS LAST)
              FILTER (WHERE s.ch4 > 0
                        AND NOT COALESCE(s.ch4_is_atmospheric, FALSE)
                        AND COALESCE((s.params->>'ch4_flag')::int, 0) <> 9))[1] AS ch4_surf,
           (ARRAY_AGG(s.n2o ORDER BY s.depth_m NULLS LAST)
              FILTER (WHERE s.n2o > 0
                        AND NOT COALESCE(s.n2o_is_atmospheric, FALSE)
                        AND COALESCE((s.params->>'n2o_flag')::int, 0) <> 9))[1] AS n2o_surf
    FROM memento_samples s GROUP BY s.cast_id
) w
WHERE w.cast_id = k.cast_id
"""


async def recompute_memento_atmospheric() -> int:
    """Idempotent: set the two derived per-gas flags, then recompute our own
    memento_casts rollup from water-only samples. Touches NO upstream value.

    The `_Air` label and `<gas>_flag == 9` are MEMENTO's own annotations; the
    cruise-median test is OUR inference and is disclosed as platform-derived in
    the panel, the legend, and the export provenance note.
    """
    from ingestion.memento_ingest import GAS_THRESHOLD  # runtime sys.path is backend/
    from routers.spatial_v2 import clear_layer_tile_cache

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            res = await conn.execute(
                _MEMENTO_ATM_SQL, GAS_THRESHOLD["ch4"], GAS_THRESHOLD["n2o"]
            )
            await conn.execute(_MEMENTO_SURF_SQL)
    clear_layer_tile_cache("memento")
    n = int(res.split()[-1]) if res else 0
    await _log_sync("memento-flags", n, n)
    log.info("memento: recomputed atmospheric flags on %d samples", n)
    return n


async def sync_memento(force: bool = False) -> int:
    """One-time authenticated scrape of all MEMENTO legs (one request per leg to
    avoid the portal's large-request bug). Frozen archive: re-run only via admin
    Force Sync. Credentials from env; never stored."""
    import os
    from ingestion import memento_ingest
    email = os.getenv("MEMENTO_EMAIL"); pw = os.getenv("MEMENTO_PASSWORD")
    if not email or not pw:
        log.error("memento: MEMENTO_EMAIL/MEMENTO_PASSWORD not set — skipping")
        await _log_sync("memento", 0, 0)
        return 0
    # ⛔ EVERY LINE OF THE SCRAPE RUNS IN A THREAD. `memento_ingest` uses `requests`,
    # which is synchronous: 313 legs at one blocking HTTP call each. Called directly
    # from this coroutine it holds the event loop for the whole scrape, and a FastAPI
    # process that cannot reach its event loop answers nothing at all.
    #
    # That is not hypothetical. On 2026-09-08, minutes after MEMENTO credentials were
    # added to the VPS for the first time, this function took production down: the
    # public /health timed out, every layer timed out, and the service still reported
    # `active` because the process was alive and merely blocked. The bug had sat here
    # harmlessly for months only because MEMENTO_EMAIL was never set, so the guard
    # above returned early every single time. Supplying a credential armed it.
    #
    # `asyncio.to_thread` is what the seaflea sync in this same file already does.
    def _scrape() -> tuple[list, list, list]:
        session = memento_ingest.login_session(email, pw)
        legs = memento_ingest.fetch_leg_index(session)
        samples: list = []
        failed: list = []
        for leg in legs:
            try:
                csv_text = memento_ingest.download_leg_csv(session, leg["id"])
                samples.extend(memento_ingest.build_samples(csv_text, leg["name"]))
            except Exception as e:  # one bad leg must not abort the whole scrape
                failed.append(leg["name"])
                log.warning("memento: leg %s (%s) failed: %s", leg["id"], leg["name"], e)
        return legs, samples, failed

    legs, all_samples, failed_legs = await asyncio.to_thread(_scrape)
    if not all_samples:
        log.error("memento: scrape produced 0 samples — keeping existing data")
        await _log_sync("memento", 0, 0)
        return 0

    # ⛔ load_memento TRUNCATEs before inserting, and its docstring claimed the empty
    # check above made that safe. It does not. A PARTIAL scrape sails through it.
    # On 2026-09-08 two legs died on a momentary "Connection refused" from the portal
    # and the run replaced a complete table with one 9,831 casts smaller — 155,418
    # down to 145,587 — reporting success the whole way, because losing a leg is only
    # a WARNING and the totals it printed were the totals it had.
    #
    # So a scrape that lost legs may only publish if it still carries MORE than what
    # is already stored. Retrying costs four minutes; the truncate is not reversible.
    if failed_legs:
        async with db.pool.acquire() as conn:
            existing = await conn.fetchval("SELECT count(*) FROM memento_samples") or 0
        if len(all_samples) < existing:
            log.error(
                "memento: %d of %d legs failed (%s) and the scrape carries %d samples "
                "against %d already stored — REFUSING to truncate. Existing data kept; "
                "re-run when the portal is healthy.",
                len(failed_legs), len(legs), ", ".join(failed_legs[:5]),
                len(all_samples), existing)
            await _log_sync("memento", 0, 0)
            return 0
        log.warning("memento: %d legs failed but the scrape still carries %d samples "
                    "against %d stored — publishing",
                    len(failed_legs), len(all_samples), existing)
    # derive_casts is pure CPU over ~200k samples — also off the loop.
    casts = await asyncio.to_thread(memento_ingest.derive_casts, all_samples)
    inserted = await memento_ingest.load_memento(db.pool, all_samples, casts)
    from routers.spatial_v2 import clear_tile_cache
    clear_tile_cache()
    # derive_casts can only apply the label / flag-9 half of the rule (it sees one
    # cast at a time). The cruise-median half needs the whole archive.
    await recompute_memento_atmospheric()
    await _log_sync("memento", len(all_samples), inserted)
    log.info("memento: %d legs, %d samples, %d casts", len(legs), inserted, len(casts))
    return inserted


async def sync_geotraces(force: bool = False) -> int:
    """GEOTRACES IDP2025 — ALL 386 measured parameters, not just the five
    dissolved trace metals (Mn/Fe/Co/Ni/Cu) that were kept historically. Those
    five still populate the wide geotraces_samples/geotraces_stations columns
    unchanged (additive design — nothing consuming them was touched); every
    other parameter lands in geotraces_values/geotraces_params.

    Frozen archive: skip if table is already populated unless force=True.
    Admin Force Sync passes force=True. Download is ~260 MB (measured
    2026-09-08 — an earlier docstring here claimed ~1.5 GB; it did not).

    Both the download/extract and the CSV parse are CPU/IO-bound and run via
    asyncio.to_thread — a synchronous 268 MB download+parse on the event loop
    is exactly what took production down once already (MEMENTO, same day).
    The CSV itself is streamed row-by-row (csv.reader over a file handle),
    never read whole into memory.
    """
    from ingestion import geotraces_ingest as gt
    if not force:
        existing_stations = await db.pool.fetchval("SELECT count(*) FROM geotraces_stations") or 0
        existing_values = await db.pool.fetchval("SELECT count(*) FROM geotraces_values") or 0
        # "Populated" must mean fully populated, not just "load() got as far as
        # stations". load_values_from_csv() now runs in one transaction, so a
        # failed values load rolls back to 0 rows on its own — but this check
        # also protects against any partial state left by a run before that
        # fix (or a future bug that bypasses the transaction). A silent
        # skip-forever here is exactly DEFECT 2, 2026-09-08 audit.
        #
        # ⚠️ This whole `if not force:` block is UNREACHABLE as wired today.
        # The single call site is main.py's admin sync map, which passes
        # force=True, and geotraces is not in the periodic sync chain. So what
        # actually recovers a partial load is that every admin-triggered run
        # truncates and reloads unconditionally — NOT this check. Kept because
        # it becomes live the moment anyone adds a scheduled geotraces sync,
        # and a frozen 260 MB archive is exactly the kind of layer someone
        # will eventually put on a cadence. ⛔ Do not cite it as the guarantee.
        if existing_stations > 0 and existing_values == 0:
            log.warning(
                "geotraces: %s stations present but geotraces_values is EMPTY — "
                "a previous sync left a PARTIAL load. Reloading despite force=False.",
                existing_stations)
        elif existing_stations > 0:
            log.info("geotraces: %s stations already present — skip (use force)", existing_stations)
            return 0
    import tempfile, shutil
    tmp = tempfile.mkdtemp(prefix="geotraces-")
    try:
        csv_path = await asyncio.to_thread(gt.fetch_and_extract, tmp)
        samples, stations, units, params_meta = await asyncio.to_thread(
            gt.parse_samples_and_meta, csv_path
        )
        # load() carries the anti-truncation guard: refuses to publish (and
        # returns 0) if this parse yielded fewer samples than are already
        # stored, WITHOUT touching the table or the sync log.
        inserted = await gt.load(db.pool, samples, stations, units, params_meta)
        if inserted == 0:
            # load() already logged the refusal reason. Do NOT call _log_sync
            # here — stamping last_synced_at on a refused/skipped parse would
            # hide from the monitor that nothing was actually published.
            return 0
        n_values = await gt.load_values_from_csv(db.pool, csv_path, params_meta)
        await _log_sync("geotraces", len(samples), inserted)
        from routers.spatial_v2 import clear_tile_cache
        clear_tile_cache()
        global _geotraces_hex_cache
        _geotraces_hex_cache = None
        log.info("geotraces: loaded %s samples / %s stations / %s values across %s params",
                  inserted, len(stations), n_values, len(params_meta))
        return inserted
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


_MOSAIC_GEO_URL = "https://mosaicprd.ethz.ch/api/mosaic_app/geopoints"
_MOSAIC_SAMP_URL = "https://mosaicprd.ethz.ch/api/mosaic_app/samples"


def mosaic_tiles(step: int = 30):
    """Coarse global bbox grid; each analysis is fetched per tile to dodge the ~36MB
    global-TOC IncompleteRead and per-request 500s."""
    tiles = []
    lat = -90
    while lat < 90:
        lon = -180
        while lon < 180:
            tiles.append((lat, min(lat + step, 90), lon, min(lon + step, 180)))
            lon += step
        lat += step
    return tiles


async def _mosaic_get_with_retry(client, url, *, label, params=None, retries=3):
    """Same backoff `fetch_mosaic_analysis` already used, made callable.

    ⛔ The seed request had none of it. `_MOSAIC_GEO_URL` is the FIRST call of
    the sync and the one that produces every core; a single transient failure
    there aborted the run with zero cores written, while each of the ~200
    per-tile sample requests below it retried three times. That is the exact
    shape of the /argo/vocabulary defect (2026-09-09): one 429 on the opening
    call threw away a whole run whose every later call was protected.

    Returns the parsed body, or raises the last error — the caller decides,
    because a seed failure and a tile failure do not mean the same thing.
    """
    last = None
    for attempt in range(retries):
        try:
            r = await client.get(url, params=params, timeout=180)
            if r.status_code == 200:
                return r.json()
            last = RuntimeError(f"HTTP {r.status_code}")
            log.warning("mosaic: %s -> HTTP %s (attempt %d)", label, r.status_code, attempt + 1)
        except Exception as exc:
            last = exc
            log.warning("mosaic: %s -> %s (attempt %d)", label, exc, attempt + 1)
        await asyncio.sleep(2 * (attempt + 1))
    raise last if last else RuntimeError(f"mosaic: {label} failed")


async def fetch_mosaic_analysis(client, api_name, tile, retries=3):
    lat0, lat1, lon0, lon1 = tile
    params = {
        "latitude": str((lat0, lat1)), "longitude": str((lon0, lon1)),
        "analyses": api_name, "material_analyzed": "bulk,TOC",
        "references": "True", "method": "True", "method_details": "True",
        "calculated_column": "False", "material_analyzed_column": "True",
        "sampling_date": "True",
        "sampling_campaign": "True",
        "core_comment": "True",
    }
    for attempt in range(retries):
        try:
            r = await client.get(_MOSAIC_SAMP_URL, params=params, timeout=180)
            if r.status_code == 200:
                return r.json()
            log.warning("mosaic: %s tile %s -> HTTP %s (attempt %d)", api_name, tile, r.status_code, attempt + 1)
        except Exception as exc:  # IncompleteRead, timeout, conn reset
            log.warning("mosaic: %s tile %s -> %s (attempt %d)", api_name, tile, exc, attempt + 1)
        await asyncio.sleep(2 * (attempt + 1))
    return []


async def sync_mosaic(force: bool = False) -> int:
    if db.pool is None:
        log.warning("mosaic: no pool"); return 0
    if not force:
        existing = await db.pool.fetchval("SELECT count(*) FROM mosaic_cores")
        if existing and existing > 0:
            log.info("mosaic: already populated (%d cores) — skip (force=True to reload)", existing); return 0
    from ingestion import mosaic_ingest as mi
    import httpx
    async with httpx.AsyncClient() as client:
        # 1) cores
        geo = await _mosaic_get_with_retry(client, _MOSAIC_GEO_URL, label="geopoints seed")
        cores = mi.parse_geopoints(geo)
        # 2) per-analysis, bbox-tiled sections
        by_analysis = {}
        for api_name, var_key in mi.MOSAIC_ANALYSES:
            frags = {}
            for tile in mosaic_tiles():
                rows = await fetch_mosaic_analysis(client, api_name, tile)
                if rows:
                    frags.update(mi.parse_samples(rows, var_key, api_name))
            by_analysis[var_key] = frags
            log.info("mosaic: %s -> %d sections", api_name, len(frags))
    sections = mi.merge_sections(by_analysis)
    roll = mi.core_rollups(sections)
    # 3) write
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("TRUNCATE mosaic_samples; TRUNCATE mosaic_cores CASCADE;")
            for c in cores:
                r = roll.get(c["core_id"], {})
                await conn.execute(
                    """INSERT INTO mosaic_cores
                       (core_id, core_name, latitude, longitude, water_depth_m, sampling_year, decade,
                        sampling_method, research_vessel, seas, eez, longhurst,
                        has_toc, has_tn, has_d13c, has_d14c, toc_surf, tn_surf, d13c_surf, d14c_surf,
                        sampling_date, sampling_month, sampling_day,
                        campaign_name, campaign_start, campaign_end,
                        core_comment, date_precision, geom)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,
                               $21,$22,$23,$24,$25,$26,$27,$28,
                               ST_SetSRID(ST_MakePoint($4,$3),4326))
                       ON CONFLICT (core_id) DO NOTHING""",
                    c["core_id"], c["core_name"], c["latitude"], c["longitude"], c["water_depth_m"],
                    c["sampling_year"], c["decade"], c["sampling_method"], c["research_vessel"],
                    c["seas"], c["eez"], c["longhurst"],
                    r.get("has_toc", False), r.get("has_tn", False), r.get("has_d13c", False), r.get("has_d14c", False),
                    r.get("toc_surf"), r.get("tn_surf"), r.get("d13c_surf"), r.get("d14c_surf"),
                    c["sampling_date"], c["sampling_month"], c["sampling_day"],
                    c["campaign_name"], c["campaign_start"], c["campaign_end"],
                    c["core_comment"], c["date_precision"],
                )
            core_ll = {c["core_id"]: (c["latitude"], c["longitude"]) for c in cores}
            for s in sections:
                ll = core_ll.get(s["core_id"])
                if ll is None:
                    continue
                await conn.execute(
                    """INSERT INTO mosaic_samples
                       (sample_id, core_id, depth_upper_cm, depth_bottom_cm, depth_avg_cm,
                        material_analyzed, replicate, toc, tn, d13c, d14c, fm14c, provenance, geom)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13::jsonb,
                               ST_SetSRID(ST_MakePoint($15,$14),4326))
                       ON CONFLICT (sample_id) DO NOTHING""",
                    s["sample_id"], s["core_id"], s["depth_upper_cm"], s["depth_bottom_cm"], s["depth_avg_cm"],
                    s["material_analyzed"], s["replicate"], s.get("toc"), s.get("tn"), s.get("d13c"),
                    s.get("d14c"), s.get("fm14c"), json.dumps(s["prov"]), ll[0], ll[1],
                )
    await _log_sync("mosaic", len(sections), len(cores))
    log.info("mosaic: %d cores, %d sections", len(cores), len(sections))
    return len(cores)


async def sync_seaflea(force: bool = False) -> int:
    """SEAFLEA observed methane-seep source locations (NRL / NOAA NCEI).

    Static frozen dataset (Feb 2019): skip if the table is already populated
    unless force=True. Admin Force Sync passes force=True.
    """
    assert db.pool is not None
    async with db.pool.acquire() as conn:
        existing = await conn.fetchval("SELECT COUNT(*) FROM seaflea_seeps")
    if not force and existing and existing > 0:
        log.info("seaflea: skipping — %d rows already present (static dataset)", existing)
        return 0

    try:
        gj = await asyncio.to_thread(seaflea_ingest.fetch_seaflea_geojson)
    except Exception as e:  # network / upstream failure — keep existing data
        log.error("seaflea: fetch failed (%s) — keeping existing %d rows", e, existing or 0)
        return 0

    rows = seaflea_ingest.build_seep_rows(gj)
    if not rows:
        log.warning("seaflea: parser returned 0 rows — preserving existing data")
        return 0

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("TRUNCATE seaflea_seeps RESTART IDENTITY")
            await conn.executemany(
                """INSERT INTO seaflea_seeps
                     (ext_id, lat, lon, depth_m, obs_year, loc_uncert_m,
                      feature_types, primary_type, type_raw, source_ref, source_url,
                      pockmark_depth_m, pockmark_radius_m, geom)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11,$12,$13,
                           ST_SetSRID(ST_MakePoint($3,$2),4326))""",
                [(r["ext_id"], r["lat"], r["lon"], r["depth_m"], r["obs_year"],
                  r["loc_uncert_m"], r["feature_types"], r["primary_type"],
                  json.dumps(r["type_raw"]), r["source_ref"], r["source_url"],
                  r["pockmark_depth_m"], r["pockmark_radius_m"]) for r in rows],
            )

    global _methane_seeps_cache
    _methane_seeps_cache = None
    await _log_sync("seaflea", len(rows), len(rows))
    log.info("seaflea: inserted %d seep points", len(rows))
    return len(rows)


# ── MARHYS ──────────────────────────────────────────────────────────────────
#
# ⭐ THE COLUMN LIST IS DERIVED FROM THE PARSER, NOT RETYPED. A field added to
# `marhys_ingest._NUMERIC_COLUMNS` but forgotten here would not raise anything —
# the value would simply never reach the database, and the layer would look
# complete while quietly missing an element. Building the statement from the
# same maps the parser uses makes that drift impossible.
_MARHYS_TEXT_FIELDS = list(marhys_ingest._TEXT_COLUMNS.values())
_MARHYS_NUMBER_FIELDS = [field for field, _unit in marhys_ingest._NUMERIC_COLUMNS.values()]
_MARHYS_FIELDS = _MARHYS_TEXT_FIELDS + _MARHYS_NUMBER_FIELDS + ["coord_status"]

_MARHYS_COLUMNS = ["source_row", *_MARHYS_FIELDS, "params"]
_MARHYS_PLACEHOLDERS = ", ".join(f"${i}" for i in range(1, len(_MARHYS_COLUMNS) + 1))
_MARHYS_LAT = _MARHYS_COLUMNS.index("lat") + 1
_MARHYS_LON = _MARHYS_COLUMNS.index("lon") + 1

# ⛔ The geometry is built ONLY where the source's coordinates are usable. 844
# samples carry no position and 39 carry `Latitude = 111.4` (the Guaymas rows,
# whose axes the source transposed). Those rows still land in the table, with
# their numbers intact and `geom` NULL — `ST_MakePoint` would otherwise either
# throw or, worse, quietly accept an impossible latitude.
_MARHYS_INSERT = f"""
    INSERT INTO marhys_samples ({", ".join(_MARHYS_COLUMNS)}, geom)
    VALUES ({_MARHYS_PLACEHOLDERS},
            -- ⚠️ The casts are required, not decoration. Inside `abs()` and
            -- `ST_MakePoint()` alone Postgres cannot infer a parameter's type
            -- and refuses to prepare the statement with
            -- "could not determine data type of parameter".
            CASE WHEN ${_MARHYS_LAT}::double precision IS NOT NULL
                  AND ${_MARHYS_LON}::double precision IS NOT NULL
                  AND abs(${_MARHYS_LAT}::double precision) <= 90
                  AND abs(${_MARHYS_LON}::double precision) <= 180
                 THEN ST_SetSRID(ST_MakePoint(${_MARHYS_LON}::double precision,
                                              ${_MARHYS_LAT}::double precision), 4326)
            END)
    ON CONFLICT (source_row) DO UPDATE SET
        {", ".join(f"{c} = EXCLUDED.{c}" for c in _MARHYS_COLUMNS[1:])},
        geom = EXCLUDED.geom
"""


async def sync_marhys(force: bool = False) -> int:
    """MARHYS 4.0 hydrothermal fluid chemistry. Frozen archive — seeded once.

    Source: Diehl, A; Bach, W (2024): MARHYS Database 4.0. PANGAEA,
    https://doi.org/10.1594/PANGAEA.972999 — CC-BY-4.0.
    ⭐ The publisher requires the base publication to be cited alongside it:
    Diehl & Bach (2020), https://doi.org/10.1029/2020GC009385.

    ⚠️ Version 4.0 is immutable behind its DOI, so re-running this spends 5.1 MB
    to insert nothing. The guard below makes that a deliberate act (`force`)
    rather than a schedule. A version 5.0 would carry a different DOI and is a
    new ingest, not a silent update to this one.
    """
    if not force:
        async with db.pool.acquire() as conn:
            seeded = await conn.fetchval(
                "SELECT last_synced_at FROM sync_log WHERE source = 'marhys'"
            )
        if seeded is not None:
            await _log_sync("marhys", 0, 0)
            return 0

    blob = await marhys_ingest.fetch_marhys_workbook()
    parsed = marhys_ingest.parse_marhys(blob)
    records = parsed["records"]
    if not records:
        await _log_sync("marhys", 0, 0)
        log.warning("marhys: workbook parsed to zero records — nothing written")
        return 0

    rows = [
        tuple(
            [record["source_row"]]
            + [record[field] for field in _MARHYS_FIELDS]
            # allow_nan=False: a bare NaN survives Python's round-trip and only
            # explodes at the jsonb cast, far from its cause.
            + [json.dumps(record["params"], allow_nan=False)]
        )
        for record in records
    ]

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(_MARHYS_INSERT, rows)
            await conn.execute(
                """INSERT INTO marhys_meta (version, param_units, updated_at)
                   VALUES ($1, $2, now())
                   ON CONFLICT (version) DO UPDATE
                   SET param_units = EXCLUDED.param_units, updated_at = now()""",
                marhys_ingest.MARHYS_VERSION,
                json.dumps(parsed["param_units"], allow_nan=False),
            )
        placed = await conn.fetchval(
            "SELECT count(*) FROM marhys_samples WHERE geom IS NOT NULL"
        )

    global _marhys_cache, _marhys_meta_cache
    _marhys_cache = None
    _marhys_meta_cache = None
    await _log_sync("marhys", len(records), len(rows))
    log.info(
        "marhys: %d samples stored, %d placeable on the map (%d without a usable position)",
        len(records), placed, len(records) - placed,
    )
    return len(rows)


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/v1/map/memento/hexes", dependencies=[Depends(get_api_key)])
async def memento_hexes():
    """Per-hexagon cast counts over the shared density_hex_cells grid, with a
    per-decade histogram so the client can filter by decade locally."""
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable")
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(geochem_sql.MEMENTO_HEX_SQL)
    return geochem_sql.hex_feature_collection(rows)


@router.get("/v1/map/geotraces/hexes", dependencies=[Depends(get_api_key)])
async def geotraces_hexes():
    """Per-hexagon station counts over the shared density_hex_cells grid, with
    a per-decade histogram so the client can filter by decade locally."""
    global _geotraces_hex_cache
    if _geotraces_hex_cache is not None:
        return Response(content=_geotraces_hex_cache, media_type="application/json")
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable")
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(geochem_sql.GEOTRACES_HEX_SQL)
    payload = json.dumps(geochem_sql.hex_feature_collection(rows))
    _geotraces_hex_cache = payload
    return Response(content=payload, media_type="application/json")


@router.get("/v1/map/mosaic/hexes", dependencies=[Depends(get_api_key)])
async def mosaic_hexes():
    """Per-hexagon station counts over the shared density_hex_cells grid."""
    global _mosaic_hexes_cache
    if _mosaic_hexes_cache is not None:
        return Response(content=_mosaic_hexes_cache, media_type="application/json")
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable")
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(geochem_sql.MOSAIC_HEX_SQL)
    payload = json.dumps(geochem_sql.hex_feature_collection(rows))
    _mosaic_hexes_cache = payload
    return Response(content=payload, media_type="application/json")


@router.get("/v1/map/methane-seeps", dependencies=[Depends(get_api_key)])
async def get_methane_seeps():
    global _methane_seeps_cache
    if _methane_seeps_cache:
        return Response(content=_methane_seeps_cache, media_type="application/json")
    assert db.pool is not None
    async with db.pool.acquire() as conn:
        txt = await conn.fetchval("""
            SELECT json_build_object(
              'type','FeatureCollection',
              'features', COALESCE(json_agg(json_build_object(
                'type','Feature',
                'geometry', ST_AsGeoJSON(geom)::json,
                'properties', json_build_object(
                  'ext_id', ext_id,
                  'primary_type', primary_type,
                  'feature_types', to_json(feature_types),
                  'type_raw', type_raw,
                  'depth_m', depth_m,
                  'obs_year', obs_year,
                  'loc_uncert_m', loc_uncert_m,
                  'pockmark_depth_m', pockmark_depth_m,
                  'pockmark_radius_m', pockmark_radius_m,
                  'source_ref', source_ref,
                  'source_url', source_url
                )
              )), '[]'::json)
            )::text
            FROM seaflea_seeps
        """)
    _methane_seeps_cache = txt or '{"type":"FeatureCollection","features":[]}'
    return Response(content=_methane_seeps_cache, media_type="application/json")


# ── MARHYS endpoints ────────────────────────────────────────────────────────
#
# ⚠️ `/meta` IS DECLARED BEFORE `/{source_row}` ON PURPOSE. FastAPI matches in
# declaration order; the other way round, a request for `/meta` would be handed
# to the integer route and answered with a 422.

# ⛔ THE PAYLOAD CARRIES THE WHOLE RECORD, AND THAT IS THE POINT. This project
# forbids a detail panel from fetching on click — every enriched value must come
# from properties already in hand, or opening a sample shows a spinner. Measured
# 2026-09-23 over all 5,905 placeable samples:
#
#     identity only       1.50 MB   ->  0.10 MB gzipped
#     every named column  7.62 MB   ->  0.52 MB gzipped
#     plus `params`       8.12 MB   ->  0.65 MB gzipped
#
# ⚠️ Cloud Run's 32 MiB response ceiling applies BEFORE compression, so 8.12 MB
# is the number that has to fit, and it does with room to spare.
#
# `to_jsonb(m) - 'geom'` rather than a hand-written field list: a column added to
# the table reaches the client without anyone remembering to add it here, which
# is the same drift the insert statement avoids by deriving its column list from
# the parser.
_MARHYS_LIST_SQL = """
    SELECT json_build_object(
      'type','FeatureCollection',
      'features', COALESCE(json_agg(json_build_object(
        'type','Feature',
        'geometry', ST_AsGeoJSON(geom)::json,
        'properties', to_jsonb(m) - 'geom'
      )), '[]'::json)
    )::text
    FROM marhys_samples m
    WHERE geom IS NOT NULL
"""


@router.get("/v1/map/marhys", dependencies=[Depends(get_api_key)])
async def get_marhys():
    """Every MARHYS sample the source placed well enough to map."""
    global _marhys_cache
    if _marhys_cache:
        return Response(content=_marhys_cache, media_type="application/json")
    assert db.pool is not None
    async with db.pool.acquire() as conn:
        txt = await conn.fetchval(_MARHYS_LIST_SQL)
    _marhys_cache = txt or '{"type":"FeatureCollection","features":[]}'
    return Response(content=_marhys_cache, media_type="application/json")


@router.get("/v1/map/marhys/meta", dependencies=[Depends(get_api_key)])
async def get_marhys_meta():
    """Units, attribution, and an honest account of what is NOT on the map.

    ⛔ `unplaceable` is not decoration. 883 of 6,788 samples cannot be given a
    position, and a layer that silently renders 5,905 dots while calling itself
    "6,788 samples" is making a claim it cannot support. The counts are served
    so the interface can say which is which.
    """
    global _marhys_meta_cache
    if _marhys_meta_cache:
        return Response(content=_marhys_meta_cache, media_type="application/json")
    assert db.pool is not None
    async with db.pool.acquire() as conn:
        units = await conn.fetchval(
            "SELECT param_units::text FROM marhys_meta ORDER BY version DESC LIMIT 1"
        )
        by_status = await conn.fetch(
            "SELECT coord_status, count(*) AS n FROM marhys_samples GROUP BY 1"
        )
        by_type = await conn.fetch(
            """SELECT sample_type,
                      count(*) AS n,
                      count(*) FILTER (WHERE geom IS NOT NULL) AS mapped
               FROM marhys_samples GROUP BY 1 ORDER BY 1"""
        )
        total = await conn.fetchval("SELECT count(*) FROM marhys_samples")

    payload = {
        "version": marhys_ingest.MARHYS_VERSION,
        "doi": marhys_ingest.MARHYS_DOI,
        "base_publication_doi": marhys_ingest.MARHYS_BASE_PUBLICATION_DOI,
        "licence": "CC-BY-4.0",
        "citation": (
            "Diehl, Alexander; Bach, Wolfgang (2024): MARHYS Database 4.0 "
            "[dataset]. PANGAEA, https://doi.org/10.1594/PANGAEA.972999"
        ),
        "total_samples": total,
        "coord_status": {r["coord_status"]: r["n"] for r in by_status},
        "sample_types": [
            {"code": r["sample_type"], "total": r["n"], "mapped": r["mapped"]}
            for r in by_type
        ],
        # asyncpg hands JSONB back as a string; decode it here or the client gets
        # a JSON-encoded JSON string and every lookup on it fails.
        "param_units": json.loads(units) if units else {},
    }
    _marhys_meta_cache = json.dumps(payload, allow_nan=False)
    return Response(content=_marhys_meta_cache, media_type="application/json")


@router.get("/v1/map/marhys/{source_row}", dependencies=[Depends(get_api_key)])
async def get_marhys_sample(source_row: int):
    """One sample in full, including the sparse tail.

    Reachable for samples with no geometry too — an unplaceable sample is still
    a real measurement, and the only way to see it is by its row.
    """
    assert db.pool is not None
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM marhys_samples WHERE source_row = $1", source_row
        )
    if row is None:
        raise HTTPException(status_code=404, detail="no such MARHYS sample")

    record = {k: v for k, v in dict(row).items() if k != "geom"}
    params = record.get("params")
    record["params"] = json.loads(params) if isinstance(params, str) else (params or {})
    return Response(
        content=json.dumps(record, allow_nan=False, default=str),
        media_type="application/json",
    )
