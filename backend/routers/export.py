# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from __future__ import annotations

import asyncio
import datetime as _dt
import importlib
import io
import json
import math
import zipfile

import asyncpg
import db
from auth import get_api_key
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from services.export_registry import (
    EXPORT_LAYERS,
    CompositeExport,
    FieldSource,
    Provenance,
    VectorExport,
    kind_of,
)
from services.export_query import Aoi, parse_aoi, build_vector_sql
from services.export_serialize import rows_to_geojson, rows_to_csv, PASS_THROUGH_NOTE, dumps_geojson
from services.export_fields import cells_in_aoi, normalize_lons

router = APIRouter(prefix="/v2/export", tags=["export"])

# Per-request DB statement timeout for vector export queries.
# Regional AOIs finish in <1.5s; only near-global/pathological queries approach this limit.
_EXPORT_STMT_TIMEOUT_MS = 12_000


def _utcnow_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_layer(layer: str):
    entry = EXPORT_LAYERS.get(layer)
    if entry is None:
        raise HTTPException(404, f"unknown export layer: {layer}")
    return entry


def _aoi_or_400(bbox, poly, cells):
    try:
        return parse_aoi(bbox, poly, cells)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ─── Cells → bbox helpers ────────────────────────────────────────────────────

def _bbox_row_to_aoi(row) -> Aoi | None:
    """Pure: convert a DB extent row (minx, miny, maxx, maxy) to a bbox Aoi.
    Returns None when the row or its first element is NULL (no matching cells).
    """
    if row is None or row[0] is None:
        return None
    return Aoi(kind="bbox", bbox=(float(row[0]), float(row[1]), float(row[2]), float(row[3])))


async def _resolve_field_aoi(aoi: Aoi) -> Aoi | None:
    """If aoi.kind == 'cells', resolve to the bounding bbox of matching hex cells via DB.
    Returns a bbox Aoi, or None if no cells match. For bbox/poly returns aoi unchanged.
    """
    if aoi.kind != "cells":
        return aoi
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable")
    sql = (
        "SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) "
        "FROM (SELECT ST_Extent(geom) e FROM density_hex_cells"
        " WHERE cell_id = ANY($1::text[])) s"
    )
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(sql, list(aoi.cell_ids))
    return _bbox_row_to_aoi(row)


# ─── Field grid helpers ────────────────────────────────────────────────────────

def _is_woa(mod) -> bool:
    return getattr(mod, "__name__", "").endswith("woa_climatology")


def _load_any_grid(mod, fs: FieldSource):
    """Load a representative grid to inspect axis shape (lats/lons/depths/decades)."""
    if hasattr(mod, "load_recent_grid"):        # oxygen_deox (no sample(); grid used directly)
        return mod.load_recent_grid()
    if _is_woa(mod):
        return mod._load_grid(fs.vars[0], 0)   # tt=0 = annual climatology
    return mod._load_grid(fs.vars[0])           # socat_co2, glodap_carbon


