# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from __future__ import annotations

from dataclasses import dataclass

from services.export_registry import VectorExport

_MAX_CELLS = 500


@dataclass(frozen=True)
class Aoi:
    kind: str  # "bbox" | "poly" | "cells"
    bbox: tuple[float, float, float, float] | None = None
    poly_geojson: str | None = None
    cell_ids: tuple[str, ...] | None = None


def parse_aoi(bbox: str | None, poly: str | None, cells: str | None) -> Aoi:
    present = [p for p in (bbox, poly, cells) if p]
    if len(present) != 1:
        raise ValueError("provide exactly one of bbox, poly, cells")
    if bbox:
        parts = bbox.split(",")
        if len(parts) != 4:
            raise ValueError("bbox must be minLng,minLat,maxLng,maxLat")
        try:
            nums = tuple(float(p) for p in parts)
        except ValueError as e:
            raise ValueError("bbox values must be numeric") from e
        return Aoi(kind="bbox", bbox=nums)  # type: ignore[arg-type]
    if poly:
        if "coordinates" not in poly:
            raise ValueError("poly must be a GeoJSON geometry")
        return Aoi(kind="poly", poly_geojson=poly)
    # cell_id is "i,j" (contains a comma), so the list delimiter is ";", NOT ",".
    # Splitting on "," would shred each id into two halves and match nothing.
    ids = tuple(c for c in cells.split(";") if c)  # type: ignore[union-attr]
    if not ids:
        raise ValueError("cells empty")
    if len(ids) > _MAX_CELLS:
        raise ValueError(f"too many cells (max {_MAX_CELLS})")
    return Aoi(kind="cells", cell_ids=ids)


def _where(aoi: Aoi, geom: str) -> tuple[str, list, str]:
    """Return (extra_from, params, where). `geom` is the qualified geom column."""
    if aoi.kind == "bbox":
        env = "ST_MakeEnvelope($1,$2,$3,$4,4326)"
        where = f"{geom} && {env} AND ST_Intersects({geom}, {env})"
        return "", list(aoi.bbox), where  # type: ignore[arg-type]
    if aoi.kind == "poly":
        g = "ST_SetSRID(ST_GeomFromGeoJSON($1),4326)"
        where = f"{geom} && {g} AND ST_Intersects({geom}, {g})"
        return "", [aoi.poly_geojson], where
    # cells
    extra = "JOIN density_hex_cells h ON h.cell_id = ANY($1::text[])"
    where = f"ST_Intersects({geom}, h.geom)"
    return extra, [list(aoi.cell_ids)], where  # type: ignore[arg-type]


def build_vector_sql(layer: VectorExport, aoi: Aoi, *, count_only: bool) -> tuple[str, list]:
    geom = layer.geom_col  # already qualified (t.geom / c.geom)
    join = layer.join_sql or ""
    extra_from, params, where = _where(aoi, geom)
    from_clause = f"{layer.table} t {join} {extra_from}".strip()
    if count_only:
        return f"SELECT COUNT(*) FROM {from_clause} WHERE {where}", params
    cols = ", ".join(f"t.{c}" if "." not in c else c for c in layer.fields)
    sql = (
        f"SELECT {cols}, ST_AsGeoJSON({geom})::json AS geometry "
        f"FROM {from_clause} WHERE {where} LIMIT {layer.cap}"
    )
    return sql, params
