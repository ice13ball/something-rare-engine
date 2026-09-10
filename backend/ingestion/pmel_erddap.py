# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Fetch latest TAO/TRITON/PIRATA/RAMA buoy observations from NOAA PMEL ERDDAP.

Used as a fallback enrichment for OceanSITES moorings that NDBC does not carry
(the equatorial Pacific TAO array, the Atlantic PIRATA array, the Indian-Ocean
RAMA array — collectively ~70 platforms).

Strategy: bulk-fetch latest reading per station from each pollutant dataset in
ONE request per dataset using ERDDAP's ``orderByMax("station,time")`` filter.
Five concurrent requests cover SST, wind, air temp, pressure, salinity.

Mapping to OceanSITES: PMEL ``station`` ID is the lowercased OceanSITES ``name``
(e.g. OceanSITES "9N140W" → PMEL "9n140w").

Reference: https://data.pmel.noaa.gov/pmel/erddap/
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

log = logging.getLogger(__name__)

_BASE = "https://data.pmel.noaa.gov/pmel/erddap/tabledap"

# (dataset_id, [value variables], [quality variables]) — value variables map to
# keys in our normalized obs dict, quality variables to PMEL's own flag for them.
# WU_422/WV_423 are u/v wind components (m/s); we derive speed + direction.
#
# ⛔ The quality columns were absent from this list until 2026-09-10, while the
# sync's docstring called PMEL "daily QC'd". PMEL publishes the flag next to
# every value and says what to do with it, verbatim from its own metadata:
#
#   QT_5025 description: "Quality: 0=missing data, 1=highest, 2=standard,
#   3=lower, 4=questionable, 5=bad, -9=contact ... To get probably valid data
#   only, request QT_5025>=1 and QT_5025<=3."
#
# We asked for none of them. Measured the same day across the exact query this
# module runs, every value came back flag 2 — 57 stations for SST, 53 for SSS,
# 65 for air temperature, zero above 3 anywhere. So nothing bad was reaching
# readers; there was simply nothing stopping it.
_ACCEPTABLE_QC = (1, 2, 3)

_DATASETS: list[tuple[str, list[str], list[str]]] = [
    ("pmelTaoDySst",  ["T_25"],              ["QT_5025"]),    # sea surface temp (°C)
    ("pmelTaoDyW",    ["WU_422", "WV_423"],  ["QWS_5401", "QWD_5410"]),  # wind u/v (m/s)
    ("pmelTaoDyAirt", ["AT_21"],             ["QAT_5021"]),   # air temp (°C)
    ("pmelTaoDyBp",   ["BP_915"],            ["QBP_5915"]),   # pressure (hPa)
    ("pmelTaoDySss",  ["S_41"],              ["QS_5041"]),    # sea surface salinity (PSU)
]


def _qc_verdict(row: list[Any], first_flag_index: int, n_flags: int) -> int | None:
    """The worst flag PMEL attached to this row, or None if it attached none.

    Wind is the reason this takes several: we ask for u/v components and derive
    speed and direction from BOTH, so a reading is only usable if PMEL vouches
    for the speed AND the direction. The worst of the two decides.
    """
    flags = [row[first_flag_index + i] for i in range(n_flags)]
    present = [int(f) for f in flags if isinstance(f, (int, float))]
    return max(present) if present else None


async def _fetch_dataset(
    client: httpx.AsyncClient, dataset: str, variables: list[str],
    quality: list[str], since_iso: str
) -> list[list[Any]]:
    """Bulk-fetch latest reading per station for one ERDDAP dataset.

    Returns ERDDAP rows: [station, time, var1, var2, ...]. Empty list on any
    error or 404 (no rows in the time window).
    """
    cols = "station,time," + ",".join(variables + quality)
    # ERDDAP requires the orderByMax argument quoted with %22; raw quotes get
    # rejected by the coastwatch mirror (where pmel.noaa.gov silently redirects).
    url = (
        f"{_BASE}/{dataset}.json?{cols}"
        f"&time>={since_iso}"
        f"&orderByMax(%22station,time%22)"
    )
    try:
        r = await client.get(url, timeout=60, follow_redirects=True)
        if r.status_code == 404:
            return []  # no data in window — silently skip
        r.raise_for_status()
        payload = r.json()
        return payload.get("table", {}).get("rows", []) or []
    except Exception as exc:
        log.warning("PMEL ERDDAP fetch %s failed: %s", dataset, exc)
        return []


