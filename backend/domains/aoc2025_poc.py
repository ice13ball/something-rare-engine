# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""Preview layer (dev-only) `greenland-sea-poc-aoc2025` — particulate organic
carbon in the Greenland Sea, AOC2025 cruise (IO PAN, doi:10.48457/IOPAN.2026.571,
CC-BY 4.0).

Storage is 1:1 with the source (schema/aoc2025_poc.py). Serving hides nothing —
every stored column is in AOC_POC_SERVED_FIELDS except `raw`/`geom`, which are
structural (see AOC_POC_HIDDEN_FIELDS) — but the allowlist discipline matches
every other layer in this codebase so a column added later is served by nobody
until someone decides.

Sync, daily (scheduling.py, 24 h after sync_log.last_synced_at) and on admin force-sync ("aoc2025-poc"):
  1. download the whole CSV;
  2. refuse (raise) on a header mismatch — refuses to guess column positions;
  3. same SHA-256 as the current version -> nothing new;
  4. new SHA-256 -> insert a NEW version's rows and flip is_current, in one
     transaction. Old versions stay: there is no upsert and nothing is deleted.
Any failure aborts before the transaction commits; log_sync_skipped records why.
"""
from __future__ import annotations

import hashlib
import logging

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

import db
from auth import get_api_key
from ingestion import aoc2025_poc as parser
from ingestion.http_retry import get_with_retry
from sync_log import log_sync as _log_sync
from sync_log import log_sync_skipped as _log_sync_skipped

log = logging.getLogger(__name__)
router = APIRouter()

_UA = {"User-Agent": "abyssal-claims/1.0 (+https://something-rare.com)"}
SYNC_SOURCE = "aoc2025-poc"

#: Author + title + publisher + DOI, taken verbatim from the ISO XML
#: (citedResponsibleParty / CI_Citation), never retyped from memory.
CITATION = (
    "Kowalczuk, P. (2026). Particulate organic carbon concentrations in water "
    "samples collected in the Greenland Sea, during Atlantic-Arctic Ocean Change "
    "cruise (AOC2025) between 19-31 May 2025. Institute of Oceanology Polish "
    "Academy of Sciences. https://doi.org/10.48457/IOPAN.2026.571"
)
LICENSE = "CC-BY 4.0"

#: The metadata record's own temporal extent (gml:TimePeriod) does NOT match the
#: title or the data (both May 2025) — a defect of the source, shown, not fixed.
METADATA_TEMPORAL_EXTENT_DISCREPANCY = (
    "The dataset's ISO metadata states a temporal extent of 2024-07-24..2024-08-09; "
    "the title and every sample date in the data itself are 19-31 May 2025. This "
    "platform uses the dates in the data."
)

_stations_cache: str | None = None


def clear_caches() -> None:
    global _stations_cache
    _stations_cache = None


async def _fetch_bytes(url: str, *, timeout: float = 60.0) -> bytes:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=_UA) as client:
        response = await get_with_retry(client, url, label="aoc2025-poc")
        response.raise_for_status()
        return response.content


def _insert_sql() -> str:
    cols = ["version_id", "row_no", *parser.FIELDS, "raw"]
    lat = cols.index("lat") + 1
    lon = cols.index("lon") + 1
    geom = (f"CASE WHEN ${lat}::float8 IS NULL OR ${lon}::float8 IS NULL THEN NULL "
            f"ELSE ST_SetSRID(ST_MakePoint(${lon}::float8, ${lat}::float8), 4326) END")
    values = ", ".join(f"${i}" for i in range(1, len(cols) + 1))
    return f"INSERT INTO aoc2025_poc_samples ({', '.join(cols)}, geom) VALUES ({values}, {geom})"


async def sync_aoc2025_poc(force: bool = False) -> int:
    try:
        return await _sync_inner(force)
    except (parser.Aoc2025PocFormatError, httpx.HTTPError, UnicodeDecodeError) as exc:
        reason = f"aborted, stored version untouched: {type(exc).__name__}: {exc}"[:500]
        await _log_sync_skipped(SYNC_SOURCE, reason)
        log.error("%s: %s", SYNC_SOURCE, reason)
        raise
    except asyncpg.PostgresError as exc:
        reason = f"aborted, stored version untouched: {type(exc).__name__}: {exc}"[:500]
        await _log_sync_skipped(SYNC_SOURCE, reason)
        log.error("%s: %s", SYNC_SOURCE, reason)
        raise


async def _sync_inner(force: bool) -> int:
    raw = await _fetch_bytes(parser.SOURCE_URL)
    sha = hashlib.sha256(raw).hexdigest()

    async with db.pool.acquire() as conn:
        current = await conn.fetchrow(
            "SELECT version_id, sha256, rows_in_source FROM aoc2025_poc_version WHERE is_current")
        stored = 0
        if current is not None:
            stored = await conn.fetchval(
                "SELECT count(*) FROM aoc2025_poc_samples WHERE version_id = $1", current["version_id"])

    whole = current is not None and stored == current["rows_in_source"]
    if not force and current is not None and sha == current["sha256"] and whole:
        await _log_sync(SYNC_SOURCE, 0, stored)
        log.info("%s: same file (sha256 %s) - nothing new", SYNC_SOURCE, sha[:12])
        return 0

    pf = parser.parse_csv(raw)
    records = [parser.parse_row(i + 1, cells) for i, cells in enumerate(pf.rows)]
    n_rows = len(records)

    if current is not None and sha == current["sha256"]:
        if whole:
            await _log_sync(SYNC_SOURCE, 0, stored)
            log.info("%s: same file (sha256 %s) - nothing new", SYNC_SOURCE, sha[:12])
            return 0
        if stored != 0:
            raise parser.Aoc2025PocFormatError(
                f"version {current['version_id']} holds {stored} of {current['rows_in_source']} "
                "rows; refusing to add to a partial version")
        version_id, new_version = current["version_id"], False
    else:
        version_id, new_version = None, True

    sql = _insert_sql()
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            if new_version:
                version_id = await conn.fetchval(
                    """INSERT INTO aoc2025_poc_version
                         (is_current, doi, source_url, sha256, rows_in_source, citation, license)
                       VALUES (false, $1, $2, $3, $4, $5, $6)
                       RETURNING version_id""",
                    parser.DOI, parser.SOURCE_URL, sha, n_rows, CITATION, LICENSE,
                )
            batch = [
                (version_id, rec["row_no"], *[rec[f] for f in parser.FIELDS], rec["raw"])
                for rec in records
            ]
            if batch:
                await conn.executemany(sql, batch)
            if new_version:
                await conn.execute(
                    "UPDATE aoc2025_poc_version SET is_current = false WHERE is_current")
                await conn.execute(
                    "UPDATE aoc2025_poc_version SET is_current = true WHERE version_id = $1", version_id)

    clear_caches()
    await _log_sync(SYNC_SOURCE, n_rows, n_rows)
    log.info("%s: version %s current - %d rows, sha256 %s", SYNC_SOURCE, version_id, n_rows, sha[:12])
    return n_rows


# ── Serving allowlists ─────────────────────────────────────────────────────
# ⛔ Every stored column appears in EXACTLY ONE of SERVED / HIDDEN
# (tests/test_aoc2025_poc_serving.py).

AOC_POC_SERVED_FIELDS: tuple[str, ...] = (
    "version_id", "row_no", "cruise_id", "station", "sample_date", "lat", "lon",
    "prespr01_db", "pressure_db", "activity", "sample_id", "salinity", "temp_c",
    "d15n_permil", "d13c_permil", "poc_mg_dm3", "pn_mg_dm3",
)
AOC_POC_HIDDEN_FIELDS: dict[str, str] = {
    "raw": "Every source cell verbatim, kept so a later exposure needs no re-sync — "
           "not an API field because every typed column it carries is already served.",
    "geom": "Served as the feature geometry, never as a property; lat and lon carry the position.",
}

#: Unit for each served measurement field, and where the string comes from.
#: ⛔ Never invented — see ingestion/aoc2025_poc.py module docstring.
AOC_POC_UNITS: dict[str, str] = {
    "prespr01_db": parser.PRESPR01_UNIT,
    "pressure_db": "db",
    "salinity": "PSU",
    "temp_c": "°C",
    "d15n_permil": parser.D15N_UNIT,
    "d13c_permil": parser.D13C_UNIT,
    "poc_mg_dm3": parser.POC_PN_UNIT,
    "pn_mg_dm3": parser.POC_PN_UNIT,
}

_EMPTY_FC = '{"type":"FeatureCollection","features":[]}'


def _jsonable(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


@router.get("/v1/map/aoc2025-poc/stations", dependencies=[Depends(get_api_key)])
async def aoc2025_poc_stations():
    """One feature per station of the current version — n_samples, depth range
    (nominal depth/pressure, SDN:P01::PRESPR01) and observation date range.
    ⛔ No measurement is aggregated across samples at a station."""
    global _stations_cache
    if _stations_cache is not None:
        return Response(content=_stations_cache, media_type="application/json")
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable")
    async with db.pool.acquire() as conn:
        txt = await conn.fetchval("""
            SELECT json_build_object('type', 'FeatureCollection', 'features',
                     COALESCE(json_agg(f ORDER BY station), '[]'::json))::text
            FROM (
              SELECT station,
                     (array_agg(lat ORDER BY row_no))[1] AS lat,
                     (array_agg(lon ORDER BY row_no))[1] AS lon,
                     json_build_object(
                       'type', 'Feature',
                       'geometry', json_build_object('type', 'Point',
                         'coordinates', json_build_array((array_agg(lon ORDER BY row_no))[1],
                                                          (array_agg(lat ORDER BY row_no))[1])),
                       'properties', json_build_object(
                         'station', station,
                         'n_samples', count(*),
                         'depth_min_db', min(prespr01_db), 'depth_max_db', max(prespr01_db),
                         'date_min', min(sample_date), 'date_max', max(sample_date))) AS f
              FROM aoc2025_poc_samples_current
              WHERE geom IS NOT NULL
              GROUP BY station
            ) s""")
    _stations_cache = txt or _EMPTY_FC
    return Response(content=_stations_cache, media_type="application/json")


@router.get("/v1/map/aoc2025-poc/samples", dependencies=[Depends(get_api_key)])
async def aoc2025_poc_samples(station: str = Query(...)):
    """Every current-version sample at one station, ordered by depth (nominal
    depth/pressure, PRESPR01)."""
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable")
    cols = ", ".join(AOC_POC_SERVED_FIELDS)
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT {cols} FROM aoc2025_poc_samples_current
                 WHERE station = $1
                 ORDER BY prespr01_db NULLS LAST, row_no""",
            station)
    if not rows:
        raise HTTPException(404, "no AOC2025 POC samples for this station in the current version")
    samples = [{k: _jsonable(r[k]) for k in AOC_POC_SERVED_FIELDS} for r in rows]
    return {"station": station, "n_samples": len(samples), "samples": samples, "units": AOC_POC_UNITS}


@router.get("/v1/map/aoc2025-poc/meta", dependencies=[Depends(get_api_key)])
async def aoc2025_poc_meta():
    """The current stored version: DOI, source URL, SHA-256, row count, citation
    and licence verbatim, plus known source defects and each served field's unit."""
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable")
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT version_id, doi, source_url, sha256, rows_in_source, citation, license, fetched_at
                 FROM aoc2025_poc_version WHERE is_current""")
    if row is None:
        return {"version": None}
    item = {k: _jsonable(row[k]) for k in row.keys()}
    item["units"] = AOC_POC_UNITS
    item["metadata_url"] = parser.METADATA_URL
    item["temporal_extent_discrepancy"] = METADATA_TEMPORAL_EXTENT_DISCREPANCY
    return {"version": item}
