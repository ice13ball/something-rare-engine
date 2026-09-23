# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""
Extractive-industry land layers: mining footprints, key biodiversity areas
(KBAs), WDPA protected areas, tailings dams, and global dams. Split out of
land_layers.py.

`_normalise_hazard` was removed 2026-09-22 together with the derived
`risk_class` it produced. Its docstring here had claimed it was called only by
`_sync_dams`; it was in fact called by `_enrich_tailings_from_grid`, and the
comment misled a review into looking at the wrong layer.
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


# ⛔ Deleted by accident on 2026-09-03, collateral damage of the commit that
# withdrew the WDPA layer, which took this line with it. `_sync_tailings` has
# raised NameError on every run since. Nothing went red: no test in this repo imported the module, so the
# break was invisible for nineteen days. Restored verbatim.
#
# ⚠️ Zenodo 8324697 is a MIRROR. The citation for this layer is WAPHA on
# Dryad, doi:10.5061/dryad.j3tx95xmg — see rules/layers/tailings-dams.md.
TAILINGS_ZENODO_URL = "https://zenodo.org/records/8324697/files/Global_TSFs.zip?download=1"


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

# ⛔ Deleting the dead `_normalise_hazard` on 2026-09-22 sliced from its `def`
# to the next one, and this constant sat between them. The sync then raised
# `NameError: GRID_TAILINGS_API` on its first real run — after deploy, in
# production. Nothing went red first: the guard test for this module reads the
# source as TEXT and never imports it, so a missing global is invisible to it.
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
            # ⛔ An early return without a log leaves the monitor unable to tell
            # "ran, found nothing" from "never ran" — the engine rule in
            # CLAUDE.md. This one was silent, and the silence is exactly what
            # hid a sync that had not run since April.
            await _log_land_sync("tailings_enrich", 0, 0)
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

    # ⛔ REMOVED 2026-09-22: `if COUNT(data_source='grid') > 100: return 0`.
    #
    # There are 234 such rows, so the condition was true on every run from the
    # day the first batch landed. The enrichment last completed 2026-04-13 and
    # could never run again — not on schedule, and not from the admin panel
    # either, because `force=True` is consumed by `should_sync` ABOVE this point
    # and never reached the guard. The Force Sync button returned success and
    # did nothing.
    #
    # The guard was not paranoia: this sync was not idempotent. A second pass
    # could not re-find the dams it had already enriched, because the spatial
    # match excludes `data_source = 'grid-enriched'`, so it would have inserted
    # ~1,414 duplicates. The fix is to make the pass idempotent rather than to
    # forbid it — the facility's own key (`ubc_number`, stored as
    # `grid_facility_id`) is looked up first, so a re-run refreshes the row it
    # wrote last time.
    #
    # Cost of the freeze, measured against the live API 2026-09-22: GTP now
    # publishes 2,144 facilities, 2,113 with coordinates; we hold 1,648.
    log.info("tailings-enrich: fetching from GRID-Arendal API...")
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        resp = await client.get(GRID_TAILINGS_API)
        resp.raise_for_status()
        facilities = resp.json()

    log.info("tailings-enrich: got %d facilities, matching...", len(facilities))
    matched = 0
    inserted = 0
    refreshed = 0
    skipped_dupe = 0
    skipped_nogeo = 0
    skipped_nokey = 0

    def _txt(key: str) -> str | None:
        """GTP's own string, stripped of surrounding whitespace and nothing else.

        ⛔ No case folding, no vocabulary mapping, no Yes/No coercion. Several of
        these columns are ragged at source — `downstream_impact` holds "Yes",
        "No" AND bare years like "2018"; `history_stability_concerns` holds both
        "No" and "no". That raggedness is the source's, and flattening it would
        be this platform putting words in an operator's mouth.
        """
        return (str(fac.get(key)).strip() or None) if fac.get(key) is not None else None

    async with db.pool.acquire() as conn:
        for fac in facilities:
            # The source marks its own duplicate records. Honouring that flag is
            # mirroring it; re-deriving duplicates ourselves would not be.
            if str(fac.get("duplicate") or "").strip().lower() == "yes":
                skipped_dupe += 1
                continue

            lat = fac.get("latitude")
            lon = fac.get("longitude")
            if not lat or not lon:
                skipped_nogeo += 1
                continue

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
            if not ubc:
                # ⛔ Without the facility's own key this row cannot be claimed,
                # so the NEXT run would match it again and insert a duplicate —
                # the same failure that produced 1,584 of them on 2026-09-22.
                # All 2,144 facilities carried ubc_number when measured that
                # day; if that ever stops being true, the honest answer is to
                # skip and say so, not to write an untrackable row.
                skipped_nokey += 1
                continue

            # ── The 15 fields this sync used to fetch and discard ────────────
            # Stored verbatim. `classification_system` is the one that makes the
            # rest readable: it names WHICH national system produced
            # `hazard_categorization`, and there are 255 of them.
            gtp = (
                _txt("classification_system"),
                _txt("link"),                                 # disclosure_link
                _txt("disclosure_origin"),
                _txt("history_stability_concerns"),
                _txt("downstream_impact"),
                _txt("recent_independent_expert_review"),
                _txt("extreme_weather_secure"),
                _txt("currently_approved_design"),
                _txt("closure_plan_dam"),
                _txt("closure_plan_long_term_monitoring"),
                _txt("internal_external_eng_support"),
                _txt("relevant_engineering_records"),
                _txt("notes"),                                # disclosure_notes
                _txt("partners"),
                fac.get("planned_storage_5_years"),
            )

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
            # ── 1) Already linked to this facility on an earlier run? ────────
            # This lookup is what makes a re-run safe. Without it the spatial
            # match below cannot see rows it enriched last time (it excludes
            # 'grid-enriched' by design), so every pass after the first would
            # insert the same ~1,414 facilities again as fresh rows. That is why
            # the sync was frozen behind a guard instead of being run.
            target_id = await conn.fetchval(
                "SELECT id FROM tailings_dams WHERE grid_facility_id = $1", ubc
            ) if ubc else None
            first_link = False

            # ── 2) Otherwise, match the nearest UNCLAIMED row within 5 km ────
            #
            # ⛔ The exclusion is `grid_facility_id IS NULL`, NOT a data_source
            # test. That distinction cost 1,584 duplicate rows in production on
            # 2026-09-22 and had to be deleted by hand.
            #
            # What happened: `grid_facility_id` was added on 2026-09-10, but
            # this sync had not run since 2026-04-13, so the column was NULL on
            # all 1,648 rows the April run had written. The lookup in step 1
            # therefore matched nothing, and the old exclusion — on data_source
            # — hid those very rows from step 2 as well. Every facility fell
            # through to INSERT: "0 refreshed, 336 newly matched, 1584
            # inserted". An idempotency key that nothing has populated yet is
            # not idempotency; claiming otherwise is how this shipped.
            #
            # Keying the exclusion on the key itself fixes both halves at once:
            # a legacy row with no key is adoptable exactly once, and the claim
            # writes the key, so no later facility in the same pass can take it.
            match_id = None if target_id else await conn.fetchval("""
                SELECT id FROM tailings_dams
                WHERE ST_DWithin(geom::geography,
                      ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography,
                      5000)
                  AND grid_facility_id IS NULL
                ORDER BY geom <-> ST_SetSRID(ST_MakePoint($1, $2), 4326)
                LIMIT 1
            """, lon, lat)
            if match_id:
                target_id, first_link = match_id, True

            if target_id:
                # ⛔ `risk_class` is set to NULL, not written.
                #
                # It held this platform's own 6-tier collapse of
                # `hazard_categorization` — Extreme / Very High / High /
                # Significant / Medium / Low — produced by keyword-matching the
                # source string. The source publishes 120 distinct ratings drawn
                # from 255 different national classification systems, so that
                # collapse asserted a comparability the source does not claim.
                # Michal's ruling 2026-09-22: show the source's own rating, run
                # no scoring of our own. What replaces it is `hazard_raw` beside
                # `classification_system`, both verbatim.
                #
                # ⚠️ No COALESCE on the GTP-derived columns. The WAPHA shapefile
                # publishes exactly one attribute, `Name`, so there is no local
                # value here to protect — and COALESCE would freeze whatever the
                # first run saw, which is the opposite of mirroring a source that
                # updates. `dam_name` and `country` are not touched: those ARE
                # local (WAPHA's name; a platform-derived country).
                await conn.execute("""
                    UPDATE tailings_dams SET
                        risk_class = NULL,
                        dam_type = $1, height_m = $2, volume_m3 = $3,
                        status = $4, owner_company = $5, operator = $6,
                        mine_name = $7, construction_year = $8, hazard_raw = $9,
                        raise_type = $10,
                        -- A row first seen as a GRID-only facility stays 'grid';
                        -- only a WAPHA dam we enriched becomes 'grid-enriched'.
                        -- Without this a refresh silently reclassified 234 rows.
                        data_source = CASE WHEN data_source = 'grid'
                                           THEN 'grid' ELSE 'grid-enriched' END,
                        grid_facility_id = $11,
                        classification_system = $12, disclosure_link = $13,
                        disclosure_origin = $14, history_stability_concerns = $15,
                        downstream_impact = $16, recent_independent_expert_review = $17,
                        extreme_weather_secure = $18, currently_approved_design = $19,
                        closure_plan_dam = $20, closure_plan_long_term_monitoring = $21,
                        internal_external_eng_support = $22,
                        relevant_engineering_records = $23, disclosure_notes = $24,
                        partners = $25, planned_storage_5_years = $26
                    WHERE id = $27
                """, dam_type, height, volume, status, owner, operator, mine,
                     year, hazard_raw, dam_type, ubc, *gtp, target_id)
                if first_link:
                    matched += 1
                else:
                    refreshed += 1
            else:
                # Insert as new dam
                await conn.execute("""
                    INSERT INTO tailings_dams
                        (dam_name, mine_name, country, dam_type, height_m,
                         volume_m3, status, owner_company, operator,
                         construction_year, hazard_raw, raise_type, data_source,
                         grid_facility_id,
                         classification_system, disclosure_link, disclosure_origin,
                         history_stability_concerns, downstream_impact,
                         recent_independent_expert_review, extreme_weather_secure,
                         currently_approved_design, closure_plan_dam,
                         closure_plan_long_term_monitoring,
                         internal_external_eng_support, relevant_engineering_records,
                         disclosure_notes, partners, planned_storage_5_years,
                         geom)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                            'grid', $13,
                            $14, $15, $16, $17, $18, $19, $20, $21, $22, $23,
                            $24, $25, $26, $27, $28,
                            ST_SetSRID(ST_MakePoint($29, $30), 4326))
                """, tsf_name, mine, country, dam_type, height,
                     volume, status, owner, operator,
                     year, hazard_raw, dam_type, ubc, *gtp, lon, lat)
                inserted += 1

    global _tailings_cache
    _tailings_cache = None
    total = matched + inserted + refreshed
    # `fetched` is what the source offered, `stored` what we wrote. Reporting
    # the same number for both hides a source that shrank.
    await _log_land_sync("tailings_enrich", len(facilities), total)
    log.info(
        "tailings-enrich: %d facilities from source → %d refreshed, %d newly matched, "
        "%d inserted (skipped: %d flagged duplicate at source, %d without coordinates, %d without a facility key)",
        len(facilities), refreshed, matched, inserted, skipped_dupe, skipped_nogeo, skipped_nokey)
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
                            'status', status,
                            'owner_company', owner_company,
                            'operator', operator,
                            'construction_year', construction_year,
                            -- ⛔ `risk_class` is gone from this response. It was
                            -- this platform's own collapse of the line below
                            -- into six tiers; the source's own rating is
                            -- `hazard_raw`, and `classification_system` names
                            -- the system that produced it. Sending both and
                            -- letting the reader see them is the whole point.
                            'hazard_raw', hazard_raw,
                            'classification_system', classification_system,
                            'raise_type', raise_type,
                            'data_source', data_source,
                            -- The operator's own answers, as published by the
                            -- Global Tailings Portal. Ragged on purpose: some
                            -- hold "Yes"/"No", some a bare year. Not cleaned.
                            'history_stability_concerns', history_stability_concerns,
                            'downstream_impact', downstream_impact,
                            'recent_independent_expert_review', recent_independent_expert_review,
                            'extreme_weather_secure', extreme_weather_secure,
                            'currently_approved_design', currently_approved_design,
                            'closure_plan_dam', closure_plan_dam,
                            'closure_plan_long_term_monitoring', closure_plan_long_term_monitoring,
                            'internal_external_eng_support', internal_external_eng_support,
                            'relevant_engineering_records', relevant_engineering_records,
                            'disclosure_origin', disclosure_origin,
                            'disclosure_link', disclosure_link,
                            'disclosure_notes', disclosure_notes,
                            'partners', partners,
                            'planned_storage_5_years', planned_storage_5_years,
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
    """Load GDW — the Global Dam Watch database v1.0 — from the VPS data dir.

    Source: GDW v1.0, figshare doi:10.6084/m9.figshare.25988293.v1, CC BY 4.0.
    File:   /opt/abyssal-data/dams-gdw/GDW_v1_0_shp/GDW_barriers_v1_0.shp
    41,145 barrier points; a separate reservoir-polygon layer is NOT loaded.

    ⛔ WHAT THIS REPLACED. Until 2026-09-11 the layer served GOODD (GOOD2_dams,
    2019), which publishes four fields — DAM_ID, Count_ID, Latitud, Longitud —
    and nothing else, while this function's docstring claimed to import Global
    Dam Watch. Every attribute column was NULL on all 38,667 rows and the
    numeric DAM_ID was rendered where a name belonged. GDW absorbed GOODD and
    GRanD; globaldamwatch.org states both "will be discontinued".

    ⛔ GDW's NO-DATA CODE IS -99, AND IT IS EVERYWHERE. Measured on the loaded
    file: power_mw 40,903 · dam_hgt_m 31,834 · year_dam 25,915 · area_skm 5,824 ·
    cap_mcm 5,811. Stored as-is they would print "-99 m" and "built -99" as
    measurements, so they become SQL NULL — the rule already written down in
    docs/methods/data-passthrough.md for WRI Aqueduct's -9999.
    0 MW is NOT no-data: a non-hydro barrier genuinely generates nothing, so
    only -99 is treated as absent on power_mw.

    ⛔ GDW IS NOT A COMPLETE ATTRIBUTE DATABASE, and the legend says so. Of
    41,145 barriers: country 41,145 (100%), cap_mcm 35,334 (86%), year 15,229
    (37%), NAME 10,071 (24.5%), river 9,501 (23%), height 9,311 (23%),
    power_mw 242 (0.6%). Three quarters of the points still have no name.
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
            # ⛔ The row-count guard stays even under force. This load appends,
            # so re-running against a populated table DOUBLES it — force skips
            # the cadence window, never the duplicate barrier. A deliberate
            # reload is a TRUNCATE plus this function, in one transaction.
            if force:
                log.warning(
                    "dams: force requested but the table already holds %d rows; "
                    "this load is append-only and cannot be safely re-run. "
                    "TRUNCATE deliberately first if a reload is really wanted.",
                    count)
            await _log_land_sync("dams", 0, count)
            return 0

    src_file = None
    for root in ("/opt/abyssal-data/dams-gdw", "/opt/abyssal-data/dams"):
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                # the barrier POINTS, never the reservoir polygons
                if fn.lower().endswith(".shp") and "barrier" in fn.lower():
                    src_file = os.path.join(dirpath, fn)
                    break
            if src_file:
                break
        if src_file:
            break

    if not src_file:
        log.warning(
            "dams: no GDW barrier shapefile under /opt/abyssal-data/dams-gdw — "
            "fetch GDW_v1_0_shp.zip from figshare doi:10.6084/m9.figshare.25988293")
        await _log_land_sync("dams", 0, 0)
        return 0

    # Load into a staging table, then map into `dams` in SQL. ogr2ogr cannot
    # express the -99 rule, and a direct -append would carry the sentinels in.
    cmd = [
        OGR2OGR, "-f", "PostgreSQL", _pg_conn_string(), src_file,
        "-nln", "gdw_barriers_staging", "-overwrite", "-nlt", "POINT",
        "-lco", "GEOMETRY_NAME=geom", "-lco", "FID=gid",
        "-t_srs", "EPSG:4326", "--config", "PG_USE_COPY", "YES",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        log.error("dams ogr2ogr failed: %s", result.stderr)
        await _log_land_sync("dams", 0, 0)
        return 0

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            inserted = await conn.fetchval(_GDW_INSERT_SQL)
        total = await conn.fetchval("SELECT COUNT(*) FROM dams")

    global _dams_cache
    _dams_cache = None
    await _log_land_sync("dams", inserted, total)
    log.info("dams: %d new / %d total (GDW v1.0)", inserted, total)
    return inserted


# ⛔ Every -99 becomes NULL here, and nowhere else. Keeping the mapping in one
# named statement is what lets the guard assert on it instead of on prose.
_GDW_INSERT_SQL = """
WITH ins AS (
    INSERT INTO dams (gdw_id, dam_name, river, country, height_m, purpose,
                      year_built, volume_mcm, dam_type, power_mw, grand_id,
                      main_basin, area_skm, quality, geom)
    SELECT s.gdw_id,
           NULLIF(NULLIF(NULLIF(btrim(s.dam_name), ''), 'None'), 'Unknown'),
           NULLIF(btrim(s.river),      ''),
           NULLIF(btrim(s.country),    ''),
           CASE WHEN s.dam_hgt_m > 0   THEN s.dam_hgt_m END,
           NULLIF(btrim(s.main_use),   ''),
           CASE WHEN s.year_dam  > 0   THEN s.year_dam  END,
           CASE WHEN s.cap_mcm   >= 0  THEN s.cap_mcm   END,
           NULLIF(btrim(s.dam_type),   ''),
           CASE WHEN s.power_mw  > -99 THEN s.power_mw  END,
           CASE WHEN s.grand_id  > 0   THEN s.grand_id  END,
           NULLIF(btrim(s.main_basin), ''),
           CASE WHEN s.area_skm  >= 0  THEN s.area_skm  END,
           NULLIF(btrim(s.quality),    ''),
           s.geom
    FROM gdw_barriers_staging s
    WHERE s.geom IS NOT NULL
    RETURNING 1
)
SELECT count(*) FROM ins
"""


@router.get("/dams")
async def get_dams():
    global _dams_cache
    if _dams_cache:
        return Response(content=_dams_cache, media_type="application/json")

    async with db.pool.acquire() as conn:
        # ⛔ SIZE IS A PROPERTY OF THIS ENDPOINT, NOT AN AFTERTHOUGHT.
        # Moving from GOODD to GDW took the payload to 16.72 MB decoded across
        # 41,145 features and the browser stalled for tens of seconds parsing
        # it. The wire was never the problem: 1.26 MB gzipped in 1.97 s.
        #
        # Two changes, both lossless for a reader:
        #   json_strip_nulls  — GDW leaves most attributes empty and a null
        #     costs as many bytes as a value. power_mw alone spent 0.78 MB to
        #     carry 242 real numbers among 40,903 nulls. An ABSENT key and a
        #     null key render identically here: every panel row sits behind a
        #     presence check, and in JavaScript `undefined != null` is false.
        #   ST_AsGeoJSON(geom, 5) — five decimals is about one metre. These
        #     are point centroids of dam structures, not survey marks.
        row = await conn.fetchval("""
            SELECT json_strip_nulls(json_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(json_agg(
                    json_build_object(
                        'type', 'Feature',
                        'geometry', ST_AsGeoJSON(geom, 5)::json,
                        'properties', json_build_object(
                            'id', id,
                            'gdw_id', gdw_id,
                            'dam_name', dam_name,
                            'river', river,
                            'country', country,
                            'main_basin', main_basin,
                            'height_m', height_m,
                            'purpose', purpose,
                            'dam_type', dam_type,
                            'year_built', year_built,
                            'volume_mcm', volume_mcm,
                            'area_skm', area_skm,
                            'power_mw', power_mw,
                            'grand_id', grand_id
                            -- ⛔ `quality` is deliberately NOT sent. It is GDW's
                            -- internal editorial-confidence flag, present on all
                            -- 41,145 rows, and no panel renders it — 0.95 MB of a
                            -- payload the browser has to parse for something no
                            -- reader ever sees. It stays in the table; add it back
                            -- here only alongside a row that displays it.
                        )
                    )
                ), '[]'::json)
            ))::text
            FROM dams
        """)
    _dams_cache = row
    return Response(content=row, media_type="application/json")

