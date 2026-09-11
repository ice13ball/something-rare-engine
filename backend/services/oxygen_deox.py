# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""ISAS20 BGC-Argo dissolved-oxygen gridded fields (SEANOE DOI 10.17882/52367,
CC-BY 4.0): downloader, baker, and pure colour/resample helpers. Heavy deps
(xarray/PIL) are imported lazily so the pure functions stay test-importable.

Two views: 'recent' = absolute O2 (2014-2018); 'change' = recent minus the WOA
WOA23N 1971-2000 'Climate Normal' baseline (services.woa_climatology),
i.e. deoxygenation. ⛔ Not '~1980s' — that wording was on four user-facing
surfaces while layer_temporal_coverage.py carried NOAA's own 1971-2000.
"""
from __future__ import annotations

import logging
import os
import pathlib
import shutil
import subprocess

import numpy as np

from services.woa_climatology import (
    encode_field_to_rgba, _ramp_hex, _RAMPS, DISPLAY_DEPTHS,
)

_CURL = shutil.which("curl") or "/usr/bin/curl"
log = logging.getLogger("oxygen_deox")

CACHE_DIR = pathlib.Path(os.getenv("OXYGEN_CACHE_DIR", "/var/cache/abyssal-oxygen"))
RAW_DIR = CACHE_DIR / "raw"          # extracted NetCDF
BAKE_DIR = CACHE_DIR / "baked"       # {view}/{depth}.png

ISAS_TARBALL_URL = "https://www.seanoe.org/data/00412/52367/data/105207.tar.gz"
RECENT_PERIOD_TAG = "2014_2018"      # yearly-mean recent period used for both views

RECENT_VMIN = 0.0
RECENT_VMAX = 350.0
RECENT_CMAP = "oxy"
CHANGE_VLIM = 60.0  # µmol/kg, symmetric; tune after first VPS bake

# Diverging ramp for Δ: t=0 (max loss) deep red -> t=0.5 (no change) pale ->
# t=1 (max gain) deep blue. (encode_change maps delta=-vlim->0, 0->0.5, +vlim->1.)
_DIVERGING: list[tuple[float, tuple[int, int, int]]] = [
    (0.0, (130, 20, 30)),
    (0.25, (210, 90, 70)),
    (0.5, (245, 240, 225)),
    (0.75, (80, 140, 195)),
    (1.0, (20, 60, 140)),
]


def hex_feature(lat: float, lon: float, value: float, geometry: dict) -> dict:
    """One GeoJSON hex Feature: hex polygon geometry + centroid lat/lon + field value."""
    return {"type": "Feature", "geometry": geometry,
            "properties": {"lat": float(lat), "lon": float(lon), "value": float(value)}}


def encode_change_to_rgba(delta: np.ndarray, vlim: float) -> np.ndarray:
    """Encode a (H,W) Δ-O₂ field to (H,W,4) RGBA via the diverging ramp. NaN -> transparent."""
    mask = np.isnan(delta)
    span = (2.0 * vlim) or 1.0
    t = np.clip((np.nan_to_num(delta, nan=0.0) + vlim) / span, 0.0, 1.0)
    pos = np.array([a[0] for a in _DIVERGING])
    cols = np.array([a[1] for a in _DIVERGING], dtype="float32")
    rgb = np.empty((*t.shape, 3), dtype="float32")
    for ch in range(3):
        rgb[..., ch] = np.interp(t, pos, cols[:, ch])
    rgba = np.zeros((*delta.shape, 4), dtype="uint8")
    rgba[..., :3] = np.round(rgb).astype("uint8")
    rgba[..., 3] = np.where(mask, 0, 255).astype("uint8")
    return rgba


# Recent-view target: a regular 0.5° global raster, rows north→south, cols −180..179.5.
RECENT_TGT_LATS = np.linspace(89.75, -89.75, 360).astype("float64")
RECENT_TGT_LONS = np.linspace(-180.0, 179.5, 720).astype("float64")


def regrid_nearest(src_vals: np.ndarray, src_lats: np.ndarray, src_lons: np.ndarray,
                   tgt_lats: np.ndarray, tgt_lons: np.ndarray) -> np.ndarray:
    """Nearest-neighbour regrid a (src_lat, src_lon) field onto (tgt_lat, tgt_lon).
    Target rows whose latitude lies outside the source latitude coverage are set to
    NaN — we never fabricate polar data the source doesn't have (ISAS stops at ~−77°)."""
    src_lats = np.asarray(src_lats, dtype="float64")
    src_lons = np.asarray(src_lons, dtype="float64")
    tgt_lats = np.asarray(tgt_lats, dtype="float64")
    tgt_lons = np.asarray(tgt_lons, dtype="float64")
    lat_idx = np.abs(tgt_lats[:, None] - src_lats[None, :]).argmin(axis=1)
    lon_idx = np.abs(tgt_lons[:, None] - src_lons[None, :]).argmin(axis=1)
    out = src_vals[np.ix_(lat_idx, lon_idx)].astype("float32")
    lo, hi = float(np.min(src_lats)), float(np.max(src_lats))
    outside = (tgt_lats < lo) | (tgt_lats > hi)
    out[outside, :] = np.nan
    return out


