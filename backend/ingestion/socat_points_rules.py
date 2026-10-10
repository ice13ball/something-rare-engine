# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""SOCATv2026 observation-point rules — pure, no I/O. Every fact here was measured on the real
SOCATv2026.tsv (9 GB, 44,018,204 rows) on 2026-10-09: see tests/fixtures/socat_points/SCHEMA_NOTES.md."""
from __future__ import annotations
import math
import os
import re
from datetime import datetime, timedelta, timezone

# ── Identity ──────────────────────────────────────────────────────────────────────────────────────────
SOURCE = "socat-points"          # sync_log.source of the import
TILES_SOURCE = "socat-tiles"     # sync_log.source of the tile-cache marker
RELEASE = "v2026"
SWAPPED_WITH_REJECTS_PREFIX = "swapped with rejects"   # sync_log.skipped_reason of a swap that stored rejected rows

# ── Worker (socat_points_worker.py) ──────────────────────────────────────────────────────────────────────
STARTED_PREFIX = "started"                  # sync_log.skipped_reason marker an import writes when it begins
# STARTED_STALE == the unit's TimeoutStartSec (deploy/socat-points.service): 2 h shared-lock wait (the worker's
# LOCK_WAIT_S) + the import measured in Task 2 (642 s parse; the DB side is the long part, hours) + 45 min tile
# bake (PREBAKE_DEADLINE_S). A start marker older than this belongs to a process that was killed. Keep BOTH in step.
STARTED_STALE = timedelta(hours=6)
LOW_MEMORY_PREFIX = "low memory"
DISK_PREFIX = "disk above"
HEAD_FAILED_PREFIX = "head failed"
TRANSIENT_PREFIXES = (LOW_MEMORY_PREFIX, DISK_PREFIX, HEAD_FAILED_PREFIX)
FAILED_OUTCOMES = ("blocked", "error", "schema", "disk")   # loader outcomes that start the 7-day back-off
MAX_SAME_POINT_INTERRUPTS = 2    # interrupt_count at which a run that died twice at the SAME expocode backs off

# Tile pre-bake after a swap (plankton pre-bake precedent, 2026-10-07): z0..PREBAKE_ALL_ZOOM in full, plus every tile of
# z(PREBAKE_ALL_ZOOM+1)..PREBAKE_HEAVY_ZOOM holding at least PREBAKE_HEAVY_OBS drawable observations (counted
# at swap time), so the ferry-corridor tiles (z9 max 857,953 obs, Task 2) are not computed on the request path.
PREBAKE_ALL_ZOOM = 6
PREBAKE_HEAVY_ZOOM = 10
PREBAKE_HEAVY_OBS = 100_000
PREBAKE_TIMEOUT = "60s"            # per-tile statement timeout (the request path keeps its 10 s)
PREBAKE_DEADLINE_S = 2700          # 45 min; env SOCAT_PREBAKE_DEADLINE_S. The lock 4242001 is held meanwhile.
PREBAKE_MAX_CONSECUTIVE_TIMEOUTS = 20

# Observation key `EXPOCODE~N` (N = 0-based ordinal of the row in its cruise). Expocode character set measured
# on the whole file (Task 2, 2026-10-09): [-0-9A-Z] only. Nothing else is ever looked up.
EXPOCODE_RE = re.compile(r"[-0-9A-Z]{1,64}")
OBS_KEY_RE = re.compile(r"([-0-9A-Z]{1,64})~(0|[1-9][0-9]{0,8})")
ZIP_URL = os.getenv(
    "SOCAT_POINTS_ZIP_URL",
    "https://www.ncei.noaa.gov/data/oceans/ncei/ocads/data/0315110/SOCATv2026_synthesis_file.zip")

# The 32 data columns, verbatim from the file's own header line (SCHEMA_NOTES section 2). A renamed,
# added or reordered column means the file is no longer the one these rules were measured on.
EXPECTED_HEADER: tuple[str, ...] = (
    "Expocode", "version", "Source_DOI", "QC_Flag", "yr", "mon", "day", "hh", "mm", "ss",
    "longitude [dec.deg.E]", "latitude [dec.deg.N]", "sample_depth [m]", "sal", "SST [deg.C]",
    "Tequ [deg.C]", "PPPP [hPa]", "Pequ [hPa]", "WOA_SSS", "NCEP_SLP [hPa]", "ETOPO2_depth [m]",
    "dist_to_land [km]", "GVCO2 [umol/mol]", "xCO2water_equ_dry [umol/mol]",
    "xCO2water_SST_dry [umol/mol]", "pCO2water_equ_wet [uatm]", "pCO2water_SST_wet [uatm]",
    "fCO2water_equ_wet [uatm]", "fCO2water_SST_wet [uatm]", "fCO2rec [uatm]", "fCO2rec_src",
    "fCO2rec_flag",
)

# ── Quality: dataset flag A-D and WOCE 2 are drawn; everything else is stored, never drawn ──────────────
GOOD_QC = frozenset("ABCD")
GOOD_WOCE = 2

# ── Segments: the tile unit of the point level. Every row is stored, rejected ones included ───────────────
SEG_MAX_OBS = 512
SEG_MAX_GAP_S = 6 * 3600         # a longer pause between two rows starts a new segment
# dt_s stays whole seconds: no fractional seconds in the file (Task 2 measured 0 rows; "60." is a whole second)
SEG_MAX_SPAN_DEG = 1.0           # lon or lat extent of one segment (keeps its bbox a usable index key)

# ── Level-of-detail pieces: a cruise reduced to the cells it passed through, level 0..3 ───────────────────
LOD_CELLS = (1.0, 0.25, 1 / 16, 1 / 64)
# L0 cap 64 (Task 2: at 8, 85 % of L0 pieces hit the cap and the z0 tile estimate was 20.3 MB); the 4 MB z0
# bound is re-measured on real MVT bytes after the first import (Task 7).
PIECE_MAX_VERTICES = (64, 8, 8, 8)
PIECE_MAX_GAP_S = 24 * 3600
PIECE_JUMP_CELLS = 3             # two consecutive cells further apart than this are not joined by a line

POINT_MIN_ZOOM = 9               # Task 2: smallest z with p99.9 distinct positions/tile <= 50,000 (z9 22.8k, z8 88k)
MERC_LAT = 85.0511               # Web-Mercator latitude limit: LOD vertices are clamped to it

_UTC = timezone.utc


def normalize_lon(lon: float) -> float:
    """The file's 0..360 east-positive longitude as -180..180. 360.0 -> 0.0; 180.014 -> -179.986."""
    if -180.0 <= lon < 180.0:
        return lon
    return ((lon + 180.0) % 360.0) - 180.0


