# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Fetch Ocean Networks Canada observatory station locations from Oceans 3.0 API.

API docs: https://wiki.oceannetworks.ca/spaces/O2A/pages/49447542/API+Guide
Token: set ONC_TOKEN env var (register free at https://data.oceannetworks.ca/Registration)
License: CC BY 4.0
"""
import logging
import os
import httpx

log = logging.getLogger(__name__)

ONC_BASE = "https://data.oceannetworks.ca/api"
ONC_TOKEN = os.getenv("ONC_TOKEN", "")

# Only pull locations that have real oceanographic instruments.
# AIS receivers (shore-based ship-tracking stations) are excluded — they
# are not observatories and produce no oceanographic data relevant to this map.
_OCEANOGRAPHIC_CATEGORIES = [
    "CTD",
    "OXYSENSOR",
]


async def fetch_onc_locations() -> list[dict]:
    """Fetch ONC observatory locations that have at least one oceanographic sensor.

    Queries each target device category for the locations that carry it, then
    deduplicates. This excludes the ~1,800 AIS shore stations that the plain
    `locations?method=get` call returns.

    Returns list of dicts: location_code, name, lat, lon, depth_m, description.
    """
    if not ONC_TOKEN:
        log.warning("ONC_TOKEN not set — skipping ONC ingestion")
        return []

    seen: set[str] = set()
    locations: list[dict] = []

    async with httpx.AsyncClient(timeout=30) as client:
        for category in _OCEANOGRAPHIC_CATEGORIES:
            try:
                resp = await client.get(
                    f"{ONC_BASE}/locations",
                    params={
                        "method":             "getByDeviceCategory",
                        "deviceCategoryCode": category,
                        "token":              ONC_TOKEN,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                log.warning("onc: category %s fetch failed: %s", category, exc)
                continue

            for item in data:
                code = item.get("locationCode", "")
                if not code or code in seen:
                    continue
                lat = item.get("lat")
                lon = item.get("lon")
                if lat is None or lon is None:
                    continue
                seen.add(code)
                depth = item.get("depth")
                locations.append({
                    "location_code": code,
                    "name":          item.get("locationName", ""),
                    "lat":           float(lat),
                    "lon":           float(lon),
                    "depth_m":       float(depth) if depth is not None else None,
                    "description":   item.get("description", "") or "",
                })

    log.info("onc: fetched %d oceanographic locations (from %d categories)",
             len(locations), len(_OCEANOGRAPHIC_CATEGORIES))
    return locations
