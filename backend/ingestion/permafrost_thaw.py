# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Alaska Permafrost Thaw Database v2.0.0 (Webb et al. 2026, ESSD 18:3147, CC-BY 4.0).

Source: Zenodo record 17494851 (github.com/ArcticWebb/Alaska_Permafrost_Thaw_Database).
~19,540 observed thaw-feature points, Alaska only. Pure parser + downloader; no DB access here.

Schema note (verified against the real v2.0.0 zip, not assumed): the source GeoJSON
carries NO `UniqueID`/`Latitude`/`Longitude` properties -- only `geometry.coordinates`.
Property keys are exactly: Authors, DOI, DataSourceType, FeatureCategory, FeatureName,
FeatureType, Imagery, ImageryDates, ImageryResolution_meters, ThawType. Since there is
no natural source id, `unique_id` is a deterministic hash derived from coordinates +
identifying fields (see `_make_unique_id`).
"""
from __future__ import annotations
import hashlib
import json
import logging
import os
import subprocess
import tempfile
import zipfile

log = logging.getLogger(__name__)

_ZIP_URL = ("https://zenodo.org/api/records/17494851/files/"
            "ArcticWebb/Alaska_Permafrost_Thaw_Database-v2.0.0.zip/content")
# Real path inside the zip (verified 2026-07-03): note "Spatial_Files" (not
# "Geospatial_Files") and the version suffix on the filename itself.
_GEOJSON_SUFFIX = "Main_Dataset/v2.0.0/Spatial_Files/Alaska_Permafrost_Thaw_Database_v2.0.0.geojson"
_NA = {"", "n/a", "na", "none", "null", "-", "nan"}


def fetch_alaska_thaw_geojson() -> dict:
    """Download the Zenodo zip via curl -4 and return the parsed GeoJSON dict."""
    with tempfile.TemporaryDirectory() as td:
        zip_path = os.path.join(td, "akthaw.zip")
        subprocess.run(
            ["/usr/bin/curl", "-4", "-fsSL", "-o", zip_path, _ZIP_URL],
            check=True, timeout=300,
        )
        with zipfile.ZipFile(zip_path) as z:
            member = next((n for n in z.namelist() if n.endswith(_GEOJSON_SUFFIX)), None)
            if member is None:
                raise RuntimeError("permafrost_thaw: GeoJSON not found in zip")
            # Manual path-traversal guard (zipfile has no filter= kwarg on this Python).
            target = os.path.realpath(os.path.join(td, member))
            if not target.startswith(os.path.realpath(td) + os.sep):
                raise RuntimeError("permafrost_thaw: unsafe zip member path")
            raw = z.read(member)
    # Source file is latin-1, not UTF-8 (confirmed: decoding as UTF-8 raises
    # UnicodeDecodeError on non-ASCII bytes in Authors/Imagery free text).
    return json.loads(raw.decode("latin-1"))


def _clean(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return None if s.lower() in _NA else s


def _make_unique_id(lon: float, lat: float, p: dict) -> str:
    """Deterministic id: the source has no UniqueID/OBJECTID column, so derive
    a stable sha1 hash from coordinates plus the fields that identify a feature."""
    basis = "|".join([
        f"{lon:.6f}", f"{lat:.6f}",
        str(p.get("FeatureName") or ""), str(p.get("FeatureType") or ""),
        str(p.get("Authors") or ""), str(p.get("DOI") or ""),
    ])
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def build_thaw_rows(geojson: dict) -> list[dict]:
    """Pure: GeoJSON FeatureCollection -> list of insert-ready row dicts."""
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for f in geojson.get("features", []):
        p = f.get("properties") or {}
        geom = f.get("geometry") or {}
        lon = lat = None
        if geom.get("type") == "Point" and isinstance(geom.get("coordinates"), (list, tuple)):
            try:
                lon, lat = float(geom["coordinates"][0]), float(geom["coordinates"][1])
            except (TypeError, ValueError, IndexError):
                lon = lat = None
        if lat is None or lon is None:
            continue

        uid = _make_unique_id(lon, lat, p)
        key = ("alaska_webb", uid)
        if key in seen:
            log.debug("permafrost_thaw: dedup-skip on duplicate id %s", uid)
            continue
        seen.add(key)

        imagery = " · ".join(x for x in (
            _clean(p.get("Imagery")), _clean(p.get("ImageryDates")),
            _clean(p.get("ImageryResolution_meters")),
        ) if x) or None

        rows.append({
            "source": "alaska_webb",
            "unique_id": uid,
            "feature_name": _clean(p.get("FeatureName")),
            "feature_type": _clean(p.get("FeatureType")),
            "feature_category": _clean(p.get("FeatureCategory")),
            "thaw_type": (_clean(p.get("ThawType")) or "").lower() or None,
            "data_source_type": _clean(p.get("DataSourceType")),
            "authors": _clean(p.get("Authors")),
            "source_doi": _clean(p.get("DOI")),
            "imagery": imagery,
            "lat": lat,
            "lon": lon,
        })
    return rows
