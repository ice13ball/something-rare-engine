# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""CMEMS ocean current fetching and RK4 back-tracking."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from math import cos, radians, isnan
from typing import List, Tuple

import numpy as np

# Multi-year reanalysis: 1993–present minus ~28 days lag
DATASET_REANALYSIS = "cmems_mod_glo_phy_my_0.083deg_P1D-m"
REANALYSIS_LAG_DAYS = 28

# Near-real-time analysis/forecast: covers up to ~2 days ahead, ~2022 onwards
DATASET_NRT = "cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m"


class CMEMSTooRecentError(Exception):
    """Profile date is too recent for the reanalysis dataset."""


class CMEMSUnavailableError(Exception):
    """CMEMS service is unreachable or credentials are invalid."""


def _cm():
    """Import copernicusmarine lazily — it is a heavy optional dependency and
    is absent on developer machines and in the gate's import-smoke path."""
    try:
        import copernicusmarine
    except ImportError as exc:  # pragma: no cover - depends on host env
        raise CMEMSUnavailableError(
            "copernicusmarine is not installed — CMEMS access unavailable"
        ) from exc
    return copernicusmarine


@dataclass
class BacktrackResult:
    path: List[Tuple[float, float]]   # [(lon, lat), ...] from float position to estimated origin
    origin: Tuple[float, float]        # last point: (lon, lat) of estimated water-mass source
    u_mean: float                      # mean eastward velocity in m/s
    v_mean: float                      # mean northward velocity in m/s
    speed_cms: float                   # mean current speed in cm/s
    steps_completed: int               # number of daily steps actually taken (may be < requested if NaN hit)


def _credentials() -> dict:
    username = os.getenv("CMEMS_USERNAME")
    password = os.getenv("CMEMS_PASSWORD")
    if not username or not password:
        raise CMEMSUnavailableError("CMEMS_USERNAME or CMEMS_PASSWORD not set in environment")
    return {"username": username, "password": password}


def fetch_currents(lon: float, lat: float, date: datetime, depth_m: int, hours: int):
    """
    Fetch uo/vo from CMEMS for a tight bbox and time window.

    Automatically selects dataset:
    - Recent profiles (< REANALYSIS_LAG_DAYS old): NRT analysis/forecast
    - Older profiles: multi-year reanalysis

    Returns a lazy xarray Dataset via open_dataset (no file download).
    Raises CMEMSUnavailableError on network/auth failure.
    """
    now = datetime.now(timezone.utc)
    reanalysis_cutoff = now - timedelta(days=REANALYSIS_LAG_DAYS)
    profile_dt = date if date.tzinfo else date.replace(tzinfo=timezone.utc)

    # Pick dataset based on profile age
    dataset_id = DATASET_NRT if profile_dt > reanalysis_cutoff else DATASET_REANALYSIS

    start = profile_dt - timedelta(hours=hours)
    bbox_pad = 4.0  # degrees — wide enough to cover daily drift

    try:
        ds = _cm().open_dataset(
            dataset_id=dataset_id,
            variables=["uo", "vo"],
            minimum_longitude=lon - bbox_pad,
            maximum_longitude=lon + bbox_pad,
            minimum_latitude=lat - bbox_pad,
            maximum_latitude=lat + bbox_pad,
            start_datetime=start,
            end_datetime=profile_dt,
            minimum_depth=float(depth_m - 50),
            maximum_depth=float(depth_m + 50),
            **_credentials(),
        )
    except Exception as exc:
        raise CMEMSUnavailableError(f"CMEMS fetch failed: {exc}") from exc

    return ds


def _sample_uv(
    uo,
    vo,
    depth_coord: str,
    depth_m: float,
    lon: float,
    lat: float,
    t,
) -> Tuple[float, float]:
    """Sample (u, v) from pre-loaded xarray arrays at the given position and time."""
    u = float(
        uo.sel(time=t, method="nearest")
          .sel(**{depth_coord: depth_m}, method="nearest")
          .sel(latitude=lat, longitude=lon, method="nearest")
          .values
    )
    v = float(
        vo.sel(time=t, method="nearest")
          .sel(**{depth_coord: depth_m}, method="nearest")
          .sel(latitude=lat, longitude=lon, method="nearest")
          .values
    )
    return u, v