def diverging_ramp_hex() -> list[dict]:
    return [{"pos": p, "hex": "#%02x%02x%02x" % rgb} for p, rgb in _DIVERGING]



# Candidate NetCDF names (confirmed in Task 2 Step 1; adjust if discovery differs).
ISAS_DOXY_VARS = ("DOXY", "doxy", "O2", "DOX")          # analyzed-field var candidates
ISAS_LAT_NAMES = ("latitude", "lat")
ISAS_LON_NAMES = ("longitude", "lon")
ISAS_DEPTH_NAMES = ("depth", "PRES", "pressure")


def ensure_holdings() -> bool:
    """Download + extract the ISAS DOXY tarball once. True if raw NetCDF present."""
    if list(RAW_DIR.rglob("*.nc")):
        return True
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    tarball = CACHE_DIR / "doxy.tar.gz"
    try:
        subprocess.run(
            [_CURL, "-4", "-fsSL", "--connect-timeout", "30", "--max-time", "1800",
             "-o", str(tarball), ISAS_TARBALL_URL],
            check=True,
        )
        if not tarball.is_file() or tarball.stat().st_size == 0:
            raise RuntimeError("empty download")
        import tarfile  # lazy
        with tarfile.open(tarball, "r:gz") as tf:
            tf.extractall(RAW_DIR, filter="data")
        log.info("oxygen: extracted ISAS DOXY holdings")
        return bool(list(RAW_DIR.rglob("*.nc")))
    except Exception as exc:
        log.warning("oxygen: holdings fetch failed: %s", exc)
        return False


def _recent_file() -> pathlib.Path | None:
    """The 2014-2018 analyzed-field (_fld_) DOXY NetCDF. Period is in the directory
    name (…2014_2018…); the filename is dated by midpoint, so match on the full path."""
    cands = [p for p in RAW_DIR.rglob("*.nc")
             if "2014_2018" in str(p) and "_fld_" in p.name]
    if not cands:  # fallback: both years anywhere in the path, prefer the field file
        cands = [p for p in RAW_DIR.rglob("*.nc")
                 if "2014" in str(p) and "2018" in str(p) and "_fld_" in p.name]
    return cands[0] if cands else None


def _first_var(ds, names):
    for n in names:
        if n in ds.variables:
            return n
    return None


class _IsasGrid:
    __slots__ = ("lats", "lons", "depths", "data")

    def __init__(self, lats, lons, depths, data):
        self.lats, self.lons, self.depths, self.data = lats, lons, depths, data


_RECENT_CACHE: _IsasGrid | None = None


def load_recent_grid() -> "_IsasGrid | None":
    """Load (and cache) the 2014-2018 annual DOXY grid (depth,lat,lon), 0.5°."""
    global _RECENT_CACHE
    if _RECENT_CACHE is not None:
        return _RECENT_CACHE
    path = _recent_file()
    if path is None:
        return None
    import xarray as xr  # lazy
    ds = xr.open_dataset(path, decode_times=False)
    try:
        vn = _first_var(ds, ISAS_DOXY_VARS)
        la = _first_var(ds, ISAS_LAT_NAMES)
        lo = _first_var(ds, ISAS_LON_NAMES)
        de = _first_var(ds, ISAS_DEPTH_NAMES)
        if not all((vn, la, lo, de)):
            log.warning("oxygen: could not resolve ISAS var/coord names: %s", list(ds.variables))
            return None
        da = ds[vn].squeeze()  # drop singleton time
        grid = _IsasGrid(
            lats=ds[la].values.astype("float64"),
            lons=ds[lo].values.astype("float64"),
            depths=ds[de].values.astype("float64"),
            data=np.asarray(da.values, dtype="float32"),  # (depth, lat, lon)
        )
    finally:
        ds.close()
    grid.data[np.abs(grid.data) > 1e30] = np.nan  # fill -> NaN
    # Normalize longitude to -180..180 if the source uses 0..360 (ISAS may be either).
    # The frontend tile bounds and the WOA baseline both assume -180..180, so an
    # un-rolled 0..360 grid would wrap the recent view and misalign the Δ subtraction.
    if float(np.nanmax(grid.lons)) > 180.0:
        shifted = ((grid.lons + 180.0) % 360.0) - 180.0
        order = np.argsort(shifted)
        grid.lons = shifted[order]
        grid.data = grid.data[:, :, order]
    _RECENT_CACHE = grid
    return grid


def _nearest_idx(coords: np.ndarray, value: float) -> int:
    return int(np.abs(coords - value).argmin())


