# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""World Ocean Atlas 2023 climatology: shared NetCDF holdings, point sampler,
and colour-map PNG baker. Heavy deps (xarray/netCDF4/PIL) are imported lazily so
the pure config + encoder functions stay importable in test environments.

Source: NOAA NCEI WOA23 (public domain). Citation: Reagan, J.R. et al. (2024),
World Ocean Atlas 2023, NCEI Accession 0270533.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import shutil
import subprocess

import numpy as np

# Absolute curl path: the systemd service runs with PATH=.venv/bin only, so a
# bare "curl" subprocess raises FileNotFoundError. Resolve at import with a
# hardcoded fallback to the standard location.
_CURL = shutil.which("curl") or "/usr/bin/curl"

log = logging.getLogger("woa_climatology")

CACHE_DIR = pathlib.Path(os.getenv("WOA_CACHE_DIR", "/var/cache/abyssal-woa"))
BAKE_DIR = CACHE_DIR / "baked"

# var key -> NCEI metadata. `folder` = DATA subdir (case-sensitive — AOU is upper);
# `code` = NCEI var letter (case-sensitive — o2sat is "O", oxygen "o", aou "A");
# `period` = WOA period token (CONFIRMED against the live index);
# `an_var` = NetCDF variable holding the objectively analyzed mean. vmin/vmax =
# fixed display range so colours compare across depths.
WOA_VARS: dict[str, dict] = {
    "temperature": dict(folder="temperature", code="t", period="decav91C0", an_var="t_an", units="°C",      vmin=-2.0, vmax=32.0, cmap="thermal", label="Temperature",   baseline="1991–2020"),
    "salinity":    dict(folder="salinity",    code="s", period="decav91C0", an_var="s_an", units="PSU",     vmin=30.0, vmax=38.0, cmap="haline",  label="Salinity",      baseline="1991–2020"),
    "oxygen":      dict(folder="oxygen",      code="o", period="decav71A0", an_var="o_an", units="µmol/kg", vmin=0.0,  vmax=350.0, cmap="oxy",     label="Dissolved O₂",  baseline="1971–2000"),
    "aou":         dict(folder="AOU",         code="A", period="decav71A0", an_var="A_an", units="µmol/kg", vmin=-25.0, vmax=200.0, cmap="matter", label="AOU",           baseline="1971–2000"),
    "o2sat":       dict(folder="o2sat",       code="O", period="decav71A0", an_var="O_an", units="%",       vmin=0.0,  vmax=110.0, cmap="oxy",     label="O₂ saturation", baseline="1971–2000"),
    "phosphate":   dict(folder="phosphate",   code="p", period="all",       an_var="p_an", units="µmol/kg", vmin=0.0,  vmax=3.5,   cmap="matter",  label="Phosphate",     baseline="1965–2022"),
    "silicate":    dict(folder="silicate",    code="i", period="all",       an_var="i_an", units="µmol/kg", vmin=0.0,  vmax=180.0, cmap="matter",  label="Silicate",      baseline="1965–2022"),
    "nitrate":     dict(folder="nitrate",     code="n", period="all",       an_var="n_an", units="µmol/kg", vmin=0.0,  vmax=45.0,  cmap="matter",  label="Nitrate",       baseline="1965–2022"),
}

DISPLAY_DEPTHS = [0, 50, 100, 200, 500, 1000, 1500, 2000]

# Anchor-colour ramps (pos 0..1 -> RGB). Linear-interpolated; perceptual enough
# for a translucent overlay without pulling in matplotlib.
_RAMPS: dict[str, list[tuple[float, tuple[int, int, int]]]] = {
    "thermal": [(0.0, (3, 35, 92)), (0.35, (40, 110, 170)), (0.6, (180, 200, 130)), (0.8, (235, 170, 70)), (1.0, (170, 30, 30))],
    "haline":  [(0.0, (40, 30, 90)), (0.4, (30, 110, 130)), (0.7, (60, 175, 130)), (1.0, (235, 240, 150))],
    "oxy":     [(0.0, (120, 20, 30)), (0.25, (200, 90, 40)), (0.5, (235, 200, 120)), (0.75, (90, 170, 200)), (1.0, (20, 60, 150))],
    "matter":  [(0.0, (250, 245, 220)), (0.4, (220, 160, 110)), (0.7, (170, 70, 110)), (1.0, (70, 20, 80))],
}


