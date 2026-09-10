# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Acoustic — 22-network hydrophone stations, soundscape, and noise-risk grid.

Moved verbatim out of backend/main.py (Task 4 of the backend vertical-split
refactor — the second domain that owns caches the admin sweep actually
clears: `_noise_risk_cache` and `_noise_stations_cache` were 2 of the 9
caches hand-cleared in `admin_cache_clear`; they are now reached only through
this module's `clear_caches()` via the Task-1 registry, alongside two more
caches — `_acoustic_stations_cache` and `_acoustic_soundscape_cache` — that
main.py already cleared inside the moved sync functions but never listed in
`admin_cache_clear` itself). Only permitted edits applied: `@app.get` ->
`@router.get`, `_pool.acquire()` -> `db.pool.acquire()`, leading underscore
dropped from the three sync function names (`_sync_acoustic_stations` ->
`sync_acoustic_stations`, `_sync_acoustic_soundscape` ->
`sync_acoustic_soundscape`, `_sync_noise_risk` -> `sync_noise_risk`), and
imports/docstring.

**All four endpoints share one auth posture** — `Depends(get_api_key)`, no
admin-token-gated endpoints in this domain:
- `GET /v1/map/noise/risk-grid`
- `GET /v1/map/noise/stations`
- `GET /v1/map/hydrophones` (optional `?source=` filter)
- `GET /v1/hydrophones/{station_id}/soundscape` — **parameterised**, the
  first such route this refactor moves. It sits after its three literal
  siblings in registration order (mirroring their position in main.py), so
  none of `/v1/map/noise/risk-grid`, `/v1/map/noise/stations`,
  `/v1/map/hydrophones` can ever be shadowed by it — a parameterised path
  only risks shadowing a *literal* path that matches its own pattern, and
  none of those three do (`{station_id}` sits under a completely different
  prefix, `/v1/hydrophones/...`, not `/v1/map/...`).

`_sync_acoustic_stations`/`_sync_acoustic_soundscape` orchestrate ~22
per-source ingest modules from `backend/ingestion/acoustic_*_ingest.py` —
those files stay where they are; this module only imports them (inside the
sync functions, at call time, exactly as main.py did).

`_ACOUSTIC_SOURCE_TIMEOUT_S` moved with the two functions that are its only
readers — verified via `grep` before the cut, same check that caught
`_ONC_INSTRUMENTS_WFS` staying behind in Phase 1.

`_log_noise_risk_count_on_startup` (main.py ~3581) stayed in main.py — it
only counts `noise_risk_grid` rows into `sync_log` at boot and touches none
of this domain's four caches; it is not one of the eight symbols this task
moves.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import db
from auth import get_api_key
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sync_log import log_sync as _log_sync

log = logging.getLogger(__name__)
router = APIRouter()

# Max seconds any single acoustic source fetch may run before it's abandoned.
# Generous enough for legitimate NOAA-archive GCS walks (~20-60s) but bounded
# so one hung source can't freeze the whole sync.
_ACOUSTIC_SOURCE_TIMEOUT_S = 120

# ── Honest sync counters ────────────────────────────────────────────────────
# ⛔ `records_added += len(rows)` after an `ON CONFLICT DO UPDATE` counts every
# row we TOUCHED, not every row we ADDED. On 2026-09-10 sync_log carried
# `acoustic-stations records_added=5738 total_records=5738` against a table
# holding 641 rows — nine times the table, reported as new arrivals, and
# `total_records` was the same inflated figure rather than the table's size.
#
# `executemany` cannot RETURNING, so the count comes from the table itself.
# Safe here because every sync in this process is serialised behind the single
# `_sync_lock`, and neither function deletes: the table only grows, so the
# difference is exactly the number of inserts.
async def _upsert_and_count(conn, table: str, sql: str, params: list) -> int:
    """Run an upsert and return how many rows it genuinely INSERTED."""
    before = await conn.fetchval(f"SELECT count(*) FROM {table}")
    await conn.executemany(sql, params)
    after = await conn.fetchval(f"SELECT count(*) FROM {table}")
    return after - before


# ── Caches ──────────────────────────────────────────────────────────────────
_noise_risk_cache:     str | None = None
_noise_stations_cache: str | None = None
_acoustic_stations_cache:   str | None = None
_acoustic_soundscape_cache: dict[str, str] = {}  # station_id → JSON of last 90 days


