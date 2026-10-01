# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Surface nutrients and productivity from the Copernicus Marine global
biogeochemical analysis-and-forecast system (monthly means, 0.25 degree).

Layer id ``ocean-nutrients-model``. Source product
GLOBAL_ANALYSISFORECAST_BGC_001_028 (DOI 10.48670/moi-00015), the PISCES
biogeochemical model forced offline by the Mercator global physics analysis,
with chlorophyll constrained by assimilated ocean-colour. ⛔ MODEL OUTPUT, not
measurements: every number this module serves must be presentable as such.

Variables served (the unit is part of the API field name, see ``VARS``):

* ``no3``   nitrate, mmol m-3
* ``chl``   chlorophyll-a, mg m-3
* ``nppv``  net primary production as a VOLUMETRIC RATE at the surface level,
            mg m-3 day-1. ⛔ NOT a water-column integral: it cannot be compared
            with satellite NPP products reported in mg C m-2 day-1.
* ``nstar`` no3 - 16 * po4, mmol m-3, derived at bake time from two real grids.
            ``po4`` itself is read but not served.

Storage (``CACHE_DIR``, env ``BGC_MODEL_CACHE_DIR``)::

    <yyyy-mm>/<var>.png     colour-mapped RGBA texture, rows run N -> S
    <yyyy-mm>/<var>.npz     float32 grid ``v``, rows run S -> N (dataset order)
    <yyyy-mm>/meta.json     grid geometry, per-variable statistics, provenance

A month directory is built under a temporary name and renamed into place only
when every variable has been fetched, computed, encoded and written. A month is
COMPLETE if and only if its ``meta.json`` exists, and ``meta.json`` is the last
file written. So an upstream failure on any one variable leaves no trace of
that month and never renders as an empty map.

Heavy dependencies (copernicusmarine, Pillow) are imported lazily and
separately, so the pure encoder and the sampler stay importable in CI.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import shutil
import uuid
from datetime import datetime, timezone

import numpy as np

from services import woa_climatology

try:
    from PIL import Image as _Image
    _PIL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PIL_AVAILABLE = False

try:
    import copernicusmarine as _copernicusmarine
except ImportError:  # pragma: no cover
    _copernicusmarine = None

log = logging.getLogger("bgc_model")

SYNC_SOURCE = "ocean-nutrients-model"
LAYER_ID = "ocean-nutrients-model"

CACHE_DIR = pathlib.Path(os.getenv("BGC_MODEL_CACHE_DIR", "/var/cache/abyssal-bgc"))

MONTHS_KEPT = 12

PRODUCT_ID = "GLOBAL_ANALYSISFORECAST_BGC_001_028"
PRODUCT_TITLE = "Global Ocean Biogeochemistry Analysis and Forecast"
PRODUCT_DOI = "10.48670/moi-00015"
PRODUCT_DOI_URL = f"https://doi.org/{PRODUCT_DOI}"
PRODUCT_URL = f"https://data.marine.copernicus.eu/product/{PRODUCT_ID}/description"
LICENCE_URL = "https://marine.copernicus.eu/user-corner/service-commitments-and-licence"
# Wording the licence (section 2.4 (a)) asks for on derived pictures and maps.
ATTRIBUTION = f"Generated using E.U. Copernicus Marine Service Information; {PRODUCT_DOI_URL}"
CAVEAT = ("Model output (PISCES biogeochemical model, Copernicus Marine global "
          "analysis and forecast, 0.25 degree, monthly means at the surface level), "
          "not measurements.")

# dataset key -> (Copernicus Marine dataset id, variables read from it)
DATASETS: dict[str, tuple[str, list[str]]] = {
    "nut": ("cmems_mod_glo_bgc-nut_anfc_0.25deg_P1M-m", ["no3", "po4"]),
    "pft": ("cmems_mod_glo_bgc-pft_anfc_0.25deg_P1M-m", ["chl"]),
    "bio": ("cmems_mod_glo_bgc-bio_anfc_0.25deg_P1M-m", ["nppv"]),
}

