# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from __future__ import annotations

import csv as _csv
import datetime as _dt
import io
import json
from decimal import Decimal as _Decimal

from services.export_registry import Provenance


def _json_default(o):
    """JSON serialization fallback for types asyncpg returns that json.dumps can't handle."""
    if isinstance(o, (_dt.datetime, _dt.date, _dt.time)):
        return o.isoformat()
    if isinstance(o, _Decimal):
        return float(o)
    if isinstance(o, (bytes, bytearray)):
        return o.decode("utf-8", "replace")
    return str(o)


def dumps_geojson(fc: dict) -> str:
    """Serialize a GeoJSON FeatureCollection to a JSON string.

    Uses _json_default so date/datetime/Decimal/bytes values from asyncpg rows
    never raise TypeError during export (previously caused HTTP 500 on layers
    with date or numeric columns such as wdpa, contracts, arctic-rivers, sios).
    """
    return json.dumps(fc, default=_json_default)

_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(s: str) -> str:
    """Prefix trigger characters so spreadsheet apps don't execute the cell as a formula."""
    return "'" + s if s and s[0] in _CSV_FORMULA_PREFIXES else s


def _safe_cell(v):
    """Like _cell but neutralizes CSV formula injection for string values only.

    int/float values pass through unchanged so negative numbers like -12.5
    are never corrupted by a spurious apostrophe prefix.
    """
    c = _cell(v)
    return _csv_safe(c) if isinstance(c, str) else c

PASS_THROUGH_NOTE = (
    "Records passed through unmodified from the upstream source; "
    "verify and cite via source_url."
)


def rows_to_geojson(rows, prov: Provenance, *, retrieved_at: str, capped: bool, layer_id: str) -> dict:
    features = []
    for r in rows:
        d = dict(r)
        geom = d.pop("geometry", None)
        features.append({"type": "Feature", "geometry": geom, "properties": d})
    return {
        "type": "FeatureCollection",
        "metadata": {
            "layer": layer_id,
            "source": prov.source,
            "source_url": prov.source_url,
            "license": prov.license,
            "citation": prov.citation,
            "retrieved_at": retrieved_at,
            "feature_count": len(features),
            "capped": capped,
            "note": (prov.note + " " if prov.note else "") + PASS_THROUGH_NOTE,
        },
        "features": features,
    }


def _wkt_from_geojson(geom: dict) -> str:
    t = geom["type"].upper()

    def ring(coords):
        return "(" + ", ".join(f"{x} {y}" for x, y in coords) + ")"

    if t == "POLYGON":
        return "POLYGON(" + ", ".join(ring(r) for r in geom["coordinates"]) + ")"
    if t == "MULTIPOLYGON":
        polys = ["(" + ", ".join(ring(r) for r in poly) + ")" for poly in geom["coordinates"]]
        return "MULTIPOLYGON(" + ", ".join(polys) + ")"
    if t == "LINESTRING":
        return "LINESTRING" + ring(geom["coordinates"])
    if t == "MULTILINESTRING":
        return "MULTILINESTRING(" + ", ".join(ring(r) for r in geom["coordinates"]) + ")"
    return json.dumps(geom)


def rows_to_csv(
    rows, geom_kind: str, prov: Provenance, *, columns: list[str] | None = None
) -> str:
    buf = io.StringIO()
    w = _csv.writer(buf, lineterminator="\r\n")
    # Seed prop_keys from caller-supplied columns for a stable header on 0 rows.
    # When rows exist, any extra keys present in them are appended (union, columns first).
    prop_keys: list[str] = list(columns) if columns else []
    for r in rows:
        for k in r.keys():
            if k != "geometry" and k not in prop_keys:
                prop_keys.append(k)
    # For point layers, only append geometry-derived lat/lon columns when they are
    # NOT already present as source-data properties (avoids duplicate headers for
    # layers like arctic-rivers / sios-svalbard that store lat/lon natively).
    if geom_kind == "point":
        geo_cols = [c for c in ("lat", "lon") if c not in prop_keys]
    else:
        geo_cols = ["geometry_wkt"]
    # Collision-proof trailing provenance columns: if a row property already uses
    # "source" or "source_url", rename the layer-level provenance columns so the
    # CSV header never contains a duplicate key (e.g. seaflea/methane-seeps layer).
    src_col = "dataset_source" if "source" in prop_keys else "source"
    src_url_col = "dataset_source_url" if "source_url" in prop_keys else "source_url"
    w.writerow(prop_keys + geo_cols + [src_col, src_url_col])
    for r in rows:
        d = dict(r)
        geom = d.pop("geometry", None)
        row = [_safe_cell(d.get(k)) for k in prop_keys]
        if geom_kind == "point":
            coords = geom["coordinates"] if geom else None
            for col in geo_cols:
                if coords:
                    row.append(coords[1] if col == "lat" else coords[0])
                else:
                    row.append("")
        else:
            row += [_csv_safe(_wkt_from_geojson(geom)) if geom else ""]
        row += [_csv_safe(prov.source), _csv_safe(prov.source_url)]
        w.writerow(row)
    return buf.getvalue()


def _cell(v):
    if isinstance(v, (dict, list)):
        return json.dumps(v, separators=(",", ":"))
    return "" if v is None else v