def clear_caches() -> None:
    """Drop this domain's cached responses. Called by /admin/cache/clear."""
    global _noise_risk_cache, _noise_stations_cache, _acoustic_stations_cache
    _noise_risk_cache = None
    _noise_stations_cache = None
    _acoustic_stations_cache = None
    _acoustic_soundscape_cache.clear()


async def sync_acoustic_stations(force: bool = False) -> int:
    """Sync hydrophone station metadata from OOI + IMOS + MARS + PALAOA + OBSEA + KM3NeT.

    Per-source try/except — partial failure leaves stale rows but never blocks
    other sources. Upserts on station_id PK; no TRUNCATE.
    """
    from ingestion import (
        acoustic_ooi_ingest,
        acoustic_imos_ingest,
        acoustic_mars_ingest,
        acoustic_palaoa_ingest,
        acoustic_obsea_ingest,
        acoustic_km3net_ingest,
        acoustic_nrs_ingest,
        acoustic_sanctsound_ingest,
        acoustic_nefsc_ingest,
        acoustic_noaa_archive_ingest,
        acoustic_hausgarten_ingest,
        acoustic_sambah_ingest,
        acoustic_ims_ingest,
    )

    if not force:
        async with db.pool.acquire() as conn:
            last = await conn.fetchval(
                "SELECT MAX(last_synced_at) FROM sync_log WHERE source = 'acoustic-stations'"
            )
        if last and (datetime.now(timezone.utc) - last).days < 7:
            log.info("_sync_acoustic_stations: within 7-day guard, skipping")
            return 0

    sources = [
        ("ooi",        acoustic_ooi_ingest.fetch_ooi_stations),
        ("imos",       acoustic_imos_ingest.fetch_imos_stations),
        ("mars",       acoustic_mars_ingest.fetch_mars_stations),
        ("palaoa",     acoustic_palaoa_ingest.fetch_palaoa_stations),
        ("obsea",      acoustic_obsea_ingest.fetch_obsea_stations),
        ("km3net",     acoustic_km3net_ingest.fetch_km3net_stations),
        ("nrs",        acoustic_nrs_ingest.fetch_nrs_stations),
        ("sanctsound", acoustic_sanctsound_ingest.fetch_sanctsound_stations),
        ("nefsc",      acoustic_nefsc_ingest.fetch_nefsc_stations),
        # Phase 4 — 12 NOAA Passive Acoustic Archive programs from the
        # shared GCS bucket (one generic walker, per-program config).
        ("pifsc",      acoustic_noaa_archive_ingest.fetch_pifsc_stations),
        ("sefsc",      acoustic_noaa_archive_ingest.fetch_sefsc_stations),
        ("onms",       acoustic_noaa_archive_ingest.fetch_onms_stations),
        ("adeon",      acoustic_noaa_archive_ingest.fetch_adeon_stations),
        ("boem",       acoustic_noaa_archive_ingest.fetch_boem_stations),
        ("aeon",       acoustic_noaa_archive_ingest.fetch_aeon_stations),
        ("navy",       acoustic_noaa_archive_ingest.fetch_navy_stations),
        ("nps",        acoustic_noaa_archive_ingest.fetch_nps_stations),
        ("jasco",      acoustic_noaa_archive_ingest.fetch_jasco_stations),
        ("fram",       acoustic_noaa_archive_ingest.fetch_fram_stations),
        ("coastal_studies_institute", acoustic_noaa_archive_ingest.fetch_coastal_studies_institute_stations),
        ("ioos",       acoustic_noaa_archive_ingest.fetch_ioos_stations),
        # Phase 3 — PANGAEA/Dryad additions
        ("fram",       acoustic_hausgarten_ingest.fetch_hausgarten_stations),   # 7 HAUSGARTEN moorings; reuses 'fram' enum
        ("sambah",     acoustic_sambah_ingest.fetch_sambah_stations),           # ~298 Baltic C-POD stations
        # Phase 4 — CTBTO IMS
        ("ims",        acoustic_ims_ingest.fetch_ims_stations),                 # 11 global IMS hydroacoustic stations
    ]
    total_inserted = 0
    total_fetched = 0
    succeeded = 0
    # Per-source timeout: a hanging fetch (e.g. a NOAA-archive GCS walk that
    # never returns) used to freeze the whole chain, so _log_sync never fired
    # and later sources (HAUSGARTEN/SAMBAH/IMS) never synced. wait_for turns a
    # hang into a caught TimeoutError → log + continue to the next source.
    for name, fn in sources:
        try:
            rows = await asyncio.wait_for(fn(), timeout=_ACOUSTIC_SOURCE_TIMEOUT_S)
        except Exception as exc:
            log.warning("acoustic stations %s fetch failed/timed out: %s", name, exc)
            continue
        if not rows:
            log.info("acoustic stations %s: 0 rows returned", name)
            succeeded += 1
            continue
        try:
            async with db.pool.acquire() as conn:
                inserted = await _upsert_and_count(
                    conn, "acoustic_stations",
                    """
                    INSERT INTO acoustic_stations (
                        station_id, source, name, operator, lat, lon, depth_m,
                        deploy_start, deploy_end, model, hz_range_lo, hz_range_hi, portal_url,
                        license
                    )
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                    ON CONFLICT (station_id) DO UPDATE SET
                        name=EXCLUDED.name, operator=EXCLUDED.operator,
                        lat=EXCLUDED.lat, lon=EXCLUDED.lon, depth_m=EXCLUDED.depth_m,
                        deploy_start=EXCLUDED.deploy_start, deploy_end=EXCLUDED.deploy_end,
                        model=EXCLUDED.model, hz_range_lo=EXCLUDED.hz_range_lo,
                        hz_range_hi=EXCLUDED.hz_range_hi, portal_url=EXCLUDED.portal_url,
                        license=EXCLUDED.license,
                        fetched_at=NOW()
                    """,
                    [(r["station_id"], r["source"], r.get("name"), r.get("operator"),
                      r["lat"], r["lon"], r.get("depth_m"),
                      r.get("deploy_start"), r.get("deploy_end"),
                      r.get("model"), r.get("hz_range_lo"), r.get("hz_range_hi"),
                      r.get("portal_url"), r.get("license")) for r in rows],
                )
            total_inserted += inserted
            total_fetched += len(rows)
            succeeded += 1
            log.info("acoustic stations %s: %d rows fetched, %d new", name, len(rows), inserted)
        except Exception as exc:
            log.warning("acoustic stations %s upsert failed: %s", name, exc)

    global _acoustic_stations_cache
    _acoustic_stations_cache = None
    async with db.pool.acquire() as conn:
        in_table = await conn.fetchval("SELECT count(*) FROM acoustic_stations")
    await _log_sync("acoustic-stations", total_inserted, in_table)
    log.info("_sync_acoustic_stations: %d/%d sources succeeded, %d rows fetched, "
             "%d genuinely new, %d in table",
             succeeded, len(sources), total_fetched, total_inserted, in_table)
    return total_inserted


