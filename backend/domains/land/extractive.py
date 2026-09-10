# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""
Extractive-industry land layers: mining footprints, key biodiversity areas
(KBAs), WDPA protected areas, tailings dams, and global dams. Split out of
land_layers.py.

`_normalise_hazard` lives here physically inside the tailings block but is
called ONLY by `_sync_dams` — moved with dams per the family split, kept
next to the other tailings/hazard code as it was in land_layers.py.
"""
from __future__ import annotations

from datetime import datetime, timezone
from ingestion.cadence import should_sync

import csv
import json
import logging
import os
import shutil
import subprocess
import tempfile
import zipfile

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

import db
from auth import get_api_key
from domains.land.common import (
    _log_land_sync,
    _log_land_sync_failure,
    _pg_conn_string,
)

log = logging.getLogger("land_layers")
OGR2OGR = shutil.which("ogr2ogr") or "/usr/bin/ogr2ogr"
router = APIRouter(tags=["land-layers"], dependencies=[Depends(get_api_key)])

# ── Module-level caches (cleared on sync) ──────────────────────────────────
_mining_footprints_cache: str | None = None
_kbas_cache: str | None = None
_wdpa_cache: str | None = None
_tailings_cache: str | None = None
_dams_cache: str | None = None


def clear_caches() -> None:
    """Reset this module's caches. Delegated into from land_layers.clear_caches()
    so the combined 13-cache sweep still clears everything from one call."""
    global _mining_footprints_cache, _kbas_cache, _wdpa_cache, _tailings_cache, _dams_cache
    _mining_footprints_cache = None
    _kbas_cache = None
    _wdpa_cache = None
    _tailings_cache = None
    _dams_cache = None


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 1 — Core Conflict Map
# ═══════════════════════════════════════════════════════════════════════════

# ── Mining Footprints ──────────────────────────────────────────────────────

async def _sync_mining_footprints(force: bool = False) -> int:
    """
    Import Maus et al. (2022) global mining footprints from PANGAEA.
    ~44,929 polygons, 23.5MB GeoPackage — downloads directly (no zip).
    Downloads once; skips if table already populated.
    Requires gdal-bin on VPS (apt install gdal-bin).
    """
    async with db.pool.acquire() as conn:
        last = await conn.fetchval(
            "SELECT last_synced_at FROM sync_log WHERE source = $1", "mining_footprints")
        run, why = should_sync("mining_footprints", last, datetime.now(timezone.utc), force=force)
        log.info("%s", why)
        if not run:
            return 0
        count = await conn.fetchval("SELECT COUNT(*) FROM mining_footprints")
        if count > 0:
            log.info("mining_footprints: already have %d records, skipping", count)
            # ⛔ The row-count guard stays even under force. These loads use
            # `ogr2ogr -append`, so re-running against a populated table
            # DOUBLES it — force skips the cadence window, never the duplicate
            # barrier. Logged at WARNING so a forced run that does nothing is
            # visible rather than being reported as a success.
            if force:
                log.warning(
                    "mining_footprints: force requested but the table already holds %d rows; "
                    "this load is append-only and cannot be safely re-run. "
                    "TRUNCATE deliberately first if a reload is really wanted.",
                    count)
            return 0

    # Direct GeoPackage download from PANGAEA file server
    url = "https://download.pangaea.de/dataset/942325/files/global_mining_polygons_v2.gpkg"
    log.info("mining_footprints: downloading GeoPackage from PANGAEA (23.5 MB)...")

    async with httpx.AsyncClient(timeout=600, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    tmpdir = tempfile.mkdtemp()
    try:
        gpkg = os.path.join(tmpdir, "global_mining_polygons_v2.gpkg")
        with open(gpkg, "wb") as f:
            f.write(resp.content)
        log.info("mining_footprints: downloaded %.1f MB", len(resp.content) / 1_000_000)

        cmd = [
            OGR2OGR, "-f", "PostgreSQL", _pg_conn_string(), gpkg,
            "-nln", "mining_footprints",
            "-append",
            "-nlt", "MULTIPOLYGON",
            "-lco", "GEOMETRY_NAME=geom",
            "-t_srs", "EPSG:4326",
            "--config", "PG_USE_COPY", "YES",
        ]
        log.info("mining_footprints: running ogr2ogr import...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            log.error("mining_footprints ogr2ogr failed: %s", result.stderr)
            return 0

        async with db.pool.acquire() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM mining_footprints")

        global _mining_footprints_cache
        _mining_footprints_cache = None
        await _log_land_sync("mining_footprints", total, total)
        log.info("mining_footprints: imported %d polygons", total)
        return total

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@router.get("/mining-footprints")
async def get_mining_footprints():
    global _mining_footprints_cache
    if _mining_footprints_cache:
        return Response(content=_mining_footprints_cache, media_type="application/json")

    async with db.pool.acquire() as conn:
        row = await conn.fetchval("""
            SELECT json_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(json_agg(
                    json_build_object(
                        'type', 'Feature',
                        'geometry', ST_AsGeoJSON(ST_Simplify(geom, 0.001))::json,
                        'properties', json_build_object(
                            'id', id,
                            'country', country,
                            'area_km2', ROUND(area_km2::numeric, 2),
                            'ftype', ftype,
                            'source', source
                        )
                    )
                ), '[]'::json)
            )::text
            FROM mining_footprints
        """)
    _mining_footprints_cache = row
    return Response(content=row, media_type="application/json")


# ── Key Biodiversity Areas ─────────────────────────────────────────────────

KBA_FEATURE_SERVER = (
    "https://maps.birdlife.org/server/rest/services/Hosted/Confirmed_KBAs/FeatureServer/0"
)
KBA_PAGE_SIZE = 1000
KBA_STAGING_TABLE = "key_biodiversity_areas_staging"


# A paged download that dies half-way leaves staging with SOME rows, and "some"
# passes a zero-check. Below this share of the expected count we treat the load
# as failed rather than as a smaller release. Not 1.0: ArcGIS servers routinely
# return a handful fewer features than their own returnCountOnly reports, and a
# sync that refuses to ever complete is its own outage.
_MIN_COMPLETE_SHARE = 0.95


async def _replace_table_atomically(conn, table: str, staging: str,
                                    expected: int | None = None) -> int:
    """Swap `staging` into `table` inside the caller's transaction.

    ⛔ Order is load-bearing: validate the staging load BEFORE deleting. An
    upstream that serves an empty or truncated release must cost us nothing —
    the exception rolls the transaction back and the previous release survives.
    The reverse order turns their bad day into our data loss.

    ⛔ `expected` is not optional in spirit. A zero-check alone is fail-open:
    `_sync_kbas` breaks out of its paging loop on an empty page or an ogr2ogr
    error, so a network hiccup on page 3 of 10 leaves a partial staging table
    that a truthy count waves through — deleting a complete layer and replacing
    it with a fragment. Pass the source's own count for the run whenever you
    have it.

    ⛔ But `expected` alone is not a reference either: it comes from the SAME
    server that serves the pages, and servers degrade as a whole. A
    `returnCountOnly` answering 500 instead of 16,800 makes the paging loop
    fetch 500, and 500 of 500 passes a guard that only compares the server
    against itself — 16,800 live rows deleted and replaced by 500, reported as
    a successful sync. So the floor is `max(expected, live)`: the live table is
    the one reference the upstream cannot degrade.

    ⛔ `expected == 0` is refused explicitly. Under `if expected and ...` a
    count endpoint answering 0 — the loudest possible signal that the upstream
    is broken — silently DISABLED the guard, which is the quietest possible
    response.

    A legitimate upstream that genuinely shrinks by more than
    `1 - _MIN_COMPLETE_SHARE` will be refused here, deliberately. That is a
    decision for a person: confirm the release at the source, then truncate the
    live table so the floor drops, and re-run.
    """
    n = await conn.fetchval(f"SELECT count(*) FROM {staging}")
    if not n:
        raise RuntimeError(f"{table}: staging holds 0 rows — leaving live data intact")
    if expected is not None and expected <= 0:
        raise RuntimeError(
            f"{table}: upstream reported 0 expected rows — treating that as a "
            f"broken count endpoint, not as an empty release; leaving live data "
            f"intact (staging held {n})")

    live = await conn.fetchval(f"SELECT count(*) FROM {table}") or 0
    floor_from = max(expected or 0, live)
    if floor_from and n < floor_from * _MIN_COMPLETE_SHARE:
        against = (
            f"{expected} expected" if expected and expected >= live
            else f"{live} rows already live"
        )
        raise RuntimeError(
            f"{table}: staging is short — {n} rows against {against} "
            f"(<{_MIN_COMPLETE_SHARE:.0%}); treating as a failed download and "
            f"leaving live data intact")
    await conn.execute(f"DELETE FROM {table}")
    await conn.execute(f"INSERT INTO {table} SELECT * FROM {staging}")
    return int(n)


async def _promote_staging(source: str, table: str, staging: str,
                           expected: int | None = None) -> int:
    """Run the validated swap, then clean up — on BOTH paths.

    ⛔ The DROP used to sit after the transaction block, so a raise from
    `_replace_table_atomically` skipped it and left a full copy of the table on
    disk. A run that keeps failing keeps leaving one.

    ⛔ The DROP stays OUTSIDE the transaction on purpose. Inside, a failure
    would roll the drop back too, and the next run's `count(*)` would happily
    accept the stale staging table as a fresh load.

    ⛔ And a failure must reach `sync_log`, or the monitor cannot tell "tried and
    failed" from "never ran" — the engine rule that every early exit from a sync
    writes a log row. `_log_land_sync_failure` records the attempt WITHOUT
    advancing `last_synced_at`, so the source keeps ageing and the staleness
    alert still fires.
    """
    async with db.pool.acquire() as conn:
        try:
            async with conn.transaction():
                total = await _replace_table_atomically(
                    conn, table, staging, expected=expected)
        except Exception as exc:
            live = await conn.fetchval(f"SELECT count(*) FROM {table}") or 0
            await _log_land_sync_failure(source, int(live), str(exc))
            raise
        finally:
            # Never leave the staging copy behind, on either path.
            await conn.execute(f"DROP TABLE IF EXISTS {staging}")
    return total


async def _sync_kbas(force: bool = False) -> int:
    """
    Download KBA polygons from BirdLife ArcGIS Feature Server page by page,
    into a staging table. Cadence permits this sync to re-run, so the load
    lands in `key_biodiversity_areas_staging` first and only replaces the
    live table via `_replace_table_atomically` once every page is in — a
    re-run never doubles the table, and an empty/broken upstream page never
    costs us the previous release.
    """
    async with db.pool.acquire() as conn:
        last = await conn.fetchval(
            "SELECT last_synced_at FROM sync_log WHERE source = $1", "kbas")
        run, why = should_sync("kbas", last, datetime.now(timezone.utc), force=force)
        log.info("%s", why)
        if not run:
            return 0
        await conn.execute(f"DROP TABLE IF EXISTS {KBA_STAGING_TABLE}")
        await conn.execute(
            f"CREATE TABLE {KBA_STAGING_TABLE} "
            f"(LIKE key_biodiversity_areas INCLUDING DEFAULTS)"
        )

    # Get total count
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.get(
            f"{KBA_FEATURE_SERVER}/query",
            params={"where": "1=1", "returnCountOnly": "true", "f": "json"},
        )
        resp.raise_for_status()
        total_remote = resp.json()["count"]

    log.info("kbas: %d features on server, downloading page by page...", total_remote)
    imported = 0
    offset = 0
    page = 0

    while offset < total_remote:
        page += 1
        params = {
            "where": "1=1",
            "outFields": "intname,country,kbastatus,area",
            "resultOffset": str(offset),
            "resultRecordCount": str(KBA_PAGE_SIZE),
            "f": "geojson",
        }
        async with httpx.AsyncClient(timeout=600) as client:
            resp = await client.get(f"{KBA_FEATURE_SERVER}/query", params=params)
            resp.raise_for_status()
            data = resp.json()

        features = data.get("features", [])
        if not features:
            log.warning("kbas: empty page at offset %d, stopping", offset)
            break

        # Write page to temp file, import via ogr2ogr
        tmp = tempfile.NamedTemporaryFile(suffix=".geojson", delete=False, mode="w")
        json.dump({"type": "FeatureCollection", "features": features}, tmp)
        tmp.close()

        layer_name = os.path.splitext(os.path.basename(tmp.name))[0]
        cmd = [
            OGR2OGR, "-f", "PostgreSQL", _pg_conn_string(), tmp.name,
            "-nln", KBA_STAGING_TABLE, "-append",
            "-nlt", "MULTIPOLYGON", "-lco", "GEOMETRY_NAME=geom",
            "-t_srs", "EPSG:4326", "--config", "PG_USE_COPY", "YES",
            "-sql", (
                f'SELECT intname AS site_name, country, kbastatus AS status, '
                f'area AS area_km2 FROM "{layer_name}"'
            ),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        os.unlink(tmp.name)

        if result.returncode != 0:
            log.error("kbas: ogr2ogr failed page %d: %s", page, result.stderr)
            offset += KBA_PAGE_SIZE
            continue

        imported += len(features)
        log.info("kbas: page %d — %d imported (total %d / %d)", page, len(features), imported, total_remote)
        offset += KBA_PAGE_SIZE

    # expected=total_remote is what makes the guard real. The paging loop above
    # `break`s on an empty page or an ogr2ogr failure, so reaching here proves
    # nothing about completeness.
    total = await _promote_staging(
        "kbas", "key_biodiversity_areas", KBA_STAGING_TABLE,
        expected=total_remote,
    )

    global _kbas_cache
    _kbas_cache = None
    await _log_land_sync("kbas", total, total)
    log.info("kbas: done — %d areas in DB", total)
    return total


@router.get("/kbas")
async def get_kbas():
    """410 Gone — withheld pending written permission from the KBA Secretariat.

    The rows are still in the database. BirdLife's KBA terms forbid
    redistribution "through interactive web maps ... that grant users download
    access" without prior written permission, plus a separate no-commercial-use
    clause. Verified against keybiodiversityareas.org/termsofservice
    2026-09-03. Restore this endpoint if permission is granted.

    ⛔ 410, not 404: 404 tells Google the URL might come back and it holds it
    in the index for weeks. 410 says withdrawn on purpose.
    """
    raise HTTPException(
        status_code=410,
        detail="KBA is withheld pending written permission from the KBA Secretariat.",
    )


# ── WDPA Protected Areas ──────────────────────────────────────────────────

async def _sync_wdpa(force: bool = False) -> int:
    """
    Import WDPA from pre-downloaded file.
    Data from https://www.protectedplanet.net/en/thematic-areas/wdpa
    Place downloaded file in /opt/abyssal-data/wdpa/ on VPS.
    """
    async with db.pool.acquire() as conn:
        last = await conn.fetchval(
            "SELECT last_synced_at FROM sync_log WHERE source = $1", "wdpa")
        run, why = should_sync("wdpa", last, datetime.now(timezone.utc), force=force)
        log.info("%s", why)
        if not run:
            return 0
        count = await conn.fetchval("SELECT COUNT(*) FROM wdpa")
        if count > 0:
            log.info("wdpa: already have %d records, skipping", count)
            # ⛔ The row-count guard stays even under force. These loads use
            # `ogr2ogr -append`, so re-running against a populated table
            # DOUBLES it — force skips the cadence window, never the duplicate
            # barrier. Logged at WARNING so a forced run that does nothing is
            # visible rather than being reported as a success.
            if force:
                log.warning(
                    "wdpa: force requested but the table already holds %d rows; "
                    "this load is append-only and cannot be safely re-run. "
                    "TRUNCATE deliberately first if a reload is really wanted.",
                    count)
            return 0

    wdpa_path = "/opt/abyssal-data/wdpa"
    src_file = None
    if os.path.isdir(wdpa_path):
        for fn in os.listdir(wdpa_path):
            if fn.endswith((".gpkg", ".shp", ".geojson")):
                src_file = os.path.join(wdpa_path, fn)
                break

    if not src_file:
        log.warning("wdpa: no data file in %s — download from protectedplanet.net", wdpa_path)
        return 0

    cmd = [
        "ogr2ogr", "-f", "PostgreSQL", _pg_conn_string(), src_file,
        "-nln", "wdpa",
        "-append",
        "-nlt", "MULTIPOLYGON",
        "-lco", "GEOMETRY_NAME=geom",
        "-t_srs", "EPSG:4326",
        "--config", "PG_USE_COPY", "YES",
    ]
    log.info("wdpa: importing from %s...", src_file)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        log.error("wdpa ogr2ogr failed: %s", result.stderr)
        return 0

    async with db.pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM wdpa")

    global _wdpa_cache
    _wdpa_cache = None
    await _log_land_sync("wdpa", total, total)
    log.info("wdpa: imported %d protected areas", total)
    return total


@router.get("/wdpa")
async def get_wdpa():
    """410 Gone — withheld pending written permission from UNEP-WCMC.

    The rows are still in the database. Protected Planet's terms forbid
    redistribution "through interactive web maps ... that grant users download
    access" without prior written permission; requested 2026-09-03. Restore
    this endpoint if it is granted.

    ⛔ 410, not 404: 404 tells Google the URL might come back and it holds it
    in the index for weeks. 410 says withdrawn on purpose.
    """
    raise HTTPException(
        status_code=410,
        detail="WDPA is withheld pending written permission from UNEP-WCMC.",
    )


async def _sync_tailings(force: bool = False) -> int:
    """
    Download tailings dam locations from Zenodo (Maus et al. WAPHA dataset).
    ~11,587 point features. Static — skips if table already populated.
    """
    async with db.pool.acquire() as conn:
        last = await conn.fetchval(
            "SELECT last_synced_at FROM sync_log WHERE source = $1", "tailings")
        run, why = should_sync("tailings", last, datetime.now(timezone.utc), force=force)
        log.info("%s", why)
        if not run:
            return 0
        count = await conn.fetchval("SELECT COUNT(*) FROM tailings_dams")
        if count > 0:
            log.info("tailings: already have %d records, skipping", count)
            # ⛔ The row-count guard stays even under force. These loads use
            # `ogr2ogr -append`, so re-running against a populated table
            # DOUBLES it — force skips the cadence window, never the duplicate
            # barrier. Logged at WARNING so a forced run that does nothing is
            # visible rather than being reported as a success.
            if force:
                log.warning(
                    "tailings: force requested but the table already holds %d rows; "
                    "this load is append-only and cannot be safely re-run. "
                    "TRUNCATE deliberately first if a reload is really wanted.",
                    count)
            return 0

    log.info("tailings: downloading from Zenodo...")
    async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
        resp = await client.get(TAILINGS_ZENODO_URL)
        resp.raise_for_status()

    # Extract shapefile from zip
    tmpdir = tempfile.mkdtemp(prefix="tailings_")
    try:
        zip_path = os.path.join(tmpdir, "Global_TSFs.zip")
        with open(zip_path, "wb") as f:
            f.write(resp.content)

        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmpdir)

        # Find the .shp file
        shp_file = None
        for fn in os.listdir(tmpdir):
            if fn.endswith(".shp"):
                shp_file = os.path.join(tmpdir, fn)
                break

        if not shp_file:
            log.error("tailings: no .shp found in Zenodo zip")
            return 0

        # Import via ogr2ogr — map 'Name' field to dam_name
        layer_name = os.path.splitext(os.path.basename(shp_file))[0]
        cmd = [
            OGR2OGR, "-f", "PostgreSQL", _pg_conn_string(), shp_file,
            "-nln", "tailings_dams", "-append",
            "-nlt", "POINT", "-lco", "GEOMETRY_NAME=geom",
            "-t_srs", "EPSG:4326", "--config", "PG_USE_COPY", "YES",
            "-sql", f'SELECT Name AS dam_name FROM "{layer_name}"',
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            log.error("tailings ogr2ogr failed: %s", result.stderr)
            return 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    async with db.pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM tailings_dams")

        # Fix mojibake in dam names — the source shapefile's DBF reader
        # interprets UTF-8 bytes as CP437, producing box-drawing characters.
        # Reverse: encode as CP437 → decode as UTF-8.
        rows = await conn.fetch("SELECT id, dam_name FROM tailings_dams")
        for r in rows:
            name = r["dam_name"]
            if not name or name.isascii():
                continue
            try:
                correct = name.encode("cp437").decode("utf-8")
                if correct != name:
                    await conn.execute(
                        "UPDATE tailings_dams SET dam_name = $1 WHERE id = $2",
                        correct, r["id"],
                    )
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass  # genuine non-Latin text (Chinese 尾矿库), skip

    global _tailings_cache
    _tailings_cache = None
    await _log_land_sync("tailings", total, total)
    log.info("tailings: imported %d dams from Zenodo", total)
    return total


# ── Hazard normalisation for GRID-Arendal data ──────────────────────────────

def _normalise_hazard(raw: str | None) -> str:
    """Map 100+ hazard categorisations from different classification systems
    into a simplified 6-tier risk scale."""
    if not raw or raw.strip() in ("", "N/A", "NA", "n/a", "-", "Not Given",
                                   "Not classified", "Unknown", "Unclassified",
                                   "Not rated", "not categorized", "Not applicable"):
        return "Unclassified"
    h = raw.strip().lower().rstrip(".")
    # Extreme tier
    if any(k in h for k in ("extreme", "catastrophic")):
        return "Extreme"
    # Very High tier
    if "very high" in h:
        return "Very High"
    # High tier
    if any(k in h for k in ("high", "major", "serious", "category 1",
                             "class 1", "hazard class i", "level 5",
                             "high consequence")):
        return "High"
    # Significant tier
    if any(k in h for k in ("significant", "category a")):
        return "Significant"
    # Medium tier
    if any(k in h for k in ("medium", "moderate", "category b", "class 2",
                             "class ii", "level 3")):
        return "Medium"
    # Low tier
    if any(k in h for k in ("low", "minor", "insignificant", "non-hazard",
                             "small", "category c", "class 3", "class iii",
                             "not high")):
        return "Low"
    return "Unclassified"


GRID_TAILINGS_API = "https://tailing.grida.no/api/tailings_all?format=json"


async def _enrich_tailings_from_grid(force: bool = False) -> int:
    """
    Fetch ~2,100 tailings facilities from GRID-Arendal Global Tailings Portal
    and enrich our WAPHA dams with risk, height, volume, ownership data.
    Matches by spatial proximity (< 5 km). Unmatched GRID dams are inserted.
    """
    async with db.pool.acquire() as conn:
        last = await conn.fetchval(
            "SELECT last_synced_at FROM sync_log WHERE source = $1", "tailings_enrich")
        run, why = should_sync("tailings_enrich", last, datetime.now(timezone.utc), force=force)
        log.info("%s", why)
        if not run:
            return 0
        # Add new columns if they don't exist (idempotent migration)
        for col, typ in [
            ("owner_company", "TEXT"),
            ("operator", "TEXT"),
            ("construction_year", "INTEGER"),
            ("hazard_raw", "TEXT"),
            ("raise_type", "TEXT"),
            ("data_source", "TEXT DEFAULT 'wapha'"),
        ]:
            await conn.execute(f"""
                DO $$ BEGIN
                    ALTER TABLE tailings_dams ADD COLUMN {col} {typ};
                EXCEPTION WHEN duplicate_column THEN NULL;
                END $$
            """)

        # Check if already enriched
        enriched = await conn.fetchval(
            "SELECT COUNT(*) FROM tailings_dams WHERE data_source = 'grid'"
        )
        if enriched and enriched > 100:
            log.info("tailings-enrich: already have %d GRID records, skipping", enriched)
            return 0

    log.info("tailings-enrich: fetching from GRID-Arendal API...")
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        resp = await client.get(GRID_TAILINGS_API)
        resp.raise_for_status()
        facilities = resp.json()

    log.info("tailings-enrich: got %d facilities, matching...", len(facilities))
    matched = 0
    inserted = 0

    async with db.pool.acquire() as conn:
        for fac in facilities:
            lat = fac.get("latitude")
            lon = fac.get("longitude")
            if not lat or not lon:
                continue

            risk_class = _normalise_hazard(fac.get("hazard_categorization"))
            dam_type = (fac.get("raise_type") or "").strip() or None
            height = fac.get("current_maximum_height")
            volume = fac.get("current_tailings_storage")
            status = (fac.get("status") or "").strip() or None
            owner = (fac.get("owner_company") or "").strip() or None
            operator = (fac.get("operator") or "").strip() or None
            mine = (fac.get("mine") or "").strip() or None
            tsf_name = (fac.get("tsf") or "").strip() or None
            year = fac.get("construction_year")
            hazard_raw = (fac.get("hazard_categorization") or "").strip() or None
            country = (fac.get("country") or "").strip() or None
            # GRID's stable key for this facility. Stored so the enrichment link
            # is auditable instead of being re-guessed from distance each run.
            ubc = str(fac.get("ubc_number")).strip() if fac.get("ubc_number") else None

            # Try to match to an existing WAPHA dam within 5 km.
            #
            # ⛔ The exclusion used to be `data_source IS DISTINCT FROM 'grid'`,
            # which skipped GRID's own inserted rows but NOT the ones a previous
            # facility had already enriched ('grid-enriched'). So a second GRID
            # facility could claim a dam that already carried a first one's
            # attributes and overwrite risk_class, owner_company and operator —
            # none of which are COALESCEd.
            #
            # Measured against the live GRID API on 2026-09-10: 2,144
            # facilities, 1,406 dams matched, 224 of them the nearest match for
            # MORE THAN ONE facility, giving 473 overwrites. Dam id 7832 was
            # claimed by 22 different facilities; its hazard rating and owner
            # were simply whichever came last in the API's ordering.
            #
            # This portal mirrors its sources 1:1. Attributing GRID's record of
            # facility A to dam B is not mirroring, it is misattribution — and
            # risk_class is a safety rating. A facility that cannot claim an
            # unclaimed dam is stored as its own row instead, below, which keeps
            # both sources intact and invents no link.
            match_id = await conn.fetchval("""
                SELECT id FROM tailings_dams
                WHERE ST_DWithin(geom::geography,
                      ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography,
                      5000)
                  AND data_source IS DISTINCT FROM 'grid'
                  AND data_source IS DISTINCT FROM 'grid-enriched'
                ORDER BY geom <-> ST_SetSRID(ST_MakePoint($1, $2), 4326)
                LIMIT 1
            """, lon, lat)

            if match_id:
                # Enrich existing dam
                await conn.execute("""
                    UPDATE tailings_dams SET
                        risk_class = $1, dam_type = COALESCE(dam_type, $2),
                        height_m = COALESCE(height_m, $3),
                        volume_m3 = COALESCE(volume_m3, $4),
                        status = COALESCE(status, $5),
                        owner_company = $6, operator = $7,
                        mine_name = COALESCE(mine_name, $8),
                        construction_year = $9, hazard_raw = $10,
                        raise_type = $11, data_source = 'grid-enriched',
                        -- GRID's own key for the facility these attributes came
                        -- from. Without it the link was re-derived from bare
                        -- proximity on every run and nobody could audit which
                        -- facility a dam's hazard rating actually describes.
                        grid_facility_id = $13
                    WHERE id = $12
                """, risk_class, dam_type, height, volume, status,
                     owner, operator, mine, year, hazard_raw, dam_type, match_id,
                     ubc)
                matched += 1
            else:
                # Insert as new dam
                await conn.execute("""
                    INSERT INTO tailings_dams
                        (dam_name, mine_name, country, dam_type, height_m,
                         volume_m3, risk_class, status, owner_company, operator,
                         construction_year, hazard_raw, raise_type, data_source,
                         grid_facility_id, geom)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
                            'grid', $16, ST_SetSRID(ST_MakePoint($14, $15), 4326))
                """, tsf_name, mine, country, dam_type, height,
                     volume, risk_class, status, owner, operator,
                     year, hazard_raw, dam_type, lon, lat, ubc)
                inserted += 1

    global _tailings_cache
    _tailings_cache = None
    total = matched + inserted
    await _log_land_sync("tailings_enrich", total, total)
    log.info("tailings-enrich: matched %d, inserted %d (%d total)", matched, inserted, total)
    return total


@router.get("/tailings")
async def get_tailings():
    global _tailings_cache
    if _tailings_cache:
        return Response(content=_tailings_cache, media_type="application/json")

    async with db.pool.acquire() as conn:
        row = await conn.fetchval("""
            SELECT json_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(json_agg(
                    json_build_object(
                        'type', 'Feature',
                        'geometry', ST_AsGeoJSON(geom)::json,
                        'properties', json_build_object(
                            'id', id,
                            'dam_name', dam_name,
                            'mine_name', mine_name,
                            'country', country,
                            'dam_type', dam_type,
                            'height_m', height_m,
                            'volume_m3', volume_m3,
                            'risk_class', risk_class,
                            'status', status,
                            'owner_company', owner_company,
                            'operator', operator,
                            'construction_year', construction_year,
                            'hazard_raw', hazard_raw,
                            'raise_type', raise_type,
                            'data_source', data_source,
                            'latitude', ROUND(ST_Y(geom)::numeric, 4),
                            'longitude', ROUND(ST_X(geom)::numeric, 4)
                        )
                    )
                ), '[]'::json)
            )::text
            FROM tailings_dams
        """)
    _tailings_cache = row
    return Response(content=row, media_type="application/json")



# surface-water, carbon-flux, soil-carbon: raster tile layers (frontend-only)

# ── Global Dams ────────────────────────────────────────────────────────────

async def _sync_dams(force: bool = False) -> int:
    """
    Import Global Dam Watch data.
    Source: https://www.globaldamwatch.org/database
    Place downloaded file in /opt/abyssal-data/dams/ on VPS.
    """
    async with db.pool.acquire() as conn:
        last = await conn.fetchval(
            "SELECT last_synced_at FROM sync_log WHERE source = $1", "dams")
        run, why = should_sync("dams", last, datetime.now(timezone.utc), force=force)
        log.info("%s", why)
        if not run:
            return 0
        count = await conn.fetchval("SELECT COUNT(*) FROM dams")
        if count > 0:
            log.info("dams: already have %d records, skipping", count)
            # ⛔ The row-count guard stays even under force. These loads use
            # `ogr2ogr -append`, so re-running against a populated table
            # DOUBLES it — force skips the cadence window, never the duplicate
            # barrier. Logged at WARNING so a forced run that does nothing is
            # visible rather than being reported as a success.
            if force:
                log.warning(
                    "dams: force requested but the table already holds %d rows; "
                    "this load is append-only and cannot be safely re-run. "
                    "TRUNCATE deliberately first if a reload is really wanted.",
                    count)
            return 0

    dams_path = "/opt/abyssal-data/dams"
    src_file = None
    if os.path.isdir(dams_path):
        for fn in os.listdir(dams_path):
            if fn.endswith((".csv", ".geojson", ".gpkg", ".shp")):
                src_file = os.path.join(dams_path, fn)
                break

    if not src_file:
        log.warning("dams: no data file in %s — download from globaldamwatch.org", dams_path)
        return 0

    if src_file.endswith(".csv"):
        with open(src_file) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        inserted = 0
        async with db.pool.acquire() as conn:
            for r in rows:
                try:
                    lat = float(r.get("latitude") or r.get("lat") or r.get("LAT_DD") or 0)
                    lon = float(r.get("longitude") or r.get("lon") or r.get("LONG_DD") or 0)
                    if lat == 0 and lon == 0:
                        continue
                    await conn.execute("""
                        INSERT INTO dams
                            (dam_name, river, country, height_m, purpose, year_built, volume_mcm, geom)
                        VALUES ($1, $2, $3, $4, $5, $6, $7,
                                ST_SetSRID(ST_MakePoint($8, $9), 4326))
                    """,
                        r.get("DAM_NAME", r.get("dam_name", "")),
                        r.get("RIVER", r.get("river", "")),
                        r.get("COUNTRY", r.get("country", "")),
                        float(r.get("DAM_HGT_M", r.get("height_m", 0)) or 0),
                        r.get("MAIN_USE", r.get("purpose", "")),
                        int(r.get("YEAR", r.get("year_built", 0)) or 0),
                        float(r.get("CATCH_SKM", r.get("volume_mcm", 0)) or 0),
                        lon, lat,
                    )
                    inserted += 1
                except Exception as e:
                    log.warning("dams: row failed: %s", e)
            total = await conn.fetchval("SELECT COUNT(*) FROM dams")
    else:
        cmd = [
            OGR2OGR, "-f", "PostgreSQL", _pg_conn_string(), src_file,
            "-nln", "dams", "-append",
            "-nlt", "POINT", "-lco", "GEOMETRY_NAME=geom",
            "-t_srs", "EPSG:4326", "--config", "PG_USE_COPY", "YES",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            log.error("dams ogr2ogr failed: %s", result.stderr)
            return 0
        async with db.pool.acquire() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM dams")
        inserted = total

    global _dams_cache
    _dams_cache = None
    await _log_land_sync("dams", inserted, total)
    log.info("dams: %d new / %d total", inserted, total)
    return inserted


@router.get("/dams")
async def get_dams():
    global _dams_cache
    if _dams_cache:
        return Response(content=_dams_cache, media_type="application/json")

    async with db.pool.acquire() as conn:
        row = await conn.fetchval("""
            SELECT json_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(json_agg(
                    json_build_object(
                        'type', 'Feature',
                        'geometry', ST_AsGeoJSON(geom)::json,
                        'properties', json_build_object(
                            'id', id,
                            'dam_name', dam_name,
                            'river', river,
                            'country', country,
                            'height_m', height_m,
                            'purpose', purpose,
                            'year_built', year_built,
                            'volume_mcm', volume_mcm
                        )
                    )
                ), '[]'::json)
            )::text
            FROM dams
        """)
    _dams_cache = row
    return Response(content=row, media_type="application/json")