def _field_rows(fs: FieldSource, aoi) -> tuple[list[dict], bool]:
    """Emit native-grid rows for one field source within the AOI. Returns (rows, capped).

    Verified dispatch per module (2026-06-29):
      socat_co2        — _load_grid(var); .lats/.lons/.decades; sample(var,lat,lon,decade_idx)
      glodap_carbon    — _load_grid(var); .lats/.lons/.depths; sample(var,lat,lon,depth_m)
      oxygen_deox      — load_recent_grid(); .lats/.lons/.depths/.data; nearest_grid_value(…)
      woa_climatology  — _load_grid(var,0); .lats/.lons/.depths; sample(var,lat,lon,depth_m,month=0)
      seabed_lithology — CATEGORICAL; load_grid(); sample(lat,lon)->int; emits class_code/class_name
    """
    mod = importlib.import_module(f"services.{fs.sampler}")

    # ── Categorical sampler branch ────────────────────────────────────────────
    # Detected by LITHOLOGY_CLASSES attribute; uses load_grid()+sample(lat,lon)
    # which returns an int class code — incompatible with the continuous _call path.
    if hasattr(mod, "LITHOLOGY_CLASSES"):
        grid = mod.load_grid()
        if grid is None:
            return [], False
        lons = normalize_lons(grid.lons)
        nodes = cells_in_aoi(list(grid.lats), lons, aoi)
        rows: list[dict] = []
        for (_, _, lat, lon) in nodes:
            code = mod.sample(lat, lon)
            if code is None:
                continue
            rows.append({
                "lat": lat,
                "lon": lon,
                "class_code": code,
                "class_name": mod.LITHOLOGY_CLASSES.get(code, "Unknown"),
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
            })
            if len(rows) >= fs.cap:
                return rows, True
        return rows, False

    # ── Continuous sampler path ───────────────────────────────────────────────
    grid = _load_any_grid(mod, fs)
    if grid is None:
        return [], False

    # Build a per-call dispatcher closure (captured grid avoids re-loading oxygen_deox grid
    # for every (cell × depth) combination since nearest_grid_value requires the arrays).
    if hasattr(mod, "load_recent_grid"):
        # oxygen_deox: no sample(); nearest_grid_value(lats,lons,depths,data,lat,lon,depth_m)
        def _call(var, lat, lon, lev, dec):
            return mod.nearest_grid_value(
                grid.lats, grid.lons, grid.depths, grid.data, lat, lon, lev
            )
    elif fs.has_decade:
        # socat_co2: sample(var_key, lat, lon, decade_idx)
        def _call(var, lat, lon, lev, dec):
            return mod.sample(var, lat, lon, dec)
    elif _is_woa(mod):
        # woa_climatology: sample(var_key, lat, lon, depth_m, month); 0 = annual
        def _call(var, lat, lon, lev, dec):
            return mod.sample(var, lat, lon, lev, 0)
    else:
        # glodap_carbon: sample(var_key, lat, lon, depth_m)
        def _call(var, lat, lon, lev, dec):
            return mod.sample(var, lat, lon, lev)

    lons = normalize_lons(grid.lons)
    nodes = cells_in_aoi(list(grid.lats), lons, aoi)
    levels = list(getattr(grid, "depths", [None])) if fs.has_depth else [None]
    # decades: iterate indices 0..n-1; passed as decade_idx to sample()
    decades = list(range(len(getattr(grid, "decades", [0])))) if fs.has_decade else [None]

    rows: list[dict] = []
    for (_, _, lat, lon) in nodes:
        for lev in levels:
            for dec in decades:
                rec: dict = {"lat": lat, "lon": lon}
                if lev is not None:
                    rec["depth_m"] = float(lev)
                if dec is not None:
                    rec["decade"] = dec
                any_val = False
                for var in fs.vars:
                    val = _call(var, lat, lon, lev, dec)
                    # Non-finite → None: acidification "horizon" returns math.inf for
                    # always-supersaturated cells, which json.dumps would emit as the
                    # invalid `Infinity` token. Coerce here (also a general NaN/inf
                    # backstop for any field sampler) so the export stays valid JSON.
                    if isinstance(val, float) and not math.isfinite(val):
                        val = None
                    rec[var] = val
                    any_val = any_val or (val is not None)
                if not any_val:
                    continue
                rec["geometry"] = {"type": "Point", "coordinates": [lon, lat]}
                rows.append(rec)
                if len(rows) >= fs.cap:
                    return rows, True
    return rows, False


# ─── Shared row-fetch helpers ────────────────────────────────────────────────

async def _vector_rows(entry: VectorExport, aoi) -> tuple[list[dict], bool]:
    """Fetch and decode vector rows for one layer. Returns (rows, capped)."""
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable")
    sql, params = build_vector_sql(entry, aoi, count_only=False)
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(f"SET LOCAL statement_timeout = {_EXPORT_STMT_TIMEOUT_MS}")
            rows = await conn.fetch(sql, *params)
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("geometry"), str):
            d["geometry"] = json.loads(d["geometry"])
        out.append(d)
    return out, len(out) >= entry.cap


async def _rows_for(entry, aoi) -> tuple[list[dict], bool, str, Provenance]:
    """Return (rows, capped, geom_kind, prov) for a vector or field entry.

    Raises ValueError for composite entries — callers must expand members first.
    """
    k = kind_of(entry)
    if k == "vector":
        rows, capped = await _vector_rows(entry, aoi)
        return rows, capped, entry.geom_kind, entry.prov
    if k == "field":
        faoi = await _resolve_field_aoi(aoi)
        if faoi is None:
            return [], False, "point", entry.prov
        rows, capped = await asyncio.to_thread(_field_rows, entry, faoi)
        return rows, capped, "point", entry.prov
    raise ValueError(f"{entry.id!r} is composite; expand members first")


