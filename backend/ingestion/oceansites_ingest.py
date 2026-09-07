# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Fetch OceanSITES mooring station locations from the OceanOPS registry.

Primary source: OceanOPS JSON API — the official registry for all WMO-registered
ocean observing platforms. The OceanSITES network ID is 1000175.

Endpoint (no auth required):
  https://www.ocean-ops.org/api/data/oceanjson/platforms
  ?pageSize=100000&fields=ref,deplLat,deplLon,wigosId,status&filters={"networks":"1000175"}

Returns only OPERATIONAL primary mooring stations (redeployments with _NNN suffix and
non-OPERATIONAL status excluded). NDBC observation fetching in domains/sensors.py
further filters to stations with live data.

License: OceanOPS data is publicly available under the WMO data policy.
Contact: Thomas (OceanOPS) — prototype endpoint built specifically for Abyssal Claims.
"""
import logging
import httpx

log = logging.getLogger(__name__)

_OCEANOPS_URL = (
    "https://www.ocean-ops.org/api/data/oceanjson/platforms"
    "?pageSize=100000"
    "&fields=ref,name,deplLat,deplLon,wigosId,status,age,model"
    "&filters=%7B%22networks%22%3A%221000175%22%7D"
)

# WMO ref-prefix → OceanSITES sub-network label.
# Matches the filter keys used in Map3DControls.tsx.
# 32xxx/33xxx = PIRATA (tropical Atlantic, France/Brazil co-managed)
# 48xxx/49xxx = RAMA (Indian Ocean)
# All others → generic "OceanSITES" bucket.
_PREFIX_NETWORK: list[tuple[str, str]] = [
    ("32", "OceanSITES/PIRATA"),
    ("33", "OceanSITES/PIRATA"),
    ("48", "OceanSITES/RAMA"),
    ("49", "OceanSITES/RAMA"),
]


def _network_from_ref(ref: str) -> str:
    for prefix, network in _PREFIX_NETWORK:
        if ref.startswith(prefix):
            return network
    return "OceanSITES"


async def fetch_oceansites_stations() -> list[dict]:
    """Fetch active OceanSITES mooring station metadata from OceanOPS.

    Filters out redeployment records (ref ending in _NNN) and the single
    null-island entry (lat=0, lon=0). Returns ~1,053 primary stations.

    Dict keys match what sensors.sync_oceansites() in domains/sensors.py expects:
      ref, name, lat, lon, status, network, deploy_date
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(_OCEANOPS_URL)
        resp.raise_for_status()
        payload = resp.json()

    records = payload.get("data") or []
    stations: list[dict] = []

    # Active moorings are represented by their latest redeployment record (_NNN suffix).
    # We keep only OPERATIONAL records, strip the suffix to get the canonical base ref,
    # and deduplicate — keeping the highest-numbered deployment per base ref.
    best: dict[str, dict] = {}  # base_ref -> record with highest deployment number

    for r in records:
        raw_ref = r.get("ref") or ""

        # Only OPERATIONAL stations
        status_name = (r.get("status") or {}).get("name", "")
        if status_name != "OPERATIONAL":
            continue

        depl = r.get("deployment") or {}
        lat = depl.get("latitude")
        lon = depl.get("longitude")

        if lat is None or lon is None:
            continue
        if lat == 0 and lon == 0:
            continue

        # Strip _NNN redeployment suffix to get canonical base ref
        if "_" in raw_ref:
            base_ref, suffix = raw_ref.rsplit("_", 1)
            deploy_num = int(suffix) if suffix.isdigit() else 0
        else:
            base_ref, deploy_num = raw_ref, 0

        # Keep the record with the highest deployment number
        existing = best.get(base_ref)
        if existing is None or deploy_num > existing["_deploy_num"]:
            raw_age = r.get("age")
        age_days = float(raw_age) if isinstance(raw_age, (int, float)) and str(raw_age) != "NaN" else None
        station_name = r.get("name") or base_ref
        model_name = (r.get("model") or {}).get("name") or None

        best[base_ref] = {
                "ref":         base_ref,
                "name":        station_name,
                "lat":         float(lat),
                "lon":         float(lon),
                "status":      "OPERATIONAL",
                "network":     _network_from_ref(base_ref),
                "deploy_date": None,
                "age_days":    age_days,
                "model":       model_name,
                "_deploy_num": deploy_num,
            }

    stations = [{k: v for k, v in s.items() if k != "_deploy_num"} for s in best.values()]
    log.info("oceansites: fetched %d operational stations from OceanOPS", len(stations))
    return stations
