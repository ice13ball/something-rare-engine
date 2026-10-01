# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""Two PANGAEA water-column point layers: CoastDOM v1 (`coastdom`) and Greenland
Sea primary production 2021-2022 (`greenland-primary-production`).

Storage is 1:1 with the source (see schema/pangaea_water.py). Serving hides only
what the HIDDEN_FIELDS allowlists name, each with its reason; the export registry
reads the SERVED tuples themselves, so a hidden field cannot leak through a
download.

Sync, monthly (scheduling.py) and on admin force-sync:
  1. fetch the JSON-LD (0.4 MB / 12 KB);
  2. if its `datePublished` equals the current version's and that version still
     holds all its rows → done, the 24 MB TSV is not downloaded;
  3. otherwise download the TSV, prove it whole (byte-exact header, the file's
     own data-point count, the JSON-LD's count), and:
       - same SHA-256 as the current version → nothing new (refill it only if a
         purge emptied it);
       - new SHA-256 → insert a NEW version's rows and flip `is_current`, in one
         transaction. Old versions stay: row position is not a stable key
         across source revisions, so there is no upsert and nothing is deleted.
Any failure aborts before the transaction commits and leaves the stored version
untouched; `log_sync_skipped` records why, and `last_synced_at` keeps ageing.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from types import ModuleType

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

import db
from auth import get_api_key
from ingestion import coastdom, greenland_pp, pangaea_tsv
from ingestion.http_retry import get_with_retry
from sync_log import log_sync as _log_sync
from sync_log import log_sync_skipped as _log_sync_skipped

log = logging.getLogger(__name__)
router = APIRouter()

_coastdom_locations_cache: str | None = None
_greenland_pp_cache: str | None = None


def clear_caches() -> None:
    """Drop this domain's cached responses. Called by /admin/cache/clear and after every sync."""
    global _coastdom_locations_cache, _greenland_pp_cache
    _coastdom_locations_cache = None
    _greenland_pp_cache = None


@dataclass(frozen=True)
class LayerSpec:
    layer_id: str
    sync_source: str
    table: str
    parser: ModuleType


COASTDOM = LayerSpec("coastdom", "coastdom", "coastdom_samples", coastdom)
GREENLAND_PP = LayerSpec("greenland-primary-production", "greenland-pp", "greenland_pp_stations", greenland_pp)
SPEC_BY_LAYER: dict[str, LayerSpec] = {s.layer_id: s for s in (COASTDOM, GREENLAND_PP)}

_UA = {"User-Agent": "abyssal-claims/1.0 (+https://something-rare.com)"}
_BATCH = 2000


async def _fetch_bytes(url: str, *, timeout: float = 300.0) -> bytes:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=_UA) as client:
        response = await get_with_retry(client, url, label="pangaea")
        response.raise_for_status()
        return response.content


def _insert_sql(table: str, fields: tuple[str, ...]) -> str:
    cols = ["version_id", "row_no", *fields, "raw"]
    lat = cols.index("lat") + 1
    lon = cols.index("lon") + 1
    geom = (f"CASE WHEN ${lat}::float8 IS NULL OR ${lon}::float8 IS NULL THEN NULL "
            f"ELSE ST_SetSRID(ST_MakePoint(${lon}::float8, ${lat}::float8), 4326) END")
    values = ", ".join(f"${i}" for i in range(1, len(cols) + 1))
    return f"INSERT INTO {table} ({', '.join(cols)}, geom) VALUES ({values}, {geom})"


async def sync_coastdom(force: bool = False) -> int:
    return await _sync_layer(COASTDOM, force)


async def sync_greenland_pp(force: bool = False) -> int:
    return await _sync_layer(GREENLAND_PP, force)


async def _sync_layer(spec: LayerSpec, force: bool) -> int:
    try:
        return await _sync_layer_inner(spec, force)
    except (pangaea_tsv.PangaeaFormatError, httpx.HTTPError, UnicodeDecodeError) as exc:
        reason = f"aborted, stored version untouched: {type(exc).__name__}: {exc}"[:500]
        await _log_sync_skipped(spec.sync_source, reason)
        log.error("%s: %s", spec.sync_source, reason)
        raise
    except asyncpg.PostgresError as exc:
        reason = f"aborted, stored version untouched: {type(exc).__name__}: {exc}"[:500]
        await _log_sync_skipped(spec.sync_source, reason)
        log.error("%s: %s", spec.sync_source, reason)
        raise