async def sync_acoustic_soundscape(force: bool = False) -> int:
    """Sync daily soundscape rows for every known acoustic_stations row.

    Phase 1: all three sources return [] (OOI requires raw-audio compute; IMOS publishes
    raw .wav only; MARS publishes JPG spectrograms only). The orchestrator iterates and
    finds no rows to insert. Phase 2 will populate fetch_ooi_soundscape() and this will
    start producing data.
    """
    from ingestion import (
        acoustic_ooi_ingest,
        acoustic_imos_ingest,
        acoustic_mars_ingest,
        acoustic_palaoa_ingest,
        acoustic_obsea_ingest,
        acoustic_km3net_ingest,
        acoustic_nrs_ingest,
        acoustic_sanctsound_ingest,
        acoustic_nefsc_ingest,
        acoustic_noaa_archive_ingest,
        acoustic_hausgarten_ingest,
        acoustic_sambah_ingest,
        acoustic_ims_ingest,
    )

    if not force:
        async with db.pool.acquire() as conn:
            last = await conn.fetchval(
                "SELECT MAX(last_synced_at) FROM sync_log WHERE source = 'acoustic-soundscape'"
            )
        if last and (datetime.now(timezone.utc) - last).days < 7:
            log.info("_sync_acoustic_soundscape: within 7-day guard, skipping")
            return 0

    fetchers = {
        "ooi":        acoustic_ooi_ingest.fetch_ooi_soundscape,
        "imos":       acoustic_imos_ingest.fetch_imos_soundscape,
        "mars":       acoustic_mars_ingest.fetch_mars_soundscape,
        "palaoa":     acoustic_palaoa_ingest.fetch_palaoa_soundscape,
        "obsea":      acoustic_obsea_ingest.fetch_obsea_soundscape,
        "km3net":     acoustic_km3net_ingest.fetch_km3net_soundscape,
        "nrs":        acoustic_nrs_ingest.fetch_nrs_soundscape,
        "sanctsound": acoustic_sanctsound_ingest.fetch_sanctsound_soundscape,
        "nefsc":      acoustic_nefsc_ingest.fetch_nefsc_soundscape,
        # Phase 4 — all 12 return [] (Phase 5 NetCDF work would populate)
        "pifsc":      acoustic_noaa_archive_ingest.fetch_pifsc_soundscape,
        "sefsc":      acoustic_noaa_archive_ingest.fetch_sefsc_soundscape,
        "onms":       acoustic_noaa_archive_ingest.fetch_onms_soundscape,
        "adeon":      acoustic_noaa_archive_ingest.fetch_adeon_soundscape,
        "boem":       acoustic_noaa_archive_ingest.fetch_boem_soundscape,
        "aeon":       acoustic_noaa_archive_ingest.fetch_aeon_soundscape,
        "navy":       acoustic_noaa_archive_ingest.fetch_navy_soundscape,
        "nps":        acoustic_noaa_archive_ingest.fetch_nps_soundscape,
        "jasco":      acoustic_noaa_archive_ingest.fetch_jasco_soundscape,
        "fram":       acoustic_noaa_archive_ingest.fetch_fram_soundscape,
        "coastal_studies_institute": acoustic_noaa_archive_ingest.fetch_coastal_studies_institute_soundscape,
        "ioos":       acoustic_noaa_archive_ingest.fetch_ioos_soundscape,
        # Phase 3 — both return [] (archives only)
        "hausgarten": acoustic_hausgarten_ingest.fetch_hausgarten_soundscape,
        "sambah":     acoustic_sambah_ingest.fetch_sambah_soundscape,
        # Phase 4 — returns [] (treaty-restricted waveforms)
        "ims":        acoustic_ims_ingest.fetch_ims_soundscape,
    }

    async with db.pool.acquire() as conn:
        stations = await conn.fetch(
            "SELECT station_id, source FROM acoustic_stations ORDER BY source, station_id"
        )

    total_inserted = 0
    total_fetched = 0
    for st in stations:
        fn = fetchers.get(st["source"])
        if fn is None:
            continue
        try:
            rows = await asyncio.wait_for(fn(st["station_id"], days=90), timeout=_ACOUSTIC_SOURCE_TIMEOUT_S)
        except Exception as exc:
            log.warning("acoustic soundscape fetch failed/timed out for %s: %s", st["station_id"], exc)
            continue
        if not rows:
            continue
        try:
            async with db.pool.acquire() as conn:
                inserted = await _upsert_and_count(
                    conn, "acoustic_soundscape",
                    """
                    INSERT INTO acoustic_soundscape (
                        station_id, day,
                        broadband_spl_db, spl_10hz_db, spl_63hz_db, spl_100hz_db,
                        spl_125hz_db, spl_1khz_db, spl_10khz_db,
                        l50_db, l95_db, n_minutes_recorded, source_url
                    )
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                    ON CONFLICT (station_id, day) DO UPDATE SET
                        broadband_spl_db=EXCLUDED.broadband_spl_db,
                        spl_10hz_db =EXCLUDED.spl_10hz_db,
                        spl_63hz_db =EXCLUDED.spl_63hz_db,
                        spl_100hz_db=EXCLUDED.spl_100hz_db,
                        spl_125hz_db=EXCLUDED.spl_125hz_db,
                        spl_1khz_db =EXCLUDED.spl_1khz_db,
                        spl_10khz_db=EXCLUDED.spl_10khz_db,
                        l50_db=EXCLUDED.l50_db, l95_db=EXCLUDED.l95_db,
                        n_minutes_recorded=EXCLUDED.n_minutes_recorded,
                        source_url=EXCLUDED.source_url,
                        fetched_at=NOW()
                    """,
                    [(r["station_id"], r["day"],
                      r.get("broadband_spl_db"), r.get("spl_10hz_db"), r.get("spl_63hz_db"),
                      r.get("spl_100hz_db"), r.get("spl_125hz_db"),
                      r.get("spl_1khz_db"), r.get("spl_10khz_db"),
                      r.get("l50_db"), r.get("l95_db"),
                      r.get("n_minutes_recorded"), r.get("source_url"))
                     for r in rows],
                )
            total_inserted += inserted
            total_fetched += len(rows)
        except Exception as exc:
            log.warning("acoustic soundscape upsert failed for %s: %s", st["station_id"], exc)

    global _acoustic_soundscape_cache
    _acoustic_soundscape_cache = {}
    async with db.pool.acquire() as conn:
        in_table = await conn.fetchval("SELECT count(*) FROM acoustic_soundscape")
    await _log_sync("acoustic-soundscape", total_inserted, in_table)
    log.info("_sync_acoustic_soundscape: %d daily rows fetched, %d genuinely new, "
             "%d in table", total_fetched, total_inserted, in_table)
    return total_inserted