def _ramp_lookup(t: np.ndarray, cmap: str) -> np.ndarray:
    """Map t in [0,1] (H,W) to (H,W,3) uint8 via the named anchor ramp."""
    anchors = _RAMPS[cmap]
    pos = np.array([a[0] for a in anchors])
    cols = np.array([a[1] for a in anchors], dtype="float32")
    out = np.empty((*t.shape, 3), dtype="float32")
    for ch in range(3):
        out[..., ch] = np.interp(t, pos, cols[:, ch])
    return np.round(out).astype("uint8")


def encode_field_to_rgba(arr: np.ndarray, vmin: float, vmax: float, cmap: str) -> np.ndarray:
    """Encode a (H,W) climatology field to (H,W,4) RGBA. NaN -> transparent."""
    mask = np.isnan(arr)
    span = (vmax - vmin) or 1.0
    t = np.clip((np.nan_to_num(arr, nan=vmin) - vmin) / span, 0.0, 1.0)
    rgb = _ramp_lookup(t, cmap)
    rgba = np.zeros((*arr.shape, 4), dtype="uint8")
    rgba[..., :3] = rgb
    rgba[..., 3] = np.where(mask, 0, 255).astype("uint8")
    return rgba


# ──────────────────────────────────────────────────────────────────────────────
# Sub-task A: holdings downloader
# ──────────────────────────────────────────────────────────────────────────────

_BASE = "https://www.ncei.noaa.gov/data/oceans/woa/WOA23/DATA"


def _grid_filename(var_key: str, tt: int) -> str:
    """tt: 00=annual, 01-12=monthly. 1° grid code is '01'."""
    code = WOA_VARS[var_key]["code"]
    period = WOA_VARS[var_key]["period"]
    return f"woa23_{period}_{code}{tt:02d}_01.nc"


def _grid_url(var_key: str, tt: int) -> str:
    cfg = WOA_VARS[var_key]
    return f"{_BASE}/{cfg['folder']}/netcdf/{cfg['period']}/1.00/{_grid_filename(var_key, tt)}"


def _local_path(var_key: str, tt: int) -> pathlib.Path:
    return CACHE_DIR / var_key / _grid_filename(var_key, tt)


def ensure_grid(var_key: str, tt: int) -> pathlib.Path | None:
    """Download one WOA grid file if absent. Returns local path, or None on failure.

    Annual (tt=00) is always available. Monthly files only exist for some
    variables — a 404 returns None and the caller falls back."""
    dest = _local_path(var_key, tt)
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = _grid_url(var_key, tt)
    tmp = dest.with_suffix(".nc.tmp")
    # Use `curl -4`, NOT urllib/httpx: NCEI publishes AAAA records but its IPv6
    # endpoint is black-holed from the VPS, and Python's clients connect to the
    # first-resolved (IPv6) address and stall the full timeout per file. curl
    # races IPv4/IPv6 (Happy Eyeballs); -4 pins IPv4 directly.
    try:
        subprocess.run(
            [_CURL, "-4", "-fsSL", "--connect-timeout", "30", "--max-time", "600",
             "-o", str(tmp), url],
            check=True,
        )
        if not tmp.is_file() or tmp.stat().st_size == 0:
            raise RuntimeError("empty download")
        os.replace(tmp, dest)
        log.info("woa: downloaded %s", dest.name)
        return dest
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        log.warning("woa: download failed %s: %s", url, exc)
        return None


def ensure_all_grids() -> int:
    """Ensure annual grid for every variable + monthly grids for the anomaly vars
    (T/S/O₂, used by month-matched point sampling). Returns count present."""
    have = 0
    for var_key in WOA_VARS:
        if ensure_grid(var_key, 0):  # annual
            have += 1
    for var_key in ("temperature", "salinity", "oxygen"):
        for mm in range(1, 13):
            ensure_grid(var_key, mm)  # monthly; missing months tolerated
    return have


