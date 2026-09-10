# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""NOAA NRS (Ocean Noise Reference Stations) hydrophone ingest.

Stations: discovered dynamically from the public Google Cloud Storage bucket
`noaa-passive-bioacoustic` (`nrs/audio/{NN}/` prefix). Each NRS site folder
holds one folder per deployment cycle; each deployment carries a
`metadata/NRS_{NN}_{years}.json` file describing the deployment. We aggregate
to one row per site (NRS01..NRS12) — earliest DEPLOYMENT_TIME and latest
RECOVERY_TIME across all cycles, hardware/depth taken from the most recent
cycle.

Soundscape: not a first-party aggregated SPL/decade-band product is exposed
via REST. Phase 3 may add a NetCDF ingestion pipeline reading the
`nrs/products/sound_level_metrics/` prefix. For now returns [].

for endpoint discovery + full 12-station table.
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

# NRS site ids are 01..12 — bench-confirmed station count. We list them explicitly
# (vs walking the top-level `nrs/audio/` prefix) because (a) the count is stable,
# (b) it lets us fail soft on per-site errors without dropping the whole sync.
_NRS_SITE_IDS = [f"{n:02d}" for n in range(1, 13)]


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
    """Parse an ISO date or datetime string into a date.

    Tolerates trailing 'Z', space separators, and bare YYYY-MM-DD."""
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
    """Case-insensitive nested getter — NRS JSON uses lower-case keys in pre-2020
    deployments and upper-case in post-2020 ones. We walk both."""
    if not isinstance(d, dict):
        return None
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        # exact, then case-insensitive
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


async def _list_prefix(client: httpx.AsyncClient, prefix: str, delimiter: str | None = "/") -> dict[str, Any]:
    """One page of GCS object listing. Returns the raw JSON dict (with `items`
    and/or `prefixes`). Caller paginates via `nextPageToken`."""
    params: dict[str, str] = {"prefix": prefix, "maxResults": "200"}
    if delimiter:
        params["delimiter"] = delimiter
    resp = await get_with_retry(client, _GCS_LIST, params=params, label="nrs listing")
    resp.raise_for_status()
    return resp.json()


async def _list_all(client: httpx.AsyncClient, prefix: str, delimiter: str | None = "/") -> tuple[list[str], list[dict[str, Any]]]:
    """Walk pagination, return (prefixes, items)."""
    prefixes: list[str] = []
    items: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        params: dict[str, str] = {"prefix": prefix, "maxResults": "200"}
        if delimiter:
            params["delimiter"] = delimiter
        if page_token:
            params["pageToken"] = page_token
        resp = await get_with_retry(client, _GCS_LIST, params=params, label="nrs listing page")
        resp.raise_for_status()
        data = resp.json()
        prefixes.extend(data.get("prefixes") or [])
        items.extend(data.get("items") or [])
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return prefixes, items


async def _fetch_json(client: httpx.AsyncClient, object_name: str) -> dict[str, Any] | None:
    """Download a JSON object from the bucket by its full GCS object name.

    Returns None on any error so a single bad file doesn't sink the sync."""
    url = f"{_GCS_OBJECT}/{object_name}"
    try:
        resp = await get_with_retry(client, url, label="nrs object")
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.warning("acoustic_nrs_ingest: fetch %s failed: %s", url, exc)
        return None


def _extract_station_fields(site_id: str, meta: dict[str, Any]) -> dict[str, Any] | None:
    """Pull the canonical fields from one deployment JSON. Returns None if the
    JSON lacks usable lat/lon (some early-deployment files are skeleton stubs)."""
    lat = _safe_float(_get_ci(meta, "DEPLOYMENT", "DEPLOY_LAT")) \
        or _safe_float(_get_ci(meta, "DEPLOYMENT", "DEPLOY_LATITUDE")) \
        or _safe_float(_get_ci(meta, "deployment", "lat")) \
        or _safe_float(_get_ci(meta, "deployment", "latitude"))
    lon = _safe_float(_get_ci(meta, "DEPLOYMENT", "DEPLOY_LON")) \
        or _safe_float(_get_ci(meta, "DEPLOYMENT", "DEPLOY_LONGITUDE")) \
        or _safe_float(_get_ci(meta, "deployment", "lon")) \
        or _safe_float(_get_ci(meta, "deployment", "longitude"))
    if lat is None or lon is None:
        return None
    depth_raw = _safe_float(_get_ci(meta, "DEPLOYMENT", "DEPLOY_INSTRUMENT_DEPTH")) \
        or _safe_float(_get_ci(meta, "DEPLOYMENT", "INSTRUMENT_DEPTH")) \
        or _safe_float(_get_ci(meta, "deployment", "instrument_depth"))
    # ⛔ None of DEPLOY_INSTRUMENT_DEPTH/INSTRUMENT_DEPTH has a public field
    # dictionary we could find for this bucket's metadata JSON. abs() is OUR
    # assumption, not a documented source convention: a genuine height above
    # the seafloor would be silently turned into a depth. Recorded rather than
    # resolved - see docs/methods/data-passthrough.md.
    depth_m = abs(depth_raw) if depth_raw is not None else None
    sea_area = _get_ci(meta, "DEPLOYMENT", "SEA_AREA") \
        or _get_ci(meta, "deployment", "sea_area") \
        or _get_ci(meta, "SITE_ALIAS") \
        or _get_ci(meta, "site_alias")
    sea_area = str(sea_area).strip() if sea_area else None
    instrument = _get_ci(meta, "INSTRUMENT_TYPE") \
        or _get_ci(meta, "instrument_type") \
        or _get_ci(meta, "PLATFORM_NAME") \
        or _get_ci(meta, "platform")
    deploy_start = _parse_iso_date(_get_ci(meta, "DEPLOYMENT", "DEPLOYMENT_TIME")) \
        or _parse_iso_date(_get_ci(meta, "DEPLOYMENT", "AUDIO_START")) \
        or _parse_iso_date(_get_ci(meta, "deployment", "deployment_time"))
    deploy_end = _parse_iso_date(_get_ci(meta, "DEPLOYMENT", "RECOVERY_TIME")) \
        or _parse_iso_date(_get_ci(meta, "DEPLOYMENT", "AUDIO_END")) \
        or _parse_iso_date(_get_ci(meta, "deployment", "recovery_time"))
    return {
        "lat":          lat,
        "lon":          lon,
        "depth_m":      depth_m,
        "sea_area":     sea_area,
        "instrument":   str(instrument).strip() if instrument else None,
        "deploy_start": deploy_start,
        "deploy_end":   deploy_end,
    }


