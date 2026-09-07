# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Pure parser for the SIOS Station Data REST catalogue.
Source: https://sios-svalbard.org/rest/stations/data.json (paginated, 15/page).
Only IN-SITU, Open-access, Svalbard-region point records are mappable.
NOTE: the upstream east-bbox key is the typo 'geographic_extent_ectangle_east'.
"""
from __future__ import annotations
import html

# (lat_min, lat_max, lon_min, lon_max)
SVALBARD_BBOX = (74.0, 81.5, -15.0, 40.0)
_MAX_SPAN_DEG = 3.0  # reject bboxes larger than this (basin/global, not a local Svalbard footprint)


def decode_keywords(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [html.unescape(k).strip() for k in raw.split(",") if k.strip()]


def parse_collections(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [c.strip() for c in raw.split(",") if c.strip()]


def _f(row: dict, key: str):
    v = row.get(key)
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def point_from_bbox(row: dict) -> tuple[float, float] | None:
    try:
        n = float(row["geographic_extent_rectangle_north"])
        s = float(row["geographic_extent_rectangle_south"])
        w = float(row["geographic_extent_rectangle_west"])
        # upstream typo key for east:
        e = float(row.get("geographic_extent_ectangle_east",
                          row.get("geographic_extent_rectangle_east")))
    except (KeyError, TypeError, ValueError):
        return None
    if abs(n - s) >= _MAX_SPAN_DEG or abs(e - w) >= _MAX_SPAN_DEG:
        return None
    lat = (n + s) / 2.0
    lon = (e + w) / 2.0
    lat_min, lat_max, lon_min, lon_max = SVALBARD_BBOX
    if not (lat_min <= lat <= lat_max and lon_min <= lon <= lon_max):
        return None
    return lat, lon


def is_mappable(row: dict) -> bool:
    if "In Situ" not in (row.get("activity_type") or ""):
        return False
    if (row.get("access_constraint") or "").strip().lower() != "open":
        return False
    return point_from_bbox(row) is not None


def parse_record(row: dict) -> dict | None:
    pt = point_from_bbox(row)
    if not is_mappable(row) or pt is None:
        return None
    lat, lon = pt
    cols = parse_collections(_f(row, "collection"))
    return {
        "metadata_id": _f(row, "metadata_identifier"),
        "title": _f(row, "title"),
        "abstract": _f(row, "abstract"),
        "is_core_data": "SIOSCD" in cols,
        "collections": cols,
        "activity_type": _f(row, "activity_type"),
        "iso_topic": _f(row, "iso_topic_category"),
        "keywords": decode_keywords(_f(row, "keywords_keyword")),
        "platform_short": _f(row, "platform_short_name"),
        "platform_long": _f(row, "platform_long_name"),
        "platform_url": _f(row, "platform_resource"),
        "institution": _f(row, "data_center_long_name") or _f(row, "personnel_investigator_organisation"),
        "pi_name": _f(row, "personnel_investigator_name"),
        "time_start": _f(row, "temporal_extent_start_date"),
        "time_end": _f(row, "temporal_extent_end_date"),
        "license": _f(row, "use_constraint_identifier"),
        "license_url": _f(row, "use_constraint_resource"),
        "url_http": _f(row, "data_access_url_http"),
        "url_opendap": _f(row, "data_access_url_opendap"),
        "url_wms": _f(row, "data_access_url_ogc_wms"),
        "url_landing": _f(row, "related_url_landing_page"),
        "lat": lat,
        "lon": lon,
    }
