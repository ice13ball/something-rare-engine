# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""NOAA NEFSC (Northeast Fisheries Science Center) hydrophone ingest.

Stations: discovered dynamically from the public Google Cloud Storage bucket
`noaa-passive-bioacoustic` (`nefsc/audio/` prefix). Same bucket and access
pattern as NRS and SanctSound — only the prefix and a few JSON-schema
deltas differ.

Three projects ingested:
- `monh`   — Monhegan Island SoundTrap (Gulf of Maine, 1 site, recent 2021)
- `pmanan` — Petit Manan SoundTrap (Gulf of Maine, 1 site, recent 2020-2021)
- `sbnms`  — Stellwagen Bank NMS Cornell MARU array (historic 2007-2010,
             multi-channel ensembles producing ~21 unique seafloor positions
             after rounding to 0.1 degree / ~10 km)

Skipped:
- `nefsc_sne` (Cox Ledge, Massachusetts–Rhode Island) — only audio uploaded,
  no metadata JSON in the bucket as of bench day.

Three schema deltas vs NRS/SanctSound (all handled below):
1. SBNMS deployments publish `DEPLOY_LAT` / `DEPLOY_LON` as a list of N
   coordinates (one per MARU channel in the ensemble), not a scalar. List
   length varies per deployment (1–10). Each list element is a separate
   recorder location.
2. SBNMS longitude uses the 0–360 convention (e.g. 289.5 = -70.5). Apply
   `lon = raw_lon - 360 if raw_lon > 180 else raw_lon`.
3. `INSTRUMENT_TYPE` is at the top level of the JSON, not nested per-channel
   like SanctSound's CHANNELS structure.

Cornell-built MARUs at Stellwagen are part of NEFSC's archive — credit
Cornell inline in the `operator` string for SBNMS rows. No separate
`cornell` source enum.

Soundscape: not a first-party aggregated SPL/decade-band product. Returns
[] for the soundscape endpoint, just like NRS/SanctSound — Phase 3 NetCDF
ingestion would handle it.

for endpoint discovery details.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

import httpx
from ingestion.http_retry import get_with_retry

log = logging.getLogger(__name__)

_BUCKET = "noaa-passive-bioacoustic"
_GCS_LIST = f"https://storage.googleapis.com/storage/v1/b/{_BUCKET}/o"
_GCS_OBJECT = f"https://storage.googleapis.com/{_BUCKET}"
_TIMEOUT = httpx.Timeout(60.0, connect=20.0)

# Three projects with metadata JSON available. `nefsc_sne` is skipped — bench
# 2026-05-11 confirmed audio-only (no metadata JSON yet).
_NEFSC_PROJECTS = ["monh", "pmanan", "sbnms"]

# SBNMS MARU clusters: round positions to this many decimal places (~0.1°
# ≈ ~10 km) to produce the canonical ~21 unique seafloor positions called
# out in the bench notes. Finer rounding (2 dp = ~1 km) produces ~78 distinct
# positions, which over-represents mooring drift / cable-cycle re-positioning
# of the same instrument site.
_SBNMS_CLUSTER_DP = 1


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _parse_iso_date(value: Any) -> date | None:
    """Parse an ISO date or datetime string into a date. Tolerates 'T',
    trailing 'Z', space separators, bare YYYY-MM-DD."""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _get_ci(d: dict[str, Any], *keys: str) -> Any:
    """Case-insensitive nested getter — defensive across publish-year variants."""
    if not isinstance(d, dict):
        return None
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        if k in cur:
            cur = cur[k]
            continue
        lk = k.lower()
        match = None
        for kk in cur:
            if kk.lower() == lk:
                match = kk
                break
        if match is None:
            return None
        cur = cur[match]
    return cur


def _normalize_longitude(raw: float) -> float:
    """SBNMS publishes 0-360 longitude convention; normalize to -180/180."""
    return raw - 360 if raw > 180 else raw


async def _list_all(client: httpx.AsyncClient, prefix: str, delimiter: str | None = "/") -> tuple[list[str], list[dict[str, Any]]]:
    """Walk GCS object-listing pagination, return (prefixes, items)."""
    prefixes: list[str] = []
    items: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        params: dict[str, str] = {"prefix": prefix, "maxResults": "200"}
        if delimiter:
            params["delimiter"] = delimiter
        if page_token:
            params["pageToken"] = page_token
        resp = await get_with_retry(client, _GCS_LIST, params=params, label="nefsc listing")
        resp.raise_for_status()
        data = resp.json()
        prefixes.extend(data.get("prefixes") or [])
        items.extend(data.get("items") or [])
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return prefixes, items


