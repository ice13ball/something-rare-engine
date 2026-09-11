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

`fields=` — every name here was probed against the live API and confirmed to
return data. ⛔ The API only echoes fields it recognises BY EXACT NAME; an
unknown name is silently dropped, not an error, so a typo costs a whole column
with an HTTP 200 and no log line.

⚠️ The REQUEST name and the RESPONSE key are different things, and the request
name is not guessable from the response. Measured 2026-09-09:

  request name   response key                        non-empty / 5,795
  ------------   ---------------------------------   -----------------
  deplLat/Lon    deployment.latitude / .longitude    5,795
  deplDate       deployment.date                     5,789
  deplShip       deployment.ship.name                2,764
  wigosId        identifiers.wigos_id                5,063
  country        program.country.name                5,792
  sensors        sensor_lists.models                 4,113
  model          model.name                          5,795
  status         status.name                         5,795
  age            age (string, "NaN" when unknown)      556

⛔ Asking for `deployment`, `identifiers`, `program` or `sensor_lists` — the
RESPONSE key names — returns nothing. Verified 2026-09-09: a request built
from response names came back carrying only `model` and `status`.

⛔ These also return NOTHING, silently, with HTTP 200 — do not add them:
  deploymentDate, ptfDepl.deplDate, startDate, obsDate, ptfDepl, agency,
  variables, masterProgram, manufacturer, telecom, ptfDepth, waterDepth,
  wmo, serialNumber

Always empty in this feed, so nothing is lost by not storing them:
  program.name, model.manufacturer.name (0 of 5,795 each).

Exactly one sentinel has been observed in this feed: `1900-01-01`, on a
nameless CLOSED platform (ref 2300495_001). Rejected to NULL here and counted
in the return value's `_sentinel_count` marker (popped by the caller before
building station dicts — see `fetch_oceansites_stations`).

