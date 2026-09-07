# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""SEAFLEA observed seafloor methane-seep database ingest (NRL / NOAA NCEI).

Static frozen dataset (Feb 2019). ArcGIS FeatureServer layer 6 = all 10,386 points.
Pure parsers (build_seep_rows + helpers) are unit-tested against a saved real fixture;
the live fetch helper is thin and not unit-tested.
"""
from __future__ import annotations
import httpx

SERVICE = ("https://services2.arcgis.com/C8EMgrsFcRFL6LrL/arcgis/rest/services/"
           "SEAFLEAs_Web_Map_WFL1/FeatureServer/6/query")

# ArcGIS flag column -> canonical type, IN PRIORITY ORDER (first present = primary_type).
# Shallow_Gas is intentionally excluded: the column exists but is empty for all 10,386 rows.
FLAG_COLUMNS: list[tuple[str, str]] = [
    ("Gas_Bubbles", "gas_bubbles"),
    ("Hydrate", "hydrate"),
    ("Mound", "mound"),
    ("Pockmark", "pockmark"),
    ("ChemCommunity", "chem_community"),
    ("Hardground", "hardground"),
]


def _parse_depth(s) -> float | None:
    if s is None:
        return None
    try:
        return float(str(s).strip())
    except (ValueError, TypeError):
        return None


def _parse_year(v) -> int | None:
    try:
        y = int(v)
    except (ValueError, TypeError):
        return None
    return y if y > 0 else None


def _clean(s) -> str | None:
    if s is None:
        return None
    s = str(s).strip()
    return s or None


def _derive_types(props: dict) -> tuple[list[str], str | None, dict]:
    types: list[str] = []
    raw: dict = {}
    for col, canon in FLAG_COLUMNS:
        val = props.get(col)
        if val is not None and str(val).strip() != "":
            types.append(canon)
            raw[canon] = str(val).strip()
    primary = types[0] if types else None
    return types, primary, raw


def build_seep_rows(geojson: dict) -> list[dict]:
    rows: list[dict] = []
    for ft in geojson.get("features", []):
        p = ft.get("properties", {}) or {}
        geom = ft.get("geometry") or {}
        coords = geom.get("coordinates") or [None, None]
        lon, lat = coords[0], coords[1]
        ext_id = _clean(p.get("Data_Base_ID"))
        if ext_id is None or lat is None or lon is None:
            continue
        types, primary, raw = _derive_types(p)
        rows.append({
            "ext_id": ext_id,
            "lat": float(lat),
            "lon": float(lon),
            "depth_m": _parse_depth(p.get("Depth__m_")),
            "obs_year": _parse_year(p.get("YYYY")),
            "loc_uncert_m": _parse_depth(p.get("LocUncert__m_")),
            # Pockmark morphometry (~606 of the 5,329 pockmark points carry these).
            # PM_Depth__m_ is stored negative in the source (depression depth below
            # surrounding seafloor); kept raw for source fidelity, abs() applied at display.
            "pockmark_depth_m": _parse_depth(p.get("PM_Depth__m_")),
            "pockmark_radius_m": _parse_depth(p.get("PM_Radius__m_")),
            "feature_types": types,
            "primary_type": primary,
            "type_raw": raw,
            "source_ref": _clean(p.get("SourceRef")),
            "source_url": _clean(p.get("SourceRef_url")),
        })
    return rows


def fetch_seaflea_geojson(page_size: int = 8000) -> dict:
    """Paginated fetch of all layer-6 features as one GeoJSON FeatureCollection.

    10,386 points fit in two pages at page_size=8000; resultOffset paging is the
    safety net. Uses httpx with default TLS verification (matches the backend's
    other ArcGIS syncs, e.g. NOAA corals/cables) — do NOT disable cert verification.
    """
    feats: list[dict] = []
    offset = 0
    with httpx.Client(timeout=120) as client:
        while True:
            r = client.get(SERVICE, params={
                "where": "1=1", "outFields": "*", "outSR": 4326, "f": "geojson",
                "resultRecordCount": page_size, "resultOffset": offset,
                "orderByFields": "OBJECTID",
            })
            r.raise_for_status()
            batch = r.json().get("features", [])
            feats.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size
    return {"type": "FeatureCollection", "features": feats}