async def _fetch_json(client: httpx.AsyncClient, object_name: str) -> dict[str, Any] | None:
    """Download a JSON object by GCS name. Returns None on error so one bad
    file doesn't sink the sync."""
    url = f"{_GCS_OBJECT}/{object_name}"
    try:
        resp = await get_with_retry(client, url, label="nefsc object")
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.warning("acoustic_nefsc_ingest: fetch %s failed: %s", url, exc)
        return None


async def _list_deployment_metadata_jsons(client: httpx.AsyncClient, dep_prefix: str) -> list[str]:
    """List candidate metadata JSON file names inside `{dep_prefix}metadata/`.
    Skips `_deployments*.json/.xml` index files in favour of the primary
    `NEFSC_*` JSON.
    """
    meta_prefix = f"{dep_prefix}metadata/"
    try:
        _, items = await _list_all(client, meta_prefix, delimiter=None)
    except Exception as exc:
        log.warning("acoustic_nefsc_ingest: list %s failed: %s", meta_prefix, exc)
        return []
    primary: list[str] = []
    for item in items:
        name = item.get("name") or ""
        lname = name.lower()
        if not lname.endswith(".json"):
            continue
        # Skip composite "*_deployments.json" indexes if present
        if "deployments" in lname.rsplit("/", 1)[-1]:
            continue
        primary.append(name)
    return primary


def _first_or_scalar(value: Any) -> Any:
    """If value is a (non-empty) list, return its first element. Otherwise
    return as-is. Used for fields like DEPLOY_BOTTOM_DEPTH which arrive as
    arrays for SBNMS but scalars for monh/pmanan."""
    if isinstance(value, list):
        if not value:
            return None
        return value[0]
    return value


def _expand_positions(meta: dict[str, Any], project: str) -> list[dict[str, Any]]:
    """Extract one record per recorder position from a deployment JSON.

    For `monh` and `pmanan` the JSON publishes scalar lat/lon → one record.
    For `sbnms` the JSON publishes parallel lists of lat/lon/bottom_depth
    (one entry per MARU in the ensemble) → N records, longitude normalized
    from 0-360 to -180/180.
    """
    raw_lat = _get_ci(meta, "DEPLOYMENT", "DEPLOY_LAT")
    raw_lon = _get_ci(meta, "DEPLOYMENT", "DEPLOY_LON")
    raw_inst_depth = _get_ci(meta, "DEPLOYMENT", "DEPLOY_INSTRUMENT_DEPTH")
    raw_bot_depth = _get_ci(meta, "DEPLOYMENT", "DEPLOY_BOTTOM_DEPTH")

    deploy_start = _parse_iso_date(_get_ci(meta, "DEPLOYMENT", "DEPLOYMENT_TIME")) \
        or _parse_iso_date(_get_ci(meta, "DEPLOYMENT", "AUDIO_START"))
    deploy_end = _parse_iso_date(_get_ci(meta, "DEPLOYMENT", "RECOVERY_TIME")) \
        or _parse_iso_date(_get_ci(meta, "DEPLOYMENT", "AUDIO_END"))

    instrument_type = _get_ci(meta, "INSTRUMENT_TYPE") \
        or _get_ci(meta, "PLATFORM_NAME")
    instrument_type = str(instrument_type).strip() if instrument_type else None

    site_alias = None
    aliases = _get_ci(meta, "SITE_ALIASES")
    if isinstance(aliases, list) and aliases:
        first = aliases[0]
        if isinstance(first, str) and first.strip():
            site_alias = first.strip()
    site = _get_ci(meta, "SITE")
    site = str(site).strip() if site else None

    records: list[dict[str, Any]] = []

    def _pkg(lat_f: float, lon_f: float, depth_v: Any, bottom_v: Any) -> dict[str, Any]:
        # ⛔ DEPLOY_INSTRUMENT_DEPTH has no public field dictionary we could find
        # for this bucket's metadata JSON. abs() is OUR assumption, not a
        # documented source convention: a genuine height above the seafloor
        # would be silently turned into a depth. Recorded rather than resolved -
        # see docs/methods/data-passthrough.md.
        depth_n = _safe_float(depth_v)
        depth_m = abs(depth_n) if depth_n is not None else None
        # ⛔ Same gap for DEPLOY_BOTTOM_DEPTH - no documented sign convention found.
        bottom_n = _safe_float(bottom_v)
        bottom_m = abs(bottom_n) if bottom_n is not None else None
        # Fall back to bottom depth when instrument depth absent (typical for
        # SBNMS MARUs — bottom-mounted, so instrument depth == bottom depth).
        if depth_m is None and bottom_m is not None:
            depth_m = bottom_m
        return {
            "lat":             lat_f,
            "lon":             lon_f,
            "depth_m":         depth_m,
            "deploy_start":    deploy_start,
            "deploy_end":      deploy_end,
            "instrument_type": instrument_type,
            "site":            site,
            "site_alias":      site_alias,
        }

    if isinstance(raw_lat, list) and isinstance(raw_lon, list):
        # Parallel arrays — SBNMS case. Lengths can be 1..10.
        n = min(len(raw_lat), len(raw_lon))
        depths: list[Any] = raw_inst_depth if isinstance(raw_inst_depth, list) else [raw_inst_depth] * n
        bottoms: list[Any] = raw_bot_depth if isinstance(raw_bot_depth, list) else [raw_bot_depth] * n
        for i in range(n):
            lat_f = _safe_float(raw_lat[i])
            lon_raw = _safe_float(raw_lon[i])
            if lat_f is None or lon_raw is None:
                continue
            lon_f = _normalize_longitude(lon_raw) if project == "sbnms" else lon_raw
            d_val = depths[i] if i < len(depths) else None
            b_val = bottoms[i] if i < len(bottoms) else None
            records.append(_pkg(lat_f, lon_f, d_val, b_val))
    else:
        lat_f = _safe_float(raw_lat)
        lon_raw = _safe_float(raw_lon)
        if lat_f is None or lon_raw is None:
            return records
        lon_f = _normalize_longitude(lon_raw) if project == "sbnms" else lon_raw
        d_val = _first_or_scalar(raw_inst_depth)
        b_val = _first_or_scalar(raw_bot_depth)
        records.append(_pkg(lat_f, lon_f, d_val, b_val))

    return records