async def _fetch_site(client: httpx.AsyncClient, site_id: str) -> dict[str, Any] | None:
    """Discover all deployments for one NRS site, aggregate to a single row.

    Aggregation rules:
    - lat/lon/depth/model from the deployment with the LATEST deploy_start
      (the canonical "current" position; mooring drift means earlier
      deployments may be ~1 km away).
    - deploy_start = MIN(DEPLOYMENT_TIME) across all cycles
    - deploy_end   = MAX(RECOVERY_TIME) across all cycles; None if any cycle
      lacks RECOVERY_TIME (= active).
    """
    site_prefix = f"nrs/audio/{site_id}/"
    try:
        deployment_prefixes, _ = await _list_all(client, site_prefix, delimiter="/")
    except Exception as exc:
        log.warning("acoustic_nrs_ingest: list %s failed: %s", site_prefix, exc)
        return None
    if not deployment_prefixes:
        log.info("acoustic_nrs_ingest: no deployments found for site %s", site_id)
        return None

    deployments: list[dict[str, Any]] = []
    for dep_prefix in deployment_prefixes:
        meta_prefix = f"{dep_prefix}metadata/"
        try:
            _, meta_items = await _list_all(client, meta_prefix, delimiter=None)
        except Exception as exc:
            log.warning("acoustic_nrs_ingest: list %s failed: %s", meta_prefix, exc)
            continue
        # Pick first *.json file (each deployment publishes one)
        json_name: str | None = None
        for item in meta_items:
            name = item.get("name") or ""
            if name.lower().endswith(".json"):
                json_name = name
                break
        if not json_name:
            continue
        meta = await _fetch_json(client, json_name)
        if meta is None:
            continue
        fields = _extract_station_fields(site_id, meta)
        if fields is None:
            continue
        deployments.append(fields)

    if not deployments:
        log.info("acoustic_nrs_ingest: NRS%s had deployment folders but no usable metadata", site_id)
        return None

    # Aggregate
    deployments_dated = [d for d in deployments if d["deploy_start"] is not None]
    if deployments_dated:
        latest = max(deployments_dated, key=lambda d: d["deploy_start"])  # type: ignore[arg-type]
    else:
        latest = deployments[-1]

    starts = [d["deploy_start"] for d in deployments if d["deploy_start"] is not None]
    deploy_start = min(starts) if starts else None
    any_open = any(d["deploy_end"] is None for d in deployments)
    ends = [d["deploy_end"] for d in deployments if d["deploy_end"] is not None]
    deploy_end = None if any_open else (max(ends) if ends else None)

    name_suffix = latest.get("sea_area") or ""
    name = f"NRS{site_id} {name_suffix}".strip()
    instrument = latest.get("instrument") or "Autonomous Underwater Hydrophone (AUH)"

    return {
        "station_id":   f"nrs:NRS{site_id}",
        "source":       "nrs",
        "name":         name,
        "operator":     "NOAA NCEI / Ocean Noise Reference Stations",
        "lat":          latest["lat"],
        "lon":          latest["lon"],
        "depth_m":      latest.get("depth_m"),
        "deploy_start": deploy_start,
        "deploy_end":   deploy_end,
        "model":        instrument,
        # NRS continuous 5 kHz sample rate (Haver et al. 2025); ~10 Hz - Nyquist 2.5 kHz usable
        "hz_range_lo":  10.0,
        "hz_range_hi":  2_500.0,
        "portal_url":   "https://www.ncei.noaa.gov/maps/passive-acoustic-data/",
    }


async def fetch_nrs_stations() -> list[dict[str, Any]]:
    """Discover NRS deployments via GCS bucket listing and aggregate to one row
    per station (NRS01..NRS12). Per-site try/except — a single bad metadata file
    doesn't sink the sync."""
    rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for site_id in _NRS_SITE_IDS:
            try:
                row = await _fetch_site(client, site_id)
            except Exception as exc:
                log.warning("acoustic_nrs_ingest: NRS%s failed: %s", site_id, exc)
                continue
            if row is not None:
                rows.append(row)
    log.info("fetch_nrs_stations: %d unique stations", len(rows))
    return rows


async def fetch_nrs_soundscape(station_id: str, days: int = 90) -> list[dict[str, Any]]:
    """Return [] — NRS publishes daily NetCDF hybrid millidecade SPL products at
    gs://noaa-passive-bioacoustic/nrs/products/sound_level_metrics/, but Phase 2
    ships stations only. Phase 3 will add a NetCDF/xarray pipeline to populate
    this with broadband + decade-band SPL time series."""
    return []
