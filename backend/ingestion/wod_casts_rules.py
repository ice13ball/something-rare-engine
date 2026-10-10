# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""WOD23 casts (`wod-casts`): pure constants and functions shared by the parser, the loader, the tiles service,
the API and the measurement script. numpy only; no I/O, no DB. ⛔ The API reads its constants from HERE."""
from __future__ import annotations

import math
import os
import re
from datetime import date, datetime, timedelta, timezone

import numpy as np

SOURCE = "wod-casts"                 # sync_log.source of the import
TILES_SOURCE = "wod-tiles"           # sync_log.source of the pre-bake
RELEASE = "WOD23"
BASE_URL = os.getenv("WOD_CASTS_BASE_URL", "https://www.ncei.noaa.gov/data/oceans/ncei/wod")
YEAR_DIR_RE = re.compile(r'href="([0-9]{4})/"')
FILE_HREF_RE = re.compile(r'href="(wod_(osd|ctd|pfl)_([0-9]{4})\.nc)"')

# (code, netCDF variable, WOA variable key, smallint scale of the picks). Units are checked against
# EXPECTED_UNITS at read time and never converted. Salinity carries NO units attribute in WOD (Phase 0).
VARS = (("t", "Temperature", "temperature", 100), ("s", "Salinity", "salinity", 100),
        ("o", "Oxygen", "oxygen", 10), ("p", "Phosphate", "phosphate", 100),
        ("i", "Silicate", "silicate", 10), ("n", "Nitrate", "nitrate", 10))
EXPECTED_UNITS = {"z": "m", "Temperature": "degree_C", "Salinity": None, "Oxygen": "umol/kg",
                  "Phosphate": "umol/kg", "Silicate": "umol/kg", "Nitrate": "umol/kg"}
PICK_VARS = tuple(v[2] for v in VARS) + ("nstar",)          # N* = NO3 - 16 PO4, same level, both good (R8)
VAR_CODE = {**{v[2]: v[0] for v in VARS}, "nstar": "x"}
VAR_CODE_TO_INDEX = {v[0]: k for k, v in enumerate(VARS)}
SCALES = {**{v[2]: v[3] for v in VARS}, "nstar": 10}
NSTAR_K = 16.0
DEPTHS = (0, 50, 100, 200, 500, 1000, 1500, 2000)            # == woa_climatology.DISPLAY_DEPTHS (pinned)
WINDOWS = ((0.0, 10.0), (40.0, 60.0), (90.0, 110.0), (175.0, 225.0), (450.0, 550.0),
           (950.0, 1050.0), (1425.0, 1575.0), (1900.0, 2100.0))   # R1: argo-oxygen-points' windows
N_PICKS = len(PICK_VARS) * len(DEPTHS)                        # 56
MAX_LEVELS = 100
NO_VALUE_FLAG = 255                                           # flag byte where a variable has no value
GOOD_FLAG = 0                                                 # WODflag / z_WODflag / WODprofileflag "accepted"
SMALLINT = 32767

# Run state (worker + loader; the unit's TimeoutStartSec = LOCK_WAIT_S + RUN_BUDGET_S + LOD/prebake + margin)
LOCK_KEY = 4242001
LOCK_WAIT_S = 2 * 3600
RUN_BUDGET_S = int(3.5 * 3600)
STARTED_PREFIX = "started"                                    # sync_log.skipped_reason marker an import writes when it begins
STARTED_STALE = timedelta(hours=8)                            # == TimeoutStartSec=8h in deploy/wod-casts.service
CHECK_EVERY = timedelta(days=91)                              # quarterly source check (R10)
MAX_SAME_FILE_INTERRUPTS = 2
CHUNK_CASTS = 5000                                            # casts per COPY
CHUNK_OBS = 2_000_000                                         # z levels per netCDF read (bounds RSS)
DROP_BLOCK_FRACTION = 0.10                                    # a republished file losing >10 % of stored casts blocks
PREBAKE_ALL_ZOOM = 5
PREBAKE_HEAVY_CASTS = 50_000
PREBAKE_HEAVY_MAX_ZOOM = 10
PREBAKE_TIMEOUT = "60s"
PREBAKE_DEADLINE_S = int(os.getenv("WOD_PREBAKE_DEADLINE_S", "2700"))   # the pre-bake stops at this deadline
PREBAKE_MAX_CONSECUTIVE_TIMEOUTS = 20
WAL_ALLOWANCE_BYTES = 2 * 1024**3                             # max_wal_size 1GB on the VPS -> 2 GiB headroom
DISK_STOP_PROJECTED = 0.80                                    # preflight refuses a file projected above this fill
DISK_STOP_ACTUAL = 0.82                                       # a running load stops when the real fill passes this
DOWNLOAD_DIR = os.getenv("WOD_DOWNLOAD_DIR", "/mnt/abyssal-data/wod-download")
TILE_CACHE_DIR = os.getenv("WOD_TILE_CACHE_DIR", "/mnt/abyssal-data/wod-tiles")
CAP_LIST = 1000                                               # casts listed by /cell (totals stay exact)

# Tiles / cells (R3). The census (2026-10-09) fixed POINT_MIN_ZOOM = 6.
POINT_MIN_ZOOM = 6
TILE_MAX_ZOOM = 12
GRID_BITS = 20
LOD_LEVELS = tuple(range(POINT_MIN_ZOOM // 2))
WORLD = 20037508.342789244
R_EARTH = 6378137.0
MERC_LAT = 85.0511

EPOCH = date(1770, 1, 1)
EPOCH_DT = datetime(1770, 1, 1, tzinfo=timezone.utc)


def slot(var: str, depth_i: int) -> int:
    return PICK_VARS.index(var) * len(DEPTHS) + depth_i


def pick_levels(z: np.ndarray, good: np.ndarray) -> list[int | None]:
    """Per display depth: index of the good level nearest the target inside its window (ties -> shallower, then
    lower index), or None. One implementation for the parser and the API, so the stored picks and the panel agree."""
    out: list[int | None] = []
    for target, (lo, hi) in zip(DEPTHS, WINDOWS):
        cand = np.flatnonzero(good & (z >= lo) & (z <= hi))
        if cand.size == 0:
            out.append(None)
            continue
        order = np.lexsort((cand, z[cand], np.abs(z[cand] - target)))
        out.append(int(cand[order[0]]))
    return out


def thin_indices(z: np.ndarray, must: set[int]) -> np.ndarray:
    """Indices (into z) kept for one variable after its fills were dropped: all when <= MAX_LEVELS, else the
    must-keep set (picks), the shallowest and deepest level and the level nearest each evenly spaced target."""
    n = len(z)
    if n <= MAX_LEVELS:
        return np.arange(n)
    keep = set(must) | {int(np.argmin(z)), int(np.argmax(z))}
    order = np.argsort(z, kind="stable")
    zs = z[order]
    budget = MAX_LEVELS - len(keep)
    if budget > 0:
        for t in np.linspace(zs[0], zs[-1], budget + 2)[1:-1]:
            k = int(np.searchsorted(zs, t))
            if k > 0 and (k == n or abs(zs[k - 1] - t) <= abs(zs[k] - t)):
                k -= 1                                            # tie -> shallower
            keep.add(int(order[k]))
            if len(keep) >= MAX_LEVELS:
                break
    return np.array(sorted(keep), dtype=np.int64)


def scaled(value: float, var: str) -> int:
    return max(-SMALLINT, min(SMALLINT, int(round(value * SCALES[var]))))


def decode_time(t, d) -> tuple[date | None, datetime | None, str | None]:
    """WOD `time` (days since 1770-01-01 UTC; < 1.0 = fill) first, then the `date` variable (YYYYMMDD, month/day
    may be 0). A zero fraction means no time of day was recorded: a date, never a midnight. 1970-01-01 is real."""
    if t is not None and math.isfinite(t) and t >= 1.0:
        whole = math.floor(t)
        frac = t - whole
        day = EPOCH + timedelta(days=whole)
        if frac > 0:
            secs = min(round(frac * 86400), 86399)
            return day, EPOCH_DT + timedelta(days=whole, seconds=secs), "second"
        return day, None, "day"
    if d is None or d <= 0:
        return None, None, None
    d = int(d)
    y, m, dd = d // 10000, (d // 100) % 100, d % 100
    if not (1770 <= y <= 2100) or m > 12:
        return None, None, None
    if m == 0:
        return date(y, 1, 1), None, "year"
    if dd == 0:
        return date(y, m, 1), None, "month"
    try:
        return date(y, m, dd), None, "day"
    except ValueError:
        return None, None, None


def to_3857(lon, lat):
    lon = np.asarray(lon, dtype=np.float64)
    lat = np.clip(np.asarray(lat, dtype=np.float64), -MERC_LAT, MERC_LAT)
    return R_EARTH * np.radians(lon), R_EARTH * np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))


_MASKS = (0x0000FFFF0000FFFF, 0x00FF00FF00FF00FF, 0x0F0F0F0F0F0F0F0F, 0x3333333333333333, 0x5555555555555555)


def _spread(v):
    v = np.asarray(v, dtype=np.uint64)
    for shift, mask in zip((16, 8, 4, 2, 1), _MASKS):
        v = (v | (v << np.uint64(shift))) & np.uint64(mask)
    return v


def _compact(v: int) -> int:
    v &= 0x5555555555555555
    for shift, mask in zip((1, 2, 4, 8, 16), (0x3333333333333333, 0x0F0F0F0F0F0F0F0F, 0x00FF00FF00FF00FF,
                                              0x0000FFFF0000FFFF, 0x00000000FFFFFFFF)):
        v = (v | (v >> shift)) & mask
    return v


def morton_key(x, y) -> np.ndarray:
    """Cell of a 2^20 x 2^20 grid over EPSG:3857, cx from the west, cy from the NORTH (MVT y runs down),
    interleaved (cx in the even bits). A tile and every coarser cell is one contiguous key range."""
    n = 1 << GRID_BITS
    cx = np.clip(np.floor((np.asarray(x) + WORLD) / (2 * WORLD) * n), 0, n - 1)
    cy = np.clip(np.floor((WORLD - np.asarray(y)) / (2 * WORLD) * n), 0, n - 1)
    return (_spread(cx) | (_spread(cy) << np.uint64(1))).astype(np.int64)


def _prefix(z: int, tx: int, ty: int) -> int:
    return int(_spread(tx)) | (int(_spread(ty)) << 1)


def tile_key_range(z: int, tx: int, ty: int) -> tuple[int, int]:
    s = 2 * (GRID_BITS - z)
    p = _prefix(z, tx, ty)
    return p << s, (p + 1) << s


def lod_level(z: int) -> int:
    if not 0 <= z < POINT_MIN_ZOOM:
        raise ValueError("no LOD level at this zoom")
    return z // 2


def level_bits(level: int) -> int:
    return 6 + 2 * level                                   # 64 cells per tile axis at z = 2L, 32 at z = 2L+1


def cell_bits(z: int) -> int:
    return level_bits(lod_level(z)) if z < POINT_MIN_ZOOM else z + 8   # 256 per tile axis from POINT_MIN_ZOOM


def cell_key_range(z: int, tx: int, ty: int, q: int) -> tuple[int, int]:
    k = cell_bits(z)
    cell = (_prefix(z, tx, ty) << (2 * (k - z))) + q
    s = 2 * (GRID_BITS - k)
    return cell << s, (cell + 1) << s


def cell_bounds_3857(z: int, tx: int, ty: int, q: int) -> tuple[float, float, float, float]:
    k = cell_bits(z)
    per = 1 << (k - z)
    lx, ly = _compact(q), _compact(q >> 1)
    size = 2 * WORLD / (1 << k)
    x0 = -WORLD + (tx * per + lx) * size
    y1 = WORLD - (ty * per + ly) * size
    return x0, y1 - size, x0 + size, y1
