# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""Preview layer (dev-only) `svalbard-fjords-primary-production` — in situ
primary production, Kongsfjorden & Hornsund (Svalbard), 1994-2019 (IO PAN
GeoNetwork 5a2ef3d9-02ea-4b9c-acef-10e9b1968458, doi:10.48457/iopan-2024-198).
© IO PAN, used with permission — the source publishes no open licence.

Storage is 1:1 with the source (schema/svalbard_fjords_pp.py). Serving hides
nothing beyond the structural columns (SVALBARD_FJORDS_PP_HIDDEN_FIELDS) —
same allowlist discipline as every other layer.

Sync, daily (scheduling.py, 24 h after sync_log.last_synced_at) and on admin force-sync ("svalbard-fjords-pp"):
  1. download the whole CSV;
  2. refuse (raise) on a header mismatch — refuses to guess column positions;
  3. same SHA-256 as the current version -> nothing new;
  4. new SHA-256 -> insert a NEW version's rows and flip is_current, in one
     transaction. Old versions stay: there is no upsert and nothing is deleted.
Any failure aborts before the transaction commits; log_sync_skipped records why.
"""
from __future__ import annotations

import hashlib
import json
import logging

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

import db
from auth import get_api_key
from ingestion import svalbard_fjords_pp as parser
from ingestion.http_retry import get_with_retry
from sync_log import log_sync as _log_sync
from sync_log import log_sync_skipped as _log_sync_skipped

log = logging.getLogger(__name__)
router = APIRouter()

_UA = {"User-Agent": "abyssal-claims/1.0 (+https://something-rare.com)"}
SYNC_SOURCE = "svalbard-fjords-pp"

#: Author + title + publisher + DOI, taken verbatim from the ISO XML
#: (citedResponsibleParty / CI_Citation), never retyped from memory.
CITATION = (
    "Institute of Oceanology Polish Academy of Sciences (2024). In situ primary "
    "production, Kongsfjorden & Hornsund (Svalbard), 1994-2019. "
    "https://doi.org/10.48457/iopan-2024-198"
)
LICENCE = parser.LICENCE

#: Metadata's own claims, kept as constants; the data side is computed at serve
#: time in _discrepancies() so this module never re-derives what the source says.
_METADATA_INCUBATION_TOTAL = 348
_METADATA_HORNSUND_LEVELS = 137
_METADATA_KONGSFJORDEN_LEVELS = 232
_METADATA_KONGSFJORDEN_STATIONS = 28
_METADATA_HORNSUND_STATIONS = 17
_METADATA_BBOX_WEST = 11.0308

_stations_cache: str | None = None


def clear_caches() -> None:
    global _stations_cache
    _stations_cache = None


async def _fetch_bytes(url: str, *, timeout: float = 60.0) -> bytes:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=_UA) as client:
        response = await get_with_retry(client, url, label="svalbard-fjords-pp")
        response.raise_for_status()
        return response.content


def _insert_sql() -> str:
    cols = ["version_id", "row_no", *parser.FIELDS, "raw"]
    lat = cols.index("lat") + 1
    lon = cols.index("lon") + 1
    geom = (f"CASE WHEN ${lat}::float8 IS NULL OR ${lon}::float8 IS NULL THEN NULL "
            f"ELSE ST_SetSRID(ST_MakePoint(${lon}::float8, ${lat}::float8), 4326) END")
    values = ", ".join(f"${i}" for i in range(1, len(cols) + 1))
    return f"INSERT INTO svalbard_fjords_pp_samples ({', '.join(cols)}, geom) VALUES ({values}, {geom})"


async def sync_svalbard_fjords_pp(force: bool = False) -> int:
    try:
        return await _sync_inner(force)
    except (parser.SvalbardFjordsPpFormatError, httpx.HTTPError, UnicodeDecodeError) as exc:
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
            "SELECT version_id, sha256, rows_in_source FROM svalbard_fjords_pp_version WHERE is_current")
        stored = 0
        if current is not None:
            stored = await conn.fetchval(
                "SELECT count(*) FROM svalbard_fjords_pp_samples WHERE version_id = $1", current["version_id"])

    whole = current is not None and stored == current["rows_in_source"]
    if not force and current is not None and sha == current["sha256"] and whole:
        await _log_sync(SYNC_SOURCE, 0, stored)
        log.info("%s: same file (sha256 %s) - nothing new", SYNC_SOURCE, sha[:12])
        return 0

    pf = parser.parse_csv(raw)
    records = [parser.parse_row(i + 1, cells) for i, cells in enumerate(pf.rows)]
    parser.validate_pi_placement(records)
    n_rows = len(records)

    if current is not None and sha == current["sha256"]:
        if whole:
            await _log_sync(SYNC_SOURCE, 0, stored)
            log.info("%s: same file (sha256 %s) - nothing new", SYNC_SOURCE, sha[:12])
            return 0
        if stored != 0:
            raise parser.SvalbardFjordsPpFormatError(
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
                    """INSERT INTO svalbard_fjords_pp_version
                         (is_current, doi, source_url, sha256, rows_in_source, citation, licence)
                       VALUES (false, $1, $2, $3, $4, $5, $6)
                       RETURNING version_id""",
                    parser.DOI, parser.SOURCE_URL, sha, n_rows, CITATION, LICENCE,
                )
            batch = [
                (version_id, rec["row_no"], *[rec[f] for f in parser.FIELDS], rec["raw"])
                for rec in records
            ]
            if batch:
                await conn.executemany(sql, batch)
            if new_version:
                await conn.execute(
                    "UPDATE svalbard_fjords_pp_version SET is_current = false WHERE is_current")
                await conn.execute(
                    "UPDATE svalbard_fjords_pp_version SET is_current = true WHERE version_id = $1", version_id)

    clear_caches()
    await _log_sync(SYNC_SOURCE, n_rows, n_rows)
    log.info("%s: version %s current - %d rows, sha256 %s", SYNC_SOURCE, version_id, n_rows, sha[:12])
    return n_rows


# ── Serving allowlists ─────────────────────────────────────────────────────
# ⛔ Every stored column appears in EXACTLY ONE of SERVED / HIDDEN
# (tests/test_svalbard_fjords_pp_serving.py).

SVALBARD_FJORDS_PP_SERVED_FIELDS: tuple[str, ...] = (
    "version_id", "row_no", "exposition_no", "sample_date", "region_code", "fjord_part",
    "station", "lat", "lon", "depth_m", "temperature_degc", "salinity", "ca_mg_m3",
    "pe_mgc_m3_h", "pi_mgc_m2_day", "water_mass",
)
SVALBARD_FJORDS_PP_HIDDEN_FIELDS: dict[str, str] = {
    "raw": "Every source cell verbatim, kept so a later exposure needs no re-sync — "
           "not an API field because every typed column it carries is already served.",
    "geom": "Served as the feature geometry, never as a property; lat and lon carry the position.",
}

#: Unit / provenance note for each served measurement field. ⛔ Never invented —
#: see ingestion/svalbard_fjords_pp.py module docstring.
SVALBARD_FJORDS_PP_UNITS: dict[str, str] = {
    "depth_m": "m",
    "temperature_degc": "°C",
    "salinity": "no unit stated in the source",
    "ca_mg_m3": f"mg m⁻³ ({parser.CA_NOTE})",
    "pe_mgc_m3_h": "mgC m⁻³ h⁻¹",
    "pi_mgc_m2_day": "mgC m⁻² day⁻¹ (daily water-column-integrated production of the whole profile)",
}

_EMPTY_FC = '{"type":"FeatureCollection","features":[]}'


def _jsonable(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


@router.get("/v1/map/svalbard-fjords-pp/stations", dependencies=[Depends(get_api_key)])
async def svalbard_fjords_pp_stations():
    """One feature per distinct position (43) of the current version."""
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
              SELECT region_code || ':' || station || ':' || raw_lat || ':' || raw_lon AS position_id,
                     station, region_code,
                     (array_agg(fjord_part ORDER BY row_no))[1] AS fjord_part,
                     (array_agg(lat ORDER BY row_no))[1] AS lat,
                     (array_agg(lon ORDER BY row_no))[1] AS lon,
                     count(DISTINCT exposition_no) AS n_expositions,
                     min(sample_date) AS first_date, max(sample_date) AS last_date,
                     json_build_object(
                       'type', 'Feature',
                       'geometry', json_build_object('type', 'Point',
                         'coordinates', json_build_array((array_agg(lon ORDER BY row_no))[1],
                                                          (array_agg(lat ORDER BY row_no))[1])),
                       'properties', json_build_object(
                         'position_id', region_code || ':' || station || ':' || raw_lat || ':' || raw_lon,
                         'station', station,
                         'region_code', region_code,
                         'region_name', COALESCE($1::jsonb ->> region_code, region_code),
                         'fjord_part', (array_agg(fjord_part ORDER BY row_no))[1],
                         'n_expositions', count(DISTINCT exposition_no),
                         'first_date', min(sample_date), 'last_date', max(sample_date))) AS f
              FROM (
                SELECT *, raw[6] AS raw_lat, raw[7] AS raw_lon
                FROM svalbard_fjords_pp_samples_current
                WHERE geom IS NOT NULL
              ) t
              GROUP BY region_code, station, raw_lat, raw_lon
            ) s""", json.dumps(parser.REGION_NAMES))
    _stations_cache = txt or _EMPTY_FC
    return Response(content=_stations_cache, media_type="application/json")


