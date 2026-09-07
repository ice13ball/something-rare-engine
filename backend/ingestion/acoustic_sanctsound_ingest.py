# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""NOAA SanctSound hydrophone ingest.

Stations: discovered dynamically from the public Google Cloud Storage bucket
`noaa-passive-bioacoustic` (`sanctsound/audio/{site}/` prefix). Each site
folder holds per-deployment subfolders carrying a
`metadata/SanctSound_{SITE}_{NN}.json` describing the deployment. We store
one row per recorder (~30 sites across 7 sanctuaries) — NOT per deployment —
since that's the granularity the map panel needs.

Soundscape: deferred to Phase 3. NCEI does publish hourly Broadband (BB) and
Power Spectral Density (PSD) CSV products at
`gs://noaa-passive-bioacoustic/sanctsound/products/sound_level_metrics/`, but
ingesting + downsampling them is out of Phase 2 scope. Returns [].

for endpoint discovery + full 30-station table.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any

import httpx

log = logging.getLogger(__name__)

_BUCKET = "noaa-passive-bioacoustic"
_GCS_LIST = f"https://storage.googleapis.com/storage/v1/b/{_BUCKET}/o"
_GCS_OBJECT = f"https://storage.googleapis.com/{_BUCKET}"
_TIMEOUT = httpx.Timeout(60.0, connect=20.0)

# Sanctuary codes confirmed in the bucket as of 2026-05-11 (per bench notes).
# `mnms` (Monitor / Carolina Capes) is referenced in NOAA press releases but
# the bucket prefix doesn't exist — surface 7 sanctuaries, not 8.
_SITE_PREFIX = "sanctsound/audio/"

# Pretty-name suffix per 2-letter sanctuary code — surfaced in panel when
# SITE_ALIASES[0] is empty.
_SANCTUARY_LABEL = {
    "ci": "Channel Islands NMS",
    "fk": "Florida Keys NMS",
    "gr": "Gray's Reef NMS",
    "hi": "Hawaiian Islands Humpback NMS",
    "mb": "Monterey Bay NMS",
    "oc": "Olympic Coast NMS",
    "pm": "Papahānaumokuākea NM",
    "sb": "Stellwagen Bank NMS",
}

# Match `sanctsound/audio/<site>/sanctsound_<site>_<NN>/`. The site code is
# letters+digits (e.g. `ci01`, `pm05`); the backreference forces both halves
# to match the same code.
_DEPLOY_RE = re.compile(r"sanctsound/audio/([a-z]{2,3}\d{2})/sanctsound_\1_(\d+)/$")


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return f


def _parse_iso_date(value: Any) -> date | None:
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


async def _list_all(client: httpx.AsyncClient, prefix: str, delimiter: str | None = "/") -> tuple[list[str], list[dict[str, Any]]]:
    prefixes: list[str] = []
    items: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        params: dict[str, str] = {"prefix": prefix, "maxResults": "200"}
        if delimiter:
            params["delimiter"] = delimiter
        if page_token:
            params["pageToken"] = page_token
        resp = await client.get(_GCS_LIST, params=params)
        resp.raise_for_status()
        data = resp.json()
        prefixes.extend(data.get("prefixes") or [])
        items.extend(data.get("items") or [])
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return prefixes, items


async def _fetch_json(client: httpx.AsyncClient, object_name: str) -> dict[str, Any] | None:
    url = f"{_GCS_OBJECT}/{object_name}"
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.warning("acoustic_sanctsound_ingest: fetch %s failed: %s", url, exc)
        return None