async def sync_noise_risk():
    """Re-ingest ICES/EMODnet noise + OBIS cetacean data, then recompute risk grid.
    Heavy operation (~30 min) — triggered manually from dashboard, not on weekly cycle."""
    global _noise_risk_cache
    log.info("noise_risk: starting sync…")

    from ingestion.noise_ingest import main as _noise_ingest
    from ingestion.cetacean_ingest import main as _cet_ingest
    from ingestion.noise_risk_compute import main as _compute

    # noise_cells and cetacean_cells are upserted `ON CONFLICT (cell_key) DO
    # UPDATE` by their ingest modules, which return nothing. Counting the table
    # afterwards and calling that figure `records_added` reported the entire
    # grid as new arrivals on every run — sync_log carried noise_cells 101/101
    # and cetacean_cells 7189/7189 on 2026-09-10, exactly the table sizes, so a
    # stalled ingest was indistinguishable from a healthy one. Bracketing the
    # call is the smallest honest measurement that does not reach into the
    # ingest modules.
    async with db.pool.acquire() as conn:
        noise_before = await conn.fetchval("SELECT COUNT(*) FROM noise_cells")
        cet_before   = await conn.fetchval("SELECT COUNT(*) FROM cetacean_cells")

    await _noise_ingest()
    log.info("noise_risk: noise_cells populated")

    await _cet_ingest()
    log.info("noise_risk: cetacean_cells populated")

    await _compute()
    log.info("noise_risk: risk grid computed")

    async with db.pool.acquire() as conn:
        noise_count = await conn.fetchval("SELECT COUNT(*) FROM noise_cells")
        cet_count   = await conn.fetchval("SELECT COUNT(*) FROM cetacean_cells")
        grid_count  = await conn.fetchval("SELECT COUNT(*) FROM noise_risk_grid")
        await _log_sync("noise_cells",   noise_count - noise_before, noise_count)
        await _log_sync("cetacean_cells", cet_count - cet_before,    cet_count)
        # ⛔ The only honest same-value pair in this file: noise_risk_compute
        # TRUNCATEs noise_risk_grid and rebuilds it, so every row really is new.
        await _log_sync("noise_risk",    grid_count,  grid_count)

    _noise_risk_cache = None
    log.info("noise_risk: sync complete — %d grid cells", grid_count)


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/v1/map/noise/risk-grid", dependencies=[Depends(get_api_key)])
async def get_noise_risk_grid():
    """Return noise risk grid as GeoJSON FeatureCollection. Cached in memory."""
    global _noise_risk_cache
    if _noise_risk_cache:
        return Response(content=_noise_risk_cache, media_type="application/json")

    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT lon, lat, pbd_norm, spl_norm, pbd_year, pbd_year_min, pbd_year_max,
                   cetacean_norm, species_weight,
                   risk_index, risk_level, data_gap, noise_source,
                   cetacean_count, max_species
            FROM   noise_risk_grid
            ORDER  BY risk_index DESC
        """)

    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r["lon"] + 0.5, r["lat"] + 0.5]},
            "properties": {
                "pbd_norm":        r["pbd_norm"],
                "spl_norm":        r["spl_norm"],
                "pbd_year":        r["pbd_year"],
                "pbd_year_min":    r["pbd_year_min"],
                "pbd_year_max":    r["pbd_year_max"],
                "cetacean_norm":   r["cetacean_norm"],
                "species_weight":  r["species_weight"],
                "risk_index":      r["risk_index"],
                "risk_level":      r["risk_level"],
                "data_gap":        r["data_gap"],
                "noise_source":    r["noise_source"],
                "cetacean_count":  r["cetacean_count"],
                "max_species":     r["max_species"],
            },
        }
        for r in rows
    ]
    result = json.dumps({"type": "FeatureCollection", "features": features})
    _noise_risk_cache = result
    return Response(content=result, media_type="application/json")


@router.get("/v1/map/noise/stations", dependencies=[Depends(get_api_key)])
async def get_noise_stations():
    """Return EMODnet continuous noise monitoring station points."""
    global _noise_stations_cache
    if _noise_stations_cache:
        return Response(content=_noise_stations_cache, media_type="application/json")

    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT lon, lat, continuous_spl, spl_norm, source, region
            FROM   noise_cells
            WHERE  continuous_spl IS NOT NULL
        """)

    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r["lon"] + 0.5, r["lat"] + 0.5]},
            "properties": {
                "spl":        r["continuous_spl"],
                "spl_norm":   r["spl_norm"],
                "source":     r["source"],
                "region":     r["region"],
            },
        }
        for r in rows
    ]
    result = json.dumps({"type": "FeatureCollection", "features": features})
    _noise_stations_cache = result
    return Response(content=result, media_type="application/json")