# ──────────────────────────────────────────────────────────────────────────────
# Sub-task B: point sampler
# ──────────────────────────────────────────────────────────────────────────────

MONTHLY_DEPTH_LIMIT_M = 1500.0  # WOA monthly fields don't extend deeper

_GRID_CACHE: dict[tuple[str, int], "_Grid"] = {}


class _Grid:
    """Loaded WOA grid: lats/lons/depths coord arrays + (depth,lat,lon) data."""
    __slots__ = ("lats", "lons", "depths", "data")

    def __init__(self, lats, lons, depths, data):
        self.lats, self.lons, self.depths, self.data = lats, lons, depths, data


def _load_grid(var_key: str, tt: int) -> "_Grid | None":
    """Load (and cache) a WOA grid from disk. Lazily imports xarray."""
    key = (var_key, tt)
    if key in _GRID_CACHE:
        return _GRID_CACHE[key]
    path = _local_path(var_key, tt)
    if not path.is_file():
        return None
    import xarray as xr  # lazy
    an = WOA_VARS[var_key]["an_var"]
    ds = xr.open_dataset(path, decode_times=False)
    try:
        da = ds[an].squeeze()  # drops the singleton time dim
        grid = _Grid(
            lats=ds["lat"].values.astype("float64"),
            lons=ds["lon"].values.astype("float64"),
            depths=ds["depth"].values.astype("float64"),
            data=np.asarray(da.values, dtype="float32"),  # (depth, lat, lon)
        )
    finally:
        ds.close()
    _GRID_CACHE[key] = grid
    return grid


def _nearest_idx(coords: np.ndarray, value: float) -> int:
    return int(np.abs(coords - value).argmin())


def sample(var_key: str, lat: float, lon: float, depth_m: float,
           month: int | None) -> float | None:
    """Nearest-cell climatology value at (lat, lon, depth). Month-matched in the
    upper ocean (≤1500 m) when a monthly grid exists; annual otherwise.
    Returns None for land / fill / missing grid."""
    if var_key not in WOA_VARS:
        return None
    tt = 0
    if month and 1 <= month <= 12 and depth_m <= MONTHLY_DEPTH_LIMIT_M:
        tt = month
    grid = _load_grid(var_key, tt)
    if grid is None and tt != 0:
        grid = _load_grid(var_key, 0)  # monthly missing -> annual fallback
    if grid is None:
        return None
    di = _nearest_idx(grid.depths, depth_m)
    la = _nearest_idx(grid.lats, lat)
    lo = _nearest_idx(grid.lons, lon)
    val = grid.data[di, la, lo]
    if val is None or np.isnan(val) or abs(float(val)) > 1e30:  # WOA fill ~9.97e36
        return None
    return float(val)