License: OceanOPS data is publicly available under the WMO data policy.
Contact: Thomas (OceanOPS) — prototype endpoint built specifically for Abyssal Claims.
"""
import logging
import math

import httpx

log = logging.getLogger(__name__)

_OCEANOPS_URL = (
    "https://www.ocean-ops.org/api/data/oceanjson/platforms"
    "?pageSize=100000"
    "&fields=ref,name,deplLat,deplLon,wigosId,status,age,model,deplDate"
    ",country,sensors,deplShip"
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


def _finite_coord(v) -> float | None:
    """A coordinate is a finite float or it is nothing.

    ⛔ OceanOPS spells an unknown position as the STRING "NaN" — 37 of 5,795
    deployments on 2026-09-11 — the same convention this file already guards
    for `age`. `float("NaN")` is not None and is not 0, so the string walked
    through the None-or-null-island test below, into a NOT NULL float8 column
    as a real NaN. PostGIS built POINT(NaN NaN), json.dumps wrote a bare NaN,
    and every browser refused the whole layer with "Unexpected token 'N'".
    The map showed "OceanSITES Moorings unavailable" while the endpoint
    answered 200.
    """
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


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
    deployments: list[dict] = []
    sentinel_count = 0

    for r in records:
        raw_ref = r.get("ref") or ""
        if not raw_ref:
            continue

        depl = r.get("deployment") or {}
        lat = depl.get("latitude")
        lon = depl.get("longitude")

        # Strip _NNN redeployment suffix to get canonical base ref
        if "_" in raw_ref:
            base_ref, suffix = raw_ref.rsplit("_", 1)
            deploy_num = int(suffix) if suffix.isdigit() else 0
        else:
            base_ref, deploy_num = raw_ref, 0

        status_name = (r.get("status") or {}).get("name") or "UNKNOWN"
        raw_age = r.get("age")
        age_days = float(raw_age) if isinstance(raw_age, (int, float)) and str(raw_age) != "NaN" else None
        station_name = r.get("name") or base_ref
        model_name = (r.get("model") or {}).get("name") or None
        wigos_id = (r.get("identifiers") or {}).get("wigos_id") or None
        country = ((r.get("program") or {}).get("country") or {}).get("name") or None
        sensor_models = (r.get("sensor_lists") or {}).get("models") or None
        deploy_ship = ((depl.get("ship") or {}).get("name")) or None

        deploy_date = _parse_deploy_date(r)
        if deploy_date is None and depl.get("date"):
            # depl.get("date") was truthy but _parse_deploy_date rejected it —
            # that only happens for the sentinel.
            sentinel_count += 1

        # ⛔ (0,0) is a PLACEHOLDER, not a position in the Gulf of Guinea.
        # 23 of 5,795 records carry it (measured 2026-09-09; none is missing
        # lat/lon outright). The deployment row is still kept — the platform,
        # its date, ship, WIGOS id and instruments are all real — but its
        # coordinates are NULLed and the reason recorded, so "we do not know
        # where this was" never renders as a point off West Africa.
        lat = _finite_coord(lat)
        lon = _finite_coord(lon)
        null_island = (lat == 0 and lon == 0)
        has_position = lat is not None and lon is not None and not null_island

        # ⛔ EVERY source record becomes a deployment row. 4,735 of the 5,795
        # carry an _NNN suffix and the station table keeps only the highest per
        # base ref — one mooring (5100007) has 61 deployments spanning
        # 1988-05-27 to 2026-03-27, and each one has its OWN WIGOS identifier
        # (0-22000-<n>-<base>), its own ship and its own position; 31 base refs
        # hold deployments more than 1 degree apart, the widest 7.9 degrees.
        # Collapsing them is right for the map; discarding them is not.
        deployments.append({
            "ref":           raw_ref,
            "base_ref":      base_ref,
            "deploy_num":    deploy_num,
            "name":          station_name,
            "lat":           lat if has_position else None,
            "lon":           lon if has_position else None,
            "position_flag": None if has_position else ("null-island" if null_island else "missing"),
            "status":        status_name,
            "network":       _network_from_ref(base_ref),
            "deploy_date":   deploy_date,
            "deploy_ship":   deploy_ship,
            "age_days":      age_days,
            "model":         model_name,
            "wigos_id":      wigos_id,
            "country":       country,
            "sensor_models": sensor_models,
            "oceanops_id":   r.get("id"),
        })

        # The station table stays one row per base ref, positioned — that is
        # what the map, the panel and the SEO pages consume, and none of them
        # changed. A record without a usable position cannot be a map point.
        if not has_position:
            continue

        # Keep the record with the highest deployment number
        existing = best.get(base_ref)
        if existing is None or deploy_num > existing["_deploy_num"]:
            best[base_ref] = {
                "ref":         base_ref,
                "name":        station_name,
                "lat":         lat,
                "lon":         lon,
                "status":      status_name,
                "network":     _network_from_ref(base_ref),
                "deploy_date": deploy_date,
                "age_days":    age_days,
                "model":       model_name,
                "wigos_id":    wigos_id,
                "country":     country,
                "sensor_models": sensor_models,
                "deploy_ship": deploy_ship,
                "_deploy_num": deploy_num,
            }

    for st in best.values():
        st["deployment_count"] = sum(1 for d in deployments if d["base_ref"] == st["ref"])
    stations = [{k: v for k, v in s.items() if k != "_deploy_num"} for s in best.values()]
    log.info(
        "oceansites: fetched %d stations from OceanOPS (%d statuses collapsed from %d raw records; "
        "%d deployment rows kept; %d sentinel deploy dates rejected to NULL; "
        "%d records without a usable position)",
        len(stations), len({s["status"] for s in stations}), len(records),
        len(deployments), sentinel_count,
        sum(1 for d in deployments if d["position_flag"]),
    )
    global last_sentinel_count, last_deployments
    last_sentinel_count = sentinel_count
    last_deployments = deployments
    return stations


# Set by the most recent fetch_oceansites_stations() call — the simplest way
# for sync_oceansites() to log the sentinel-rejection count without changing
# this function's return type (a list of station dicts, as domains/sensors.py
# already expects).
last_sentinel_count: int = 0

# Every source record from the most recent fetch, one dict per DEPLOYMENT —
# 5,795 of them against the 1,072 station rows the function returns. Same
# idiom as last_sentinel_count above: the return type stays the list of
# station dicts domains/sensors.py already expects, and one HTTP call feeds
# both tables.
# ⛔ Read it in the SAME call as fetch_oceansites_stations(); it is overwritten
# by the next fetch, and reading a stale value would write one sync's
# deployments against another's stations.
last_deployments: list[dict] = []
