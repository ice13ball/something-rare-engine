# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Surface Ocean CO₂ Atlas (SOCAT) v2026: config, colour-map encoder, and meta.

Heavy deps (netCDF4 / PIL) are imported lazily in the download/bake tasks
(Tasks 3-4) so this module stays importable in test environments without them.

Source: SOCATv2026 Gridded Decadal Data (CC-BY 4.0).
Citation: Bakker et al. 2026 (NCEI Accession 0315110, doi:10.25921/8dba-fr90);
          Sabine et al. 2013 (gridded products, doi:10.5194/essd-5-145-2013).
"""
from __future__ import annotations

import logging
import os
import pathlib

import numpy as np

# ── Cache directories ─────────────────────────────────────────────────────────
CACHE_DIR = pathlib.Path(os.getenv("SOCAT_CACHE_DIR", "/var/cache/abyssal-socat"))
RAW_DIR   = CACHE_DIR / "raw"
BAKE_DIR  = CACHE_DIR / "baked"

# ── Source URL ────────────────────────────────────────────────────────────────
SOCAT_NC_URL = (
    "https://www.ncei.noaa.gov/data/oceans/ncei/ocads/data/0315110/"
    "SOCATv2026_Gridded_Data/SOCATv2026_tracks_gridded_decadal.nc"
)
NC_FILE = "SOCATv2026_tracks_gridded_decadal.nc"

CITATION = (
    "Bakker et al. 2026, Surface Ocean CO2 Atlas v2026 (SOCATv2026), "
    "NCEI Accession 0315110, doi:10.25921/8dba-fr90; "
    "Sabine et al. 2013 (gridded products, doi:10.5194/essd-5-145-2013). CC-BY 4.0."
)

# ── Variable config ───────────────────────────────────────────────────────────
CO2_VARS: dict[str, dict] = {
    "fco2": {
        "nc_var": "fco2_ave_weighted_decade",
        "units": "µatm",
        "vmin": 280,
        "vmax": 450,
        "cmap": "matter",
        "label": "Surface fCO₂",
    },
    "density": {
        "nc_var": "fco2_count_nobs_decade",
        "units": "count",
        "vmin": 0,
        "vmax": 500,
        "cmap": "oxy",
        "label": "Observation density",
    },
    "sst": {
        "nc_var": "sst_ave_weighted_decade",
        "units": "°C",
        "vmin": -2,
        "vmax": 32,
        "cmap": "thermal",
        "label": "Sea-surface temperature",
    },
    "salinity": {
        "nc_var": "salinity_ave_weighted_decade",
        "units": "PSU",
        "vmin": 30,
        "vmax": 38,
        "cmap": "haline",
        "label": "Salinity",
    },
}

# 6 decades; index = position along the tdecade axis (0..5), label is human-facing.
DECADES: list[dict] = [
    {"index": i, "label": lbl}
    for i, lbl in enumerate(["1970s", "1980s", "1990s", "2000s", "2010s", "2020s"])
]

# ── Colour ramps ──────────────────────────────────────────────────────────────
# Anchor-point ramps (pos 0..1 → RGB). Linear-interpolated; perceptual enough
# for a translucent overlay without pulling in matplotlib.
_RAMPS: dict[str, list[tuple[float, tuple[int, int, int]]]] = {
    "matter":  [(0.0, (253, 237, 176)), (0.5, (221, 109, 124)), (1.0, (62, 24, 78))],
    "haline":  [(0.0, (42, 24, 108)),   (0.5, (32, 144, 140)),  (1.0, (253, 238, 153))],
    "oxy":     [(0.0, (64, 5, 5)),       (0.5, (220, 220, 220)), (1.0, (24, 82, 24))],
    "ph":      [(0.0, (178, 24, 43)),    (0.5, (247, 247, 247)), (1.0, (33, 102, 172))],
    "thermal": [(0.0, (8, 29, 88)),      (0.5, (34, 160, 160)),  (1.0, (253, 219, 90))],
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
    """Colour-ramp anchor stops as {pos, hex} — lets the frontend draw a colour-bar
    legend whose gradient exactly matches the baked PNG palette."""
    return [{"pos": t, "hex": "#%02x%02x%02x" % rgb} for t, rgb in _RAMPS[cmap]]


def build_meta() -> dict:
    """Meta payload for /v1/co2/meta — variables, ranges, palettes, decades, citation."""
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
                "decades": DECADES,
            }
            for k, v in CO2_VARS.items()
        ],
        "decades": DECADES,
        "citation": CITATION,
    }


# ── Grid load + sample (Task 3) ───────────────────────────────────────────────
import glob  # noqa: E402  (stdlib; kept here so the module stays importable without heavy deps)

_GRID_CACHE: dict[str, "_Grid | None"] = {}


class _Grid:
    __slots__ = ("lats", "lons", "decades", "data")

    def __init__(
        self,
        lats: np.ndarray,
        lons: np.ndarray,
        decades: list[int],
        data: np.ndarray,
    ) -> None:
        self.lats = lats
        self.lons = lons
        self.decades = decades
        self.data = data


def _nearest_idx(coords: np.ndarray, value: float) -> int:
    return int(np.argmin(np.abs(np.asarray(coords) - value)))


def _load_grid(var_key: str) -> "_Grid | None":
    """Lazily load and cache the SOCAT NetCDF grid for *var_key*.

    SOCAT lon is already −180..180 — no 20°E roll needed; argsort defensively.
    Decade axis (tdecade) is index 0; shape is (tdecade, ylat, xlon) = (6, 180, 360).
    """
    if var_key in _GRID_CACHE:
        return _GRID_CACHE[var_key]

    import xarray as xr  # lazy — not available in test envs without heavy deps

    cfg = CO2_VARS[var_key]
    matches = glob.glob(str(RAW_DIR / "**" / NC_FILE), recursive=True) or glob.glob(
        str(RAW_DIR / NC_FILE)
    )
    if not matches:
        _GRID_CACHE[var_key] = None
        return None

    ds = xr.open_dataset(matches[0])
    arr = np.asarray(ds[cfg["nc_var"]].values, dtype="float32")  # (tdecade, ylat, xlon)
    # Squeeze any extra leading size-1 dims (e.g. singleton time dim in some releases)
    while arr.ndim > 3:
        arr = arr.squeeze(axis=0)
    # Observation-density (fco2_count_nobs) uses 0 for "no observations" rather than NaN,
    # so it would otherwise render on land + every empty ocean cell. Treat 0 as no-data so
    # density shows only true ship-track coverage (and the field/hex/point paths stay
    # consistent with fco2/sst/salinity, which are already NaN where there's no measurement).
    if var_key == "density":
        arr = np.where(arr == 0, np.nan, arr)

    lats = np.asarray(ds["ylat"].values, dtype="float64")
    lons = np.asarray(ds["xlon"].values, dtype="float64")

    # SOCAT lon is already −180..180; sort defensively (no 360 roll)
    order = np.argsort(lons)
    lons = lons[order]
    arr = arr[..., order]

    g = _Grid(lats, lons, list(range(arr.shape[0])), arr)
    _GRID_CACHE[var_key] = g
    return g


def sample(var_key: str, lat: float, lon: float, decade_idx: int) -> float | None:
    """Return the nearest-grid-cell value for *var_key* at (lat, lon, decade_idx).

    Returns None for land/missing (NaN) cells or if the grid is unavailable.
    *decade_idx* is clamped to valid range [0, n_decades−1].
    """
    g = _load_grid(var_key)
    if g is None:
        return None
    di = max(0, min(int(decade_idx), g.data.shape[0] - 1))
    v = g.data[di, _nearest_idx(g.lats, lat), _nearest_idx(g.lons, lon)]
    return None if np.isnan(v) else float(v)


# ── Data acquisition + bake (Task 4) ─────────────────────────────────────────
import subprocess  # noqa: E402
import tempfile    # noqa: E402

log = logging.getLogger("socat_co2")


def ensure_holdings(force: bool = False) -> bool:
    """Download the SOCAT NetCDF file if not already present (single-file, no tarball).

    Uses /usr/bin/curl -4 (absolute path; VPS IPv6 is black-holed).
    Skips the download if the file already exists with size > 0, unless force=True.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    dst = RAW_DIR / NC_FILE
    if dst.exists() and dst.stat().st_size > 0 and not force:
        return True
    try:
        subprocess.run(
            ["/usr/bin/curl", "-4", "-fsSL", "-o", str(dst), SOCAT_NC_URL],
            check=True,
            timeout=900,
        )
    except Exception as e:
        log.warning("socat download failed: %s", e)
        return False
    return dst.exists() and dst.stat().st_size > 0


