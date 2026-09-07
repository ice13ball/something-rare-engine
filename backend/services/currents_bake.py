# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Bake global CMEMS ocean-current u/v fields into RGBA particle textures.

Encoding: R = u, G = v (both scaled from [UNSCALE_MIN, UNSCALE_MAX] m/s into
0-255), B = 0, A = 255 for water / 0 for land+NaN. WeatherLayers ParticleLayer
decodes this with imageType VECTOR + imageUnscale [UNSCALE_MIN, UNSCALE_MAX].
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import shutil
from datetime import datetime, timezone, timedelta, date

import numpy as np

# Heavy deps imported lazily inside bake_depth() so the encoder functions
# remain importable in test environments where these packages are absent.
try:
    import copernicusmarine as _copernicusmarine
    from PIL import Image as _Image
    _DEPS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _DEPS_AVAILABLE = False

log = logging.getLogger("currents_bake")

# Same NRT analysis/forecast dataset family used by services/ocean_currents.py
DATASET_NRT = "cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m"

CACHE_DIR = pathlib.Path(os.getenv("CURRENTS_CACHE_DIR", "/var/cache/abyssal-currents"))

# depth slug -> target depth in metres (matches frontend depth selector)
DEPTHS: dict[str, float] = {"surface": 0.0, "1000m": 1000.0}

# Downsample target: ~0.5 degree grid (0.083 deg native -> coarsen factor 6)
COARSEN_FACTOR = 6
BOUNDS = [-180.0, -90.0, 180.0, 90.0]  # [west, south, east, north] — CMEMS request box

# A coarse cell aggregates COARSEN_FACTOR^2 native cells. Plain mean(skipna) marks
# a cell as water if even ONE sub-cell is wet, so mostly-land coastal cells get
# painted as ocean and particles bleed inland. Require at least this fraction of
# sub-cells to be wet before a coarse cell counts as water.
COASTAL_WATER_FRAC_MIN = 0.4


def _credentials() -> dict:
    username = os.getenv("CMEMS_USERNAME")
    password = os.getenv("CMEMS_PASSWORD")
    if not username or not password:
        raise RuntimeError("CMEMS_USERNAME or CMEMS_PASSWORD not set in environment")
    return {"username": username, "password": password}

UNSCALE_MIN = -3.0   # m/s — covers strong western-boundary currents
UNSCALE_MAX = 3.0

# History window for the date slider. The existing DATASET_NRT
# ("cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m") was verified live on the VPS to
# span 2022-06-01 -> 2026-06-18, so a single product covers any 180-day window —
# no reanalysis / age-split needed (the reanalysis lags ~42 days anyway).
CURRENTS_HISTORY_DAYS = 180
CURRENTS_PRUNE_KEEP_DAYS = 185