def _cluster_key_for(project: str, lat: float, lon: float) -> str:
    """Return a stable station_id-suffix for one recorder position. For
    `sbnms` we round to 0.1° (~10 km) to collapse mooring-cycle drift into
    one MARU position. Monhegan / PManan have single sites so the cluster
    key is fixed."""
    if project == "sbnms":
        # Round latitude to 0.1 (~11 km) and longitude to 0.1 (~8 km at 42°N)
        return f"{round(lat, _SBNMS_CLUSTER_DP):.1f}_{round(lon, _SBNMS_CLUSTER_DP):.1f}"
    return project  # single-site projects


async def _fetch_project(client: httpx.AsyncClient, project: str) -> list[dict[str, Any]]:
    """List metadata JSONs under `nefsc/audio/{project}/` and aggregate one
    row per cluster (per MARU position for SBNMS, single site for the
    others). Per-deployment / per-JSON try/except keeps a partial outage from
    sinking the run.
    """
    project_prefix = f"nefsc/audio/{project}/"
    try:
        deployment_prefixes, _ = await _list_all(client, project_prefix, delimiter="/")
    except Exception as exc:
        log.warning("acoustic_nefsc_ingest: list %s failed: %s", project_prefix, exc)
        return []
    if not deployment_prefixes:
        log.info("acoustic_nefsc_ingest: no deployments found for project %s", project)
        return []

    # Collect raw records (one per MARU position per deployment)
    raw_records: list[dict[str, Any]] = []
    for dep_prefix in deployment_prefixes:
        try:
            json_names = await _list_deployment_metadata_jsons(client, dep_prefix)
        except Exception as exc:
            log.warning("acoustic_nefsc_ingest: %s list-meta failed: %s", dep_prefix, exc)
            continue
        if not json_names:
            continue
        # First primary JSON only — secondary files are usually duplicates
        meta = await _fetch_json(client, json_names[0])
        if meta is None:
            continue
        try:
            recs = _expand_positions(meta, project)
        except Exception as exc:
            log.warning("acoustic_nefsc_ingest: parse %s failed: %s", json_names[0], exc)
            continue
        raw_records.extend(recs)

    if not raw_records:
        log.info("acoustic_nefsc_ingest: %s produced no usable records", project)
        return []

    # Group by cluster key
    clusters: dict[str, list[dict[str, Any]]] = {}
    for r in raw_records:
        key = _cluster_key_for(project, r["lat"], r["lon"])
        clusters.setdefault(key, []).append(r)

    rows: list[dict[str, Any]] = []
    for cluster_key, members in clusters.items():
        rows.append(_aggregate_cluster(project, cluster_key, members))
    return rows


