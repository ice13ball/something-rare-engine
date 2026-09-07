# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Dutkiewicz et al. 2015 global seafloor lithology (categorical 0.1° grid).
Loaded into memory (no DB table). License: CC-BY-NC."""
from __future__ import annotations
import io, logging, math, os, pathlib, subprocess
import numpy as np

log = logging.getLogger("abyssal.seabed")

CACHE_DIR = pathlib.Path(os.getenv("SEABED_CACHE_DIR", "/var/cache/abyssal-seabed"))
RAW_DIR = CACHE_DIR / "raw"
NC_FILE = "seabed_lithology_v1.nc"
NC_URL = ("https://www.earthbyte.org/webdav/ftp/papers/"
          "Dutkiewicz_etal_seafloor_lithology/seabed_lithology_v1.nc")

CITATION = ("Dutkiewicz, A., Müller, R. D., O'Callaghan, S., & Jónasson, H. (2015). "
            "Census of seafloor sediments in the world's ocean. Geology, doi:10.1130/G36883.1.")
LICENSE = "CC-BY-NC"
FILL_ALPHA = 210

LITHOLOGY_CLASSES: dict[int, str] = {
    1: "Gravel and coarser", 2: "Sand", 3: "Silt", 4: "Clay",
    5: "Calcareous ooze", 6: "Radiolarian ooze", 7: "Diatom ooze",
    8: "Sponge spicules", 9: "Mixed calcareous/siliceous ooze",
    10: "Shells and coral fragments", 11: "Ash and volcanic sand/gravel",
    12: "Siliceous mud", 13: "Fine-grained calcareous sediment",
}
CLASS_KEYS: dict[int, str] = {
    1: "gravel", 2: "sand", 3: "silt", 4: "clay", 5: "calcareous_ooze",
    6: "radiolarian_ooze", 7: "diatom_ooze", 8: "sponge_spicules", 9: "mixed_ooze",
    10: "shells_coral", 11: "ash_volcanic", 12: "siliceous_mud", 13: "fine_calcareous",
}
CPT_RGB: dict[int, tuple[int, int, int]] = {
    1: (128,130,132), 2: (255,241,0), 3: (250,169,25), 4: (112,75,42),
    5: (14,145,207), 6: (13,150,71), 7: (190,215,83), 8: (85,147,141),
    9: (131,112,178), 10: (247,187,213), 11: (234,27,27), 12: (195,154,107),
    13: (0,46,167),
}

def class_color(code: int) -> tuple[int, int, int, int]:
    rgb = CPT_RGB.get(int(code))
    return (*rgb, FILL_ALPHA) if rgb else (0, 0, 0, 0)

# LUT indexed by class code 0..13 (0 = nodata → transparent)
PALETTE_LUT = np.zeros((14, 4), dtype=np.uint8)
for _c in range(1, 14):
    PALETTE_LUT[_c] = class_color(_c)

def build_meta() -> dict:
    return {
        "classes": [
            {"code": c, "key": CLASS_KEYS[c], "name": LITHOLOGY_CLASSES[c],
             "rgb": list(CPT_RGB[c])}
            for c in range(1, 14)
        ],
        "citation": CITATION,
        "license": LICENSE,
        "resolution_deg": 0.1,
    }


# ── Grid loading, sampling & tile rendering ──────────────────────────────────

from typing import NamedTuple

class _Grid(NamedTuple):
    lats: np.ndarray   # ascending
    lons: np.ndarray   # ascending, -180..180
    data: np.ndarray   # (nlat, nlon) int16

_GRID: _Grid | None = None
# Set to the names discovered from the real file via xarray.open_dataset:
# data_vars=['z'], coords=['lon','lat']
_DATA_VAR = "z"
_LAT = "lat"
_LON = "lon"

def _grid_path() -> pathlib.Path:
    return RAW_DIR / NC_FILE

def ensure_holdings(force: bool = False) -> bool:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    dst = _grid_path()
    if dst.exists() and dst.stat().st_size > 0 and not force:
        return True
    try:
        subprocess.run(["/usr/bin/curl", "-4", "-fsSL", "-o", str(dst), NC_URL],
                       check=True, timeout=900)
    except Exception as e:
        log.warning("seabed download failed: %s", e)
        return False
    return dst.exists() and dst.stat().st_size > 0

def load_grid() -> _Grid | None:
    global _GRID
    if _GRID is not None:
        return _GRID
    path = _grid_path()
    if not path.exists() or path.stat().st_size == 0:
        return None
    import xarray as xr
    ds = xr.open_dataset(path)
    var = _DATA_VAR if _DATA_VAR in ds else list(ds.data_vars)[0]
    lat_name = _LAT if _LAT in ds.coords else [c for c in ds.coords if "lat" in c.lower() or c in ("y",)][0]
    lon_name = _LON if _LON in ds.coords else [c for c in ds.coords if "lon" in c.lower() or c in ("x",)][0]
    lats = np.asarray(ds[lat_name].values, dtype=float)
    lons = np.asarray(ds[lon_name].values, dtype=float)
    data = np.asarray(ds[var].values).squeeze().astype(np.int16)   # (nlat, nlon)
    ds.close()
    # normalise lon to -180..180 and sort both axes ascending
    lons = np.where(lons > 180.0, lons - 360.0, lons)
    lon_order = np.argsort(lons); lons = lons[lon_order]; data = data[:, lon_order]
    if lats[0] > lats[-1]:
        lats = lats[::-1]; data = data[::-1, :]
    _GRID = _Grid(lats=lats, lons=lons, data=data)
    return _GRID

def _idx(axis: np.ndarray, value) -> np.ndarray:
    step = axis[1] - axis[0]
    i = np.rint((np.asarray(value, dtype=float) - axis[0]) / step).astype(int)
    return np.clip(i, 0, axis.size - 1)

def sample(lat: float, lon: float) -> int | None:
    g = load_grid()
    if g is None:
        return None
    # out-of-extent coordinates → None (no silent extrapolation)
    if not (g.lats[0] <= lat <= g.lats[-1] and g.lons[0] <= lon <= g.lons[-1]):
        return None
    code = int(g.data[int(_idx(g.lats, lat)), int(_idx(g.lons, lon))])
    return code if 1 <= code <= 13 else None

_TILE = 256

def render_tile(z: int, x: int, y: int) -> bytes | None:
    g = load_grid()
    if g is None:
        return None
    n = 2 ** z
    px = (np.arange(_TILE) + 0.5) / _TILE
    lons = (x + px) / n * 360.0 - 180.0                       # linear in lon
    yt = (y + px) / n
    merc = math.pi * (1.0 - 2.0 * yt)
    lats = np.degrees(np.arctan(np.sinh(merc)))               # inverse mercator per row
    rows = _idx(g.lats, lats)                                 # (TILE,)
    cols = _idx(g.lons, lons)                                 # (TILE,)
    codes = g.data[np.ix_(rows, cols)]                        # (TILE,TILE) int16
    codes = np.where((codes >= 1) & (codes <= 13), codes, 0).astype(np.uint8)
    rgba = PALETTE_LUT[codes]                                 # (TILE,TILE,4)
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG")
    return buf.getvalue()