@router.get("/v1/map/hydrophones", dependencies=[Depends(get_api_key)])
async def get_hydrophones(source: str | None = None) -> Response:
    """GeoJSON FeatureCollection of hydrophone stations from OOI/IMOS/MARS.

    Optional ?source=ooi,imos to filter; default returns all.
    """
    global _acoustic_stations_cache
    cache_key = source or "all"
    if _acoustic_stations_cache is not None and cache_key == "all":
        return Response(content=_acoustic_stations_cache, media_type="application/json")
    where = ""
    params: list = []
    if source:
        sources = [s.strip() for s in source.split(",") if s.strip()]
        if sources:
            where = "WHERE source = ANY($1)"
            params.append(sources)
    sql = f"""
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', COALESCE(json_agg(
                json_build_object(
                    'type', 'Feature',
                    'geometry', ST_AsGeoJSON(geom::geometry)::json,
                    'properties', json_build_object(
                        'station_id', station_id,
                        'source', source,
                        'name', name,
                        'operator', operator,
                        'depth_m', depth_m,
                        'deploy_start', deploy_start,
                        'deploy_end', deploy_end,
                        'model', model,
                        'hz_range_lo', hz_range_lo,
                        'hz_range_hi', hz_range_hi,
                        'portal_url', portal_url,
                        'license', license
                    )
                )
            ), '[]'::json)
        )::text
        FROM acoustic_stations
        {where}
    """
    async with db.pool.acquire() as conn:
        payload = await conn.fetchval(sql, *params)
    if cache_key == "all":
        _acoustic_stations_cache = payload
    return Response(content=payload, media_type="application/json")