def _members_of(entry: CompositeExport) -> list:
    """Return the member entry objects (VectorExport or FieldSource) from EXPORT_LAYERS."""
    return [EXPORT_LAYERS[m] for m in entry.members]


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get("/{layer}/count", dependencies=[Depends(get_api_key)])
async def export_count(
    layer: str,
    bbox: str | None = Query(None),
    poly: str | None = Query(None),
    cells: str | None = Query(None),
) -> dict:
    entry = _get_layer(layer)
    aoi = _aoi_or_400(bbox, poly, cells)
    entry_kind = kind_of(entry)

    if entry_kind == "vector":
        if db.pool is None:
            raise HTTPException(503, "Database pool unavailable")
        sql, params = build_vector_sql(entry, aoi, count_only=True)
        try:
            async with db.pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(f"SET LOCAL statement_timeout = {_EXPORT_STMT_TIMEOUT_MS}")
                    n = await conn.fetchval(sql, *params)
        except asyncpg.QueryCanceledError:
            raise HTTPException(400, "Area too broad to count — draw a smaller area")
        return {"count": int(n), "cap": entry.cap, "capped": int(n) > entry.cap}

    if entry_kind == "field":
        assert isinstance(entry, FieldSource)
        resolved_aoi = await _resolve_field_aoi(aoi)
        if resolved_aoi is None:
            return {"count": 0, "cap": entry.cap, "capped": False}
        try:
            rows, capped = await asyncio.to_thread(_field_rows, entry, resolved_aoi)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"count": len(rows), "cap": entry.cap, "capped": capped}

    if entry_kind == "composite":
        assert isinstance(entry, CompositeExport)
        members = []
        for member in _members_of(entry):
            mk = kind_of(member)
            if mk == "vector":
                if db.pool is None:
                    raise HTTPException(503, "Database pool unavailable")
                sql, params = build_vector_sql(member, aoi, count_only=True)
                try:
                    async with db.pool.acquire() as conn:
                        async with conn.transaction():
                            await conn.execute(f"SET LOCAL statement_timeout = {_EXPORT_STMT_TIMEOUT_MS}")
                            n = await conn.fetchval(sql, *params)
                    count = int(n)
                    capped = count > member.cap
                except asyncpg.QueryCanceledError:
                    members.append({"id": member.id, "count": None, "cap": member.cap, "capped": False})
                    continue
            else:  # field
                try:
                    rows, capped, _gk, _prov = await _rows_for(member, aoi)
                except ValueError as e:
                    raise HTTPException(400, str(e))
                count = len(rows)
            members.append({"id": member.id, "count": count, "cap": member.cap, "capped": capped})
        return {"members": members}

    raise HTTPException(404, "unknown kind")


@router.get("/bundle", dependencies=[Depends(get_api_key)])
async def export_bundle(
    layers: str = Query(...),
    bbox: str | None = Query(None),
    poly: str | None = Query(None),
    cells: str | None = Query(None),
    format: str = Query("geojson", pattern="^(geojson|csv)$"),
):
    """Download a ZIP containing one file per requested layer (composites expand to subfolders).

    - ``layers``: comma-separated export layer ids (≤40; all must be in EXPORT_LAYERS)
    - exactly one of ``bbox``, ``poly``, ``cells`` (via _aoi_or_400)
    - ``format``: ``geojson`` (default) or ``csv``

    Composite layers expand to ``{composite_id}/{member_id}.{ext}``; a member that raises
    ValueError (e.g. a nested composite) is SKIPPED with a note in MANIFEST.txt rather
    than failing the whole bundle.
    """
    ids = [x for x in layers.split(",") if x]
    if not ids:
        raise HTTPException(400, "layers required")
    if len(ids) > 40:
        raise HTTPException(400, "too many layers (max 40)")
    for i in ids:
        if i not in EXPORT_LAYERS:
            raise HTTPException(400, f"unknown export layer: {i}")
    aoi = _aoi_or_400(bbox, poly, cells)
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable")
    retrieved = _utcnow_iso()
    ext = "csv" if format == "csv" else "geojson"
    buf = io.BytesIO()
    manifest: list[str] = [f"Abyssal export — retrieved {retrieved}", ""]

    async def emit(zf: zipfile.ZipFile, name: str, entry, aoi) -> None:
        try:
            rows, capped, geom_kind, prov = await _rows_for(entry, aoi)
        except ValueError as e:
            manifest.append(f"[{name}] SKIPPED: {e}")
            manifest.append("")
            return
        except asyncpg.QueryCanceledError:
            manifest.append(f"[{name}] SKIPPED: query timed out (area too broad)")
            manifest.append("")
            return
        if not rows:
            # Don't write empty files into the ZIP — record the omission instead.
            manifest.append(f"[{name}] omitted — no data in selected area")
            manifest.append("")
            return
        try:
            if format == "csv":
                content = rows_to_csv(rows, geom_kind, prov)
            else:
                content = dumps_geojson(
                    rows_to_geojson(rows, prov, retrieved_at=retrieved, capped=capped, layer_id=entry.id)
                )
            zf.writestr(f"{name}.{ext}", content)
        except Exception as e:
            manifest.append(f"[{name}] SKIPPED: serialization error: {e}")
            manifest.append("")
            return
        manifest.extend([
            f"[{name}] {getattr(entry, 'label', name)}",
            f"  source: {prov.source}",
            f"  url: {prov.source_url}",
            f"  license: {prov.license or '—'}",
            f"  citation: {prov.citation or '—'}",
            f"  rows: {len(rows)}{' (capped)' if capped else ''}",
            "",
        ])

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i in ids:
            entry = EXPORT_LAYERS[i]
            if kind_of(entry) == "composite":
                for m in _members_of(entry):
                    await emit(zf, f"{i}/{m.id}", m, aoi)
            else:
                await emit(zf, i, entry, aoi)
        zf.writestr("MANIFEST.txt", "\n".join(manifest) + "\n" + PASS_THROUGH_NOTE + "\n")

    date_str = retrieved[:10].replace("-", "")
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="abyssal-export-{date_str}.zip"'},
    )