def baked_png_path(var_key: str, decade_idx: int) -> pathlib.Path | None:
    """Return the path to a pre-baked PNG if it exists, else None."""
    p = BAKE_DIR / var_key / f"{decade_idx}.png"
    return p if p.exists() else None


def bake_var_decade(var_key: str, decade_idx: int) -> dict | None:
    """Bake one PNG for (var_key, decade_idx).

    Applies np.flipud so row 0 = north. Writes atomically via temp file +
    os.replace. Logs p2/p98 of finite data. PIL imported lazily (not available
    in test environments).
    """
    from PIL import Image  # noqa: PLC0415  lazy — not available without heavy deps

    g = _load_grid(var_key)
    if g is None:
        return None
    cfg = CO2_VARS[var_key]
    field = np.flipud(g.data[decade_idx])  # row 0 = north
    rgba = encode_field_to_rgba(field, cfg["vmin"], cfg["vmax"], cfg["cmap"])
    out_dir = BAKE_DIR / var_key
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{decade_idx}.png"
    with tempfile.NamedTemporaryFile(dir=out_dir, suffix=".png.tmp", delete=False) as tmp:
        tmp_path = pathlib.Path(tmp.name)
    Image.fromarray(rgba, "RGBA").save(tmp_path, format="PNG", optimize=True)
    os.replace(tmp_path, out)
    finite = field[~np.isnan(field)]
    if finite.size:
        log.info(
            "co2 bake %s decade%d: p2=%.1f p98=%.1f (domain %s..%s)",
            var_key, decade_idx,
            np.percentile(finite, 2), np.percentile(finite, 98),
            cfg["vmin"], cfg["vmax"],
        )
    return {"var": var_key, "decade": decade_idx}


def bake_all() -> int:
    """Download holdings (if needed) then bake all 4 vars × 6 decades = 24 PNGs.

    Returns the count of successfully baked PNGs.
    """
    if not ensure_holdings():
        return 0
    n = 0
    for vk in CO2_VARS:
        for d in DECADES:
            if bake_var_decade(vk, d["index"]):
                n += 1
    return n