def encode_uv_to_rgba(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Encode (u, v) velocity arrays into an (H, W, 4) uint8 RGBA array.

    NaN cells (land mask / no data) become fully transparent so particles do
    not spawn or freeze on them. Values are clamped to [UNSCALE_MIN, UNSCALE_MAX].
    """
    span = UNSCALE_MAX - UNSCALE_MIN
    mask = np.isnan(u) | np.isnan(v)

    u_filled = np.nan_to_num(u, nan=0.0)
    v_filled = np.nan_to_num(v, nan=0.0)

    def to_channel(arr):
        scaled = (np.clip(arr, UNSCALE_MIN, UNSCALE_MAX) - UNSCALE_MIN) / span
        return np.round(scaled * 255.0).astype("uint8")

    h, w = u.shape
    rgba = np.zeros((h, w, 4), dtype="uint8")
    rgba[..., 0] = to_channel(u_filled)
    rgba[..., 1] = to_channel(v_filled)
    rgba[..., 2] = 0
    rgba[..., 3] = np.where(mask, 0, 255).astype("uint8")
    return rgba


def bake_depth(depth_slug: str, target_date: "datetime | date | None" = None) -> dict:
    """Fetch, downsample and encode the global current field for one depth.

    Writes dated PNG/JSON files and refreshes the latest.* pointer. Returns the
    metadata dict. Raises on CMEMS/credential failure (caller keeps old texture).

    target_date: a datetime/date/None. None = most recent available (default).
    """
    if not _DEPS_AVAILABLE:
        raise RuntimeError("copernicusmarine / Pillow not installed — cannot bake")
    if depth_slug not in DEPTHS:
        raise ValueError(f"unknown depth slug: {depth_slug}")
    depth_m = DEPTHS[depth_slug]

    now = datetime.now(timezone.utc)
    if target_date is None:
        start, end = now - timedelta(days=4), now  # end=now -> no forecast day
        select_time = None
    else:
        tgt = target_date if isinstance(target_date, datetime) else datetime(
            target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc
        )
        # Guard: NRT covers ~2022-06-01..today; skip out-of-range / forecast dates.
        if tgt > now or tgt < datetime(2022, 6, 1, tzinfo=timezone.utc):
            raise ValueError(f"date {tgt:%Y-%m-%d} outside NRT coverage")
        start, end = tgt - timedelta(days=1), tgt + timedelta(days=1)
        select_time = tgt

    ds = _copernicusmarine.open_dataset(
        dataset_id=DATASET_NRT,
        variables=["uo", "vo"],
        minimum_longitude=BOUNDS[0], maximum_longitude=BOUNDS[2],
        minimum_latitude=BOUNDS[1], maximum_latitude=BOUNDS[3],
        start_datetime=start, end_datetime=end,
        minimum_depth=float(depth_m), maximum_depth=float(depth_m) + 1.0,
        **_credentials(),
    )
    try:
        depth_coord = "depth" if "depth" in ds.coords else "elevation"
        if select_time is None:
            sub = ds.isel(time=-1)
        else:
            sub = ds.sel(time=np.datetime64(select_time.replace(tzinfo=None)), method="nearest")
        sub = sub.sel(**{depth_coord: depth_m}, method="nearest")
        # Water fraction per coarse cell (mean of the native wet/dry mask), then
        # coarsen the velocities. Cells below COASTAL_WATER_FRAC_MIN are re-masked
        # to NaN so mostly-land coastal cells stop rendering as ocean.
        wet_frac = sub["uo"].notnull().coarsen(
            longitude=COARSEN_FACTOR, latitude=COARSEN_FACTOR, boundary="trim"
        ).mean()
        sub = sub.coarsen(
            longitude=COARSEN_FACTOR, latitude=COARSEN_FACTOR, boundary="trim"
        ).mean()
        sub = sub.where(wet_frac >= COASTAL_WATER_FRAC_MIN)

        # xarray latitude is ascending (south->north). Image rows must run
        # north->south (top-left = NW) to match the bounds convention.
        sub = sub.sortby("latitude", ascending=False)

        # Derive output bounds from the ACTUAL coarsened grid, not the global
        # request box. CMEMS global-phys latitude spans ~-80..90 (NOT -90..90),
        # and coarsen(boundary="trim") drops the remainder — so the hardcoded
        # BOUNDS stretched the texture vertically and slid ocean data ~2deg onto
        # land (currents rendered over Germany/Poland). Use pixel-center extents
        # to match the frontend sampler's (width-1)/(height-1) mapping.
        out_lats = sub["latitude"].values
        out_lons = sub["longitude"].values
        out_bounds = [
            float(np.min(out_lons)), float(np.min(out_lats)),
            float(np.max(out_lons)), float(np.max(out_lats)),
        ]

        u = sub["uo"].squeeze().values.astype("float32")
        v = sub["vo"].squeeze().values.astype("float32")
        if u.ndim != 2 or v.ndim != 2:
            raise RuntimeError(f"expected 2-D uo/vo grids, got {u.shape} / {v.shape}")
        rgba = encode_uv_to_rgba(u, v)

        sel_time = sub["time"].values if "time" in sub.coords else (
            ds.time.values[-1] if select_time is None else np.datetime64(select_time.replace(tzinfo=None))
        )
        actual_time = str(np.datetime_as_string(np.array(sel_time).reshape(-1)[-1], unit="D"))

        out_dir = CACHE_DIR / depth_slug
        out_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "url": f"/v1/currents/{depth_slug}.png?date={actual_time}",
            "bounds": out_bounds,
            "imageUnscale": [UNSCALE_MIN, UNSCALE_MAX],
            "date": actual_time,
            "depth_m": depth_m,
            "depth_label": "Surface" if depth_slug == "surface" else "1000 m",
            "width": int(rgba.shape[1]),
            "height": int(rgba.shape[0]),
        }
        _write_dated(out_dir, actual_time, rgba, meta)
        _refresh_latest_pointer(out_dir)
        log.info("currents bake %s: %dx%d, date=%s", depth_slug, rgba.shape[1], rgba.shape[0], actual_time)
        return meta
    finally:
        ds.close()


def _write_dated(out_dir: pathlib.Path, date_str: str, rgba: "np.ndarray", meta: dict) -> None:
    png_tmp = out_dir / f"{date_str}.png.tmp"
    _Image.fromarray(rgba, "RGBA").save(png_tmp, format="PNG", optimize=True)
    os.replace(png_tmp, out_dir / f"{date_str}.png")
    json_tmp = out_dir / f"{date_str}.json.tmp"
    json_tmp.write_text(json.dumps(meta))
    os.replace(json_tmp, out_dir / f"{date_str}.json")


def _refresh_latest_pointer(out_dir):
    """Point latest.png/json at the newest dated file (back-compat). Atomic."""
    dates = sorted(p.stem for p in out_dir.glob("*.png")
                   if p.stem != "latest" and len(p.stem) == 10)
    if not dates:
        return
    newest = dates[-1]
    json_path = out_dir / f"{newest}.json"
    if not json_path.is_file():
        log.warning("currents: missing sibling %s — skipping latest pointer refresh", json_path)
        return
    png_tmp = out_dir / "latest.png.tmp"
    shutil.copyfile(out_dir / f"{newest}.png", png_tmp)
    os.replace(png_tmp, out_dir / "latest.png")
    meta = json.loads(json_path.read_text())
    meta = {**meta, "url": f"/v1/currents/{out_dir.name}.png"}  # no-date pointer
    json_tmp = out_dir / "latest.json.tmp"
    json_tmp.write_text(json.dumps(meta))
    os.replace(json_tmp, out_dir / "latest.json")


def available_dates(depth_slug: str) -> list[str]:
    out_dir = CACHE_DIR / depth_slug
    if not out_dir.is_dir():
        return []
    return sorted(p.stem for p in out_dir.glob("*.png")
                  if p.stem != "latest" and len(p.stem) == 10)


def prune_old(depth_slug: str, keep_days: int = CURRENTS_PRUNE_KEEP_DAYS) -> int:
    out_dir = CACHE_DIR / depth_slug
    if not out_dir.is_dir():
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    removed = 0
    for p in out_dir.glob("*.png"):
        if p.stem == "latest" or len(p.stem) != 10:
            continue
        if p.stem < cutoff:
            p.unlink(missing_ok=True)
            (out_dir / f"{p.stem}.json").unlink(missing_ok=True)
            removed += 1
    return removed


def read_meta(depth_slug: str, target_date: str | None = None) -> dict | None:
    """Return the cached metadata for a depth, or None if not yet baked."""
    name = "latest" if not target_date else target_date
    p = CACHE_DIR / depth_slug / f"{name}.json"
    return json.loads(p.read_text()) if p.is_file() else None


def texture_path(depth_slug: str, target_date: str | None = None) -> pathlib.Path | None:
    """Return the cached PNG path for a depth, or None if not yet baked."""
    name = "latest" if not target_date else target_date
    p = CACHE_DIR / depth_slug / f"{name}.png"
    return p if p.is_file() else None