def _wind_speed_dir(u: float | None, v: float | None) -> tuple[float | None, float | None]:
    """Convert u/v wind components to speed (m/s) + meteorological direction (°)."""
    if u is None or v is None:
        return None, None
    speed = (u * u + v * v) ** 0.5
    # Met convention: direction wind is FROM. atan2 returns radians; convert.
    import math
    direction = (math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0
    return round(speed, 2), round(direction, 0)


async def fetch_pmel_observations(lookback_days: int = 365) -> dict[str, dict[str, Any]]:
    """Fetch latest TAO/PIRATA/RAMA observations for every station with data.

    Returns ``{station_id: obs_dict}`` where obs_dict matches the schema used
    by ``_sync_oceansites_obs()`` (wtmp, atmp, wspd, wdir, pres, sss, obs_time).

    The lookback window is wide (365d default) because PMEL ERDDAP's
    ``actual_range`` metadata at the coastwatch mirror lags by months; narrower
    windows can 404 even when the data actually exists. ``orderByMax`` collapses
    to one row per station regardless of window width, so payload stays small.
    The DetailPanel separately marks readings older than ~6 weeks as stale.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *[_fetch_dataset(client, ds, vars_, qc_, since)
              for ds, vars_, qc_ in _DATASETS]
        )

    # Merge per-dataset results by station ID.
    merged: dict[str, dict[str, Any]] = {}

    #: dataset -> the obs keys it fills, so a rejected reading can be named.
    _KEYS = {"pmelTaoDySst": ("wtmp",), "pmelTaoDyW": ("wspd", "wdir"),
             "pmelTaoDyAirt": ("atmp",), "pmelTaoDyBp": ("pres",),
             "pmelTaoDySss": ("sss",)}

    for (dataset, variables, quality), rows in zip(_DATASETS, results):
        for row in rows:
            station = row[0]
            obs_time = row[1]
            station_obs = merged.setdefault(station, {})

            # Pick the most recent obs_time across all datasets for this station.
            existing_time = station_obs.get("obs_time")
            if existing_time is None or obs_time > existing_time:
                station_obs["obs_time"] = obs_time

            # ⛔ "Missing" and "broken" must not share a code path. A value PMEL
            # flagged as questionable is dropped, but the flag is kept under
            # `qc`, so the panel can say "PMEL flagged this reading" instead of
            # showing the same blank a station with no sensor shows.
            flag = _qc_verdict(row, 2 + len(variables), len(quality))
            qc = station_obs.setdefault("qc", {})
            for key in _KEYS[dataset]:
                if flag is not None:
                    qc[key] = flag
            if flag is not None and flag not in _ACCEPTABLE_QC:
                continue

            if dataset == "pmelTaoDySst":
                station_obs["wtmp"] = row[2]
            elif dataset == "pmelTaoDyW":
                speed, direction = _wind_speed_dir(row[2], row[3])
                if speed is not None:
                    station_obs["wspd"] = speed
                    station_obs["wdir"] = direction
            elif dataset == "pmelTaoDyAirt":
                station_obs["atmp"] = row[2]
            elif dataset == "pmelTaoDyBp":
                station_obs["pres"] = row[2]
            elif dataset == "pmelTaoDySss":
                station_obs["sss"] = row[2]

    # Drop entries that ended up with no usable variables. ⛔ `qc` and
    # `obs_time` are metadata, not readings — a station whose every value PMEL
    # rejected must not survive here as if it carried data.
    return {
        sid: obs for sid, obs in merged.items()
        if any(k not in ("obs_time", "qc") and v is not None for k, v in obs.items())
    }
