# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Cumulative Human Impact (CHI) — NCEAS / Halpern et al. 2025 present-state field.

Reads the Mollweide GeoTIFF `ssp245_current.tif` from KNB doi:10.5063/F18K77KZ (CC0 1.0),
reprojects it once to a regular EPSG:4326 grid (cached as .npy), bakes a sequential PNG and
serves a pickable hexagon / point view — the same field+hexagon pattern as
`glodap_carbon` / `acidification` / `oxygen_deox`.

Verified against the REAL source 2026-07-29 (see backend/tests/fixtures/chi/SCHEMA_NOTES.md):
  - CRS: +proj=moll +lon_0=0 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs
  - 3617x1814 Float32, NODATA = nan (NO -9999 sentinel), no negatives.
  - Value is a DIMENSIONLESS cumulative-impact index — NOT rescaled 0-1. Present-state
    distribution: median 0.20, p95 0.53, p99 0.78, max 1.82. The ramp domain is anchored on
    that reality, NOT hard-clamped to [0,1].
  - v1 = PRESENT STATE ONLY (`ssp245_current.tif`). Projections (`*_medium-term.tif`) are
    deliberately excluded; a later scenario selector adds them, never mixed with "current".

Heavy deps (rasterio/PIL) are imported lazily so this module stays importable in test envs.
"""
from __future__ import annotations

import io
import json
import logging
import math
import os
import pathlib
import subprocess
import zipfile

import numpy as np

log = logging.getLogger("chi_impact")

CACHE_DIR = pathlib.Path(os.getenv("CHI_CACHE_DIR", "/var/cache/abyssal-chi"))
RAW_DIR = CACHE_DIR / "raw"

# DataONE object for cumulative_impact.zip (62,962,811 B) within KNB doi:10.5063/F18K77KZ.
CHI_ZIP_URL = (
    "https://knb.ecoinformatics.org/knb/d1/mn/v2/object/"
    "urn:uuid:15a99425-c3cc-46a5-a3b4-3b26f4df29aa"
)
# v1 canonical present state = the moderate-scenario baseline. The two *_current tifs differ
# <1% (median 0.204 vs 0.206); we pick one and disclose the scenario dependence in the panel.
ZIP_MEMBER = "cumulative_impact/ssp245_current.tif"

# Regular EPSG:4326 grid the Mollweide source is warped onto. 0.1° ≈ the native 10 km.
GRID_RES_DEG = 0.1

CITATION = (
    "Halpern et al. 2025, 'Cumulative impacts to global marine ecosystems projected to more "
    "than double by midcentury', Science (doi:10.1126/science.adv2906). Data: KNB "
    "doi:10.5063/F18K77KZ, CC0 1.0 Public Domain. A dimensionless cumulative-impact index — "
    "the sum of ten anthropogenic pressures across six categories, weighted by ecosystem "
    "vulnerability. A modelled index, not a measurement. Seabed mining is only a minor "
    "component; a concession polygon is not a causal source of this impact."
)

# Single variable, no depth axis. Sequential ramp; domain anchored on the real present-state
# distribution (p99 ≈ 0.78, max 1.82) so most ocean reads calm and only hotspots saturate —
# consistent with the "context, not accusation" framing.
CHI_VARS: dict[str, dict] = {
    "impact": {
        "units": "index",
        "vmin": 0.0,
        "vmax": 1.0,
        "cmap": "seq_chi",
        "label": "Cumulative human impact",
    },
}

_RAMPS: dict[str, list[tuple[float, tuple[int, int, int]]]] = {
    # calm deep-teal (low pressure, most of the open ocean) → cyan → warm amber → deep red
    # (concentrated coastal / high-traffic hotspots).
    "seq_chi": [
        (0.0, (33, 78, 100)),
        (0.35, (78, 160, 160)),
        (0.7, (240, 190, 90)),
        (1.0, (150, 28, 28)),
    ],
}

_GRID_CACHE: dict[str, "_Grid | None"] = {}


class _Grid:
    __slots__ = ("lats", "lons", "data")

    def __init__(self, lats, lons, data):
        self.lats = lats  # row axis; row 0 = north (descending)
        self.lons = lons  # col axis; ascending −180..180
        self.data = data  # (H, W) float32, nan = no data


def _nearest_idx(coords: np.ndarray, value: float) -> int:
    return int(np.argmin(np.abs(coords - value)))


# ── Colour encoding (vectorised — the 0.1° grid is ~6.5M px; a per-pixel Python loop like
# glodap_carbon's would take minutes, so map through the ramp with np.interp per channel). ──

def encode_field_to_rgba(arr: np.ndarray, vmin: float, vmax: float, cmap: str) -> np.ndarray:
    """Encode a (H, W) field to (H, W, 4) RGBA uint8. NaN → fully transparent."""
    stops = _RAMPS[cmap]
    ts = np.array([s[0] for s in stops], dtype="float64")
    rs = np.array([s[1][0] for s in stops], dtype="float64")
    gs = np.array([s[1][1] for s in stops], dtype="float64")
    bs = np.array([s[1][2] for s in stops], dtype="float64")
    mask = ~np.isnan(arr)
    span = (vmax - vmin) or 1.0
    norm = np.clip((np.where(mask, arr, vmin) - vmin) / span, 0.0, 1.0)
    h, w = arr.shape
    rgba = np.zeros((h, w, 4), dtype="uint8")
    rgba[..., 0] = np.rint(np.interp(norm, ts, rs)).astype("uint8")
    rgba[..., 1] = np.rint(np.interp(norm, ts, gs)).astype("uint8")
    rgba[..., 2] = np.rint(np.interp(norm, ts, bs)).astype("uint8")
    rgba[..., 3] = np.where(mask, 255, 0).astype("uint8")
    rgba[~mask] = 0
    return rgba


def _ramp_hex(cmap: str) -> list[dict]:
    return [{"pos": t, "hex": "#%02x%02x%02x" % rgb} for t, rgb in _RAMPS[cmap]]


def build_meta() -> dict:
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
            }
            for k, v in CHI_VARS.items()
        ],
        "citation": CITATION,
    }


# ── Reproject Mollweide → regular EPSG:4326 grid (rasterio, lazy) ────────────────

def _npy_path() -> pathlib.Path:
    return CACHE_DIR / "grid.npy"


def _meta_path() -> pathlib.Path:
    return CACHE_DIR / "grid_meta.json"


def _reproject_to_4326(tif_path: pathlib.Path):
    """Warp the Mollweide source GeoTIFF to a regular global EPSG:4326 grid.
    Returns (data[H,W] float32 with nan land, lats desc row0=north, lons asc). Nearest
    resampling (source is ~10 km, target ~0.1° ≈ 11 km — near 1:1; nearest avoids nan-bleed
    across the land mask that bilinear/average would introduce along coastlines)."""
    import rasterio
    from rasterio.crs import CRS
    from rasterio.transform import from_bounds
    from rasterio.warp import Resampling, reproject

    west, south, east, north = -180.0, -90.0, 180.0, 90.0
    width = int(round((east - west) / GRID_RES_DEG))   # 3600
    height = int(round((north - south) / GRID_RES_DEG))  # 1800
    dst = np.full((height, width), np.nan, dtype="float32")
    dst_transform = from_bounds(west, south, east, north, width, height)
    with rasterio.open(tif_path) as src:
        reproject(
            source=rasterio.band(src, 1),
            destination=dst,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs=CRS.from_epsg(4326),
            src_nodata=float("nan"),
            dst_nodata=float("nan"),
            resampling=Resampling.nearest,
        )
    lats = north - (np.arange(height) + 0.5) * GRID_RES_DEG   # descending, row 0 = north
    lons = west + (np.arange(width) + 0.5) * GRID_RES_DEG     # ascending
    return dst, lats, lons


def _load_grid() -> "_Grid | None":
    if "impact" in _GRID_CACHE:
        return _GRID_CACHE["impact"]
    npy, metap = _npy_path(), _meta_path()
    if npy.exists() and metap.exists():
        data = np.load(npy)
        m = json.loads(metap.read_text())
        g = _Grid(np.asarray(m["lats"], dtype="float64"),
                  np.asarray(m["lons"], dtype="float64"), data)
        _GRID_CACHE["impact"] = g
        return g
    tif = RAW_DIR / ZIP_MEMBER
    if not tif.exists():
        _GRID_CACHE["impact"] = None
        return None
    data, lats, lons = _reproject_to_4326(tif)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    np.save(npy, data)
    _meta_path().write_text(json.dumps({"lats": lats.tolist(), "lons": lons.tolist(),
                                        "res_deg": GRID_RES_DEG}))
    g = _Grid(lats, lons, data)
    _GRID_CACHE["impact"] = g
    return g


def sample(lat: float, lon: float) -> float | None:
    """Nearest-neighbour cumulative-impact index at (lat, lon), or None for land/no-data."""
    g = _load_grid()
    if g is None:
        return None
    yi = _nearest_idx(g.lats, lat)
    xi = _nearest_idx(g.lons, lon)
    v = g.data[yi, xi]
    return None if np.isnan(v) else float(v)


# ── Web-Mercator XYZ raster tiles (single-id TileLayer on the client, so the field
# renders UNDER claims/dots via order_idx — the seabed/arctic raster pattern, not the
# manually-sliced-BitmapLayer field pattern which forces the field on top). ──────

_TILE = 256


def _tile_lonlat(z: int, x: int, y: int):
    n = 2 ** z
    def lon(px: float) -> float:
        return (x + px / _TILE) / n * 360.0 - 180.0
    def lat(py: float) -> float:
        t = math.pi * (1 - 2 * (y + py / _TILE) / n)
        return math.degrees(math.atan(math.sinh(t)))
    return lon, lat


def render_tile(z: int, x: int, y: int) -> bytes | None:
    """Render one XYZ web-mercator PNG tile (256²) from the reprojected CHI grid.
    Returns None (→ HTTP 204) for a fully land/no-data tile. nan → transparent."""
    from PIL import Image  # lazy
    g = _load_grid()
    if g is None:
        return None
    lon_of, lat_of = _tile_lonlat(z, x, y)
    lats = np.array([lat_of(py) for py in range(_TILE)])
    lons = np.array([lon_of(px) for px in range(_TILE)])
    lat_grid, lon_grid = np.meshgrid(lats, lons, indexing="ij")  # (py, px)
    res = GRID_RES_DEG
    # Regular grid: g.lons ascending from g.lons[0]; g.lats descending from g.lats[0].
    col = np.round((lon_grid - g.lons[0]) / res).astype(int)
    row = np.round((g.lats[0] - lat_grid) / res).astype(int)
    h, w = g.data.shape
    in_b = (row >= 0) & (row < h) & (col >= 0) & (col < w)
    if not in_b.any():
        return None
    vals = np.full((_TILE, _TILE), np.nan, dtype="float32")
    vals[in_b] = g.data[row[in_b], col[in_b]]
    cfg = CHI_VARS["impact"]
    rgba = encode_field_to_rgba(vals, cfg["vmin"], cfg["vmax"], cfg["cmap"])
    if not rgba[..., 3].any():
        return None                          # entirely transparent → no tile
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ── Download / bake ─────────────────────────────────────────────────────────────

def ensure_holdings(force: bool = False) -> bool:
    """Download cumulative_impact.zip and extract just ssp245_current.tif. Returns True if
    the source tif is present afterwards."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    tif = RAW_DIR / ZIP_MEMBER
    if tif.exists() and not force:
        return True
    zip_path = CACHE_DIR / "cumulative_impact.zip"
    try:
        subprocess.run(["/usr/bin/curl", "-4", "-fsSL", "-o", str(zip_path), CHI_ZIP_URL],
                       check=True, timeout=900)
    except Exception as e:  # noqa: BLE001
        log.warning("chi download failed: %s", e)
        return False
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
            if ZIP_MEMBER not in names:
                log.error("chi zip missing %s (has e.g. %s)", ZIP_MEMBER, list(names)[:6])
                return False
            # Read the ONE member by exact name — no extractall, so no path-traversal surface.
            data = zf.read(ZIP_MEMBER)
    except Exception as e:  # noqa: BLE001
        log.warning("chi unzip failed: %s", e)
        return False
    finally:
        zip_path.unlink(missing_ok=True)
    tif.parent.mkdir(parents=True, exist_ok=True)
    tif.write_bytes(data)
    # Invalidate the reprojected cache so a forced re-fetch re-warps from the new source.
    _npy_path().unlink(missing_ok=True)
    _meta_path().unlink(missing_ok=True)
    _GRID_CACHE.pop("impact", None)
    return tif.exists()


def bake_all() -> int:
    """Ensure the source is downloaded and the reprojected grid (grid.npy) is built, so the
    first /v1/chi/raster tile request doesn't pay the ~1 s reproject under user traffic.
    Map tiles are rendered on demand by render_tile() from this grid — there is no baked
    global PNG. Returns 1 once the grid is ready, else 0."""
    if not ensure_holdings():
        return 0
    _GRID_CACHE.pop("impact", None)
    g = _load_grid()                              # builds + caches grid.npy on first call
    if g is None:
        return 0
    finite = g.data[~np.isnan(g.data)]
    if finite.size:
        log.info("chi bake: grid ready valid=%d median=%.3f p99=%.3f max=%.3f",
                 finite.size, float(np.median(finite)), float(np.percentile(finite, 99)),
                 float(finite.max()))
    return 1