def obs_time(yr, mon, day, hh, mm, ss: str) -> datetime:
    """UTC time of a row. `ss` is float text with a trailing dot and reaches "60." (18,098 rows), so the
    seconds are ADDED to the minute: 21:58:60 is 21:59:00, not an exception."""
    return datetime(int(yr), int(mon), int(day), int(hh), int(mm), tzinfo=_UTC) + timedelta(seconds=float(ss))


def num(token: str) -> float | None:
    """A numeric column: the literal `NaN` is a missing value. None, never 0 (SST 0.0 and sal -0.03 are real)."""
    f = float(token)
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def decade_index(year: int) -> int | None:
    """1970-2029 -> 0..5 (the decadal columns of the gridded product); anything else has no decade."""
    if 1970 <= year <= 2029:
        return (year - 1970) // 10
    return None


def lod_level(z: int) -> int:
    """Map zoom -> LOD level: z0-2 L0, z3-4 L1, z5-6 L2, z7 up to POINT_MIN_ZOOM - 1 L3 (z7-8 today).
    From POINT_MIN_ZOOM up the tile draws the observation cells, not LOD pieces: asking for a level there is a bug."""
    if z < 0 or z >= POINT_MIN_ZOOM:
        raise ValueError(f"zoom {z} has no LOD level (points from z{POINT_MIN_ZOOM})")
    if z <= 2:
        return 0
    if z <= 4:
        return 1
    if z <= 6:
        return 2
    return 3


def crosses_antimeridian(lon_a: float, lon_b: float) -> bool:
    """Two consecutive FOLDED longitudes (-180..180) further apart than half the globe: the track went
    over +-180, and a straight line between them would run the long way round."""
    return abs(lon_b - lon_a) > 180.0