async def _sync_layer_inner(spec: LayerSpec, force: bool) -> int:
    p = spec.parser
    meta = pangaea_tsv.parse_jsonld(await _fetch_bytes(p.JSONLD_URL, timeout=60.0))

    async with db.pool.acquire() as conn:
        current = await conn.fetchrow(
            """SELECT version_id, date_published, sha256, rows_in_source
                 FROM pangaea_dataset_version WHERE layer_id = $1 AND is_current""",
            spec.layer_id,
        )
        stored = 0
        if current is not None:
            stored = await conn.fetchval(
                f"SELECT count(*) FROM {spec.table} WHERE version_id = $1", current["version_id"])

    whole = current is not None and stored == current["rows_in_source"]
    if (not force and whole and meta.date_published is not None
            and meta.date_published == current["date_published"]):
        await _log_sync(spec.sync_source, 0, stored)
        log.info("%s: datePublished %s unchanged, %d rows current - TSV not fetched",
                 spec.sync_source, meta.date_published, stored)
        return 0

    raw = await _fetch_bytes(p.TEXTFILE_URL)
    sha = hashlib.sha256(raw).hexdigest()

    def _decode_split_validate() -> tuple:
        pf = pangaea_tsv.split_pangaea(raw.decode("utf-8"))
        n_rows, n_unmappable, n_points = pangaea_tsv.validate(p, pf, meta.size_data_points)
        return pf, n_rows, n_unmappable, n_points

    pf, n_rows, n_unmappable, n_points = await asyncio.to_thread(_decode_split_validate)

    if current is not None and sha == current["sha256"]:
        if whole:
            await _log_sync(spec.sync_source, 0, stored)
            log.info("%s: same file (sha256 %s) - nothing new", spec.sync_source, sha[:12])
            return 0
        if stored != 0:
            raise pangaea_tsv.PangaeaFormatError(
                f"version {current['version_id']} holds {stored} of {current['rows_in_source']} "
                "rows; refusing to add to a partial version")
        version_id, new_version = current["version_id"], False
    else:
        version_id, new_version = None, True

    sql = _insert_sql(spec.table, p.FIELDS)
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            if new_version:
                version_id = await conn.fetchval(
                    """INSERT INTO pangaea_dataset_version
                         (layer_id, is_current, doi, date_published, sha256, rows_in_source,
                          rows_unmappable, data_points, header, citation, related_citation, license)
                       VALUES ($1, false, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                       RETURNING version_id""",
                    spec.layer_id, p.DOI, meta.date_published, sha, n_rows, n_unmappable, n_points,
                    list(pf.header), pf.meta.get("Citation"), pf.meta.get("Supplement to"), meta.license,
                )
            batch: list[tuple] = []
            for row_no, cells in pangaea_tsv.iter_rows(pf):
                rec = p.parse_row(row_no, cells)
                batch.append((version_id, rec["row_no"], *[rec[f] for f in p.FIELDS], rec["raw"]))
                if len(batch) >= _BATCH:
                    await conn.executemany(sql, batch)
                    batch.clear()
            if batch:
                await conn.executemany(sql, batch)
            if new_version:
                await conn.execute(
                    "UPDATE pangaea_dataset_version SET is_current = false WHERE layer_id = $1 AND is_current",
                    spec.layer_id)
                await conn.execute(
                    "UPDATE pangaea_dataset_version SET is_current = true WHERE version_id = $1", version_id)

    clear_caches()
    await _log_sync(spec.sync_source, n_rows, n_rows)
    log.info("%s: version %s current - %d rows (%d without coordinates), %d data points, sha256 %s",
             spec.sync_source, version_id, n_rows, n_unmappable, n_points, sha[:12])
    return n_rows


# ── Serving allowlists ─────────────────────────────────────────────────────
# ⛔ Every stored column appears in EXACTLY ONE of SERVED / HIDDEN
# (tests/test_pangaea_water_serving.py). Both are literal on purpose: a column
# added to the table later is served by nobody until someone decides.
# Exposing a hidden field = move it from HIDDEN to SERVED and add its panel line.
# The export registry reads the SERVED tuples themselves.

