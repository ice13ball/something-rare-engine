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
from ingestion import seaflea_ingest
from ingestion import wod_oxygen_ingest
from sync_log import log_sync as _log_sync

log = logging.getLogger(__name__)
router = APIRouter()

# ── Caches ──────────────────────────────────────────────────────────────────
_geotraces_hex_cache: str | None = None
_mosaic_hexes_cache: str | None = None
_methane_seeps_cache: str | None = None


def clear_caches() -> None:
    """Drop this domain's cached responses. Called by /admin/cache/clear."""
    global _geotraces_hex_cache, _mosaic_hexes_cache, _methane_seeps_cache
    _geotraces_hex_cache = None
    _mosaic_hexes_cache = None
    _methane_seeps_cache = None


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
    session = memento_ingest.login_session(email, pw)
    legs = memento_ingest.fetch_leg_index(session)
    all_samples = []
    for leg in legs:
        try:
            csv_text = memento_ingest.download_leg_csv(session, leg["id"])
            all_samples.extend(memento_ingest.build_samples(csv_text, leg["name"]))
        except Exception as e:  # one bad leg must not abort the whole scrape
            log.warning("memento: leg %s (%s) failed: %s", leg["id"], leg["name"], e)
    if not all_samples:
        log.error("memento: scrape produced 0 samples — keeping existing data")
        await _log_sync("memento", 0, 0)
        return 0
    casts = memento_ingest.derive_casts(all_samples)
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
    """GEOTRACES IDP2025 dissolved trace-metal profiles (Mn/Fe/Co/Ni/Cu).

    Frozen archive: skip if table is already populated unless force=True.
    Admin Force Sync passes force=True. Download is ~1.5 GB; admin-only.
    """
    from ingestion import geotraces_ingest as gt
    if not force:
        existing = await db.pool.fetchval("SELECT count(*) FROM geotraces_stations")
        if existing and existing > 0:
            log.info("geotraces: %s stations already present — skip (use force)", existing)
            return 0
    import tempfile, shutil
    tmp = tempfile.mkdtemp(prefix="geotraces-")
    try:
        csv_path = gt.fetch_and_extract(tmp)
        with open(csv_path, encoding="utf-8", errors="replace") as f:
            samples, units = gt.build_samples(f.read())
        stations = gt.derive_stations(samples)
        inserted = await gt.load(db.pool, samples, stations, units)
        await _log_sync("geotraces", len(samples), inserted)
        from routers.spatial_v2 import clear_tile_cache
        clear_tile_cache()
        global _geotraces_hex_cache
        _geotraces_hex_cache = None
        log.info("geotraces: loaded %s samples / %s stations", inserted, len(stations))
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
        geo = (await client.get(_MOSAIC_GEO_URL, timeout=180)).json()
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
