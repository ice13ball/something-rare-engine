# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""IMOS (Integrated Marine Observing System, Australia) hydrophone ingest.

Stations: fetched from AODN GeoServer WFS as GeoJSON.
Soundscape: not a first-party aggregated product; returns []. IMOS publishes only
raw .wav files in S3 (data_path is surfaced as portal_url for browsing).

"""
from __future__ import annotations

import logging
from datetime import datetime, date
from typing import Any

import httpx
from ingestion.http_retry import get_with_retry

log = logging.getLogger(__name__)

_STATIONS_URL = (
    "https://geoserver-123.aodn.org.au/geoserver/ows"
    "?service=WFS&version=1.0.0&request=GetFeature"
    "&typeName=imos:anmn_acoustics_map"
    "&outputFormat=application/json"
)
_TIMEOUT = httpx.Timeout(90.0, connect=20.0)


def _parse_iso(value: Any) -> date | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return None


def _safe_float(v: Any) -> float | None:
    if v is None or str(v).strip() == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


async def fetch_imos_stations() -> list[dict[str, Any]]:
    """Fetch IMOS ANMN passive-acoustic deployments as acoustic_stations rows.

    Each WFS feature is one deployment cycle (unique curtin_id). We do NOT roll up
    to site_code in Phase 1 — each deployment is its own station so temporal
    coverage stays visible in the panel.
    """
    rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await get_with_retry(client, _STATIONS_URL, label="imos stations")
        resp.raise_for_status()
        data = resp.json()
    for feat in data.get("features", []):
        p = feat.get("properties") or {}
        curtin_id = p.get("curtin_id")
        if curtin_id is None:
            continue
        # Prefer geometry coordinates; fall back to lat/lon properties if present.
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates") or [None, None]
        lon = _safe_float(coords[0] if coords[0] is not None else p.get("lon"))
        lat = _safe_float(coords[1] if coords[1] is not None else p.get("lat"))
        if lat is None or lon is None:
            continue
        rows.append({
            "station_id":   f"imos:{curtin_id}",
            "source":       "imos",
            "name":         p.get("site_name") or p.get("deployment_name") or f"IMOS {curtin_id}",
            "operator":     "IMOS Australian National Mooring Network",
            "lat":          lat,
            "lon":          lon,
            "depth_m":      _safe_float(p.get("receiver_depth")),
            "deploy_start": _parse_iso(p.get("time_coverage_start")),
            "deploy_end":   _parse_iso(p.get("time_coverage_end")),
            "model":        "Curtin CMST sea noise logger",
            "hz_range_lo":  None,
            "hz_range_hi":  None,
            "portal_url":   p.get("data_path") or None,
        })
    log.info("fetch_imos_stations: %d deployments", len(rows))
    return rows


async def fetch_imos_soundscape(station_id: str, days: int = 90) -> list[dict[str, Any]]:
    """Return [] — IMOS publishes only raw .wav recordings via S3.

    No pre-aggregated SPL / decade-band product is available. Phase 2 could add
    on-the-fly SPL computation from raw audio; out of scope for Phase 1.
    """
    return []