@router.get("/v1/hydrophones/{station_id}/soundscape", dependencies=[Depends(get_api_key)])
async def get_hydrophone_soundscape(station_id: str) -> Response:
    """Last 90 days of daily soundscape rows for one station.

    Phase 1: returns [] for all stations until Phase 2 SPL computation lands.
    """
    global _acoustic_soundscape_cache
    cached = _acoustic_soundscape_cache.get(station_id)
    if cached is not None:
        return Response(content=cached, media_type="application/json")
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT day, broadband_spl_db,
                   spl_10hz_db, spl_63hz_db, spl_100hz_db,
                   spl_125hz_db, spl_1khz_db, spl_10khz_db,
                   l50_db, l95_db, n_minutes_recorded, source_url
              FROM acoustic_soundscape
             WHERE station_id = $1
               AND day >= CURRENT_DATE - INTERVAL '90 days'
             ORDER BY day ASC
            """,
            station_id,
        )
    payload = json.dumps([
        {
            "day":                r["day"].isoformat() if r["day"] else None,
            "broadband_spl_db":   r["broadband_spl_db"],
            "spl_10hz_db":        r["spl_10hz_db"],
            "spl_63hz_db":        r["spl_63hz_db"],
            "spl_100hz_db":       r["spl_100hz_db"],
            "spl_125hz_db":       r["spl_125hz_db"],
            "spl_1khz_db":        r["spl_1khz_db"],
            "spl_10khz_db":       r["spl_10khz_db"],
            "l50_db":             r["l50_db"],
            "l95_db":             r["l95_db"],
            "n_minutes_recorded": r["n_minutes_recorded"],
            "source_url":         r["source_url"],
        }
        for r in rows
    ])
    _acoustic_soundscape_cache[station_id] = payload
    return Response(content=payload, media_type="application/json")
