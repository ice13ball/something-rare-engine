# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Pure data-shaping for neutral concession reports (v2).

No SQL, no I/O. Caller supplies prefetched rows; this module returns
a dict matching schema_version='neutral-v1-concession'.

Editorial guardrail: never emit verdict words (critical/severe/risk_score/
severity/recommend*). The existing backend/scripts/check_neutral_report.py
must exit 0 on any output of this module.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "neutral-v1-concession"

# IUCN category sort order: most-threatened first.
_IUCN_ORDER = {"CR": 0, "EN": 1, "VU": 2, "NT": 3, "LC": 4, "DD": 5, "NE": 6}


def _round1(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return round(float(v), 1)
    except (TypeError, ValueError):
        return None


def _round2(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _build_concession_header(row: dict) -> dict:
    return {
        "isa_id":         row["isa_id"],
        "contractor":     row.get("contractor_name"),
        "resource_type":  row.get("resource_type"),
        "area_km2":       _round1(row.get("area_km2")),
        "jurisdiction":   row.get("sponsoring_state") or "International Waters / ISA",
        "issued":         str(row["contract_date"])[:10] if row.get("contract_date") else None,
        "expires":        str(row["expiry_date"])[:10]   if row.get("expiry_date")   else None,
        "centroid_lat":   _round2(row.get("centroid_lat")),
        "centroid_lon":   _round2(row.get("centroid_lon")),
    }


def _build_seamounts(rows: list[dict]) -> list[dict]:
    return [
        {
            "peak_id":        r.get("peak_id"),
            "name":           r.get("name"),
            "summit_depth_m": int(r["summit_depth_m"]) if r.get("summit_depth_m") is not None else None,
            "height_m":       int(r["height_m"])       if r.get("height_m")       is not None else None,
            "area_km2":       _round1(r.get("area_km2")),
            "distance_km":    _round1(r.get("distance_km")),
        }
        for r in rows
    ]


def _build_species(rows: list[dict]) -> list[dict]:
    out = [
        {
            "scientific_name": r.get("scientific_name") or r.get("species"),
            "iucn_category":   r.get("iucn_category") or "NE",
            "record_count":    int(r["record_count"]) if r.get("record_count") is not None else None,
        }
        for r in rows
    ]
    out.sort(key=lambda s: (_IUCN_ORDER.get(s["iucn_category"], 99), s["scientific_name"] or ""))
    return out


def _build_vents(rows: list[dict]) -> list[dict]:
    return [
        {
            "vent_id":     r.get("vent_id") or r.get("id"),
            "name":        r.get("name"),
            "distance_km": _round1(r.get("distance_km")),
            "depth_m":     int(r["depth_m"]) if r.get("depth_m") is not None else None,
        }
        for r in rows
    ]


def _build_plume_attributions(rows: list[dict]) -> list[dict]:
    return [
        {
            "platform_id":           r.get("platform_id"),
            "profile_id":            r.get("profile_id"),
            "profile_date":          r.get("profile_date"),
            "origin_lat":            _round2(r.get("origin_lat")),
            "origin_lon":            _round2(r.get("origin_lon")),
            "speed_cms":             _round1(r.get("speed_cms")),
            "source_dataset":        r.get("source_dataset"),
            "oxygen_umol_kg":        _round1(r.get("oxygen_umol_kg")),
            "ph":                    _round2(r.get("ph")),
            "surface_temp_c":        _round1(r.get("surface_temp_c")),
            "surface_salinity":      _round1(r.get("surface_salinity")),
            "max_depth_m":           int(r["max_depth_m"]) if r.get("max_depth_m") is not None else None,
            "intersects_concession": True,
        }
        for r in rows
    ]


def build_neutral_concession_report(
    *,
    isa_id: str,
    concession_row: dict,
    seamount_rows: list[dict],
    species_rows: list[dict],
    species_inside_count: int | None = 0,
    vent_rows: list[dict],
    plume_rows: list[dict],
    monitoring_float_count: int,
) -> dict:
    """Return a dict matching neutral-v1-concession schema. No I/O.

    species_rows are within ~10 km of the claim (the cache's claim-focused radius);
    species_inside_count is how many distinct species fall strictly inside
    the claim polygon. Surfacing both keeps the count honest.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at":   datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "concession":     _build_concession_header(concession_row),
        "seamounts":      _build_seamounts(seamount_rows),
        "species":        _build_species(species_rows),
        "species_inside_count": None if species_inside_count is None else int(species_inside_count),
        "species_search_radius_km": 10,
        "vents":          _build_vents(vent_rows),
        "plume_attributions": _build_plume_attributions(plume_rows),
        "monitoring_floats":  int(monitoring_float_count),
    }