def _aggregate_cluster(project: str, cluster_key: str, members: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate N deployments of one recorder/MARU into a single row.

    Position + hardware + depth from the deployment with the LATEST
    deploy_start (canonical "current" config). Deploy start = MIN, deploy
    end = MAX (None if any deployment is open-ended).
    """
    dated = [m for m in members if m.get("deploy_start") is not None]
    latest = max(dated, key=lambda d: d["deploy_start"]) if dated else members[-1]  # type: ignore[arg-type]

    starts = [m["deploy_start"] for m in members if m.get("deploy_start") is not None]
    deploy_start = min(starts) if starts else None
    any_open = any(m.get("deploy_end") is None for m in members)
    ends = [m["deploy_end"] for m in members if m.get("deploy_end") is not None]
    deploy_end = None if any_open else (max(ends) if ends else None)

    instrument = latest.get("instrument_type") or "Hydrophone"

    if project == "sbnms":
        # Number MARUs by sorted cluster key for stable, readable ids
        # cluster_key looks like "42.1_-70.3" — fine for a sort but ugly in id.
        # We'll number them after the fact in fetch_nefsc_stations().
        operator = (
            "NOAA NEFSC + Cornell K. Lisa Yang Center for "
            "Conservation Bioacoustics"
        )
        # Friendly name set later once cluster ordering is known.
        name = f"Stellwagen Bank MARU (cluster {cluster_key})"
        station_id_suffix = f"sbnms_{cluster_key}"
        portal_url = "https://www.fisheries.noaa.gov/new-england-mid-atlantic/endangered-species-conservation/passive-acoustic-research-atlantic-marine"
    elif project == "monh":
        operator = "NOAA NEFSC"
        name = "Monhegan Island SoundTrap"
        station_id_suffix = "monh"
        portal_url = "https://www.fisheries.noaa.gov/new-england-mid-atlantic/endangered-species-conservation/passive-acoustic-research-atlantic-marine"
    else:  # pmanan
        operator = "NOAA NEFSC"
        name = "Petit Manan SoundTrap"
        station_id_suffix = "pmanan"
        portal_url = "https://www.fisheries.noaa.gov/new-england-mid-atlantic/endangered-species-conservation/passive-acoustic-research-atlantic-marine"

    return {
        "station_id":   f"nefsc:{station_id_suffix}",
        "source":       "nefsc",
        "name":         name,
        "operator":     operator,
        "lat":          latest["lat"],
        "lon":          latest["lon"],
        "depth_m":      latest.get("depth_m"),
        "deploy_start": deploy_start,
        "deploy_end":   deploy_end,
        "model":        instrument,
        # SoundTrap 500 / 300 nominally 96 kHz / 48 kHz sample rate;
        # MARUs nominally 2 kHz continuous (low-frequency baleen-whale band).
        # Leave NULL — varies per recorder type, panel surfaces the model.
        "hz_range_lo":  None,
        "hz_range_hi":  None,
        "portal_url":   portal_url,
    }


async def fetch_nefsc_stations() -> list[dict[str, Any]]:
    """Discover NEFSC deployments via GCS bucket listing and aggregate to one
    row per recorder (1 monh + 1 pmanan + ~21 sbnms MARU positions).

    Per-project try/except — a single project failure doesn't sink the run.
    SBNMS MARUs are numbered in the final row ordering for stable station_ids
    (sbnms_MARU01..MARU21).
    """
    rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for project in _NEFSC_PROJECTS:
            try:
                project_rows = await _fetch_project(client, project)
            except Exception as exc:
                log.warning("acoustic_nefsc_ingest: %s failed: %s", project, exc)
                continue
            log.info("fetch_nefsc_stations: %s -> %d rows", project, len(project_rows))

            if project == "sbnms":
                # Order MARUs north-to-south then west-to-east for stable
                # human-readable numbering. Mooring drift between deployments
                # is <1 km, so this stays stable across syncs as long as the
                # 0.1° cluster grain holds.
                project_rows.sort(
                    key=lambda r: (-r["lat"], r["lon"])
                )
                for i, row in enumerate(project_rows, start=1):
                    maru_num = f"{i:02d}"
                    row["station_id"] = f"nefsc:sbnms_MARU{maru_num}"
                    row["name"] = f"Stellwagen Bank MARU{maru_num}"

            rows.extend(project_rows)
    log.info("fetch_nefsc_stations: %d total stations", len(rows))
    return rows


async def fetch_nefsc_soundscape(station_id: str, days: int = 90) -> list[dict[str, Any]]:
    """Return [] — NEFSC publishes raw audio + per-deployment JSON metadata
    only; no aggregated SPL/decade-band product is exposed. Phase 3 NetCDF
    work would populate this from products under `nefsc/products/` once those
    are published (none as of 2026-05)."""
    return []