# The five numbers below were measured on the live 2026-08 field (global,
# surface, 681 x 1440; 30.4 % NaN = land and ice) rather than guessed:
#   no3   p1 0.0008  p50 1.05   p99 30.2    max 140.8   -> sqrt scale, 0..35
#   chl   p1 0.031   p50 0.189  p99 1.55    max 22.9    -> log scale, 0.03..1.5
#   nppv  p1 0.0011  p5 0.0135  p50 2.84  p99 43.7   max 2035 -> log, 0.01..50
#   nstar p1 -13.8   p50 -3.21  p99 +3.27   min -59 max +141  -> linear +-15
# sqrt for nitrate: half the ocean sits below ~1 mmol m-3 while the Southern
# Ocean and subpolar gyres reach 30, so a linear ramp would paint the gyres as
# one flat colour. A true zero is real for nitrate, so log cannot be used.
VARS: dict[str, dict] = {
    "no3": dict(
        label="Nitrate", unit="mmol m-3", field="no3_mmol_m3", dataset="nut",
        scale="sqrt", vmin=0.0, vmax=35.0, cmap="matter",
        ticks=[0.0, 1.0, 5.0, 10.0, 20.0, 30.0],
        note="Monthly mean nitrate concentration at the surface level (0.49 m)."),
    "chl": dict(
        label="Chlorophyll-a", unit="mg m-3", field="chl_mg_m3", dataset="pft",
        scale="log", vmin=0.03, vmax=1.5, cmap="chl_green",
        ticks=[0.03, 0.1, 0.3, 1.0],
        note="Monthly mean chlorophyll-a concentration at the surface level (0.49 m)."),
    "nppv": dict(
        label="Net primary production (volumetric)", unit="mg m-3 day-1",
        field="nppv_mg_m3_day", dataset="bio",
        scale="log", vmin=0.01, vmax=50.0, cmap="npp_magma",
        ticks=[0.01, 0.1, 1.0, 10.0],
        note=("Volumetric rate of net primary production at the surface level "
              "(0.49 m), in mg m-3 per day. NOT a water-column integral.")),
    "nstar": dict(
        label="N* (nitrate - 16 x phosphate)", unit="mmol m-3", field="nstar_mmol_m3",
        dataset="nut", derived=dict(a="no3", b="po4", k=16.0),
        scale="linear", vmin=-15.0, vmax=15.0, cmap="diverging",
        ticks=[-15.0, -10.0, -5.0, 0.0, 5.0, 10.0],
        note=("Nitrate minus 16 times phosphate (16:1 Redfield ratio), without a "
              "constant offset. Negative: less nitrate than phosphate would call "
              "for; positive: an excess of nitrate.")),
}

# Anchor ramps. The woa ramps are reused so the two nutrient layers read alike.
_RAMPS: dict[str, list[tuple[float, tuple[int, int, int]]]] = {
    "matter": woa_climatology._RAMPS["matter"],
    "diverging": woa_climatology._RAMPS["diverging"],
    "chl_green": [(0.0, (12, 30, 80)), (0.35, (20, 120, 140)), (0.65, (90, 190, 90)),
                  (1.0, (240, 240, 110))],
    "npp_magma": [(0.0, (30, 20, 60)), (0.4, (150, 50, 110)), (0.7, (230, 120, 60)),
                  (1.0, (250, 230, 130))],
}

_FILL_ABS = 1e20  # anything larger is a fill value that escaped decoding


class UpstreamError(RuntimeError):
    """The Copernicus Marine request failed or returned something unusable."""


# ──────────────────────────────────────────────────────────────────────────────
# Pure encoding
# ──────────────────────────────────────────────────────────────────────────────

def normalise(arr: np.ndarray, cfg: dict) -> np.ndarray:
    """Map values to [0, 1] on the variable's scale. NaN stays NaN."""
    a = arr.astype("float64")
    vmin, vmax = cfg["vmin"], cfg["vmax"]
    with np.errstate(invalid="ignore", divide="ignore"):
        if cfg["scale"] == "linear":
            t = (a - vmin) / (vmax - vmin)
        elif cfg["scale"] == "sqrt":
            t = np.sqrt(np.clip(a - vmin, 0.0, None) / (vmax - vmin))
        elif cfg["scale"] == "log":
            # values <= vmin (including the few slightly negative model values and
            # exact zeros of the polar night) clip to the lowest colour, not NaN.
            t = np.log10(np.clip(a, vmin, None) / vmin) / np.log10(vmax / vmin)
        else:  # pragma: no cover
            raise ValueError(f"unknown scale {cfg['scale']!r}")
    return np.clip(t, 0.0, 1.0)


