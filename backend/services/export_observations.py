# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Area Export rows for sources with no 4326 geometry column (ObservationExport in export_registry).

socat-points: one row per OBSERVATION. Segments are found through the EPSG:3857 bbox index; a segment whose whole
bbox lies inside the AOI contributes every observation, any other is tested point by point in 4326 — the same rule
in count() and rows(), so the preview count equals the file. ⛔ The cap counts observations (LIMIT cap + 1 on the
unnested rows), never segments.
wod-casts: one row per DRAWABLE cast (wod_cast_points). wod_casts has no spatial index; the AOI is turned into
Morton key ranges (wod_casts_rules.tile_key_range, the tile index) and tested on x/y in EPSG:3857 (latitude clamped
to ±85.0511 there, as on the map).
"""
from __future__ import annotations

import json
import math

import db
from domains.socat_points import _num
from ingestion import wod_casts_rules as WR
from services.export_query import Aoi
from services.export_registry import ObservationExport

STMT_TIMEOUT_MS = 12_000
_WORLD_3857 = "ST_MakeEnvelope(-180, -85.0511, 180, 85.0511, 4326)"


def aoi_geom_sql(aoi: Aoi) -> tuple[str, list]:
    if aoi.kind == "bbox":
        return "ST_MakeEnvelope($1, $2, $3, $4, 4326)", list(aoi.bbox)
    if aoi.kind == "poly":
        return "ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON($1), 4326))", [aoi.poly_geojson]  # a self-intersecting ring is not a 500
    return "(SELECT ST_Union(geom) FROM density_hex_cells WHERE cell_id = ANY($1::text[]))", [list(aoi.cell_ids)]


# ── SOCAT ────────────────────────────────────────────────────────────────────────────────────────────────────
def _socat_ctes(aoi_sql: str) -> str:
    return f"""
WITH aoi AS MATERIALIZED (SELECT {aoi_sql} AS g),
seg AS (
  SELECT s.*, ST_Transform(s.bbox, 4326) AS bb
  FROM aoi JOIN socat_segments s
    ON s.bbox && ST_Transform(ST_Intersection(aoi.g, {_WORLD_3857}), 3857)
  WHERE aoi.g IS NOT NULL),
seg2 AS (
  SELECT seg.*, (ST_YMax(seg.bb) < 85.05 AND ST_YMin(seg.bb) > -85.05 AND ST_Contains(aoi.g, seg.bb)) AS inside
  FROM seg CROSS JOIN aoi)"""


def socat_count_sql(aoi_sql: str) -> str:
    return _socat_ctes(aoi_sql) + """
SELECT coalesce(sum(CASE WHEN seg2.inside THEN seg2.n_obs ELSE
         (SELECT count(*) FROM unnest(seg2.lon, seg2.lat) AS u(lon, lat)
          WHERE ST_Intersects(aoi.g, ST_SetSRID(ST_MakePoint(u.lon, u.lat), 4326))) END), 0)::bigint
FROM seg2 CROSS JOIN aoi"""


def socat_rows_sql(aoi_sql: str, limit: int) -> str:
    """⛔ The LIMIT sits INSIDE the MATERIALIZED CTE pts, before the join to socat_cruises. With the join and the LIMIT
    at one level (and also with a plain subquery) the planner, which cannot estimate the unnest, put socat_cruises on
    the outside of a nested loop and re-ran the whole observation scan once per cruise (measured: 40-95 s for 75,001
    rows). Materialised, the scan runs once and the cruise lookup touches only the rows kept."""
    return _socat_ctes(aoi_sql) + f""",
pts AS MATERIALIZED (
  SELECT seg2.expocode, seg2.qc_flag, (seg2.ord0 + u.i - 1)::int AS ordinal,
         seg2.t0 + make_interval(secs => u.dt) AS time_utc, u.lon, u.lat, u.fco2 AS fco2_uatm, u.sst AS sst_c,
         u.sal AS sal_pss78, u.src AS fco2_src, u.flag AS fco2_flag
  FROM seg2
  CROSS JOIN LATERAL unnest(seg2.lon, seg2.lat, seg2.dt_s, seg2.fco2, seg2.sst, seg2.sal, seg2.fco2_src, seg2.fco2_flag)
       WITH ORDINALITY AS u(lon, lat, dt, fco2, sst, sal, src, flag, i)
  CROSS JOIN aoi
  WHERE seg2.inside OR ST_Intersects(aoi.g, ST_SetSRID(ST_MakePoint(u.lon, u.lat), 4326))
  LIMIT {int(limit)})