def _extract_fields(meta: dict[str, Any]) -> dict[str, Any] | None:
    """Pull canonical fields from one deployment JSON. Returns None if LOCATION
    is null (bench-confirmed: FK04, PM01, PM05 ship LOCATION:null in some
    deployment JSONs)."""
    lat = _safe_float(_get_ci(meta, "LOCATION", "lat")) \
        or _safe_float(_get_ci(meta, "LOCATION", "latitude"))
    lon = _safe_float(_get_ci(meta, "LOCATION", "lon")) \
        or _safe_float(_get_ci(meta, "LOCATION", "longitude"))
    if lat is None or lon is None:
        return None
    sensor_depth = _safe_float(_get_ci(meta, "SENSOR_DEPTH"))
    # ⛔ SENSOR_DEPTH has no public field dictionary we could find for this
    # bucket's metadata JSON. abs() is OUR assumption, not a documented source
    # convention: a genuine height above the seafloor would be silently turned
    # into a depth. Recorded rather than resolved - see
    # docs/methods/data-passthrough.md.
    depth_m = abs(sensor_depth) if sensor_depth is not None else None
    aliases = _get_ci(meta, "SITE_ALIASES")
    alias: str | None = None
    if isinstance(aliases, list) and aliases:
        first = aliases[0]
        if isinstance(first, str) and first.strip():
            alias = first.strip()
    site = _get_ci(meta, "SITE")
    instrument = _get_ci(meta, "INSTRUMENT_NAME") or _get_ci(meta, "PLATFORM_NAME")
    start = _parse_iso_date(_get_ci(meta, "START_DATE"))
    end = _parse_iso_date(_get_ci(meta, "END_DATE"))
    doi = _get_ci(meta, "DOI")
    return {
        "lat":          lat,
        "lon":          lon,
        "depth_m":      depth_m,
        "alias":        alias,
        "site":         str(site).strip() if site else None,
        "instrument":   str(instrument).strip() if instrument else None,
        "deploy_start": start,
        "deploy_end":   end,
        "doi":          str(doi).strip() if doi else None,
    }


async def _fetch_site(client: httpx.AsyncClient, site_code: str) -> dict[str, Any] | None:
    """Aggregate every deployment of one recorder into a single row.

    Aggregation:
    - lat/lon/depth/model from the LATEST deployment that has usable LOCATION
      (some deployments ship LOCATION:null; skip those for position but still
      use them for date aggregation if dated).
    - deploy_start = MIN(START_DATE)
    - deploy_end   = MAX(END_DATE); None if any deployment is open-ended."""
    site_prefix = f"sanctsound/audio/{site_code}/"
    try:
        deployment_prefixes, _ = await _list_all(client, site_prefix, delimiter="/")
    except Exception as exc:
        log.warning("acoustic_sanctsound_ingest: list %s failed: %s", site_prefix, exc)
        return None
    if not deployment_prefixes:
        return None

    deployments: list[dict[str, Any]] = []
    for dep_prefix in deployment_prefixes:
        # Some recorders (e.g. mb03 HARP) use bare `01/` deployment folders
        # instead of `sanctsound_mb03_01/`. Try the canonical naming first,
        # then fall back to listing `metadata/` for any .json.
        m = _DEPLOY_RE.match(dep_prefix)
        meta: dict[str, Any] | None = None
        if m:
            nn = m.group(2)
            site_upper = site_code.upper()
            canonical = f"{dep_prefix}metadata/SanctSound_{site_upper}_{nn}.json"
            meta = await _fetch_json(client, canonical)
        if meta is None:
            meta_prefix = f"{dep_prefix}metadata/"
            try:
                _, meta_items = await _list_all(client, meta_prefix, delimiter=None)
            except Exception:
                continue
            json_name = None
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
        fields = _extract_fields(meta)
        if fields is None:
            # LOCATION-null deployment — still capture dates if any
            start = _parse_iso_date(_get_ci(meta, "START_DATE"))
            end = _parse_iso_date(_get_ci(meta, "END_DATE"))
            if start or end:
                deployments.append({
                    "lat": None, "lon": None, "depth_m": None,
                    "alias": None, "site": None, "instrument": None,
                    "deploy_start": start, "deploy_end": end, "doi": None,
                })
            continue
        deployments.append(fields)

    if not deployments:
        return None

    # Find the latest position-bearing deployment for canonical lat/lon
    positioned = [d for d in deployments if d.get("lat") is not None and d.get("deploy_start") is not None]
    if not positioned:
        # All LOCATION:null — bench notes mark FK04/PM01/PM05 as such. Skip
        # these for the map layer since they'd render at (0,0).
        log.info("acoustic_sanctsound_ingest: site %s has no positioned deployment — skipping", site_code)
        return None

    latest = max(positioned, key=lambda d: d["deploy_start"])  # type: ignore[arg-type]

    starts = [d["deploy_start"] for d in deployments if d["deploy_start"] is not None]
    deploy_start = min(starts) if starts else None
    any_open = any(
        d["deploy_end"] is None for d in deployments if d.get("deploy_start") is not None
    )
    ends = [d["deploy_end"] for d in deployments if d["deploy_end"] is not None]
    deploy_end = None if any_open else (max(ends) if ends else None)

    site_upper = (latest.get("site") or site_code).upper()
    if latest.get("alias"):
        name = latest["alias"]  # type: ignore[index]
    else:
        sanctuary_prefix = site_code[:2]
        sanctuary_label = _SANCTUARY_LABEL.get(sanctuary_prefix)
        if sanctuary_label:
            name = f"SanctSound {site_upper} — {sanctuary_label}"
        else:
            name = f"SanctSound {site_upper}"

    instrument = latest.get("instrument") or "NOAA SanctSound hydrophone"

    return {
        "station_id":   f"sanctsound:{site_code}",
        "source":       "sanctsound",
        "name":         name,
        "operator":     "NOAA Office of National Marine Sanctuaries / U.S. Navy",
        "lat":          latest["lat"],
        "lon":          latest["lon"],
        "depth_m":      latest.get("depth_m"),
        "deploy_start": deploy_start,
        "deploy_end":   deploy_end,
        "model":        instrument,
        # ST500 = 96 kHz sample rate -> 20-48 kHz usable; HARP (MB03) goes to ~100 kHz.
        # Conservative per-layer legend: 20-24 kHz typical.
        "hz_range_lo":  20.0,
        "hz_range_hi":  24_000.0,
        "portal_url":   "https://sanctsound.ioos.us/",
    }


