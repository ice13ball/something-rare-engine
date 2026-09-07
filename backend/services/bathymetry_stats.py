# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""GEBCO_2024 TID + elevation per-polygon bathymetry confidence stats.
Local grids loaded windowed (never fully); only per-feature stats persist. CC: GEBCO public-domain w/ acknowledgement."""
from __future__ import annotations
import math, os, pathlib, subprocess, logging
import numpy as np

log = logging.getLogger("abyssal.bathymetry")

CACHE_DIR = pathlib.Path(os.getenv("BATHY_CACHE_DIR", "/var/cache/abyssal-bathymetry"))
RAW_DIR = CACHE_DIR / "raw"
GEBCO_VERSION = "GEBCO_2024"

TID_MEASURED = frozenset({10, 11, 12, 13, 14, 15, 16, 17})
TID_INDIRECT = frozenset({40, 41, 42, 43, 44, 45, 46})
TID_UNKNOWN = frozenset({70, 71, 72})

def classify_confidence(pct_measured: float) -> str:
    if pct_measured >= 80: return "high"
    if pct_measured < 20: return "low"
    return "medium"

def tri(elev: np.ndarray) -> float:
    """Terrain Ruggedness Index: mean abs diff to 8 neighbours."""
    if elev.size < 4:
        return 0.0
    c = elev[1:-1, 1:-1]
    if c.size == 0:
        return 0.0
    acc = np.zeros_like(c, dtype=float)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            acc += np.abs(elev[1+dy:elev.shape[0]-1+dy, 1+dx:elev.shape[1]-1+dx] - c)
    return float(np.mean(acc / 8.0))

def slope_deg(elev: np.ndarray, lat_deg: float, cell_deg: float = 1.0 / 240.0) -> float:
    """Median slope in degrees using great-circle cell spacing at this latitude."""
    if elev.shape[0] < 2 or elev.shape[1] < 2:
        return 0.0
    m_per_deg = 111_320.0
    dy_m = cell_deg * m_per_deg
    dx_m = cell_deg * m_per_deg * max(math.cos(math.radians(lat_deg)), 1e-6)
    gy, gx = np.gradient(elev.astype(float))
    slope = np.degrees(np.arctan(np.hypot(gy / dy_m, gx / dx_m)))
    return float(np.median(slope))

def summarize(tid: np.ndarray, elev: np.ndarray, mask: np.ndarray) -> dict:
    sel = mask & (tid != 0)            # drop land (TID 0)
    codes = tid[sel]
    n = int(codes.size)
    if n == 0:
        return {"n_cells": 0}
    meas = int(np.isin(codes, list(TID_MEASURED)).sum())
    ind = int(np.isin(codes, list(TID_INDIRECT)).sum())
    unk = int(np.isin(codes, list(TID_UNKNOWN)).sum())
    mb = int((codes == 11).sum())
    pct_measured = 100.0 * meas / n
    depths = -elev[sel].astype(float)   # positive-down; only ocean (elev<0) → positive
    depths = depths[depths > 0]
    out = {
        "n_cells": n,
        "pct_measured": pct_measured,
        "pct_indirect": 100.0 * ind / n,
        "pct_unknown": 100.0 * unk / n,
        "pct_multibeam": 100.0 * mb / n,
        "mapped_confidence": classify_confidence(pct_measured),
        "depth_min_m": float(depths.min()) if depths.size else None,
        "depth_median_m": float(np.median(depths)) if depths.size else None,
        "depth_max_m": float(depths.max()) if depths.size else None,
        "gebco_version": GEBCO_VERSION,
    }
    return out


# ---------------------------------------------------------------------------
# Task 2: GEBCO holdings + windowed polygon sampling
# ---------------------------------------------------------------------------
from typing import Optional

# Confirmed via IPv4 HEAD + ZIP central-directory + HDF5 header decode (2026-06-30,
# re-verified 2026-07-16):
#   TID  → ZIP, 107,140,419 B → GEBCO_2024_TID.nc (var="tid", coords lat/lon)
#   ELEV → bare netCDF4/HDF5, 7,466,018,396 B     (var="elevation", coords lat/lon)
#
# BODC moved GEBCO 2024 to CEDA in 2024; both URLs below now 301-redirect there (curl -L
# follows). The redirect is the publisher's own indirection — keep these canonical BODC
# entry points rather than hardcoding CEDA paths, so a future CEDA reshuffle can't break us.
#
# **The two payloads are different formats.** TID still serves a ZIP; ELEV now redirects to
# a bare GEBCO_2024_CF.nc (the DOI-record file). The old 4.27 GB figure was the ZIP; 7.47 GB
# is the same grid uncompressed — no data changed. So _download MUST sniff magic bytes:
# assuming ZIP raises BadZipFile, which the broad `except` swallows into a warning and a
# silently skipped bake. GEBCO_2024_CF.nc was verified to carry the identical
# elevation/lat/lon variables (CF attrs only), so it is drop-in for _window().
TID_URL  = "https://www.bodc.ac.uk/data/open_download/gebco/gebco_2024_tid/zip/"
ELEV_URL = "https://www.bodc.ac.uk/data/open_download/gebco/gebco_2024/zip/"
_ZIP_MAGIC  = b"PK\x03\x04"
_HDF5_MAGIC = b"\x89HDF\r\n\x1a\n"
_TID_FILE  = "GEBCO_2024_TID.nc"
_ELEV_FILE = "GEBCO_2024.nc"
_TID_VAR, _ELEV_VAR, _LAT, _LON = "tid", "elevation", "lat", "lon"


def _tid_path() -> pathlib.Path:  return RAW_DIR / _TID_FILE
def _elev_path() -> pathlib.Path: return RAW_DIR / _ELEV_FILE


def _download(url: str, dst: pathlib.Path) -> bool:
    """Download a BODC GEBCO grid to *dst*, unwrapping it if it arrives as a ZIP."""
    try:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
    except PermissionError as e:
        log.warning("bathymetry: cache dir not writable: %s", e)
        return False
    if dst.exists() and dst.stat().st_size > 0:
        return True
    tmp = dst.with_suffix(".download")
    try:
        subprocess.run(
            ["/usr/bin/curl", "-4", "-fsSL", "-o", str(tmp), url],
            check=True, timeout=3600,
        )
        with open(tmp, "rb") as fh:
            magic = fh.read(8)
        if magic.startswith(_ZIP_MAGIC):
            import zipfile
            with zipfile.ZipFile(tmp) as zf:
                nc_name = next(n for n in zf.namelist() if n.endswith(".nc"))
                zf.extract(nc_name, RAW_DIR)
                extracted = RAW_DIR / nc_name
                if extracted != dst:
                    extracted.replace(dst)
        elif magic.startswith(_HDF5_MAGIC):
            tmp.replace(dst)
        else:
            raise RuntimeError(
                f"unrecognised payload: expected ZIP or netCDF4/HDF5, got magic {magic!r}"
            )
    except Exception as e:
        log.warning("bathymetry download failed %s: %s", url, e)
        return False
    finally:
        tmp.unlink(missing_ok=True)
    return dst.exists() and dst.stat().st_size > 0


def ensure_holdings(force: bool = False) -> bool:
    """Download GEBCO_2024 TID + elevation grids if absent. Returns True when both are present."""
    if force:
        cleanup_holdings()
    return _download(TID_URL, _tid_path()) and _download(ELEV_URL, _elev_path())


def cleanup_holdings() -> None:
    for p in (_tid_path(), _elev_path()):
        try:
            p.unlink()
        except FileNotFoundError:
            pass


def _window(ds_path: pathlib.Path, var: str, bbox):
    import xarray as xr
    w, s, e, n = bbox
    ds = xr.open_dataset(ds_path)
    lat_vals = ds[_LAT].values
    lon_vals = ds[_LON].values
    lat_slice = slice(s, n) if lat_vals[0] <= lat_vals[-1] else slice(n, s)
    lon_slice = slice(w, e) if lon_vals[0] <= lon_vals[-1] else slice(e, w)
    sub = ds[var].sel({_LAT: lat_slice, _LON: lon_slice})
    lats = np.asarray(sub[_LAT].values, dtype=float)
    lons = np.asarray(sub[_LON].values, dtype=float)
    arr  = np.asarray(sub.values)
    ds.close()
    return lats, lons, arr


def sample_polygon(geojson: dict, bbox) -> Optional[dict]:
    """Return summarize() dict + slope_median_deg/ruggedness for *geojson* within *bbox*.

    Returns None if no ocean cells are found in the window.
    """
    from shapely.geometry import shape
    from shapely.vectorized import contains as _vcontains
    poly = shape(geojson)
    lats, lons, tid = _window(_tid_path(), _TID_VAR, bbox)
    if tid.size == 0:
        return None
    _, _, elev = _window(_elev_path(), _ELEV_VAR, bbox)
    if elev.shape != tid.shape:
        # align elevation window to tid grid (same GEBCO grid → should match; guard anyway)
        elev = elev[: tid.shape[0], : tid.shape[1]]
    # Point-in-polygon mask over the window — VECTORISED (shapely.vectorized.contains,
    # C-level). A per-cell Python `Point.contains` loop builds millions of Point objects
    # for large offshore bboxes (some span ~13°×13° ≈ 11M cells) → 6 GB+ RAM → SEGV.
    # For pathological windows, stride-downsample to bound memory; the measured/predicted
    # PERCENTAGES stay representative (n_cells reflects the sampled subset).
    _MAX_CELLS = 4_000_000
    if tid.size > _MAX_CELLS:
        stride = int(np.ceil(np.sqrt(tid.size / _MAX_CELLS)))
        tid = tid[::stride, ::stride]
        elev = elev[::stride, ::stride]
        lats = lats[::stride]
        lons = lons[::stride]
    lon_g, lat_g = np.meshgrid(lons, lats)
    mask = _vcontains(poly, lon_g, lat_g)
    out = summarize(tid.astype(np.int16), elev.astype(float), mask)
    if out.get("n_cells", 0) == 0:
        return None
    lat_c = float(np.mean(lats))
    out["slope_median_deg"] = slope_deg(elev.astype(float), lat_c)
    out["ruggedness"]       = tri(elev.astype(float))
    return out
