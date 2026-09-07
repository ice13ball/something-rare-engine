# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""ARTS — Arctic Retrogressive Thaw Slumps v6.0.0 (whrc/ARTS, CC0).

Circumpolar RTS digitisations. Pure parser + LFS-aware downloader.
Second sub-source of the permafrost-thaw layer (source='arts_panarctic').

Schema notes (verified against the real v6.0.0 GeoJSON, 61,371 features):
  - CRS is EPSG:3413 (NSIDC polar-stereographic **metres**), NOT WGS84. So the
    geometry coordinates are projected metres — a shoelace centroid on them would
    be metres, not lon/lat. The source, however, ships WGS84 `CentroidLat`/
    `CentroidLon` properties, so we take lat/lon from those directly. The
    geometry-centroid helper (`_centroid`) is kept only as a fallback for records
    that lack the centroid properties (and for the synthetic WGS84 unit tests).
  - Property keys are: Area, BaseMapDate, BaseMapID, BaseMapResolution,
    BaseMapSource, CentroidLat, CentroidLon, ContributionDate, CreatorLab,
    LabelType, MergedRTS, NewRTS, Notes, RegionName, SplitRTS, StabilizedRTS,
    TrainClass, UID, UnknownRelationship.
  - GEOM TYPES: Point, Polygon, MultiPolygon. TrainClass ∈ {Positive, Negative}.
  - `RegionName` gives a human region label (e.g. "Banks Island, Inuvik Region,
    Canada") — surfaced as `feature_name`.

Emits the SAME 12-key row dict as `permafrost_thaw.build_thaw_rows` so the shared
INSERT works downstream: source="arts_panarctic",
feature_category="retrogressive thaw slump", thaw_type="abrupt".
"""
from __future__ import annotations
import json
import logging
import os
import subprocess
import tempfile

log = logging.getLogger(__name__)

_URL = ("https://media.githubusercontent.com/media/whrc/ARTS/v.6.0.0/"
        "ARTS_main_dataset/v.6.0.0/ARTS_main_dataset_v.6.0.0.geojson")
_DOI = "https://doi.org/10.5281/zenodo.10535025"
_NA = {"", "n/a", "na", "none", "null", "-", "nan"}


def fetch_arts_geojson() -> dict:
    """Download the LFS-resolved v6.0.0 GeoJSON via curl -4 and return the dict.

    Uses the `media.githubusercontent.com/media/...` host, which resolves Git-LFS
    pointers to the real bytes. Raises if the payload looks like an LFS pointer.
    """
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "arts.geojson")
        subprocess.run(
            ["/usr/bin/curl", "-4", "-fsSL", "--max-time", "900", "-o", p, _URL],
            check=True, timeout=960,
        )
        raw = open(p, "rb").read()
    if raw[:200].lstrip().startswith(b"version https://git-lfs"):
        raise RuntimeError("arts: got a Git-LFS pointer, not data — check the media URL")
    return json.loads(raw)


def _clean(v):
    if v is None:
        return None
    s = str(v).strip()
    return None if s.lower() in _NA else s


def _float_or_none(v):
    s = _clean(v)
    if s is None:
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _centroid(geom: dict):
    """Return (lon, lat) centroid for Point/Polygon/MultiPolygon; None if unusable.

    Fallback only — the real ARTS geometry is in EPSG:3413 metres, so this is
    meaningful only for the source's rare centroid-less rows or WGS84 test inputs.
    Polygon centroid via shoelace on the exterior ring; falls back to vertex mean.
    """
    if not geom:
        return None
    t = geom.get("type")
    c = geom.get("coordinates")
    try:
        if t == "Point":
            return float(c[0]), float(c[1])
        if t == "Polygon":
            ring = c[0]
        elif t == "MultiPolygon":
            ring = c[0][0]
        else:
            return None
        pts = [(float(x), float(y)) for x, y in ring]
        if len(pts) < 3:
            return None
        a = cx = cy = 0.0
        for i in range(len(pts) - 1):
            x0, y0 = pts[i]
            x1, y1 = pts[i + 1]
            cross = x0 * y1 - x1 * y0
            a += cross
            cx += (x0 + x1) * cross
            cy += (y0 + y1) * cross
        if abs(a) < 1e-12:  # degenerate ring → vertex mean
            n = len(pts)
            return sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n
        a *= 0.5
        return cx / (6 * a), cy / (6 * a)
    except (TypeError, ValueError, IndexError):
        return None


def build_arts_rows(geojson: dict) -> list[dict]:
    """Pure: ARTS GeoJSON FeatureCollection -> list of insert-ready row dicts.

    Keeps only TrainClass=="Positive"; dedups on (source, UID); skips features
    with no UID or no locatable position.
    """
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for f in geojson.get("features", []):
        p = f.get("properties") or {}
        if (p.get("TrainClass") or "").strip().lower() != "positive":
            continue
        uid = _clean(p.get("UID"))
        if uid is None:
            continue

        # Prefer the source's WGS84 centroid (geometry is EPSG:3413 metres);
        # fall back to a geometry centroid only when those are absent.
        lat = _float_or_none(p.get("CentroidLat"))
        lon = _float_or_none(p.get("CentroidLon"))
        if lat is None or lon is None:
            cen = _centroid(f.get("geometry") or {})
            if cen is None:
                continue
            lon, lat = cen

        key = ("arts_panarctic", uid)
        if key in seen:
            log.debug("arts: dedup-skip on duplicate UID %s", uid)
            continue
        seen.add(key)

        label = _clean(p.get("LabelType"))
        imagery = " · ".join(x for x in (
            _clean(p.get("BaseMapSource")), _clean(p.get("BaseMapDate")),
            (f"{_clean(p.get('BaseMapResolution'))} m" if _clean(p.get("BaseMapResolution")) else None),
        ) if x) or None

        rows.append({
            "source": "arts_panarctic",
            "unique_id": uid,
            "feature_name": _clean(p.get("RegionName")),
            "feature_type": "retrogressive thaw slump",
            "feature_category": "retrogressive thaw slump",
            "thaw_type": "abrupt",
            "data_source_type": ("Remote sensing — " + label) if label else "Remote sensing",
            "authors": _clean(p.get("CreatorLab")),
            "source_doi": _DOI,
            "imagery": imagery,
            "lat": lat,
            "lon": lon,
        })
    return rows
