# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Neutral impact-report data shaper (v2).

Pure data-shaping. Given pre-fetched profiles, nearest-claim distance
rows, and plume-path rows, returns the neutral-v1 JSON dict.

No SQL, no DB connection, no I/O. Independent of services/impact_scoring.py
so v1 may evolve (or be deleted) without affecting v2.

"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "neutral-v1"

# Depth-adaptive p5 baselines. Replicated from v1 (services/impact_scoring.py)
# so v2 stays independent — abyssal oxygen is naturally low (~100 µmol/kg);
# a flat 165 baseline would flag normal deep water as anomalous.
def _oxygen_p5_at_depth(depth_m: float | None) -> float:
    if depth_m is None or depth_m < 200:
        return 150.0   # surface: well-oxygenated expected
    if depth_m < 1000:
        return 90.0    # OMZ: some depletion natural, <90 is hypoxic
    return 60.0        # abyssal: <60 genuinely concerning


def _ph_p5_at_depth(depth_m: float | None) -> float:
    if depth_m is None or depth_m < 200:
        return 7.95    # surface: normal seawater 8.0–8.3
    if depth_m < 1000:
        return 7.75    # mid-water: naturally lower due to CO₂
    return 7.60        # deep: <7.6 is alarming


_OXYGEN_SOURCE = "v1 depth-adaptive threshold: 150 µmol/kg <200m; 90 200-1000m; 60 >1000m"
_PH_SOURCE     = "v1 depth-adaptive threshold: 7.95 <200m; 7.75 200-1000m; 7.60 >1000m"


