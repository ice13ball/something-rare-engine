# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Field-export sampler for the bathymetry layer.

One-time bake downsamples GEBCO_2024 elevation to ~0.05° and persists a compact
holding; the sampler serves depth cells over an AOI via the standard field-export
contract. Reuses the GEBCO download + xarray machinery in bathymetry_stats."""
from __future__ import annotations
import json, logging, os, pathlib
import numpy as np

from services import cache_swap

log = logging.getLogger(__name__)

GRID_DIR = pathlib.Path(os.getenv("BATHY_GRID_DIR", "/var/cache/abyssal-bathymetry-grid"))
STEP_DEG = 0.05                      # ~5.5 km export grid
_DEPTH_NPY = "depth.npy"
_META_JSON = "meta.json"
#: "grid" -> (stamp-at-load-time, grid-or-None). The stamp is taken BEFORE the
#: load on purpose: if the file is swapped in between, the cached stamp is older
#: than the data and the next request reloads. The reverse order could cache a
#: NEW stamp beside OLD data and serve it forever.
_cache: "dict[str, tuple[tuple, _Grid | None]]" = {}


class _Grid:
    def __init__(self, lats, lons, elev):
        self.lats = lats            # descending
        self.lons = lons            # ascending
        self._elev = elev           # 2-D float32


def reset_cache() -> None:
    _cache.clear()


def _write_holding(lats, lons, elev) -> int:
    GRID_DIR.mkdir(parents=True, exist_ok=True)
    # ⛔ ATOMIC, not np.save(path, …): _load_grid() below holds depth.npy through
    # mmap_mode="r", and since the web/worker process split the writer is a
    # DIFFERENT process from that reader. A truncate-and-refill under a live
    # mapping does not raise — it yields garbage or SIGBUS, which kills the web
    # process. Temp file beside the target, then os.replace. See services/cache_swap.py.
    cache_swap.atomic_np_save(GRID_DIR / _DEPTH_NPY, elev)
    cache_swap.atomic_write_text(GRID_DIR / _META_JSON, json.dumps({
        "lats": [float(x) for x in lats], "lons": [float(x) for x in lons],
        "step_deg": STEP_DEG,
    }))
    return int(elev.size)


def bake_bathymetry_grid(force: bool = False) -> int:
    """Downsample GEBCO_2024 elevation to STEP_DEG and persist the holding. Idempotent."""
    if not force and (GRID_DIR / _DEPTH_NPY).is_file() and (GRID_DIR / _META_JSON).is_file():
        log.info("bathymetry-grid: holding present — skipping bake")
        return 0
    from services import bathymetry_stats as bs
    if not bs.ensure_holdings():
        log.error("bathymetry-grid: GEBCO holdings unavailable — bake skipped")
        return 0
    import xarray as xr
    ds = xr.open_dataset(bs._elev_path())
    da = ds[bs._ELEV_VAR]                     # dims (lat, lon)
    # native 15" grid → ~STEP_DEG via integer-stride NEAREST-POINT decimation (NOT
    # coarsen().mean()): the real grid is ~86400x43200, and .coarsen().mean() forces
    # xarray to materialize the ENTIRE array (tens of GB after float64 promotion)
    # before reducing — OOM-kills the VPS abyssal-api process. `isel` with a strided
    # slice is lazy and only reads every Nth point off disk, so only the decimated
    # ~7200x3600 subset (~100 MB) is ever materialized. Was mean (smoother), now
    # decimated (picks the nearest native cell) to keep memory flat — acceptable
    # quality for a 0.05° export product.
    native = float(abs(ds[bs._LAT].values[1] - ds[bs._LAT].values[0]))
    stride = max(1, int(round(STEP_DEG / native)))
    coarse = da.isel({bs._LAT: slice(None, None, stride), bs._LON: slice(None, None, stride)})
    lats = coarse[bs._LAT].values.astype("float64")
    lons = coarse[bs._LON].values.astype("float64")
    elev = coarse.values.astype("float32")
    if lats[0] < lats[-1]:                    # ensure N→S
        lats = lats[::-1]; elev = elev[::-1, :]
    ds.close()
    n = _write_holding(lats, lons, elev)
    reset_cache()
    # Delete the transient elevation grid after use — mirrors the sibling
    # bathymetry_stats contract: its orchestrator (sync_bathymetry_stats in
    # domains/seafloor.py) calls bs.cleanup_holdings() in a finally block after
    # every batch use, treating the downloaded GEBCO grids as transient scratch
    # space, not a persistent cache. Best-effort; only removes the elevation
    # file this bake used (leaves TID alone — untouched by this function).
    try:
        bs._elev_path().unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        log.warning("bathymetry-grid: could not remove transient elevation file: %s", exc)
    log.info("bathymetry-grid: baked %d cells at %.3f° (stride %d)", n, STEP_DEG, stride)
    return n


def _load_grid(var: str = "depth_m") -> "_Grid | None":
    npy = GRID_DIR / _DEPTH_NPY
    meta_p = GRID_DIR / _META_JSON
    # Two os.stat calls before trusting the cache. The worker process re-bakes
    # these files; nothing tells this process about it, and reset_cache() only
    # ever reaches the process that called it. Without this check a mapping made
    # before the swap keeps serving the OLD inode's data for the lifetime of the
    # web process — silently, which is the failure mode this project treats as
    # worse than a crash. st_ino catches the os.replace, st_mtime_ns an in-place
    # rewrite onto a reused inode, st_size a truncation.
    stamp = cache_swap.file_stamp((npy, meta_p))
    cached = _cache.get("grid")
    if cached is not None and cached[0] == stamp:
        return cached[1]
    if not npy.is_file() or not meta_p.is_file():
        _cache["grid"] = (stamp, None)
        return None
    meta = json.loads(meta_p.read_text())
    # mmap_mode="r": depth.npy is ~104 MB (3600x7200 float32 — see
    # rules/layers/bathymetry-gebco-paths.md) and read-only from here on — sample()
    # below only ever does scalar indexing (g._elev[i, j]), never a write or
    # in-place reshape, so a lazy read-only mapping is safe for the data itself.
    # Measured 2026-09-18: loading a comparable 104 MB array normally peaks at
    # ~135 MB RSS vs ~58 MB with mmap_mode="r" under the same scattered-index
    # access pattern sample() uses (throwaway benchmark, not kept in the repo).
    # Safe against a concurrent re-bake as of the web/worker process split: the
    # precondition the previous version of this comment named — "_write_holding
    # must go atomic before mmap_mode stays safe here" — is now MET.
    # _write_holding() writes through cache_swap (temp file beside the target +
    # os.replace), so a re-bake never truncates the file this mapping covers; it
    # publishes a new inode and leaves ours intact until we drop it. The stamp
    # check above is the other half: it is what makes us drop it.
    g = _Grid(np.asarray(meta["lats"]), np.asarray(meta["lons"]),
              np.load(npy, mmap_mode="r"))
    _cache["grid"] = (stamp, g)
    return g


def sample(var: str, lat: float, lon: float, lev):
    g = _load_grid(var)
    if g is None:
        return None
    i = int(np.argmin(np.abs(g.lats - lat)))
    j = int(np.argmin(np.abs(g.lons - lon)))
    val = g._elev[i, j]
    return None if np.isnan(val) else float(val)