def _ramp_lookup(t: np.ndarray, cmap: str) -> np.ndarray:
    anchors = _RAMPS[cmap]
    pos = np.array([a[0] for a in anchors])
    cols = np.array([a[1] for a in anchors], dtype="float32")
    out = np.empty((*t.shape, 3), dtype="float32")
    for ch in range(3):
        out[..., ch] = np.interp(t, pos, cols[:, ch])
    return np.round(out).astype("uint8")


def encode_to_rgba(arr: np.ndarray, var: str) -> np.ndarray:
    """(H, W) float grid -> (H, W, 4) uint8 RGBA. NaN is transparent, never a colour."""
    cfg = VARS[var]
    mask = ~np.isfinite(arr)
    t = normalise(np.where(mask, cfg["vmin"], arr), cfg)
    rgba = np.zeros((*arr.shape, 4), dtype="uint8")
    rgba[..., :3] = _ramp_lookup(t, cfg["cmap"])
    rgba[..., 3] = np.where(mask, 0, 255).astype("uint8")
    return rgba


def derive_nstar(no3: np.ndarray, po4: np.ndarray) -> np.ndarray:
    """N* = no3 - 16 * po4. NaN in either input gives NaN, never 0."""
    d = VARS["nstar"]["derived"]
    if no3.shape != po4.shape:
        raise ValueError(f"no3 {no3.shape} and po4 {po4.shape} are not on one grid")
    return (no3.astype("float64") - float(d["k"]) * po4.astype("float64")).astype("float32")


def _ramp_hex(cmap: str) -> list[dict]:
    return [{"pos": pos, "hex": "#%02x%02x%02x" % rgb} for pos, rgb in _RAMPS[cmap]]


def _tick_list(var: str) -> list[dict]:
    cfg = VARS[var]
    ts = normalise(np.array(cfg["ticks"], dtype="float64"), cfg)
    return [{"value": v, "pos": round(float(t), 4)} for v, t in zip(cfg["ticks"], ts)]


# ──────────────────────────────────────────────────────────────────────────────
# Months and storage
# ──────────────────────────────────────────────────────────────────────────────

def month_key(t) -> str:
    """numpy datetime64 / datetime -> 'YYYY-MM'."""
    return str(np.datetime_as_string(np.datetime64(t, "M"), unit="M"))


def valid_month(s: str) -> bool:
    if not isinstance(s, str) or len(s) != 7 or s[4] != "-":
        return False
    try:
        y, m = int(s[:4]), int(s[5:])
    except ValueError:
        return False
    return 1900 <= y <= 2200 and 1 <= m <= 12


def months_back(newest: str, n: int) -> list[str]:
    """`newest` and the n-1 calendar months before it, newest first."""
    y, m = int(newest[:4]), int(newest[5:])
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def _month_dir(month: str) -> pathlib.Path:
    return CACHE_DIR / month


def is_complete(month: str) -> bool:
    d = _month_dir(month)
    if not (d / "meta.json").is_file():
        return False
    return all((d / f"{v}.png").is_file() and (d / f"{v}.npz").is_file() for v in VARS)


def complete_months() -> list[str]:
    """Months fully on disk, oldest first."""
    if not CACHE_DIR.is_dir():
        return []
    return sorted(p.name for p in CACHE_DIR.iterdir()
                  if p.is_dir() and valid_month(p.name) and is_complete(p.name))


def read_month_meta(month: str) -> dict | None:
    p = _month_dir(month) / "meta.json"
    return json.loads(p.read_text()) if p.is_file() else None


def png_path(var: str, month: str) -> pathlib.Path | None:
    if var not in VARS or not valid_month(month):
        return None
    p = _month_dir(month) / f"{var}.png"
    return p if p.is_file() else None


def prune_old(keep: int = MONTHS_KEPT) -> int:
    """Keep the `keep` newest COMPLETE months; remove older ones, any incomplete
    month directory and any leftover temporary directory. Returns dirs removed."""
    if not CACHE_DIR.is_dir():
        return 0
    removed = 0
    complete = complete_months()
    for month in complete[:-keep] if keep > 0 else complete:
        shutil.rmtree(_month_dir(month), ignore_errors=True)
        removed += 1
    for p in CACHE_DIR.iterdir():
        if not p.is_dir():
            continue
        if p.name.startswith(".tmp-") or p.name.startswith(".old-") or (
                valid_month(p.name) and not is_complete(p.name)):
            shutil.rmtree(p, ignore_errors=True)
            removed += 1
    return removed