@router.get("/{layer}", dependencies=[Depends(get_api_key)])
async def export_data(
    layer: str,
    bbox: str | None = Query(None),
    poly: str | None = Query(None),
    cells: str | None = Query(None),
    format: str = Query("geojson", pattern="^(geojson|csv)$"),
):
    entry = _get_layer(layer)
    aoi = _aoi_or_400(bbox, poly, cells)
    entry_kind = kind_of(entry)

    if entry_kind == "field":
        assert isinstance(entry, FieldSource)
        resolved_aoi = await _resolve_field_aoi(aoi)
        if resolved_aoi is None:
            rows, capped = [], False
        else:
            try:
                rows, capped = await asyncio.to_thread(_field_rows, entry, resolved_aoi)
            except ValueError as e:
                raise HTTPException(400, str(e))
        retrieved = _utcnow_iso()
        if format == "csv":
            body = rows_to_csv(rows, "point", entry.prov)
            return Response(
                body,
                media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="{layer}.csv"'},
            )
        fc = rows_to_geojson(
            rows, entry.prov, retrieved_at=retrieved, capped=capped, layer_id=layer
        )
        return Response(content=dumps_geojson(fc), media_type="application/geo+json")

    if entry_kind == "composite":
        assert isinstance(entry, CompositeExport)
        retrieved = _utcnow_iso()
        ext = "csv" if format == "csv" else "geojson"
        buf = io.BytesIO()
        manifest_lines = [f"Marine Carbon raw sources — retrieved {retrieved}", ""]
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for member in _members_of(entry):
                try:
                    rows, capped, geom_kind, prov = await _rows_for(member, aoi)
                except ValueError as e:
                    raise HTTPException(400, str(e))
                if not rows:
                    # Skip empty members — no empty files in the ZIP.
                    manifest_lines += [f"[{member.id}] omitted — no data in selected area", ""]
                    continue
                if format == "csv":
                    content = rows_to_csv(rows, geom_kind, prov)
                else:
                    content = dumps_geojson(
                        rows_to_geojson(
                            rows, prov, retrieved_at=retrieved, capped=capped, layer_id=member.id
                        )
                    )
                zf.writestr(f"{member.id}.{ext}", content)
                manifest_lines += [
                    f"[{member.id}] {member.label}",
                    f"  source: {prov.source}",
                    f"  url: {prov.source_url}",
                    f"  license: {prov.license or '—'}",
                    f"  citation: {prov.citation or '—'}",
                    f"  rows: {len(rows)}{' (capped)' if capped else ''}",
                    "",
                ]
            zf.writestr("MANIFEST.txt", "\n".join(manifest_lines))
        return Response(
            buf.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="marine-carbon.zip"'},
        )

    # vector path
    assert isinstance(entry, VectorExport)
    try:
        out, capped = await _vector_rows(entry, aoi)
    except asyncpg.QueryCanceledError:
        raise HTTPException(400, "Area too large — narrow your selection")
    retrieved = _utcnow_iso()
    if format == "csv":
        body = rows_to_csv(out, entry.geom_kind, entry.prov, columns=list(entry.fields))
        return Response(
            content=body,
            media_type="text/csv",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{layer}_{retrieved[:10].replace("-", "")}.csv"'
                )
            },
        )
    fc = rows_to_geojson(out, entry.prov, retrieved_at=retrieved, capped=capped, layer_id=layer)
    return Response(content=dumps_geojson(fc), media_type="application/geo+json")
