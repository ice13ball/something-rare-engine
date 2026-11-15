# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""IMOS zooplankton (AusCPR + National Reference Stations): the API half of the `imos-zooplankton` layer.

A static snapshot, loaded by the one-shot `python -m ingestion.imos_zooplankton <dir>` (another process, never
the API). This module only reads what the import swapped in.

⛔ Absent is not unknown. `abundance_m3 = 0` is a counted absence. A taxon with NO row in a sample was not counted
(a JSON null in the source, or, for the NRS non-copepod file, a taxon the source simply does not list). The
per-feature `taxon_m3` of `/samples?taxon=` is therefore a number or null, and null means UNKNOWN, never zero.

⛔ Missing and broken never share a path: a malformed key is a 422, an unknown one a 404; a database that cannot
answer, or a layer that has not been imported yet, is a 503 + Retry-After — never a 200 with an empty body.

⛔ Never import `ingestion.imos_zooplankton` (the importer) here: only the pure rules module.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

import db
from auth import get_api_key
from ingestion.imos_zooplankton_rules import (
    ATTRIBUTION, ATTRIBUTION_CPR, LICENCE, LICENCE_URL, SAMPLE_KEY_RE, SOURCE, SOURCE_RECORDS,
)

log = logging.getLogger(__name__)
router = APIRouter()

_RETRY_AFTER = {"Retry-After": "60"}
_EMPTY_NOTE = "no import yet"
_MAX_CACHED = 48  # distinct documents kept (samples per taxon, taxa, one per sample key)

# {(stamp, name): serialized JSON}. The stamp is sync_log.last_synced_at of the import: the import runs in another
# process, whose clear_caches() cannot reach this one, so every request compares the stamp and rebuilds on a mismatch.
_cache: dict[tuple, str] = {}


def clear_caches() -> None:
    _cache.clear()


async def _stamp(conn) -> str:
    """Latest import stamp, or 503 when the layer was never imported."""
    ts = await conn.fetchval("SELECT last_synced_at FROM sync_log WHERE source = $1", SOURCE)
    if ts is None:
        raise HTTPException(503, f"IMOS zooplankton: {_EMPTY_NOTE}", headers=_RETRY_AFTER)
    return ts.isoformat()


def _remember(stamp: str, name: str, payload: str) -> None:
    for k in [k for k in _cache if k[0] != stamp]:
        del _cache[k]
    if len(_cache) >= _MAX_CACHED:
        _cache.pop(next(iter(_cache)))
    _cache[(stamp, name)] = payload


def _json(payload: str) -> Response:
    return Response(content=payload, media_type="application/json")


def _db_unavailable(e: Exception) -> HTTPException:
    log.warning("imos-zooplankton: database unavailable: %s", type(e).__name__)
    return HTTPException(503, "IMOS zooplankton: database unavailable", headers=_RETRY_AFTER)


_SAMPLES_SQL = """
    SELECT json_build_object(
      'type','FeatureCollection',
      'features', COALESCE(json_agg(json_build_object(
        'type','Feature',
        'geometry', json_build_object('type','Point','coordinates', json_build_array(s.lon, s.lat)),
        'properties', json_build_object(
          'sample_key', s.sample_key,
          'programme', s.programme,
          'date', to_char(s.sample_time_utc AT TIME ZONE 'UTC', 'YYYY-MM-DD'),
          'copepod_total_m3', s.copepod_total_m3{taxon_prop}
        )
      ) ORDER BY s.sample_key), '[]'::json)
    )::text
    FROM imos_zoop_samples s {taxon_join}
"""
_TAXON_PROP = ", 'taxon_m3', a.abundance_m3"