COASTDOM_SERVED_FIELDS: tuple[str, ...] = (
    "version_id", "row_no",
    "location", "sample_id", "sample_date", "lat", "lon", "elevation_m", "depth_m",
    "temp_c", "sal", "tss_mg_l", "chl_a_ug_l", "qf_chl_a",
    "no3_no2_umol_l", "qf_no3_no2", "nh4_umol_l", "qf_nh4", "hpo4_umol_l", "qf_hpo4",
    "doc_umol_l", "doc_method", "qf_doc", "don_umol_l",
    "tdn_umol_l", "tdn_method", "qf_tdn", "dop_umol_l",
    "tdp_umol_l", "tdp_method", "qf_tdp",
    "poc_umol_l", "poc_method", "qf_poc",
    "pn_umol_l", "pn_method", "qf_tpn",
    "pp_umol_l", "pp_method", "qf_pp",
    "dic_umol_kg", "qf_dic", "at_umol_kg", "qf_at",
    "pi", "institution", "ref_1", "ref_2", "ref_3", "comment",
)
COASTDOM_HIDDEN_FIELDS: dict[str, str] = {
    "pi_email": "A named person's e-mail address. Stored because storage is 1:1 with the "
                "source; not served because this platform does not republish personal "
                "contact details. The dataset citation and per-row references credit the work.",
    "raw": "Every source cell verbatim, including the pi_email cell (position 44); serving "
           "it would leak what pi_email hides. Kept so a later exposure needs no re-sync.",
    "geom": "Served as the feature geometry of /v1/map/coastdom/locations, never as a "
            "property; lat and lon carry the position in samples and export.",
}

GREENLAND_PP_SERVED_FIELDS: tuple[str, ...] = (
    "version_id", "row_no", "event", "event_2", "lat", "lon", "sample_date", "gpp_c_mg_m2_day",
)
GREENLAND_PP_HIDDEN_FIELDS: dict[str, str] = {
    "raw": "Every source cell verbatim. Carries nothing the typed columns do not; kept as "
           "storage so a later exposure needs no re-sync, not an API field.",
    "geom": "Served as the feature geometry, never as a property; lat and lon carry the position.",
}

_SERVED_BY_LAYER = {"coastdom": COASTDOM_SERVED_FIELDS,
                    "greenland-primary-production": GREENLAND_PP_SERVED_FIELDS}

_EMPTY_FC = '{"type":"FeatureCollection","features":[]}'