def enrich_profile(lat: float, lon: float, month: int,
                    surface_depth: float, deep_depth: float | None) -> dict:
    """Sample WOA climatology for one Argo profile. Surface vars at ~0 m, the rest
    at the profile's deepest level. Returns a dict of woa_* values (None on land).

    Moved here from domains/sensors.py (backend vertical-split refactor, Phase 3,
    Task 5) — it was a ten-line pure wrapper over this module's own `sample()`
    with no Argo-specific logic beyond its return keys' `woa_*` naming. Formerly
    `sensors.woa_enrich`; callers: `domains.sensors.sync_argo_profiles` (Argo
    ingest), `main._backfill_woa_anomalies` (one-shot backfill), and
    `domains.fields.climatology.woa_sample` (the `/v1/woa/sample` endpoint)."""
    dd = deep_depth if deep_depth is not None else surface_depth
    s = sample
    return dict(
        woa_surface_temp_c=s("temperature", lat, lon, surface_depth, month),
        woa_surface_sal=s("salinity", lat, lon, surface_depth, month),
        woa_deep_temp_c=s("temperature", lat, lon, dd, month),
        woa_deep_sal=s("salinity", lat, lon, dd, month),
        woa_deep_oxygen_umol_kg=s("oxygen", lat, lon, dd, month),
        woa_deep_aou=s("aou", lat, lon, dd, month),
        woa_deep_o2sat=s("o2sat", lat, lon, dd, month),
        woa_deep_phosphate=s("phosphate", lat, lon, dd, month),
        woa_deep_silicate=s("silicate", lat, lon, dd, month),
        woa_deep_nitrate=s("nitrate", lat, lon, dd, month),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Sub-task C: bake colour PNGs
# ──────────────────────────────────────────────────────────────────────────────

def bake_variable_depth(var_key: str, depth_m: int) -> dict | None:
    """Bake one annual colour-mapped PNG for (variable, depth). Returns meta or None.
    Lazily imports PIL. Atomic temp-file write (PIL needs explicit format='PNG')."""
    cfg = WOA_VARS[var_key]
    grid = _load_grid(var_key, 0)  # annual
    if grid is None:
        if ensure_grid(var_key, 0) is None:
            return None
        grid = _load_grid(var_key, 0)
        if grid is None:
            return None
    from PIL import Image  # lazy

    di = _nearest_idx(grid.depths, float(depth_m))
    field = grid.data[di].astype("float32").copy()  # (lat, lon)
    field[np.abs(field) > 1e30] = np.nan  # WOA fill -> NaN (transparent)

    lats = grid.lats
    if lats[0] < lats[-1]:
        field = field[::-1, :]
        lat_min, lat_max = float(lats[0]), float(lats[-1])
    else:
        lat_min, lat_max = float(lats[-1]), float(lats[0])
    lon_min, lon_max = float(grid.lons.min()), float(grid.lons.max())

    rgba = encode_field_to_rgba(field, cfg["vmin"], cfg["vmax"], cfg["cmap"])
    out_dir = BAKE_DIR / var_key
    out_dir.mkdir(parents=True, exist_ok=True)
    png_tmp = out_dir / f"{depth_m}.png.tmp"
    Image.fromarray(rgba, "RGBA").save(png_tmp, format="PNG", optimize=True)
    os.replace(png_tmp, out_dir / f"{depth_m}.png")
    return {
        "bounds": [lon_min, lat_min, lon_max, lat_max],
        "width": int(rgba.shape[1]), "height": int(rgba.shape[0]),
        "depth_m": depth_m,
    }


def bake_all() -> int:
    """Ensure grids, then bake every (variable × DISPLAY_DEPTHS) PNG. Returns count."""
    ensure_all_grids()
    n = 0
    for var_key in WOA_VARS:
        for d in DISPLAY_DEPTHS:
            if bake_variable_depth(var_key, d):
                n += 1
    return n


def baked_png_path(var_key: str, depth_m: int) -> pathlib.Path | None:
    p = BAKE_DIR / var_key / f"{depth_m}.png"
    return p if p.is_file() else None


def _ramp_hex(cmap: str) -> list[dict]:
    """Colour-ramp anchor stops as {pos, hex} — lets the frontend draw a colour
    bar legend whose gradient exactly matches the baked PNG palette."""
    return [
        {"pos": pos, "hex": "#%02x%02x%02x" % rgb}
        for pos, rgb in _RAMPS[cmap]
    ]


def build_meta() -> dict:
    """Meta payload for /v1/woa/meta — variables, ranges, palettes, depths."""
    variables = []
    for key, c in WOA_VARS.items():
        depths = [d for d in DISPLAY_DEPTHS if baked_png_path(key, d) is not None]
        if not depths:
            continue
        variables.append({
            "key": key, "label": c["label"], "units": c["units"],
            "vmin": c["vmin"], "vmax": c["vmax"], "cmap": c["cmap"],
            "baseline": c["baseline"], "depths": depths,
            "ramp": _ramp_hex(c["cmap"]),
        })
    return {"variables": variables, "depths": DISPLAY_DEPTHS}
