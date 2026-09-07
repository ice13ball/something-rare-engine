# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""GLODAPv2.2016b Mapped Climatology: config, colour-map encoder, and meta.

Heavy deps (netCDF4 / PIL / copernicusmarine) are imported lazily in the
download/bake tasks (Tasks 3-4) so this module stays importable in test
environments that lack them.

Source: GLODAPv2.2016b Mapped Climatologies (public, Fair Data Use).
Citation: Lauvset et al. 2016 (ESSD 8:325-340, doi:10.5194/essd-8-325-2016);
          Key et al. 2015 (NDP-093, doi:10.3334/CDIAC/OTG.NDP093_GLODAPv2).
"""
from __future__ import annotations

import os
import pathlib

import numpy as np

# ── Cache directories ─────────────────────────────────────────────────────────
CACHE_DIR = pathlib.Path(os.getenv("CARBON_CACHE_DIR", "/var/cache/abyssal-carbon"))
RAW_DIR   = CACHE_DIR / "raw"
BAKE_DIR  = CACHE_DIR / "baked"

# ── Source URLs ───────────────────────────────────────────────────────────────
GLODAP_TAR_URL = (
    "https://glodap.info/glodap_files/v2.2023/"
    "GLODAPv2.2016b.MappedProduct.tar.gz"
)
GLODAP_TAR_URL_FALLBACK = (
    "https://www.nodc.noaa.gov/archive/arc0107/0162565/"
    "1.1/data/0-data/mapped/GLODAPv2.2016b_MappedClimatologies.tar.gz"
)

CITATION = (
    "Lauvset et al. 2016 (ESSD 8:325-340, doi:10.5194/essd-8-325-2016); "
    "Key et al. 2015 (NDP-093, doi:10.3334/CDIAC/OTG.NDP093_GLODAPv2). "
    "GLODAPv2.2016b Mapped Climatology — Fair Data Use."
)

# ── Variable config ───────────────────────────────────────────────────────────
# nc_file / nc_var confirmed against the real tarball in Task 1.
CARBON_VARS: dict[str, dict] = {
    "dic": {
        "nc_file": "GLODAPv2.2016b.TCO2.nc",
        "nc_var": "TCO2",
        "units": "µmol/kg",
        "vmin": 1900,
        "vmax": 2400,
        "cmap": "matter",
        "label": "Dissolved Inorganic Carbon",
    },
    "talk": {
        "nc_file": "GLODAPv2.2016b.TAlk.nc",
        "nc_var": "TAlk",
        "units": "µmol/kg",
        "vmin": 2200,
        "vmax": 2500,
        "cmap": "haline",
        "label": "Total Alkalinity",
    },
    "ph": {
        "nc_file": "GLODAPv2.2016b.pHtsinsitutp.nc",
        "nc_var": "pHtsinsitutp",
        "units": "",
        "vmin": 7.6,
        "vmax": 8.2,
        "cmap": "ph",
        "label": "pH (in-situ, total scale)",
    },
    "cant": {
        "nc_file": "GLODAPv2.2016b.Cant.nc",
        "nc_var": "Cant",
        "units": "µmol/kg",
        "vmin": 0,
        "vmax": 60,
        "cmap": "oxy",
        "label": "Anthropogenic CO₂",
    },
}

# Subset of the 33 GLODAP standard depths actually baked (full set confirmed in Task 1).
DISPLAY_DEPTHS: list[int] = [0, 200, 500, 1000, 2000, 3000, 4000]

# ── Colour ramps ──────────────────────────────────────────────────────────────
# Anchor-point ramps (pos 0..1 → RGB). Linear-interpolated; perceptual enough
# for a translucent overlay without pulling in matplotlib.
_RAMPS: dict[str, list[tuple[float, tuple[int, int, int]]]] = {
    "matter": [(0.0, (253, 237, 176)), (0.5, (221, 109, 124)), (1.0, (62, 24, 78))],
    "haline": [(0.0, (42, 24, 108)),   (0.5, (32, 144, 140)),  (1.0, (253, 238, 153))],
    "oxy":    [(0.0, (64, 5, 5)),       (0.5, (220, 220, 220)), (1.0, (24, 82, 24))],
    "ph":     [(0.0, (178, 24, 43)),    (0.5, (247, 247, 247)), (1.0, (33, 102, 172))],
}


def _lerp(c0: tuple[int, int, int], c1: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(round(c0[i] + (c1[i] - c0[i]) * t)) for i in range(3))  # type: ignore[return-value]


def _ramp_rgb(cmap: str, t: float) -> tuple[int, int, int]:
    """Map normalised t ∈ [0, 1] to an RGB triple via named anchor ramp."""
    stops = _RAMPS[cmap]
    t = min(1.0, max(0.0, t))
    for i in range(len(stops) - 1):
        t0, c0 = stops[i]
        t1, c1 = stops[i + 1]
        if t <= t1:
            frac = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            return _lerp(c0, c1, frac)
    return stops[-1][1]


def encode_field_to_rgba(arr: np.ndarray, vmin: float, vmax: float, cmap: str) -> np.ndarray:
    """Encode a (H, W) field to (H, W, 4) RGBA uint8. NaN → transparent (alpha=0)."""
    h, w = arr.shape
    rgba = np.zeros((h, w, 4), dtype="uint8")
    mask = ~np.isnan(arr)
    span = (vmax - vmin) or 1.0
    norm = np.clip((arr - vmin) / span, 0.0, 1.0)
    for y in range(h):
        for x in range(w):
            if mask[y, x]:
                r, g, b = _ramp_rgb(cmap, float(norm[y, x]))
                rgba[y, x] = (r, g, b, 255)
    return rgba


def _ramp_hex(cmap: str) -> list[dict]:
    """Colour-ramp anchor stops as {t, hex} — lets the frontend draw a colour-bar
    legend whose gradient exactly matches the baked PNG palette."""
    return [{"pos": t, "hex": "#%02x%02x%02x" % rgb} for t, rgb in _RAMPS[cmap]]


def build_meta() -> dict:
    """Meta payload for /v1/carbon/meta — variables, ranges, palettes, depths, citation."""
    return {
        "variables": [
            {
                "key": k,
                "label": v["label"],
                "units": v["units"],
                "vmin": v["vmin"],
                "vmax": v["vmax"],
                "cmap": v["cmap"],
                "ramp": _ramp_hex(v["cmap"]),
                "depths": DISPLAY_DEPTHS,
            }
            for k, v in CARBON_VARS.items()
        ],
        "depths": DISPLAY_DEPTHS,
        "citation": CITATION,
        # ⛔ Not in the NetCDF. The file's dimensions are depth_surface/lat/lon/snr,
        # and its `Created` attribute is when the file was written, not when the
        # ships were at sea. These years come from the abstract of the paper that
        # describes the product: "covers all ocean basins over the years 1972 to
        # 2013" / "all data from the full 1972-2013 period were used".
        "observation_window": {
            "start": 1972, "end": 2013,
            "source": "Lauvset et al. 2016, ESSD 8:325-340, abstract",
        },
    }


# ── Grid load + sample ────────────────────────────────────────────────────────
import glob as _glob

_GRID_CACHE: dict[str, "_Grid | None"] = {}


class _Grid:
    __slots__ = ("lats", "lons", "depths", "data", "counts")

    def __init__(self, lats, lons, depths, data, counts=None):
        self.lats   = lats
        self.lons   = lons
        self.depths = depths
        self.data   = data
        self.counts = counts


def normalize_lon(data: np.ndarray, lon: np.ndarray):
    """GLODAP grid starts at 20°E with lon values in 20..380 range.
    Wrap values >180 to −180..180 and roll data columns to match sorted-ascending lon."""
    lon = np.where(lon > 180.0, lon - 360.0, lon)
    order = np.argsort(lon)
    return data[..., order], lon[order]


def _nearest_idx(coords: np.ndarray, value: float) -> int:
    return int(np.argmin(np.abs(coords - value)))


def _load_grid(var_key: str) -> "_Grid | None":
    if var_key in _GRID_CACHE:
        return _GRID_CACHE[var_key]
    import xarray as xr  # lazy — not available in test env without netCDF4
    cfg = CARBON_VARS[var_key]
    matches = _glob.glob(str(RAW_DIR / "**" / cfg["nc_file"]), recursive=True)
    # Also check RAW_DIR directly (no sub-directories).
    if not matches:
        matches = _glob.glob(str(RAW_DIR / cfg["nc_file"]))
    if not matches:
        _GRID_CACHE[var_key] = None
        return None
    ds = xr.open_dataset(matches[0])
    # Depth values live in a DATA VAR named "Depth" (33 levels); dim is depth_surface.
    depth_name = "Depth" if "Depth" in ds.variables else "depth_surface"
    arr = np.asarray(ds[cfg["nc_var"]].values, dtype="float32")
    # Squeeze any degenerate leading dims (e.g. size-1 snr axis).
    while arr.ndim > 3:
        arr = arr.squeeze(axis=0)
    lats     = np.asarray(ds["lat"].values,         dtype="float64")
    lons_raw = np.asarray(ds["lon"].values,         dtype="float64")
    depths   = np.asarray(ds[depth_name].values,    dtype="float64")

    # Input_N (observation count backing each cell) — same file, same grid.
    # Not every GLODAP variable file necessarily carries it, so degrade to None
    # rather than raising: a missing count is not the same as a zero count.
    counts = None
    if "Input_N" in ds.variables:
        counts = np.asarray(ds["Input_N"].values, dtype="float32")
        while counts.ndim > arr.ndim:
            counts = counts.squeeze(axis=0)

    arr, lons = normalize_lon(arr, lons_raw)
    if counts is not None:
        # ⚠️ Must roll with the ORIGINAL (pre-normalize) lon axis, not `lons`
        # above (already sorted by the call on `arr`) — normalize_lon derives
        # its column permutation from argsort(lon), so feeding it an
        # already-sorted axis yields the identity permutation and counts
        # would silently land on the wrong cells relative to `arr`.
        counts, _ = normalize_lon(counts, lons_raw)

    g = _Grid(lats, lons, depths, arr, counts)
    _GRID_CACHE[var_key] = g
    return g


def sample(var_key: str, lat: float, lon: float, depth_m: float) -> float | None:
    """Return the nearest-neighbour climatological value, or None for land/fill."""
    g = _load_grid(var_key)
    if g is None:
        return None
    di = _nearest_idx(g.depths, depth_m)
    yi = _nearest_idx(g.lats,   lat)
    xi = _nearest_idx(g.lons,   lon)
    v  = g.data[di, yi, xi]
    return None if np.isnan(v) else float(v)


def sample_count(var_key: str, lat: float, lon: float, depth_m: float) -> int | None:
    """How many measurements back this cell. None when the grid carries no
    Input_N at all (older/trimmed extracts), or when the nearest cell is
    land/fill — neither is the same as a genuine zero-observation cell."""
    g = _load_grid(var_key)
    if g is None or g.counts is None:
        return None
    di = _nearest_idx(g.depths, depth_m)
    yi = _nearest_idx(g.lats,   lat)
    xi = _nearest_idx(g.lons,   lon)
    v  = g.counts[di, yi, xi]
    return None if np.isnan(v) else int(round(v))


# ── Download / bake ───────────────────────────────────────────────────────────
import glob
import subprocess
import tarfile
import logging
import tempfile

log = logging.getLogger("glodap_carbon")


def ensure_holdings(force: bool = False) -> bool:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    have = glob.glob(str(RAW_DIR / "**" / "GLODAPv2.2016b.TCO2.nc"), recursive=True)
    if have and not force:
        return True
    tar_path = CACHE_DIR / "glodap_mapped.tar.gz"
    ok = False
    for url in (GLODAP_TAR_URL, GLODAP_TAR_URL_FALLBACK):
        try:
            subprocess.run(["/usr/bin/curl", "-4", "-fsSL", "-o", str(tar_path), url],
                           check=True, timeout=1800)
            ok = True; break
        except Exception as e:
            log.warning("glodap download failed for %s: %s", url, e)
    if not ok:
        return False
    with tarfile.open(tar_path, "r:gz") as tf:
        tf.extractall(RAW_DIR, filter="data")   # path-traversal guard — never drop
    tar_path.unlink(missing_ok=True)
    return bool(glob.glob(str(RAW_DIR / "**" / "GLODAPv2.2016b.TCO2.nc"), recursive=True))


def baked_png_path(var_key: str, depth_m: int) -> pathlib.Path | None:
    p = BAKE_DIR / var_key / f"{depth_m}.png"
    return p if p.exists() else None


def bake_variable_depth(var_key: str, depth_m: int) -> dict | None:
    from PIL import Image  # lazy
    g = _load_grid(var_key)
    if g is None:
        return None
    cfg = CARBON_VARS[var_key]
    di = _nearest_idx(g.depths, depth_m)
    field = g.data[di]                                   # (lat, lon)
    field = np.flipud(field)                             # row 0 = north
    rgba = encode_field_to_rgba(field, cfg["vmin"], cfg["vmax"], cfg["cmap"])
    out_dir = BAKE_DIR / var_key; out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{depth_m}.png"
    with tempfile.NamedTemporaryFile(dir=out_dir, suffix=".png.tmp", delete=False) as tmp:
        tmp_path = pathlib.Path(tmp.name)
    Image.fromarray(rgba, "RGBA").save(tmp_path, format="PNG", optimize=True)
    os.replace(tmp_path, out)
    # log actual data range so the Global-Constraint domains can be refined
    finite = field[~np.isnan(field)]
    if finite.size:
        log.info("carbon bake %s @%dm: data p2=%.1f p98=%.1f (domain %s..%s)",
                 var_key, depth_m, np.percentile(finite, 2), np.percentile(finite, 98),
                 cfg["vmin"], cfg["vmax"])
    return {"var": var_key, "depth": depth_m}


def bake_all() -> int:
    if not ensure_holdings():
        return 0
    n = 0
    for vk in CARBON_VARS:
        for d in DISPLAY_DEPTHS:
            if bake_variable_depth(vk, d):
                n += 1
    return n