@router.get("/v1/imos-zooplankton/samples", dependencies=[Depends(get_api_key)])
async def imos_samples(
    taxon: str | None = Query(None, min_length=1, max_length=200),
    group: str | None = Query(None, pattern="^(copepod|noncopepod)$"),
):
    """Every sample as a GeoJSON point. With `taxon`, each feature also carries `taxon_m3`: that taxon's abundance
    per m3 in the sample, or null when it was not counted (unknown, not zero). `group` picks the copepod or the
    non-copepod column of a name that occurs in both (7 do); omitted, the copepod one wins."""
    try:
        async with db.pool.acquire() as conn:
            stamp = await _stamp(conn)
            name = f"samples|{taxon}|{group}"
            hit = _cache.get((stamp, name))
            if hit:
                return _json(hit)
            if taxon is None:
                sql = _SAMPLES_SQL.format(taxon_prop="", taxon_join="")
                txt = await conn.fetchval(sql)
            else:
                groups = await conn.fetch(
                    "SELECT DISTINCT is_copepod FROM imos_zoop_abundance WHERE taxon = $1", taxon)
                if not groups:
                    raise HTTPException(404, "no such taxon")
                have = {r["is_copepod"] for r in groups}
                is_cop = (group == "copepod") if group else (True in have)
                if is_cop not in have:
                    raise HTTPException(404, "no such taxon in that group")
                sql = _SAMPLES_SQL.format(
                    taxon_prop=_TAXON_PROP,
                    taxon_join="LEFT JOIN imos_zoop_abundance a ON a.sample_key = s.sample_key "
                               "AND a.taxon = $1 AND a.is_copepod = $2")
                txt = await conn.fetchval(sql, taxon, is_cop)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 - a broken database must be a 503, never a 200
        raise _db_unavailable(e) from e
    if not txt:
        raise HTTPException(503, f"IMOS zooplankton: {_EMPTY_NOTE}", headers=_RETRY_AFTER)
    _remember(stamp, name, txt)
    return _json(txt)


@router.get("/v1/imos-zooplankton/taxa", dependencies=[Depends(get_api_key)])
async def imos_taxa():
    """Taxon names for a picker: samples where each was present (abundance above zero) and where it was counted
    at all (present or absent). Order: copepods first, then by samples present."""
    try:
        async with db.pool.acquire() as conn:
            stamp = await _stamp(conn)
            hit = _cache.get((stamp, "taxa"))
            if hit:
                return _json(hit)
            rows = await conn.fetch(
                """SELECT taxon, is_copepod,
                          count(*) FILTER (WHERE abundance_m3 > 0) AS n_present,
                          count(*) AS n_counted
                   FROM imos_zoop_abundance GROUP BY taxon, is_copepod
                   ORDER BY is_copepod DESC, n_present DESC, taxon""")
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise _db_unavailable(e) from e
    payload = json.dumps({
        "taxa": [{"taxon": r["taxon"], "group": "copepod" if r["is_copepod"] else "noncopepod",
                  "n_samples_present": r["n_present"], "n_samples_counted": r["n_counted"]} for r in rows],
    }, allow_nan=False)
    _remember(stamp, "taxa", payload)
    return _json(payload)


@router.get("/v1/imos-zooplankton/sample/{sample_key}", dependencies=[Depends(get_api_key)])
async def imos_sample(sample_key: str):
    """One sample: metadata plus its counted taxa, present ones first (by abundance), then the counted absences."""
    if not SAMPLE_KEY_RE.match(sample_key):
        raise HTTPException(422, "malformed sample key (expected cpr:<id> or nrs:<trip code>)")
    try:
        async with db.pool.acquire() as conn:
            stamp = await _stamp(conn)
            hit = _cache.get((stamp, f"sample|{sample_key}"))
            if hit:
                return _json(hit)
            s = await conn.fetchrow(
                """SELECT sample_key, programme, trip_code, region, station_code, station_name, lat, lon,
                          sample_time_utc, sample_depth_m, sample_volume_m3, biomass_mgm3, copepod_total_m3,
                          n_copepod_taxa_present, noncopepod_zeros_explicit, snapshot
                   FROM imos_zoop_samples WHERE sample_key = $1""", sample_key)
            if s is None:
                raise HTTPException(404, "no such sample")
            taxa = await conn.fetch(
                """SELECT taxon, is_copepod, abundance_m3 FROM imos_zoop_abundance WHERE sample_key = $1
                   ORDER BY (abundance_m3 > 0) DESC, abundance_m3 DESC, is_copepod DESC, taxon""", sample_key)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise _db_unavailable(e) from e
    sample = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(s).items()}
    payload = json.dumps({
        "sample": sample,
        "taxa": [{"taxon": r["taxon"], "is_copepod": r["is_copepod"], "abundance_m3": r["abundance_m3"]}
                 for r in taxa],
        "licence": LICENCE, "licence_url": LICENCE_URL, "attribution": ATTRIBUTION,
        "attribution_cpr": ATTRIBUTION_CPR, "source_records": list(SOURCE_RECORDS),
    }, allow_nan=False)
    _remember(stamp, f"sample|{sample_key}", payload)
    return _json(payload)