def _stats(arr: np.ndarray) -> dict:
    f = arr[np.isfinite(arr)]
    if f.size == 0:
        return {"n_valid": 0, "n_nan": int(arr.size)}
    p1, p50, p99 = (float(x) for x in np.percentile(f, [1, 50, 99]))
    return {"n_valid": int(f.size), "n_nan": int(arr.size - f.size),
            "min": float(f.min()), "max": float(f.max()), "p1": p1, "p50": p50, "p99": p99}


def _grid_geometry(lat: np.ndarray, lon: np.ndarray) -> dict:
    def regular(c: np.ndarray, name: str) -> float:
        if c.size < 2:
            raise UpstreamError(f"{name} axis has {c.size} point(s)")
        d = np.diff(c.astype("float64"))
        if not np.allclose(d, d[0], rtol=0.0, atol=1e-4) or d[0] <= 0:
            raise UpstreamError(f"{name} axis is not regular and ascending")
        return float(d[0])
    dlat, dlon = regular(lat, "latitude"), regular(lon, "longitude")
    if abs(dlat - dlon) > 1e-4:
        raise UpstreamError(f"cells are not square: {dlat} vs {dlon}")
    step = dlat
    n_lat, n_lon = int(lat.size), int(lon.size)
    lat0, lon0 = float(lat[0]), float(lon[0])
    return {
        "lat0": lat0, "lon0": lon0, "step": step, "n_lat": n_lat, "n_lon": n_lon,
        "lat_max": float(lat[-1]), "lon_max": float(lon[-1]),
        "lon_global": bool(abs(n_lon * step - 360.0) < 1e-3),
        # pixel EDGES [west, south, east, north]; the cell centres are the coords
        "bounds": [lon0 - step / 2, lat0 - step / 2, float(lon[-1]) + step / 2,
                   float(lat[-1]) + step / 2],
    }


def _write_month(month: str, grids: dict[str, np.ndarray], geometry: dict, extra: dict) -> None:
    """Build the month in a temporary directory and rename it into place."""
    if not _PIL_AVAILABLE:
        raise RuntimeError("Pillow not installed — cannot bake")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_DIR / f".tmp-{month}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    tmp.mkdir()
    try:
        var_stats = {}
        for var, grid in grids.items():
            g32 = np.ascontiguousarray(grid, dtype="float32")
            rgba = encode_to_rgba(g32[::-1, :], var)  # N -> S rows for the texture
            _Image.fromarray(rgba, "RGBA").save(tmp / f"{var}.png", format="PNG", optimize=True)
            # np.savez_compressed appends .npz to a bare path; write through a handle
            with open(tmp / f"{var}.npz", "wb") as fh:
                np.savez_compressed(fh, v=g32)
            var_stats[var] = _stats(g32)
        meta = {
            "month": month, "grid": geometry, "stats": var_stats,
            "product": PRODUCT_ID, "doi": PRODUCT_DOI,
            "datasets": {k: v[0] for k, v in DATASETS.items()},
            "baked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            **extra,
        }
        (tmp / "meta.json").write_text(json.dumps(meta))  # last: completeness marker
        final = _month_dir(month)
        old = None
        if final.exists():
            old = CACHE_DIR / f".old-{month}-{uuid.uuid4().hex[:8]}"
            os.replace(final, old)
        os.replace(tmp, final)
        if old is not None:
            shutil.rmtree(old, ignore_errors=True)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


# ──────────────────────────────────────────────────────────────────────────────
# Upstream access
# ──────────────────────────────────────────────────────────────────────────────

def _credentials() -> dict:
    username = os.getenv("CMEMS_USERNAME")
    password = os.getenv("CMEMS_PASSWORD")
    if not username or not password:
        raise RuntimeError("CMEMS_USERNAME or CMEMS_PASSWORD not set in environment")
    return {"username": username, "password": password}