@router.get("/v1/map/svalbard-fjords-pp/samples", dependencies=[Depends(get_api_key)])
async def svalbard_fjords_pp_samples(position_id: str = Query(...)):
    """Every current-version exposition at one position, ordered by date; each
    exposition's samples ordered by depth. Pi is attached to the exposition,
    never to a depth (None when the source did not publish it)."""
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable")
    parts = position_id.split(":", 3)
    if len(parts) != 4:
        raise HTTPException(404, "malformed position_id")
    region_code, station, lat_txt, lon_txt = parts
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT * FROM svalbard_fjords_pp_samples_current
                WHERE region_code = $1 AND station = $2 AND raw[6] = $3 AND raw[7] = $4
                ORDER BY exposition_no, depth_m NULLS LAST, row_no""",
            region_code, station, lat_txt, lon_txt)
    if not rows:
        raise HTTPException(404, "no svalbard-fjords-pp samples for this position in the current version")

    expositions: dict[str, dict] = {}
    order: list[str] = []
    for r in rows:
        no = r["exposition_no"]
        if no not in expositions:
            expositions[no] = {
                "exposition_no": no,
                "date": _jsonable(r["sample_date"]),
                "fjord_part": r["fjord_part"],
                "pi_mgc_m2_day": None,
                "samples": [],
            }
            order.append(no)
        if r["pi_mgc_m2_day"] is not None:
            expositions[no]["pi_mgc_m2_day"] = r["pi_mgc_m2_day"]
        expositions[no]["samples"].append({
            "depth_m": r["depth_m"],
            "temperature_degc": r["temperature_degc"],
            "salinity": r["salinity"],
            "ca_mg_m3": r["ca_mg_m3"],
            "pe_mgc_m3_h": r["pe_mgc_m3_h"],
            "water_mass": r["water_mass"],
        })
    ordered = sorted((expositions[no] for no in order), key=lambda e: e["date"] or "")
    return {
        "position_id": position_id,
        "station": station,
        "region_code": region_code,
        "region_name": parser.REGION_NAMES.get(region_code, region_code),
        "expositions": ordered,
    }


async def _discrepancies(conn) -> list[dict]:
    """Metadata's own claims are constants above; the data side is computed
    from the DB at serve time. Only diverging keys appear."""
    out: list[dict] = []

    row_count = await conn.fetchval("SELECT count(*) FROM svalbard_fjords_pp_samples_current")
    hornsund_rows = await conn.fetchval(
        "SELECT count(*) FROM svalbard_fjords_pp_samples_current WHERE region_code = 'H'")
    kongsfjorden_rows = await conn.fetchval(
        "SELECT count(*) FROM svalbard_fjords_pp_samples_current WHERE region_code = 'K'")
    if row_count != _METADATA_INCUBATION_TOTAL:
        out.append({
            "key": "incubation_total",
            "metadata_says": (
                f"{_METADATA_INCUBATION_TOTAL} incubation levels "
                f"({_METADATA_HORNSUND_LEVELS} Hornsund + {_METADATA_KONGSFJORDEN_LEVELS} Kongsfjorden)"),
            "data_shows": (
                f"{row_count} rows ({hornsund_rows} Hornsund + {kongsfjorden_rows} Kongsfjorden)"),
        })

    kongsfjorden_expositions = await conn.fetchval(
        "SELECT count(DISTINCT exposition_no) FROM svalbard_fjords_pp_samples_current WHERE region_code = 'K'")
    hornsund_expositions = await conn.fetchval(
        "SELECT count(DISTINCT exposition_no) FROM svalbard_fjords_pp_samples_current WHERE region_code = 'H'")
    named_stations = await conn.fetchval(
        "SELECT count(DISTINCT station) FROM svalbard_fjords_pp_samples_current")
    named_stations_k = await conn.fetchval(
        "SELECT count(DISTINCT station) FROM svalbard_fjords_pp_samples_current WHERE region_code = 'K'")
    named_stations_h = await conn.fetchval(
        "SELECT count(DISTINCT station) FROM svalbard_fjords_pp_samples_current WHERE region_code = 'H'")
    distinct_positions = await conn.fetchval(
        "SELECT count(DISTINCT (region_code, station, raw[6], raw[7])) FROM svalbard_fjords_pp_samples_current")
    if (named_stations_k != _METADATA_KONGSFJORDEN_STATIONS
            or named_stations_h != _METADATA_HORNSUND_STATIONS):
        out.append({
            "key": "station_counts",
            "metadata_says": (
                f"{_METADATA_KONGSFJORDEN_STATIONS} measurement stations in Kongsfjorden "
                f"and {_METADATA_HORNSUND_STATIONS} in Hornsund"),
            "data_shows": (
                f"those numbers equal the per-fjord exposition (station-visit) counts "
                f"({kongsfjorden_expositions} Kongsfjorden + {hornsund_expositions} Hornsund), "
                f"while named stations are {named_stations_k} Kongsfjorden + {named_stations_h} Hornsund "
                f"({named_stations} total) and distinct positions {distinct_positions}"),
        })

    west_rows = await conn.fetch(
        "SELECT DISTINCT station, lon FROM svalbard_fjords_pp_samples_current WHERE lon < $1",
        _METADATA_BBOX_WEST)
    if west_rows:
        n_rows_west = await conn.fetchval(
            "SELECT count(*) FROM svalbard_fjords_pp_samples_current WHERE lon < $1", _METADATA_BBOX_WEST)
        named = ", ".join(f"{r['station']} {r['lon']:.2f}°E" for r in west_rows)
        out.append({
            "key": "bbox_west",
            "metadata_says": f"west bound {_METADATA_BBOX_WEST}°E",
            "data_shows": f"positions west of it ({named}; {n_rows_west} rows)",
        })

    reuse_rows = await conn.fetch("""
        SELECT station, count(DISTINCT (raw[6], raw[7])) AS n_positions
        FROM svalbard_fjords_pp_samples_current
        GROUP BY station HAVING count(DISTINCT (raw[6], raw[7])) > 1
        ORDER BY station""")
    if reuse_rows:
        out.append({
            "key": "station_name_reuse",
            "metadata_says": None,
            "data_shows": ", ".join(f"{r['station']} ({r['n_positions']} positions)" for r in reuse_rows),
        })

    return out


@router.get("/v1/map/svalbard-fjords-pp/meta", dependencies=[Depends(get_api_key)])
async def svalbard_fjords_pp_meta():
    """DOI, source/metadata URLs, licence, counts computed from the DB, date
    range, units and per-region breakdown, column notes, last sync, and the
    metadata-vs-data discrepancies (only where they diverge)."""
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable")
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT version_id, doi, source_url, sha256, rows_in_source, citation, licence, fetched_at
                 FROM svalbard_fjords_pp_version WHERE is_current""")
        if row is None:
            return {"version": None}
        rows = await conn.fetchval("SELECT count(*) FROM svalbard_fjords_pp_samples_current")
        n_expositions = await conn.fetchval(
            "SELECT count(DISTINCT exposition_no) FROM svalbard_fjords_pp_samples_current")
        n_positions = await conn.fetchval(
            "SELECT count(DISTINCT (region_code, station, raw[6], raw[7])) FROM svalbard_fjords_pp_samples_current")
        n_named_stations = await conn.fetchval(
            "SELECT count(DISTINCT station) FROM svalbard_fjords_pp_samples_current")
        per_region = await conn.fetch(
            "SELECT region_code, count(*) AS n_rows, count(DISTINCT exposition_no) AS n_expositions "
            "FROM svalbard_fjords_pp_samples_current GROUP BY region_code ORDER BY region_code")
        date_range = await conn.fetchrow(
            "SELECT min(sample_date) AS first_date, max(sample_date) AS last_date "
            "FROM svalbard_fjords_pp_samples_current")
        discrepancies = await _discrepancies(conn)

    item = {k: _jsonable(row[k]) for k in row.keys()}
    item["metadata_url"] = parser.METADATA_URL
    item["licence"] = LICENCE
    item["units"] = SVALBARD_FJORDS_PP_UNITS
    item["counts"] = {
        "rows": rows,
        "expositions": n_expositions,
        "positions": n_positions,
        "named_stations": n_named_stations,
        "per_region": {
            r["region_code"]: {"rows": r["n_rows"], "expositions": r["n_expositions"]}
            for r in per_region
        },
    }
    item["date_range"] = {
        "first_date": _jsonable(date_range["first_date"]),
        "last_date": _jsonable(date_range["last_date"]),
    }
    item["column_notes"] = {
        "ca_mg_m3": parser.CA_NOTE,
        "water_mass": {
            "expansions": parser.WATER_MASS_EXPANSIONS,
            "attribution": parser.WATER_MASS_ATTRIBUTION,
        },
        "salinity": "unit not stated in the source",
    }
    item["discrepancies"] = discrepancies
    return {"version": item}