def nearest_grid_value(lats, lons, depths, data, lat: float, lon: float, depth_m: float):
    """Nearest-cell value from a (depth, lat, lon) grid. None for NaN/fill/empty."""
    if data is None or not len(lats) or not len(lons) or not len(depths):
        return None
    di = int(np.abs(np.asarray(depths) - depth_m).argmin())
    la = int(np.abs(np.asarray(lats) - lat).argmin())
    lo = int(np.abs(np.asarray(lons) - lon).argmin())
    v = data[di, la, lo]
    if v is None or not np.isfinite(v) or abs(float(v)) > 1e30:
        return None
    return float(v)


import services.woa_climatology as _woa


def _save_rgba(rgba: np.ndarray, view: str, depth_m: int) -> dict:
    from PIL import Image  # lazy
    out_dir = BAKE_DIR / view
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / f"{depth_m}.png.tmp"
    Image.fromarray(rgba, "RGBA").save(tmp, format="PNG", optimize=True)
    os.replace(tmp, out_dir / f"{depth_m}.png")
    return {"width": int(rgba.shape[1]), "height": int(rgba.shape[0]), "depth_m": depth_m}


def bake_depth(depth_m: int) -> int:
    """Bake recent + change PNGs for one depth. Returns count baked (0 or 2).
    Recent = ISAS regridded to a regular 0.5° raster. Change = ISAS regridded to the
    WOA grid minus WOA o_an (both north-first; negative Δ = O₂ loss = red)."""
    grid = load_recent_grid()
    if grid is None:
        return 0
    wgrid = _woa._load_grid("oxygen", 0) or (_woa.ensure_grid("oxygen", 0) and _woa._load_grid("oxygen", 0))
    if wgrid is None:
        log.warning("oxygen: WOA oxygen grid missing — cannot bake at %dm", depth_m)
        return 0
    di = _nearest_idx(grid.depths, float(depth_m))
    src = grid.data[di].astype("float32")  # (src_lat, src_lon)

    # recent view — regular 0.5° north-first raster
    recent = regrid_nearest(src, grid.lats, grid.lons, RECENT_TGT_LATS, RECENT_TGT_LONS)
    _save_rgba(encode_field_to_rgba(recent, RECENT_VMIN, RECENT_VMAX, RECENT_CMAP), "recent", depth_m)

    # change view — regrid ISAS onto the WOA grid (north-first) then subtract WOA o_an
    woa_lats = np.asarray(wgrid.lats, dtype="float64")
    woa_lons = np.asarray(wgrid.lons, dtype="float64")
    tgt_lats = woa_lats[::-1] if woa_lats[0] < woa_lats[-1] else woa_lats  # north-first
    recent_woa = regrid_nearest(src, grid.lats, grid.lons, tgt_lats, woa_lons)
    wdi = _woa._nearest_idx(wgrid.depths, float(depth_m))
    woa_field = wgrid.data[wdi].astype("float32").copy()
    woa_field[np.abs(woa_field) > 1e30] = np.nan
    woa_n = woa_field[::-1, :] if woa_lats[0] < woa_lats[-1] else woa_field
    delta = recent_woa - woa_n
    _save_rgba(encode_change_to_rgba(delta, CHANGE_VLIM), "change", depth_m)
    return 2


def bake_all() -> int:
    if not ensure_holdings():
        return 0
    return sum(bake_depth(d) for d in DISPLAY_DEPTHS)


def baked_png_path(view: str, depth_m: int) -> pathlib.Path | None:
    p = BAKE_DIR / view / f"{depth_m}.png"
    return p if p.is_file() else None


def build_meta() -> dict:
    views = []
    rec_depths = [d for d in DISPLAY_DEPTHS if baked_png_path("recent", d)]
    chg_depths = [d for d in DISPLAY_DEPTHS if baked_png_path("change", d)]
    if rec_depths:
        views.append({"key": "recent", "label": "Recent O₂ (2014–2018)", "units": "µmol/kg",
                      "vmin": RECENT_VMIN, "vmax": RECENT_VMAX, "cmap": RECENT_CMAP,
                      "ramp": _ramp_hex(RECENT_CMAP), "depths": rec_depths, "diverging": False})
    if chg_depths:
        views.append({"key": "change", "label": "Deoxygenation Δ (vs 1971-2000)", "units": "µmol/kg",
                      "vmin": -CHANGE_VLIM, "vmax": CHANGE_VLIM, "cmap": "diverging",
                      "ramp": diverging_ramp_hex(), "depths": chg_depths, "diverging": True})
    return {"views": views, "depths": DISPLAY_DEPTHS,
            "attribution": "ISAS20 BGC-Argo O₂ (Kolodziejczyk et al. 2024; SEANOE 10.17882/52367, CC-BY 4.0); baseline WOA23 (NOAA NCEI)."}