def _open(dataset_key: str):
    if _copernicusmarine is None:
        raise RuntimeError("copernicusmarine not installed — cannot bake")
    dataset_id, variables = DATASETS[dataset_key]
    creds = _credentials()  # fail with the plain message before touching the client
    return _copernicusmarine.open_dataset(
        dataset_id=dataset_id, variables=variables,
        minimum_depth=0.0, maximum_depth=1.0, **creds)


def time_axis(ds) -> dict[str, object]:
    """month key -> the dataset's own time value, from the ACTUAL time axis."""
    out = {}
    for t in ds["time"].values:
        out[month_key(t)] = t
    return out


def _read_surface(ds, var: str, tval):
    """One variable, one month, first (surface) level -> (lat, lon, float32 grid)."""
    if var not in ds:
        raise UpstreamError(f"variable {var!r} missing from the dataset")
    da = ds[var].sel(time=tval)
    if "depth" in da.dims:
        if float(ds["depth"].values[0]) >= 1.0:
            raise UpstreamError("first depth level is not the surface")
        da = da.isel(depth=0)
    if tuple(da.dims) != ("latitude", "longitude"):
        raise UpstreamError(f"{var}: expected (latitude, longitude), got {da.dims}")
    if not bool(np.all(np.diff(da["latitude"].values) > 0)):
        da = da.sortby("latitude")
    arr = np.asarray(da.values, dtype="float32")  # the network read happens here
    arr = np.where(np.isfinite(arr) & (np.abs(arr) < _FILL_ABS), arr, np.nan).astype("float32")
    return (np.asarray(da["latitude"].values, dtype="float64"),
            np.asarray(da["longitude"].values, dtype="float64"), arr)


def fetch_month(opened: dict, axes: dict, month: str) -> tuple[dict, dict]:
    """Read every variable for `month` BEFORE anything is written. Any failure
    raises, so the caller never holds a partial set. Returns (grids, geometry)."""
    raw: dict[str, np.ndarray] = {}
    lat = lon = None
    for key, (_, variables) in DATASETS.items():
        for var in variables:
            la, lo, arr = _read_surface(opened[key], var, axes[key][month])
            if lat is None:
                lat, lon = la, lo
            elif la.shape != lat.shape or lo.shape != lon.shape or not (
                    np.allclose(la, lat, atol=1e-6) and np.allclose(lo, lon, atol=1e-6)):
                raise UpstreamError(f"{var}: grid differs from the other variables")
            raw[var] = arr
    grids = {"no3": raw["no3"], "chl": raw["chl"], "nppv": raw["nppv"],
             "nstar": derive_nstar(raw["no3"], raw["po4"])}
    return grids, _grid_geometry(lat, lon)


def bake_month(opened: dict, axes: dict, month: str) -> None:
    grids, geometry = fetch_month(opened, axes, month)
    _write_month(month, grids, geometry, {"time_stamp": str(axes["nut"][month])[:10]})


def sync_months(force: bool = False) -> dict:
    """Bring the cache up to date. Blocking; run in a thread.

    The newest month is read from the datasets' own time axes (the latest month
    present in ALL three), never from the clock. The wanted set is that month and
    the 11 before it. Months already complete are left alone unless `force`.
    A month whose upstream read fails is skipped entirely; earlier months stay.
    """
    if not _PIL_AVAILABLE or _copernicusmarine is None:
        raise RuntimeError("copernicusmarine / Pillow not installed — cannot bake")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    opened: dict = {}
    try:
        for key in DATASETS:
            opened[key] = _open(key)
        axes = {k: time_axis(ds) for k, ds in opened.items()}
        common = set.intersection(*(set(a) for a in axes.values()))
        if not common:
            raise UpstreamError("the three datasets share no month")
        newest = max(common)
        wanted = [m for m in months_back(newest, MONTHS_KEPT) if m in common]
        have = set(complete_months())
        todo = [m for m in wanted if force or m not in have]
        baked: list[str] = []
        failed: dict[str, str] = {}
        for month in todo:  # newest first: the most useful month lands first
            try:
                bake_month(opened, axes, month)
                baked.append(month)
                log.info("bgc_model: baked %s", month)
            except Exception as exc:
                failed[month] = f"{type(exc).__name__}: {exc}"
                log.warning("bgc_model: %s not written (previous months kept): %s", month, exc)
        prune_old()
        return {"newest": newest, "wanted": wanted, "baked": baked, "failed": failed,
                "on_disk": complete_months()}
    finally:
        for ds in opened.values():
            try:
                ds.close()
            except Exception:  # pragma: no cover
                pass


