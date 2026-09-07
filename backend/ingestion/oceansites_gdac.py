# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Fetch latest observations from OceanSITES GDAC THREDDS at IFREMER.

Tertiary fallback after NDBC and NOAA PMEL ERDDAP. The GDAC carries the same
TAO Pacific moorings PMEL has, plus a handful of regional observatories that
PMEL does not (e.g. Stratus, Station-M). Realistic uplift over PMEL is small
(~4 stations today) but this also acts as a backstop if PMEL is down.

Method: pure-Python OPeNDAP without xarray/netCDF4. Steps per station:

    1. catalog.xml → list of latest R-mode (real-time) deployment files per VAR
    2. <file>.dds → TIME dimension size N
    3. <file>.ascii?VAR[N-1:1:N-1][0:1:0]  → last value as plain text
    4. <file>.ascii?TIME[N-1:1:N-1]        → last timestamp (days since 1950-01-01)

The query subscript brackets MUST be percent-encoded; raw ``[`` returns 400
from the IFREMER tomcat. ``urllib.parse.quote(..., safe='')`` is sufficient.

Reference: https://www.ocean-ops.org/oceansites/data/index.html
"""
from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

log = logging.getLogger(__name__)

_CATALOG_BASE = "https://tds0.ifremer.fr/thredds/catalog/CORIOLIS-OCEANSITES-GDAC-OBS/DATA"
_DODS_BASE = "https://tds0.ifremer.fr/thredds/dodsC/CORIOLIS-OCEANSITES-GDAC-OBS/DATA"

# CF time epoch used by all OceanSITES NetCDF files.
_TIME_EPOCH = datetime(1950, 1, 1, tzinfo=timezone.utc)

# Variables we read, mapped to our normalized obs schema. The first tuple element
# is the GDAC file suffix (`OS_<dir>_<dep>_R_<SUFFIX>_*.nc`); second is the
# variable name inside that file; third is our obs key.
_VARS: list[tuple[str, str, str]] = [
    ("SST",  "SST",  "wtmp"),
    ("AIRT", "AIRT", "atmp"),
    ("BARO", "ATMS", "pres"),
    ("SALT", "PSAL", "sss"),
    # WIND is special: read both WSPD and WDIR from the same file.
]

# Explicit name → GDAC directory overrides. Most TAO names map to T<name>;
# other moorings use ad-hoc directory names that don't follow a rule.
_DIR_OVERRIDES: dict[str, str] = {
    "STATION-M-1": "STATION-M",
    "Stratus23":   "Stratus",
}


def _candidate_dirs(name: str) -> list[str]:
    """Return ordered list of directory names to probe for ``name``."""
    if name in _DIR_OVERRIDES:
        return [_DIR_OVERRIDES[name]]
    n = name.strip()
    return [n, f"T{n}", f"P{n}", f"R{n}"]


_FILE_RE = re.compile(r'<dataset[^>]*name="(OS_[^"]+\.nc)"')
_DEPLOY_DATE_RE = re.compile(r"-(\d{8})_")


def _pick_latest_files(filenames: list[str]) -> dict[str, str]:
    """Return ``{var_suffix: filename}`` for latest R-mode deployment per VAR.

    Filename pattern: ``OS_<dir>_<deployment>-<YYYYMMDD>_<R|D>_<VAR>_<freq>.nc``.
    Prefer R (real-time) over D (delayed-mode) — R has the most recent samples.
    Within R-mode, pick deployment with highest date.
    """
    best: dict[str, tuple[str, str]] = {}  # var → (deployment_date, filename)
    for fn in filenames:
        # Split: OS, dir, deployment-date, mode, var, freq.nc
        parts = fn.split("_")
        if len(parts) < 6 or parts[3] != "R":
            continue
        var = parts[4]
        m = _DEPLOY_DATE_RE.search(fn)
        if not m:
            continue
        deploy_date = m.group(1)
        if var not in best or deploy_date > best[var][0]:
            best[var] = (deploy_date, fn)
    return {v: tup[1] for v, tup in best.items()}


async def _fetch_catalog(client: httpx.AsyncClient, dirname: str) -> list[str] | None:
    """Return list of .nc filenames in the station directory, or None on 404."""
    url = f"{_CATALOG_BASE}/{urllib.parse.quote(dirname)}/catalog.xml"
    try:
        r = await client.get(url, timeout=30, follow_redirects=True)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return _FILE_RE.findall(r.text)
    except Exception as exc:
        log.debug("GDAC catalog %s failed: %s", dirname, exc)
        return None


_DDS_DIM_RE = re.compile(r"TIME\[TIME = (\d+)\]")


async def _fetch_last_value(
    client: httpx.AsyncClient, file_url: str, var: str
) -> tuple[float | None, str | None]:
    """Return (value, iso_timestamp) for last sample of ``var`` in ``file_url``.

    Two requests: .dds for TIME dim size, then .ascii for value + timestamp.
    Returns (None, None) on any error.
    """
    try:
        # Step 1: dim size
        r = await client.get(file_url + ".dds", timeout=20, follow_redirects=True)
        r.raise_for_status()
        m = _DDS_DIM_RE.search(r.text)
        if not m:
            return None, None
        n = int(m.group(1))
        if n == 0:
            return None, None

        # Step 2: last value + last timestamp.
        # Variables wrapped in Grid use dotted access "VAR.VAR"; plain arrays don't.
        # All our targets (SST, AIRT, ATMS, WSPD, WDIR, PSAL) are Grid-wrapped.
        idx = f"[{n-1}:1:{n-1}][0:1:0]"
        time_idx = f"[{n-1}:1:{n-1}]"
        query = urllib.parse.quote(f"{var}.{var}{idx},TIME{time_idx}", safe="")
        r2 = await client.get(f"{file_url}.ascii?{query}", timeout=20, follow_redirects=True)
        r2.raise_for_status()
        return _parse_ascii_value(r2.text, var)
    except Exception as exc:
        log.debug("GDAC fetch %s/%s failed: %s", file_url, var, exc)
        return None, None


def _parse_ascii_value(text: str, var: str) -> tuple[float | None, str | None]:
    """Parse OPeNDAP ASCII payload into (value, iso_timestamp).

    Format (separator after the DDS section):
        ---------------
        SST[1][1]
        [0], 28.5113

        TIME[1]
        27869.9930555...

    Value rows for 2-D vars are ``[idx], v1, v2, …``; we take the last number.
    TIME is ``days since 1950-01-01`` as a float.
    """
    # Skip everything up to and including the dashed separator.
    parts = text.split("---", 1)
    body = parts[1] if len(parts) == 2 else text
    value: float | None = None
    ts: str | None = None
    section: str | None = None
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(var + "[") or line == var:
            section = "value"
            continue
        if line.startswith("TIME[") or line == "TIME":
            section = "time"
            continue
        if section == "value" and value is None:
            # "[0], 28.5113" → take last comma-separated token
            tok = line.rsplit(",", 1)[-1].strip()
            v = _safe_float(tok)
            # Filter sentinel fill values (-999, -9999, NaN).
            if v is not None and -900.0 < v < 1e30:
                value = v
        elif section == "time" and ts is None:
            v = _safe_float(line)
            if v is not None:
                ts = (_TIME_EPOCH + timedelta(days=v)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return value, ts


def _safe_float(s: str) -> float | None:
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


async def _fetch_station(
    client: httpx.AsyncClient, station_name: str
) -> tuple[str, dict[str, Any]] | None:
    """Return ``(station_name, obs_dict)`` or None if no data resolved."""
    resolved_dir: str | None = None
    files: list[str] | None = None
    for dirname in _candidate_dirs(station_name):
        files = await _fetch_catalog(client, dirname)
        if files:
            resolved_dir = dirname
            break
    if not files or not resolved_dir:
        return None

    latest = _pick_latest_files(files)
    if not latest:
        return None

    base = f"{_DODS_BASE}/{urllib.parse.quote(resolved_dir)}"

    obs: dict[str, Any] = {}
    obs_time_max: str | None = None

    # Scalar variables
    tasks: list[asyncio.Task] = []
    spec: list[tuple[str, str]] = []  # (file_var_suffix, internal_var)
    for var_suffix, internal, _key in _VARS:
        fn = latest.get(var_suffix)
        if not fn:
            continue
        tasks.append(asyncio.create_task(
            _fetch_last_value(client, f"{base}/{fn}", internal)
        ))
        spec.append((var_suffix, internal))
    # WIND: two reads from one file
    wind_fn = latest.get("WIND")
    if wind_fn:
        tasks.append(asyncio.create_task(
            _fetch_last_value(client, f"{base}/{wind_fn}", "WSPD")
        ))
        spec.append(("WIND", "WSPD"))
        tasks.append(asyncio.create_task(
            _fetch_last_value(client, f"{base}/{wind_fn}", "WDIR")
        ))
        spec.append(("WIND", "WDIR"))

    if not tasks:
        return None

    results = await asyncio.gather(*tasks)

    var_to_key = {
        ("SST",  "SST"):  "wtmp",
        ("AIRT", "AIRT"): "atmp",
        ("BARO", "ATMS"): "pres",
        ("SALT", "PSAL"): "sss",
        ("WIND", "WSPD"): "wspd",
        ("WIND", "WDIR"): "wdir",
    }
    for (suffix, internal), (val, ts) in zip(spec, results):
        if val is None:
            continue
        key = var_to_key[(suffix, internal)]
        obs[key] = round(val, 2) if key != "wdir" else round(val, 0)
        if ts and (obs_time_max is None or ts > obs_time_max):
            obs_time_max = ts

    if not obs:
        return None
    if obs_time_max:
        obs["obs_time"] = obs_time_max
    return station_name, obs


async def fetch_gdac_observations(
    station_names: list[str], concurrency: int = 4
) -> dict[str, dict[str, Any]]:
    """Fetch latest observations from GDAC for the given station names.

    Returns ``{station_name: obs_dict}`` in the same schema as PMEL/NDBC paths.
    Stations that don't resolve to a GDAC directory are silently skipped.
    Concurrency is intentionally low — each station triggers up to ~10 small
    OPeNDAP requests, and the IFREMER tomcat throttles bursts.
    """
    sem = asyncio.Semaphore(concurrency)
    out: dict[str, dict[str, Any]] = {}

    async with httpx.AsyncClient() as client:
        async def bound(name: str):
            async with sem:
                return await _fetch_station(client, name)

        results = await asyncio.gather(*(bound(n) for n in station_names))

    for r in results:
        if r is None:
            continue
        name, obs = r
        out[name] = obs
    return out