def _baseline_for(prop: str, depth_m: float | None) -> tuple[float, str, str] | None:
    """Return (p5_value, unit, source) for the property at the given depth,
    or None if the property isn't recognised."""
    if prop == "oxygen":
        return (_oxygen_p5_at_depth(depth_m), "µmol/kg", _OXYGEN_SOURCE)
    if prop == "ph":
        return (_ph_p5_at_depth(depth_m), "pH units", _PH_SOURCE)
    return None


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in km between two (lon, lat) points."""
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def trail_distance_km(profiles: list[dict]) -> float:
    """Sum great-circle distances along the profile sequence."""
    if len(profiles) < 2:
        return 0.0
    total = 0.0
    for a, b in zip(profiles, profiles[1:]):
        total += haversine_km(a["lon"], a["lat"], b["lon"], b["lat"])
    return round(total, 1)


def below_baseline(prop: str, value: float | None, depth_m: float | None) -> bool:
    """True iff the value is below the property's depth-conditioned p5 baseline.
    Public — also imported by routers/reports_v2.py for dossier aggregation."""
    if value is None:
        return False
    baseline = _baseline_for(prop, depth_m)
    if baseline is None:
        return False
    return value < baseline[0]


def _measurement_from_profile(profile: dict, prop: str) -> dict | None:
    """Return a neutral measurement dict for one (profile, property), or None
    if the profile has no value for that property or the value is not below baseline."""
    value = profile.get(prop)
    depth_m = profile.get("depth_m")
    if not below_baseline(prop, value, depth_m):
        return None
    baseline = _baseline_for(prop, depth_m)
    if baseline is None:
        return None
    p5, unit, source = baseline
    attribution = []
    if profile.get("nearest_claim_id") and profile.get("distance_to_claim_km") is not None:
        attribution.append({
            "concession_id":  profile["nearest_claim_id"],
            "distance_km":    round(float(profile["distance_to_claim_km"]), 2),
        })
    return {
        "id":                  f"msr-{prop}-{profile['profile_id']}",
        "type":                prop,                       # no _alarm suffix
        "value":               float(value),
        "unit":                unit,
        "baseline_p5":         p5,
        "baseline_source":     source,
        "delta_from_baseline": round(float(value) - p5, 4),
        "observed_at":         profile["date"],
        "lat":                 float(profile["lat"]),
        "lon":                 float(profile["lon"]),
        "depth_m":             depth_m,
        "attributed_to":       attribution,
    }


def _build_measurements(profiles: list[dict]) -> list[dict]:
    """Flatten profiles into a chronological measurement list (oldest first)."""
    out: list[dict] = []
    for p in sorted(profiles, key=lambda r: r["date"]):
        for prop in ("oxygen", "ph"):
            m = _measurement_from_profile(p, prop)
            if m:
                out.append(m)
    return out


def _build_plume_backtracks(plume_rows: list[dict]) -> list[dict]:
    """Project DB plume rows into neutral shape."""
    out = []
    for pr in plume_rows:
        out.append({
            "id":                     f"plm-{pr['profile_id']}",
            "intersects_concession":  pr.get("intersects_concession"),
        })
    return out


def _build_dossiers(dossier_rows: list[dict]) -> list[dict]:
    """Sort dossiers by min_distance_km ASCENDING (nearest first).
    dossier_rows is a list of dicts pre-aggregated by the router; this
    function only re-shapes and sorts them.
    """
    shaped = []
    for d in dossier_rows:
        shaped.append({
            "claim": {
                "concession_id":   d["concession_id"],
                "contractor_name": d.get("contractor_name") or "Unknown",
                "area_km2":        d.get("area_km2"),
            },
            "min_distance_km":              round(float(d["min_distance_km"]), 2),
            "attributed_measurement_count": int(d.get("attributed_measurement_count", 0)),
            "attributed_plume_count":       int(d.get("attributed_plume_count", 0)),
            "profiles_within_50km":         int(d.get("profiles_within_50km", 0)),
        })
    shaped.sort(key=lambda x: x["min_distance_km"])
    return shaped


def _build_headline(platform_id: str, distance_km: float,
                    measurement_count: int, concession_count: int) -> str:
    """Factual, count-based. No verdict words."""
    return (
        f"Argo float {platform_id} — "
        f"{distance_km:.0f} km drift, "
        f"{measurement_count} attributed measurement"
        f"{'s' if measurement_count != 1 else ''} "
        f"across {concession_count} concession"
        f"{'s' if concession_count != 1 else ''}"
    )


def build_neutral_report(
    *,
    platform_id: str,
    profiles: list[dict],
    plume_rows: list[dict],
    dossier_rows: list[dict],
) -> dict:
    """Assemble the full neutral-v1 response.

    Args:
        platform_id: Argo float identifier.
        profiles: rows with keys profile_id, date (ISO string), lon, lat,
                  depth_m, oxygen, ph, nearest_claim_id, distance_to_claim_km.
        plume_rows: rows with profile_id, backtrack_days,
                    intersects_concession, intersect_area_km2.
        dossier_rows: pre-aggregated per-concession dicts with concession_id,
                      contractor_name, area_km2, min_distance_km, and the
                      five count fields.

    Returns:
        Dict matching the neutral-v1 schema (see spec).
    """
    measurements      = _build_measurements(profiles)
    plume_backtracks  = _build_plume_backtracks(plume_rows)
    dossiers          = _build_dossiers(dossier_rows)
    distance_km       = trail_distance_km(profiles)

    if profiles:
        ordered = sorted(profiles, key=lambda r: r["date"])
        date_start = ordered[0]["date"][:10]
        date_end   = ordered[-1]["date"][:10]
    else:
        date_start = date_end = ""

    concessions_within_50km = sum(1 for d in dossiers if d["min_distance_km"] <= 50.0)
    plumes_intersecting = sum(1 for p in plume_backtracks if p.get("intersects_concession"))

    return {
        "platform_id":     platform_id,
        "schema_version":  SCHEMA_VERSION,
        "report_id":       str(uuid.uuid4()),
        "generated_at":    datetime.now(timezone.utc).isoformat(),

        "trail": {
            "date_range_start":   date_start,
            "date_range_end":     date_end,
            "total_distance_km":  distance_km,
            "profile_count":      len(profiles),
        },

        "summary": {
            "measurements_below_baseline_p5":          len(measurements),
            "plume_backtracks_intersecting_concession": plumes_intersecting,
            "concessions_within_50km":                 concessions_within_50km,
        },

        "measurements":      measurements,
        "plume_backtracks":  plume_backtracks,
        "claim_dossiers":    dossiers,

        "headline":          _build_headline(
            platform_id, distance_km, len(measurements), len(dossiers),
        ),
    }