def _jsonable(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


@router.get("/v1/map/coastdom/locations", dependencies=[Depends(get_api_key)])
async def coastdom_locations():
    """One feature per distinct sampled position of the current CoastDOM version.
    ⛔ No value is aggregated: the properties are counts, depth and date ranges.
    `year_counts` maps calendar year (string) to the number of DATED samples that
    year; undated samples are only in `n_undated`, so n_samples ==
    sum(year_counts) + n_undated."""
    global _coastdom_locations_cache
    if _coastdom_locations_cache is not None:
        return Response(content=_coastdom_locations_cache, media_type="application/json")
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable")
    async with db.pool.acquire() as conn:
        txt = await conn.fetchval("""
            WITH yc AS (
              -- dated samples only, per (position, calendar year). Undated rows
              -- have no year: they stay in n_undated and never enter a bucket.
              SELECT lat, lon, jsonb_object_agg(yr::text, n ORDER BY yr) AS year_counts
              FROM (
                SELECT lat, lon, EXTRACT(YEAR FROM sample_date)::int AS yr, count(*) AS n
                FROM coastdom_samples_current
                WHERE geom IS NOT NULL AND sample_date IS NOT NULL
                GROUP BY lat, lon, EXTRACT(YEAR FROM sample_date)::int
              ) y
              GROUP BY lat, lon
            )
            SELECT json_build_object('type', 'FeatureCollection', 'features',
                     COALESCE(json_agg(f ORDER BY lat, lon), '[]'::json))::text
            FROM (
              SELECT c.lat, c.lon, json_build_object(
                'type', 'Feature',
                'geometry', json_build_object('type', 'Point', 'coordinates', json_build_array(c.lon, c.lat)),
                'properties', json_build_object(
                  'site_id', c.lat::text || ',' || c.lon::text,
                  'lat', c.lat, 'lon', c.lon,
                  'location', string_agg(DISTINCT c.location, ' / ' ORDER BY c.location),
                  'n_samples', count(*),
                  'n_undated', count(*) FILTER (WHERE c.sample_date IS NULL),
                  'year_counts', COALESCE(yc.year_counts, '{}'::jsonb),
                  'depth_min_m', min(c.depth_m), 'depth_max_m', max(c.depth_m),
                  'date_min', min(c.sample_date), 'date_max', max(c.sample_date))) AS f
              FROM coastdom_samples_current c
              LEFT JOIN yc ON yc.lat = c.lat AND yc.lon = c.lon
              WHERE c.geom IS NOT NULL
              GROUP BY c.lat, c.lon, yc.year_counts
            ) s""")
    _coastdom_locations_cache = txt or _EMPTY_FC
    return Response(content=_coastdom_locations_cache, media_type="application/json")


@router.get("/v1/map/coastdom/samples", dependencies=[Depends(get_api_key)])
async def coastdom_samples(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180)):
    """Every current-version sample at one position, by date then depth. Undated
    samples come last with sample_date null — never a substituted date."""
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable")
    cols = ", ".join(COASTDOM_SERVED_FIELDS)
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT {cols} FROM coastdom_samples_current
                 WHERE lat = $1 AND lon = $2
                 ORDER BY sample_date NULLS LAST, depth_m NULLS LAST, row_no""",
            lat, lon)
    if not rows:
        raise HTTPException(404, "no CoastDOM samples at this position in the current version")
    samples = [{k: _jsonable(r[k]) for k in COASTDOM_SERVED_FIELDS} for r in rows]
    return {"lat": lat, "lon": lon, "n_samples": len(samples), "samples": samples}


@router.get("/v1/map/greenland-pp/stations", dependencies=[Depends(get_api_key)])
async def greenland_pp_stations():
    """All stations of the current version. `gpp_c_mg_m2_day` is an areal rate."""
    global _greenland_pp_cache
    if _greenland_pp_cache is not None:
        return Response(content=_greenland_pp_cache, media_type="application/json")
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable")
    props = ", ".join(f"'{c}', {c}" for c in GREENLAND_PP_SERVED_FIELDS)
    async with db.pool.acquire() as conn:
        txt = await conn.fetchval(f"""
            SELECT json_build_object('type', 'FeatureCollection', 'features',
                     COALESCE(json_agg(json_build_object(
                       'type', 'Feature',
                       'geometry', ST_AsGeoJSON(geom)::json,
                       'properties', json_build_object({props})) ORDER BY row_no), '[]'::json))::text
            FROM greenland_pp_stations_current WHERE geom IS NOT NULL""")
    _greenland_pp_cache = txt or _EMPTY_FC
    return Response(content=_greenland_pp_cache, media_type="application/json")


@router.get("/v1/pangaea-water/meta", dependencies=[Depends(get_api_key)])
async def pangaea_water_meta():
    """Every stored version of both layers: DOI, datePublished, SHA-256, row and
    data-point counts, rows without coordinates, the citation and related
    publication verbatim from the source file, and each served field's exact
    PANGAEA header string as its unit."""
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable")
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT version_id, layer_id, is_current, doi, date_published, sha256,
                      rows_in_source, rows_unmappable, data_points, header,
                      citation, related_citation, license, ingested_at
                 FROM pangaea_dataset_version ORDER BY layer_id, version_id""")
    versions = []
    for r in rows:
        spec = SPEC_BY_LAYER.get(r["layer_id"])
        if spec is None:
            continue
        served = set(_SERVED_BY_LAYER[r["layer_id"]])
        units = {f: h for f, h in zip(spec.parser.FIELDS, r["header"]) if f in served}
        item = {k: _jsonable(r[k]) for k in r.keys() if k != "header"}
        item["units"] = units
        versions.append(item)
    return {"versions": versions}
