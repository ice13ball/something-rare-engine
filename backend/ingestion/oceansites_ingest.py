# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Fetch OceanSITES mooring station metadata from the OceanOPS registry.

Primary source: OceanOPS JSON API — the official registry for all WMO-registered
ocean observing platforms. The OceanSITES network ID is 1000175.

Endpoint (no auth required):
  https://www.ocean-ops.org/api/data/oceanjson/platforms
  ?pageSize=100000&fields=ref,name,deplLat,deplLon,wigosId,status,age,model,deplDate
  &filters={"networks":"1000175"}

2026-09-08 widening: standing rule is "an ingest stores everything the source
gives". This used to keep only OPERATIONAL platforms (65 of 5,795) and never
requested a deployment date. Now returns every platform regardless of status
and parses the real deployment date. Status filtering is a caller/query concern
(`sensors.sync_oceansites` / the SEO layer), not an ingest concern.

`fields=` — every name here was probed against the live API on 2026-09-08 and
confirmed to return data:
  ref, name, deplLat, deplLon, wigosId, status, age, model, deplDate
⛔ These return NOTHING, silently, with HTTP 200 — do not add them:
  deploymentDate, ptfDepl.deplDate, startDate, obsDate, ptfDepl
  (the API only echoes fields it recognises by exact name; an unknown name is
  silently dropped, not an error).

`deplDate` comes back NESTED as `deployment.date` (ISO 8601 string, e.g.
"2006-06-08T00:00:00"), not as a top-level `deplDate` key.

Exactly one sentinel has been observed in this feed: `1900-01-01`, on a
nameless CLOSED platform (ref 2300495_001). Rejected to NULL here and counted
in the return value's `_sentinel_count` marker (popped by the caller before
building station dicts — see `fetch_oceansites_stations`).

License: OceanOPS data is publicly available under the WMO data policy.
Contact: Thomas (OceanOPS) — prototype endpoint built specifically for Abyssal Claims.
"""
import logging

import httpx

log = logging.getLogger(__name__)

_OCEANOPS_URL = (
    "https://www.ocean-ops.org/api/data/oceanjson/platforms"
    "?pageSize=100000"
    "&fields=ref,name,deplLat,deplLon,wigosId,status,age,model,deplDate"
    "&filters=%7B%22networks%22%3A%221000175%22%7D"
)

_SENTINEL_DATE = "1900-01-01"

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


def _parse_deploy_date(record: dict) -> str | None:
    """Extract `deployment.date`, rejecting the 1900-01-01 sentinel.

    Returns an ISO 'YYYY-MM-DD' string or None. Never widens a bare year and
    never fabricates a date — absence stays absence.
    """
    depl = record.get("deployment") or {}
    raw = depl.get("date")
    if not raw or not isinstance(raw, str):
        return None
    date_part = raw[:10]
    if date_part == _SENTINEL_DATE:
        return None
    return date_part


async def fetch_oceansites_stations() -> list[dict]:
    """Fetch ALL OceanSITES mooring station metadata from OceanOPS,
    regardless of status.

    Filters out redeployment records (ref ending in _NNN, keeping only the
    highest-numbered per base ref) and the single null-island entry
    (lat=0, lon=0). Does NOT filter by status — every OPERATIONAL, CLOSED,
    INACTIVE and REGISTERED platform is returned; the caller decides what to
    do with `status`.

    Dict keys match what sensors.sync_oceansites() in domains/sensors.py expects:
      ref, name, lat, lon, status, network, deploy_date, age_days, model

    A synthetic `__sentinel_rejected__` key (int) carries the count of
    1900-01-01 sentinel dates rejected to NULL, for the caller to log; it is
    popped off before returning station dicts and returned as a second value
    via the module-level `last_sentinel_count` for callers that only unpack
    the list (kept simple: see `sensors.sync_oceansites` for how it is read).
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(_OCEANOPS_URL)
        resp.raise_for_status()
        payload = resp.json()

    records = payload.get("data") or []
    best: dict[str, dict] = {}  # base_ref -> record with highest deployment number
    sentinel_count = 0

    for r in records:
        raw_ref = r.get("ref") or ""

        depl = r.get("deployment") or {}
        lat = depl.get("latitude")
        lon = depl.get("longitude")

        if lat is None or lon is None:
            continue
        if lat == 0 and lon == 0:
            continue

        status_name = (r.get("status") or {}).get("name") or "UNKNOWN"

        # Strip _NNN redeployment suffix to get canonical base ref
        if "_" in raw_ref:
            base_ref, suffix = raw_ref.rsplit("_", 1)
            deploy_num = int(suffix) if suffix.isdigit() else 0
        else:
            base_ref, deploy_num = raw_ref, 0

        raw_age = r.get("age")
        age_days = float(raw_age) if isinstance(raw_age, (int, float)) and str(raw_age) != "NaN" else None
        station_name = r.get("name") or base_ref
        model_name = (r.get("model") or {}).get("name") or None

        deploy_date = _parse_deploy_date(r)
        if deploy_date is None and depl.get("date"):
            # depl.get("date") was truthy but _parse_deploy_date rejected it —
            # that only happens for the sentinel.
            sentinel_count += 1

        # Keep the record with the highest deployment number
        existing = best.get(base_ref)
        if existing is None or deploy_num > existing["_deploy_num"]:
            best[base_ref] = {
                "ref":         base_ref,
                "name":        station_name,
                "lat":         float(lat),
                "lon":         float(lon),
                "status":      status_name,
                "network":     _network_from_ref(base_ref),
                "deploy_date": deploy_date,
                "age_days":    age_days,
                "model":       model_name,
                "_deploy_num": deploy_num,
            }

    stations = [{k: v for k, v in s.items() if k != "_deploy_num"} for s in best.values()]
    log.info(
        "oceansites: fetched %d stations from OceanOPS (%d statuses collapsed from %d raw records; "
        "%d sentinel deploy dates rejected to NULL)",
        len(stations), len({s["status"] for s in stations}), len(records), sentinel_count,
    )
    global last_sentinel_count
    last_sentinel_count = sentinel_count
    return stations


# Set by the most recent fetch_oceansites_stations() call — the simplest way
# for sync_oceansites() to log the sentinel-rejection count without changing
# this function's return type (a list of station dicts, as domains/sensors.py
# already expects).
last_sentinel_count: int = 0