def _rk4_step(
    uo,
    vo,
    depth_coord: str,
    depth_m: float,
    lon: float,
    lat: float,
    t,
    dt: float,
) -> Tuple[float, float, float, float]:
    """
    One RK4 backward step of duration dt (seconds).

    RK4 evaluates velocity at 4 points per step and combines them as:
        position_new = position + (dt/6) * (k1 + 2*k2 + 2*k3 + k4)

    For back-tracking dt is negative (we move backwards in time).

    Returns (new_lon, new_lat, u_at_start, v_at_start).
    """
    # k1 — velocity at current position / current time
    u1, v1 = _sample_uv(uo, vo, depth_coord, depth_m, lon, lat, t)
    if isnan(u1) or isnan(v1):
        raise ValueError("NaN at k1")

    # Convert k1 to degree/second displacements
    dlat1 = v1 / 111000.0
    dlon1 = u1 / (111000.0 * cos(radians(lat)))

    # Midpoint estimate (half-step) — still use nearest time since data is daily
    lat2 = lat + 0.5 * dt * dlat1
    lon2 = lon + 0.5 * dt * dlon1

    # k2 — velocity at midpoint
    u2, v2 = _sample_uv(uo, vo, depth_coord, depth_m, lon2, lat2, t)
    if isnan(u2) or isnan(v2):
        raise ValueError("NaN at k2")
    dlat2 = v2 / 111000.0
    dlon2 = u2 / (111000.0 * cos(radians(lat2)))

    # k3 — velocity at second midpoint (same half-step, different velocity estimate)
    lat3 = lat + 0.5 * dt * dlat2
    lon3 = lon + 0.5 * dt * dlon2

    u3, v3 = _sample_uv(uo, vo, depth_coord, depth_m, lon3, lat3, t)
    if isnan(u3) or isnan(v3):
        raise ValueError("NaN at k3")
    dlat3 = v3 / 111000.0
    dlon3 = u3 / (111000.0 * cos(radians(lat3)))

    # k4 — velocity at full-step endpoint
    lat4 = lat + dt * dlat3
    lon4 = lon + dt * dlon3

    u4, v4 = _sample_uv(uo, vo, depth_coord, depth_m, lon4, lat4, t)
    if isnan(u4) or isnan(v4):
        raise ValueError("NaN at k4")
    dlat4 = v4 / 111000.0
    dlon4 = u4 / (111000.0 * cos(radians(lat4)))

    # Weighted combination (RK4 weights: 1/6, 2/6, 2/6, 1/6)
    new_lat = lat + (dt / 6.0) * (dlat1 + 2 * dlat2 + 2 * dlat3 + dlat4)
    new_lon = lon + (dt / 6.0) * (dlon1 + 2 * dlon2 + 2 * dlon3 + dlon4)

    return new_lon, new_lat, u1, v1


def backtrack(
    lon: float,
    lat: float,
    date: datetime,
    depth_m: int = 1000,
    hours: int = 168,
) -> BacktrackResult:
    """
    RK4 daily back-tracking: estimate where the water mass at (lon, lat, depth_m)
    at `date` originated `hours` hours earlier.

    Uses 4th-order Runge-Kutta integration for significantly better accuracy than
    the previous Euler method (error scales as O(dt⁴) vs O(dt²)).
    Steps backward one day at a time through CMEMS daily velocity data.
    Stops early if a NaN velocity (land mask) is encountered.
    """
    ds = fetch_currents(lon, lat, date, depth_m, hours)

    # Determine depth coordinate name — CMEMS uses 'depth' or 'elevation'
    depth_coord = "depth" if "depth" in ds.coords else "elevation"

    # Load data into memory (small subset — typically < 5 MB)
    uo = ds.uo.load()
    vo = ds.vo.load()

    cur_lon, cur_lat = lon, lat
    path: List[Tuple[float, float]] = [(cur_lon, cur_lat)]
    u_values, v_values = [], []

    # Iterate backwards through daily timesteps (most recent first)
    time_steps = sorted(ds.time.values)[::-1]
    dt_seconds = -86400.0  # negative = backward in time

    for t in time_steps:
        try:
            new_lon, new_lat, u1, v1 = _rk4_step(
                uo, vo, depth_coord, float(depth_m),
                cur_lon, cur_lat, t, dt_seconds,
            )
        except (ValueError, Exception):
            break  # NaN or coordinate lookup failed — stop here

        u_values.append(u1)
        v_values.append(v1)

        cur_lat = max(-89.9, min(89.9, new_lat))
        cur_lon = ((new_lon + 180) % 360) - 180  # wrap longitude

        path.append((cur_lon, cur_lat))

    u_arr = np.array(u_values) if u_values else np.zeros(1)
    v_arr = np.array(v_values) if v_values else np.zeros(1)
    u_mean = float(np.nanmean(u_arr))
    v_mean = float(np.nanmean(v_arr))
    speed = float(np.nanmean(np.sqrt(u_arr**2 + v_arr**2))) * 100  # m/s → cm/s

    return BacktrackResult(
        path=path,
        origin=path[-1],
        u_mean=round(u_mean, 4),
        v_mean=round(v_mean, 4),
        speed_cms=round(speed, 2),
        steps_completed=len(u_values),
    )