async def _discover_site_codes(client: httpx.AsyncClient) -> list[str]:
    """List the `sanctsound/audio/` top-level prefix to discover all site
    codes currently in the bucket. Avoids hardcoding the list — if NOAA
    publishes new sanctuaries the sync picks them up automatically."""
    try:
        prefixes, _ = await _list_all(client, _SITE_PREFIX, delimiter="/")
    except Exception as exc:
        log.warning("acoustic_sanctsound_ingest: discover site codes failed: %s", exc)
        return []
    site_codes: list[str] = []
    for p in prefixes:
        # p looks like "sanctsound/audio/ci01/"
        tail = p[len(_SITE_PREFIX):].rstrip("/")
        if not tail or "/" in tail:
            continue
        site_codes.append(tail)
    site_codes.sort()
    return site_codes


async def fetch_sanctsound_stations() -> list[dict[str, Any]]:
    """Discover SanctSound recorders via GCS bucket listing and aggregate one
    row per recorder. Per-site try/except — a single bad metadata file doesn't
    sink the sync."""
    rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        site_codes = await _discover_site_codes(client)
        if not site_codes:
            log.warning("fetch_sanctsound_stations: no site codes discovered")
            return rows
        log.info("fetch_sanctsound_stations: discovered %d site codes", len(site_codes))
        for site_code in site_codes:
            try:
                row = await _fetch_site(client, site_code)
            except Exception as exc:
                log.warning("acoustic_sanctsound_ingest: site %s failed: %s", site_code, exc)
                continue
            if row is not None:
                rows.append(row)
    log.info("fetch_sanctsound_stations: %d unique recorders", len(rows))
    return rows


async def fetch_sanctsound_soundscape(station_id: str, days: int = 90) -> list[dict[str, Any]]:
    """Return [] — SanctSound publishes hourly BB/OL/PSD CSV products at
    gs://noaa-passive-bioacoustic/sanctsound/products/sound_level_metrics/,
    but ingestion is Phase 3 work. Phase 2 ships station metadata only."""
    return []
