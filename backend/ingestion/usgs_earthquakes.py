# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Fetch recent earthquakes from the USGS FDSN Event Web Service.

Fetches all M≥3 events globally for the past 30 days and upserts them into
``usgs_earthquakes``. No authentication required — data is public domain (CC0).

Gotcha: USGS ``properties.time`` is epoch **milliseconds**, not seconds.
Divide by 1000 before converting to datetime.

Reference: https://earthquake.usgs.gov/fdsnws/event/1/
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

log = logging.getLogger(__name__)

_FDSN_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"


async def fetch_usgs_earthquakes(
    min_magnitude: float = 3.0,
    lookback_days: int = 30,
) -> list[dict[str, Any]]:
    """Return list of earthquake dicts ready for DB upsert.

    Each dict has: usgs_id, occurred_at (datetime, UTC), magnitude, depth_km, place, lat, lon.
    Returns [] on any fetch or parse error.
    """
    start = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    params = {
        "format":       "geojson",
        "starttime":    start,
        "minmagnitude": str(min_magnitude),
        "orderby":      "time-asc",
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(_FDSN_URL, params=params, follow_redirects=True)
            r.raise_for_status()
            payload = r.json()
    except Exception as exc:
        log.warning("USGS FDSN fetch failed: %s", exc)
        return []

    out: list[dict[str, Any]] = []
    for feat in payload.get("features", []):
        props = feat.get("properties", {})
        geom  = feat.get("geometry", {})
        usgs_id = feat.get("id")
        if not usgs_id:
            continue
        coords = geom.get("coordinates")
        if not coords or len(coords) < 2:
            continue
        lon, lat = float(coords[0]), float(coords[1])
        depth_km = float(coords[2]) if len(coords) > 2 else None
        # time is epoch milliseconds
        ts_ms = props.get("time")
        if ts_ms is None:
            continue
        occurred_at = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc)
        # ⛔ `mag` alone is not a magnitude. USGS says WHICH SCALE it used, and
        # the scales are not interchangeable. Measured over the live M>=3 feed
        # on 2026-09-10 (1,577 events): mb 1,048 · ml 328 · mww 96 · md 82 ·
        # mwr 11 · mw 7. Printing "M4.2" with no scale states a number the feed
        # never states on its own.
        #
        # `status` separates a reviewed solution from an automatic one — 1,572
        # reviewed against 5 automatic in that same window, so it is rare and
        # exactly the case a reader would want flagged.
        #
        # `updated` is USGS's own revision stamp, present on 100% of events.
        upd_ms = props.get("updated")
        out.append({
            "usgs_id":    usgs_id,
            "occurred_at": occurred_at,
            "magnitude":  props.get("mag"),
            "mag_type":   (props.get("magType") or "").strip() or None,
            "status":     (props.get("status") or "").strip() or None,
            "updated_at": (datetime.fromtimestamp(int(upd_ms) / 1000, tz=timezone.utc)
                           if upd_ms is not None else None),
            "depth_km":   depth_km,
            "place":      props.get("place", ""),
            "lat":        lat,
            "lon":        lon,
        })

    log.debug("USGS FDSN: %d events fetched", len(out))
    return out
