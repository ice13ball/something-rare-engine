# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Field-export sampler for the ocean-currents layer.

Reads the u/v grids baked by services.currents_bake (surface + 1000 m) and
exposes the standard field-export contract so Area Export can emit u/v cells
over an AOI. No new bake — reads the existing holdings.

⛔ Prefers the float grid (`latest.npz`) and falls back to decoding the RGBA
texture only when it is absent. The texture is a RENDERING TARGET: u and v are
squeezed into one byte each across a ±3 m/s span, so one step is 6/255 =
2.35 cm/s. Measured on the live bake 2026-09-10:

    surface   median speed 11.6 cm/s —  5.8% of wet cells below one step
    1000 m    median speed  3.7 cm/s — 38.4% of wet cells below one step

Exporting the 1,000 m field from the texture handed a downloader a number with
less than one step of resolution over a third of the ocean — and the 1,000 m
field is the one this platform describes as carrying mining sediment plumes.
The ±3 m/s clamp is not the problem: no wet cell reached it in either depth.
The step size is."""
from __future__ import annotations
import json
import numpy as np
from PIL import Image
from services import cache_swap
from services.currents_bake import UNSCALE_MIN, UNSCALE_MAX, CACHE_DIR

_SPAN = UNSCALE_MAX - UNSCALE_MIN
_DEPTH_DIR = {0: "surface", 1000: "1000m"}
#: "grid" -> (stamp-of-every-file-read, grid-or-None). currents_bake writes these
#: atomically already, but it now runs in the WORKER process while this cache
#: lives in the WEB one: reset_cache() after a bake never reaches this dict, so
#: without the stamp the web process serves the first day it ever loaded, forever.
_cache: "dict[str, tuple[tuple, _Grid | None]]" = {}


class _Grid:
    def __init__(self, lats, lons, depths, u_by_depth, v_by_depth):
        self.lats = lats            # 1-D, descending (N→S)
        self.lons = lons            # 1-D, ascending
        self.depths = depths        # [0, 1000]
        self._u = u_by_depth        # {depth: 2-D array}
        self._v = v_by_depth


def reset_cache() -> None:
    _cache.clear()
    GRID_PRECISION.clear()


def _axes_from_meta(meta) -> "tuple[np.ndarray, np.ndarray]":
    w, s, e, n = meta["bounds"]                     # [W,S,E,N] — confirmed in currents_bake.py out_bounds
    width, height = int(meta["width"]), int(meta["height"])
    # pixel centres; rows run N→S
    lats = np.linspace(n, s, height)
    lons = np.linspace(w, e, width)
    return lats, lons


#: Which grid the last load actually used, per depth. Read by the export's
#: provenance so a download cannot silently claim float precision it lacks.
GRID_PRECISION: "dict[int, str]" = {}


def _decode_depth(depth: int):
    d = _DEPTH_DIR[depth]
    png = CACHE_DIR / d / "latest.png"
    js  = CACHE_DIR / d / "latest.json"
    npz = CACHE_DIR / d / "latest.npz"
    if not js.is_file():
        return None
    meta = json.loads(js.read_text())

    if npz.is_file():
        # NOT mmap_mode: this is a .npz (zip) archive, not a flat .npy — numpy's
        # mmap_mode applies to a single uncompressed .npy array and is not a
        # meaningful option for a zip member (unsupported for a compressed npz,
        # and the on-disk layout for an uncompressed one still isn't a plain
        # memory-mappable array). The context-manager form below already only
        # decodes the two arrays actually requested ("u", "v"), not the archive.
        with np.load(npz) as z:
            u = z["u"].astype("float32")
            v = z["v"].astype("float32")
        if u.shape == (int(meta["height"]), int(meta["width"])):
            GRID_PRECISION[depth] = "float32"
            return meta, u, v
        # A grid that disagrees with the metadata would silently shift every
        # sampled cell. Fall through to the texture rather than guess.

    if not png.is_file():
        return None
    arr = np.asarray(Image.open(png).convert("RGBA"))
    a = arr[..., 3]
    u = arr[..., 0].astype("float32") / 255.0 * _SPAN + UNSCALE_MIN
    v = arr[..., 1].astype("float32") / 255.0 * _SPAN + UNSCALE_MIN
    u[a == 0] = np.nan
    v[a == 0] = np.nan
    GRID_PRECISION[depth] = "uint8-texture"
    return meta, u, v


def _grid_stamp() -> tuple:
    """Identity of every file _decode_depth may read, across both depths.

    Cheap (6 os.stat calls, no reads) and deliberately covers latest.npz even when
    the last load fell back to the texture — the npz APPEARING is itself a change
    the reader must notice, or a float-precision bake would keep being served as
    "uint8-texture" through GRID_PRECISION.
    """
    return cache_swap.file_stamp(
        CACHE_DIR / d / name
        for d in _DEPTH_DIR.values()
        for name in ("latest.json", "latest.npz", "latest.png")
    )


def _load_grid(var: str = "u") -> "_Grid | None":
    stamp = _grid_stamp()           # before the reads, so a swap mid-load re-reads next time
    cached = _cache.get("grid")
    if cached is not None and cached[0] == stamp:
        return cached[1]
    surf = _decode_depth(0)
    if surf is None:                # currents bake never ran
        _cache["grid"] = (stamp, None)
        return None
    meta, u0, v0 = surf
    lats, lons = _axes_from_meta(meta)
    u_by, v_by = {0: u0}, {0: v0}
    deep = _decode_depth(1000)
    depths = [0]
    if deep is not None:
        _, u1, v1 = deep
        u_by[1000], v_by[1000] = u1, v1
        depths.append(1000)
    g = _Grid(lats, lons, depths, u_by, v_by)
    _cache["grid"] = (stamp, g)
    return g


def sample(var: str, lat: float, lon: float, lev):
    g = _load_grid(var)
    if g is None:
        return None
    depth = int(lev) if lev is not None else 0
    if depth not in g._u:
        return None
    i = int(np.argmin(np.abs(g.lats - lat)))
    j = int(np.argmin(np.abs(g.lons - lon)))
    arr = g._u[depth] if var == "u" else g._v[depth]
    val = arr[i, j]
    return None if np.isnan(val) else float(val)
