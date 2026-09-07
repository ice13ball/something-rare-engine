# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""CASCADE interpolated grid: ESRI-ASCII holdings + polar-stereographic sampling
+ on-demand PNG tile rendering. numpy + pyproj only (no rasterio/GDAL).
Grid CRS: custom polar stereographic, lat_ts=75, lon_0=0 (NOT EPSG:3995)."""
from __future__ import annotations
import io, math, os, pathlib, subprocess, zipfile

import numpy as np

from services.cascade_ramp import cascade_color, CASCADE_VARS

CACHE_DIR = pathlib.Path(os.getenv("CASCADE_CACHE_DIR", "/var/cache/abyssal-cascade"))
RAW_DIR = CACHE_DIR / "raw"
GRID_ZIP_URL = "https://bolin.su.se/data/uploads/cascade-grid-2.zip"
PROJ4 = "+proj=stere +lat_0=90 +lat_ts=75 +lon_0=0 +k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"

_ASCII = {
    "oc":   "cascadesurfsed_v2_ocinterp.txt",
    "tn":   "cascadesurfsed_v2_tninterp.txt",
    "d13c": "cascadesurfsed_v2_13cinterp.txt",
    "d14c": "cascadesurfsed_v2_14cinterp.txt",
}
_GRIDS: dict[str, tuple[dict, "np.ndarray"]] = {}
_TF = None  # pyproj transformer 4326 -> polar


def reset_cache():
    global _GRIDS, _TF
    _GRIDS = {}
    _TF = None


def _parse_ascii(text: str):
    lines = text.splitlines()
    hdr = {}
    for i in range(6):
        k, v = lines[i].split()
        hdr[k.lower()] = float(v)
    hdr["ncols"] = int(hdr["ncols"]); hdr["nrows"] = int(hdr["nrows"])
    arr = np.loadtxt(lines[6:6 + hdr["nrows"]])
    return hdr, arr


def _is_unsafe_zip_member(name: str) -> bool:
    """Reject absolute paths and any '..' traversal component."""
    if not name or os.path.isabs(name) or name.startswith(("/", "\\")):
        return True
    parts = pathlib.PurePosixPath(name.replace("\\", "/")).parts
    return ".." in parts


def ensure_holdings(force: bool = False) -> bool:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    present = all((RAW_DIR / "CASCADEsurfsed_v2_interp" / "ASCII" / fn).exists() for fn in _ASCII.values())
    if present and not force:
        return True
    zpath = RAW_DIR / "cascade-grid-2.zip"
    subprocess.run(["/usr/bin/curl", "-4", "-fsSL", "-o", str(zpath), GRID_ZIP_URL], check=True, timeout=1200)
    with zipfile.ZipFile(zpath) as z:
        # path-traversal guard — never drop. zipfile.extractall has no
        # tarfile-style `filter=` kwarg, so validate members manually.
        for info in z.infolist():
            if _is_unsafe_zip_member(info.filename):
                raise ValueError(f"unsafe path in cascade grid zip: {info.filename!r}")
        z.extractall(RAW_DIR)
    zpath.unlink(missing_ok=True)
    reset_cache()
    return all((RAW_DIR / "CASCADEsurfsed_v2_interp" / "ASCII" / fn).exists() for fn in _ASCII.values())


def _grid(variable: str):
    if variable not in _ASCII:
        variable = "oc"
    if variable not in _GRIDS:
        path = RAW_DIR / "CASCADEsurfsed_v2_interp" / "ASCII" / _ASCII[variable]
        if not path.exists():
            return None
        _GRIDS[variable] = _parse_ascii(path.read_text(encoding="latin-1"))
    return _GRIDS[variable]


def _transformer():
    global _TF
    if _TF is None:
        from pyproj import Transformer
        _TF = Transformer.from_crs("EPSG:4326", PROJ4, always_xy=True)
    return _TF


def sample(lat: float, lon: float, variable: str) -> float | None:
    grid = _grid(variable)
    if grid is None:
        return None
    hdr, arr = grid
    x, y = _transformer().transform(lon, lat)
    col = int((x - hdr["xllcorner"]) / hdr["cellsize"])
    y_top = hdr["yllcorner"] + hdr["nrows"] * hdr["cellsize"]   # ASCII rows run N->S
    row = int((y_top - y) / hdr["cellsize"])
    if not (0 <= row < hdr["nrows"] and 0 <= col < hdr["ncols"]):
        return None
    v = float(arr[row, col])
    return None if v <= -9990 else v


_TILE = 256


def _tile_lonlat(z, x, y):
    n = 2 ** z
    def lon(px): return (x + px / _TILE) / n * 360.0 - 180.0
    def lat(py):
        t = math.pi * (1 - 2 * (y + py / _TILE) / n)
        return math.degrees(math.atan(math.sinh(t)))
    return lon, lat


def render_tile(z: int, x: int, y: int, variable: str) -> bytes | None:
    from PIL import Image
    grid = _grid(variable)
    if grid is None:
        return None
    hdr, arr = grid
    lon_of, lat_of = _tile_lonlat(z, x, y)

    lats = np.array([lat_of(py) for py in range(_TILE)])
    lons = np.array([lon_of(pxc) for pxc in range(_TILE)])
    lat_grid, lon_grid = np.meshgrid(lats, lons, indexing="ij")  # (py, pxc)

    # CASCADE is circum-Arctic; skip southern rows fast (array mask, not a loop)
    north_mask = lat_grid >= 55
    px = np.zeros((_TILE, _TILE, 4), dtype=np.uint8)
    if not north_mask.any():
        return None

    py_idx, pxc_idx = np.where(north_mask)
    lon_flat = lon_grid[north_mask]
    lat_flat = lat_grid[north_mask]

    # single batched pyproj call instead of up to 65,536 scalar calls
    x_m, y_m = _transformer().transform(lon_flat, lat_flat)

    col = ((x_m - hdr["xllcorner"]) / hdr["cellsize"]).astype(int)
    y_top = hdr["yllcorner"] + hdr["nrows"] * hdr["cellsize"]  # ASCII rows run N->S
    row = ((y_top - y_m) / hdr["cellsize"]).astype(int)

    in_bounds = (row >= 0) & (row < hdr["nrows"]) & (col >= 0) & (col < hdr["ncols"])
    if not in_bounds.any():
        return None

    py_valid = py_idx[in_bounds]
    pxc_valid = pxc_idx[in_bounds]
    values = arr[row[in_bounds], col[in_bounds]]

    drew = False
    for k in range(values.shape[0]):
        v = float(values[k])
        v = None if v <= -9990 else v
        c = cascade_color(v, variable)
        if c[3]:
            px[py_valid[k], pxc_valid[k]] = c
            drew = True
    if not drew:
        return None
    buf = io.BytesIO()
    Image.fromarray(px, "RGBA").save(buf, format="PNG")
    return buf.getvalue()


def build_meta() -> dict:
    from services.cascade_ramp import RAMPS
    return {
        "variables": [
            {"key": k, "domain": RAMPS[k]["domain"], "kind": RAMPS[k]["kind"]}
            for k in CASCADE_VARS
        ],
        "citation": "Martens et al. 2021, ESSD 13:2561, doi:10.5194/essd-13-2561-2021",
        "license": "CC-BY 4.0",
        "note": "Interpolated surface (5 km) — modelled, not raw measurements.",
        # Counted from our own cascade_stations holding on 2026-09-04: 4,496 cores,
        # years 1934-2018, 192 of them with no year at all.
        "observation_window": {
            "start": 1934, "end": 2018,
            "source": "cascade_stations, counted 2026-09-04",
        },
    }
