# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

# backend/ingestion/arcade_ingest.py
"""ARCADE v1 pan-Arctic catchment ingest (pure parser).

Source: DataVerse doi:10.34894/U9HSPV — two zipped shapefiles in EASE-Grid 2.0
North (EPSG:6931). This module only parses; reprojection to 4326 happens in
PostGIS at insert time.
"""
from __future__ import annotations
import io
import shapefile  # pyshp

DATAVERSE_DOI = "doi:10.34894/U9HSPV"
# Tiles 36 and 37 are the SAME 47,054 catchments (identical gids/geometry); 37 only adds unused CGLS_* land-cover columns. Tile 36 carries every field we use, so we ingest it alone (verified 2026-06-28).
SOURCE_FILES = ["ARCADE_v1_36_1km"]

# source DBF col -> our column (headline, stored as real columns)
_HEADLINE = {
    "gid": "gid", "name": "name", "order": "stream_order", "continent": "continent",
    "area_km2": "area_km2", "center_lat": "center_lat", "center_lon": "center_lon",
    "ocs_mean": "ocs_mean", "oc_tot": "oc_tot", "runoff_mea": "runoff_mean",
    "pf_frac": "pf_frac", "t_2m_mean": "t_2m_mean",
}
_SOC_DEPTH = [f"soc_{i}_mean" for i in range(1, 7)]
_PF_CLASSES = {"cont": "pf_cont", "disc": "pf_disc", "isol": "pf_isol", "spor": "pf_spor"}
_PARAM_SCALARS = ["iwp_frac", "etot_mean", "ptot_mean", "total_prec",
                  "t_2m_min", "t_2m_max"]


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _signed_area(ring) -> float:
    """Shoelace signed area. Shapefile convention: exterior ring is clockwise
    (negative area); interior ring (hole) is counter-clockwise (positive area)."""
    a = 0.0
    n = len(ring)
    for i in range(n - 1):
        x_i, y_i = ring[i]
        x_j, y_j = ring[i + 1]
        a += x_i * y_j - x_j * y_i
    return 0.5 * a


def _rings_to_wkt(shape) -> str:
    """pyshp polygon (parts) -> WKT MULTIPOLYGON in source metres.

    Assemble OGC polygons by ring winding order: a negative-area (clockwise)
    ring starts a new polygon as its exterior shell; each following positive-area
    (counter-clockwise) ring is a hole appended to the current polygon."""
    pts = shape.points
    parts = list(shape.parts) + [len(pts)]
    polys: list[list[str]] = []  # each poly = [ext_ring_str, hole_str, ...]
    for i in range(len(parts) - 1):
        ring = pts[parts[i]:parts[i + 1]]
        if len(ring) < 4:
            continue
        ring_str = "(" + ", ".join(f"{x} {y}" for x, y in ring) + ")"
        area = _signed_area(ring)
        if area <= 0 or not polys:
            # exterior shell (clockwise) — or fallback: first ring is positive
            # but no exterior open yet, so treat it as an exterior shell.
            polys.append([ring_str])
        else:
            # hole (counter-clockwise) appended to the current polygon
            polys[-1].append(ring_str)
    if not polys:
        return "MULTIPOLYGON EMPTY"
    return "MULTIPOLYGON(" + ", ".join("(" + ", ".join(p) + ")" for p in polys) + ")"


def build_catchment_rows(shp_bytes: bytes, shx_bytes: bytes, dbf_bytes: bytes) -> list[dict]:
    r = shapefile.Reader(shp=io.BytesIO(shp_bytes), shx=io.BytesIO(shx_bytes),
                         dbf=io.BytesIO(dbf_bytes))
    fields = [f[0] for f in r.fields[1:]]
    rows: list[dict] = []
    for i in range(len(r)):
        rec = dict(zip(fields, r.record(i)))
        row: dict = {}
        for src, dst in _HEADLINE.items():
            v = rec.get(src)
            if dst in ("name", "continent"):
                v = (str(v).strip() or None) if v not in (None, "") else None
            elif dst in ("gid", "stream_order"):
                n = _num(v)
                v = int(n) if n is not None else None
            else:
                v = _num(v)
            row[dst] = v
        row["params"] = {
            "soc_depth": [_num(rec.get(k)) for k in _SOC_DEPTH],
            "pf_classes": {k: _num(rec.get(src)) for k, src in _PF_CLASSES.items()},
            **{k: _num(rec.get(k)) for k in _PARAM_SCALARS},
            # NDVI is the lone uppercase DBF column — emit snake_case to match
            # the frontend panel + every other param scalar.
            "ndvi_mean": _num(rec.get("NDVI_mean")),
        }
        row["wkt"] = _rings_to_wkt(r.shape(i))
        rows.append(row)
    return rows