# ──────────────────────────────────────────────────────────────────────────────
# Reading: point lookup and meta
# ──────────────────────────────────────────────────────────────────────────────

_GRID_CACHE: dict[tuple[str, str], tuple[int, np.ndarray]] = {}


def load_grid(var: str, month: str) -> np.ndarray | None:
    """The float32 grid for (var, month), cached by file mtime so a re-bake by the
    worker process is picked up by the web process without a restart."""
    p = _month_dir(month) / f"{var}.npz"
    try:
        mtime = p.stat().st_mtime_ns
    except FileNotFoundError:
        return None
    hit = _GRID_CACHE.get((var, month))
    if hit is not None and hit[0] == mtime:
        return hit[1]
    with np.load(p) as z:
        arr = np.asarray(z["v"], dtype="float32")
    if len(_GRID_CACHE) >= 16:
        _GRID_CACHE.clear()
    _GRID_CACHE[(var, month)] = (mtime, arr)
    return arr


def point_value(var: str, lat: float, lon: float, month: str | None = None) -> dict:
    """Value of the nearest cell. Raises KeyError (unknown var), LookupError (month
    not on disk). status: ok | no_data (NaN: land or ice) | not_covered (outside
    the grid, e.g. south of 80 S). A missing value is None, never 0."""
    if var not in VARS:
        raise KeyError(var)
    months = complete_months()
    if month is None:
        if not months:
            raise LookupError("nothing baked yet")
        month = months[-1]
    elif month not in months:
        raise LookupError(f"month {month} not available")
    cfg = VARS[var]
    out = {"var": var, "month": month, "lat": lat, "lon": lon, "unit": cfg["unit"],
           "value_field": cfg["field"], cfg["field"]: None, "status": "not_covered"}
    meta = read_month_meta(month)
    g = meta["grid"]
    if lat < g["lat0"] or lat > g["lat_max"]:
        return out
    if g["lon_global"]:
        col = int(np.floor((lon - g["lon0"]) / g["step"] + 0.5)) % g["n_lon"]
    else:
        if lon < g["lon0"] or lon > g["lon_max"]:
            return out
        col = int(np.floor((lon - g["lon0"]) / g["step"] + 0.5))
    row = int(np.floor((lat - g["lat0"]) / g["step"] + 0.5))
    row = min(max(row, 0), g["n_lat"] - 1)
    col = min(max(col, 0), g["n_lon"] - 1)
    grid = load_grid(var, month)
    if grid is None:
        raise LookupError(f"grid for {var} {month} not available")
    v = float(grid[row, col])
    out["cell"] = {"lat": g["lat0"] + row * g["step"],
                   "lon": ((g["lon0"] + col * g["step"] + 180.0) % 360.0) - 180.0
                   if g["lon_global"] else g["lon0"] + col * g["step"]}
    if not np.isfinite(v):
        out["status"] = "no_data"
        return out
    out[cfg["field"]] = v
    out["status"] = "ok"
    return out


def build_meta() -> dict:
    """Payload of /v1/bgc-model/meta, read from disk on every call (a handful of
    directory entries) so the web process never serves a stale month list."""
    months = complete_months()
    latest = read_month_meta(months[-1]) if months else None
    variables = []
    if latest is not None:
        for key, c in VARS.items():
            variables.append({
                "key": key, "label": c["label"], "unit": c["unit"], "field": c["field"],
                "scale": c["scale"], "vmin": c["vmin"], "vmax": c["vmax"],
                "cmap": c["cmap"], "ramp": _ramp_hex(c["cmap"]), "ticks": _tick_list(key),
                "note": c["note"], "stats": latest["stats"].get(key),
            })
    return {
        "layer": LAYER_ID, "months": months, "latest": months[-1] if months else None,
        "variables": variables, "grid": latest["grid"] if latest else None,
        "product": {"id": PRODUCT_ID, "title": PRODUCT_TITLE, "doi": PRODUCT_DOI,
                    "doi_url": PRODUCT_DOI_URL, "url": PRODUCT_URL, "licence_url": LICENCE_URL},
        "attribution": ATTRIBUTION, "caveat": CAVEAT,
    }