SELECT pts.*, c.platform_name, c.source_doi
FROM pts JOIN socat_cruises c ON c.expocode = pts.expocode"""


def _socat_row(r) -> dict:
    lon, lat = _num(r["lon"]), _num(r["lat"])
    return {"obs_key": f"{r['expocode']}~{r['ordinal']}", "expocode": r["expocode"], "ordinal": r["ordinal"],
            "time_utc": r["time_utc"], "lat": lat, "lon": lon, "fco2_uatm": _num(r["fco2_uatm"]),
            "sst_c": _num(r["sst_c"]), "sal_pss78": _num(r["sal_pss78"]), "fco2_src": r["fco2_src"],
            "fco2_flag": r["fco2_flag"], "qc_flag": r["qc_flag"], "platform_name": r["platform_name"],
            "source_doi": r["source_doi"], "geometry": {"type": "Point", "coordinates": [lon, lat]}}


# ── WOD ──────────────────────────────────────────────────────────────────────────────────────────────────────
def wod_key_ranges(w: float, s: float, e: float, n: float, max_tiles: int = 16) -> list[tuple[int, int]]:
    def tx(lon: float, z: int) -> int:
        return min((1 << z) - 1, max(0, int((lon + 180.0) / 360.0 * (1 << z))))

    def ty(lat: float, z: int) -> int:
        lat = max(-WR.MERC_LAT, min(WR.MERC_LAT, lat))
        m = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
        return min((1 << z) - 1, max(0, int((1 - m / math.pi) / 2 * (1 << z))))

    for z in range(10, -1, -1):
        x0, x1, y0, y1 = tx(w, z), tx(e, z), ty(n, z), ty(s, z)
        if (x1 - x0 + 1) * (y1 - y0 + 1) <= max_tiles:
            return [WR.tile_key_range(z, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
    return [WR.tile_key_range(0, 0, 0)]


def _wod_where(ranges: list[tuple[int, int]], first: int) -> tuple[str, list]:
    parts, params = [], []
    for i, (lo, hi) in enumerate(ranges):
        a = first + 2 * i
        parts.append(f"(p.key >= ${a}::bigint AND p.key < ${a + 1}::bigint)")
        params += [lo, hi]
    return " OR ".join(parts), params


def _wod_ctes(aoi_sql: str, where: str, limit: int | None = None) -> str:
    """⛔ The LIMIT sits INSIDE pts, before the join to the 7.65 M-row wod_casts (PK lookups only for kept rows)."""
    lim = f" LIMIT {int(limit)}" if limit is not None else ""
    return f"""
WITH aoi AS MATERIALIZED (SELECT ST_Transform(ST_Intersection({aoi_sql}, {_WORLD_3857}), 3857) AS g),
pts AS MATERIALIZED (SELECT p.cast_id, p.picks FROM wod_cast_points p CROSS JOIN aoi
        WHERE ({where}) AND ST_Intersects(aoi.g, ST_SetSRID(ST_MakePoint(p.x, p.y), 3857)){lim})"""


def decode_wod_picks(picks) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for var in WR.PICK_VARS:
        per = {str(d): picks[WR.slot(var, i)] / WR.SCALES[var]
               for i, d in enumerate(WR.DEPTHS) if picks[WR.slot(var, i)] is not None}
        if per:
            out[var] = per
    return out


_WOD_COLS = ("cast_id", "instrument", "dataset", "lat", "lon", "cast_date", "cast_time", "time_precision", "year",
             "cruise", "platform", "country", "institute", "project", "access_no")


def _wod_row(r) -> dict:
    d = {k: r[k] for k in _WOD_COLS}
    d["lat"], d["lon"] = _num(r["lat"]), _num(r["lon"])
    d["picks"] = decode_wod_picks(r["picks"])
    d["geometry"] = {"type": "Point", "coordinates": [d["lon"], d["lat"]]}
    return d


# ── dispatch ─────────────────────────────────────────────────────────────────────────────────────────────────
async def _extent(conn, aoi_sql: str, params: list):
    r = await conn.fetchrow(f"SELECT ST_XMin(g), ST_YMin(g), ST_XMax(g), ST_YMax(g) FROM (SELECT {aoi_sql} AS g) x",
                            *params)
    return None if r is None or r[0] is None else tuple(float(v) for v in r)


async def _run(entry: ObservationExport, aoi: Aoi, *, count_only: bool):
    aoi_sql, params = aoi_geom_sql(aoi)
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(f"SET LOCAL statement_timeout = {STMT_TIMEOUT_MS}")
            if entry.query == "socat":
                if count_only:
                    return int(await conn.fetchval(socat_count_sql(aoi_sql), *params))
                recs = await conn.fetch(socat_rows_sql(aoi_sql, entry.cap + 1), *params)
                return [_socat_row(r) for r in recs]
            if entry.query == "wod":
                ext = await _extent(conn, aoi_sql, params)
                if ext is None:
                    return 0 if count_only else []
                where, kp = _wod_where(wod_key_ranges(*ext), len(params) + 1)
                if count_only:
                    return int(await conn.fetchval(_wod_ctes(aoi_sql, where) + " SELECT count(*) FROM pts",
                                                   *params, *kp))
                sql = (_wod_ctes(aoi_sql, where, limit=entry.cap + 1)
                       + " SELECT c.*, pts.picks FROM pts JOIN wod_casts c USING (cast_id)")
                return [_wod_row(r) for r in await conn.fetch(sql, *params, *kp)]
    raise ValueError(f"unknown observation query {entry.query!r}")


async def count(entry: ObservationExport, aoi: Aoi) -> int:
    return await _run(entry, aoi, count_only=True)


async def rows(entry: ObservationExport, aoi: Aoi) -> tuple[list[dict], bool]:
    out = await _run(entry, aoi, count_only=False)
    return out[: entry.cap], len(out) > entry.cap
