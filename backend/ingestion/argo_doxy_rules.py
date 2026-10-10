# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""BGC-Argo DOXY rules — pure, no I/O. Every number here was measured on the real Argo GDAC files on
2026-10-06 (plan Phase 0). The API reads its constants from HERE, never from the loader or the worker."""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

# ── run-state vocabulary shared by the loader, the worker and the API's health read ──────────────────
SOURCE = "argo-doxy"                       # sync_log.source, admin force-sync key
LAYER_ID = "argo-oxygen-points"
STARTED_PREFIX = "started"
STARTED_STALE = timedelta(hours=6, minutes=30)   # = deploy/argo-doxy.service TimeoutStartSec
LOW_MEMORY_PREFIX = "low memory"
DISK_PREFIX = "disk above"
INDEX_FAILED_PREFIX = "index failed"
UNREACHABLE_OUTCOME = "unreachable"
UNREACHABLE_PREFIX = "gdac unreachable"
TRANSIENT_PREFIXES = (LOW_MEMORY_PREFIX, DISK_PREFIX, INDEX_FAILED_PREFIX, UNREACHABLE_PREFIX)
# This many floats IN A ROW failing on the network (connection, timeout, 5xx, a download over its per-file deadline)
# means the GDAC is down, not that five files are bad: the run stops with the transient outcome UNREACHABLE_OUTCOME
# (not in FAILED_OUTCOMES, so no 7-day back-off), the remaining floats stay pending, and the next daily tick resumes.
# Failures that are NOT consecutive network ones (a corrupt file, an unexpected shape, a 404) keep the old rule:
# max(FLOAT_FAILURE_LIMIT_MIN, 2 %) of the planned floats -> outcome "error" and the back-off. 5 is small enough that
# an outage costs a handful of requests, and large enough that a few unlucky files in a row do not end a weekly run.
FLOAT_FAILURE_STREAK = 5
UPDATED_WITH_REJECTS_PREFIX = "updated with failed floats"
FAILED_OUTCOMES = ("blocked", "error", "schema")

GDAC = "https://data-argo.ifremer.fr"
INDEX_URL = f"{GDAC}/argo_synthetic-profile_index.txt.gz"
INDEX_COLUMNS = ("file", "date", "latitude", "longitude", "ocean", "profiler_type", "institution",
                 "parameters", "parameter_data_mode", "date_update")

PRODUCT = "BGC-Argo DOXY, Argo GDAC synthetic profiles (current)"
FIELD_PRODUCT = "ISAS20 BGC-Argo 2014–2018 mean (SEANOE doi:10.17882/52367), built from an older Argo snapshot"
ACKNOWLEDGEMENT = ("These data were collected and made freely available by the International Argo Program and the "
                   "national programs that contribute to it. (https://argo.ucsd.edu, https://www.ocean-ops.org). "
                   "The Argo Program is part of the Global Ocean Observing System.")
CITATIONS = (ACKNOWLEDGEMENT,
             "Argo (2000). Argo float data and metadata from Global Data Assembly Centre (Argo GDAC). SEANOE. "
             "https://doi.org/10.17882/42182")

FILL = 99999.0                              # DOXY, DOXY_ADJUSTED, PRES, PRES_ADJUSTED, LATITUDE, LONGITUDE
JULD_FILL = 999999.0
ARGO_EPOCH = datetime(1950, 1, 1, tzinfo=timezone.utc)
UNITS = "µmol/kg"                           # source "micromole/kg" == the ISAS20 field's unit
# == services.woa_climatology.DISPLAY_DEPTHS (oxygen-deox's depths); test_depth_windows_match_the_field_display_depths
DISPLAY_DEPTHS = (0, 50, 100, 200, 500, 1000, 1500, 2000)
# Depth in metres (the ISAS20 axis is `depth`, units m, positive down) — NEVER pressure. Surface 0-10 m: the
# shallowest good level is <= 9.7 m in 90 % of profiles. 2000 m: floats parking at 2000 dbar sit at ~1975 m.
DEPTH_WINDOWS: dict[int, tuple[float, float]] = {
    0: (0.0, 10.0), 50: (40.0, 60.0), 100: (90.0, 110.0), 200: (175.0, 225.0), 500: (450.0, 550.0),
    1000: (950.0, 1050.0), 1500: (1425.0, 1575.0), 2000: (1900.0, 2100.0)}
GOOD_ADJ_QC = frozenset({1, 2})             # Argo: 1 good, 2 probably good. 3/4/5/8 stored, never drawn.
ADJUSTED_MODES = frozenset({"A", "D"})      # PARAMETER_DATA_MODE of DOXY; R = raw only, never drawn
BAD_POSITION_QC = frozenset({3, 4, 9})      # same exclusion as domains/sensors._ARGO_USABLE_POSITION
BAD_TIME_QC = frozenset({3, 4, 9})
MIN_PRES_DBAR = -5.0                        # Argo global range test allows -5 .. 12000 dbar
# Floats profile to 2000 dbar, Deep Argo to 6000: a level beyond 7000 dbar is a corrupt pressure, not an ocean,
# and dropping it loses nothing a float measured. (The 150-level cap in thin_levels is the second line.)
MAX_PRES_DBAR = 7000.0
BAD_PRES_QC = frozenset({3, 4})             # pressure flagged "probably bad" / "bad": the level's depth is untrusted
MAX_STORED_LEVELS = 150
# Bump on ANY change to how a Sprof profile becomes a stored row (good/QC sets, pressure rules, depth windows,
# thinning, the drawable rule). The loader re-reads every float holding a row or an empty marker built under
# another version, spread over runs by the budget. A change that does not alter stored rows must NOT bump it:
# a bump re-downloads the whole archive (about 15 GB).
RULES_VERSION = 1
SHRINK_LIMIT = 0.9                          # an index listing < 90 % of the stored profiles blocks the run

_FILE_RE = re.compile(r"^([a-z]+)/(\d{4,8})/profiles/S([RD])(\d{4,8})_(\d{3,4})(D?)\.nc$")
KEY_RE = re.compile(r"^[a-z]+_\d{4,8}_\d{3,4}D?$")

PROFILE_COLUMNS = (
    "profile_key", "argo_profile_id", "dac", "platform_number", "cycle_number", "direction", "gdac_file",
    "gdac_date_update", "profile_time", "juld_qc", "year", "lat", "lon", "position_qc", "doxy_mode",
    "pres_source", "n_levels_source", "n_good", "n_levels", "pres_dbar", "depth_m", "doxy_adj", "doxy_adj_qc",
    "doxy_raw", "doxy_raw_qc", "at_depth", "at_depth_m", "drawable")


def profile_key(dac: str, wmo: str, cycle: int, descending: bool) -> str:
    """<dac>_<wmo>_<cycle:03d>[D]. The DAC is part of the key: WMO 1902751 exists at aoml AND coriolis (two floats).
    The R/D file prefix is not: SR1900722_001.nc and SD1900722_001.nc are one profile before and after DMQC."""
    return f"{dac}_{wmo}_{int(cycle):03d}{'D' if descending else ''}"


def argo_profile_id(wmo: str, cycle: int, descending: bool) -> str:
    """The id argo_profiles (ArgoVis) uses for the same profile. Not unique across DACs."""
    return f"{wmo}_{int(cycle):03d}{'D' if descending else ''}"


def sprof_url(dac: str, wmo: str) -> str:
    return f"{GDAC}/dac/{dac}/{wmo}/{wmo}_Sprof.nc"


def gdac_file_url(gdac_file: str) -> str:
    return f"{GDAC}/dac/{gdac_file}"


def float_page_url(wmo: str) -> str:
    return f"https://fleetmonitoring.euro-argo.eu/float/{wmo}"


class IndexRow(NamedTuple):
    key: str
    dac: str
    wmo: str
    cycle: int
    descending: bool
    gdac_file: str
    date_update: datetime
    doxy_mode: str


def parse_gdac_time(s: str) -> datetime | None:
    try:
        return datetime.strptime(s.strip(), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None


def check_index_header(column_line: str) -> None:
    got = tuple(column_line.strip().split(","))
    if got != INDEX_COLUMNS:
        raise ValueError(f"index columns changed: {got!r}")


def index_line_key(line: str) -> str | None:
    """The profile key of an index line from its file path alone (None if the path does not parse). Lets the loader
    tell 'this key is gone from the index' from 'this key is on a line we could not interpret'."""
    m = _FILE_RE.match(line.split(",", 1)[0])
    return profile_key(m.group(1), m.group(2), int(m.group(5)), m.group(6) == "D") if m else None


def parse_index_line(line: str) -> "IndexRow | str | None":
    """IndexRow for a profile listing DOXY; None when it lists no DOXY (out of scope, not a reject);
    the reject reason 'index_malformed' for a line we cannot trust."""
    parts = line.rstrip("\r\n").split(",")
    if len(parts) != len(INDEX_COLUMNS):
        return "index_malformed"
    params = parts[7].split()
    if "DOXY" not in params:
        return None
    m = _FILE_RE.match(parts[0])
    if not m or m.group(2) != m.group(4):
        return "index_malformed"
    k = params.index("DOXY")
    if len(parts[8]) <= k:
        return "index_malformed"
    upd = parse_gdac_time(parts[9])
    if upd is None:
        return "index_malformed"
    dac, wmo, cycle, desc = m.group(1), m.group(2), int(m.group(5)), m.group(6) == "D"
    return IndexRow(profile_key(dac, wmo, cycle, desc), dac, wmo, cycle, desc, parts[0], upd, parts[8][k])


def clean(v) -> float | None:
    if v is None:
        return None
    f = float(v)
    if not math.isfinite(f) or f >= FILL:
        return None
    return f


def qc_int(c) -> int | None:
    """Argo QC flag as int 0-9, compared numerically: a flag may be a char, bytes, an int or float text ("2.0").
    Blank, NUL, out-of-range and non-numeric flags are None (no flag), never a guess."""
    if c is None:
        return None
    if isinstance(c, (bytes, bytearray)):
        c = c.decode("ascii", "replace")
    try:
        f = float(str(c).strip("\x00 ") or "nan")
    except ValueError:
        return None
    return int(f) if math.isfinite(f) and f == int(f) and 0 <= f <= 9 else None


def _qc_at(flags, j: int) -> int | None:
    """Flag of level j; a flag string shorter than the level axis is 'no flag', not an IndexError."""
    return qc_int(flags[j]) if j < len(flags) else None


def lon180(lon) -> float | None:
    f = clean(lon)
    if f is None or not -360.0 <= f <= 360.0:
        return None
    if f > 180.0:
        f -= 360.0
    elif f < -180.0:
        f += 360.0
    return f


def juld_to_time(juld) -> datetime | None:
    if juld is None:
        return None
    f = float(juld)
    if not math.isfinite(f) or f >= JULD_FILL or f < 0:
        return None
    return ARGO_EPOCH + timedelta(days=f)


def depth_from_pressure(p_dbar: float, lat: float) -> float:
    """UNESCO 1983 (Fofonoff & Millard, UNESCO Tech. Pap. Mar. Sci. 44): depth in m from pressure in dbar.
    Check value 9712.653 m at 10000 dbar, 30 deg. Small negative surface pressures (>= -5 dbar) are depth 0."""
    if p_dbar <= 0.0:
        return 0.0
    x = math.sin(math.radians(lat)) ** 2
    g = 9.780318 * (1.0 + (5.2788e-3 + 2.36e-5 * x) * x) + 1.092e-6 * p_dbar
    return ((((-1.82e-15 * p_dbar + 2.279e-10) * p_dbar - 2.2512e-5) * p_dbar + 9.72659) * p_dbar) / g


def pick_index(depths, values, good, std: int) -> int | None:
    """Nearest GOOD level inside std's window; ties -> shallower, then lower value. Never interpolates."""
    lo, hi = DEPTH_WINDOWS[std]
    best = None
    for i, (d, v, g) in enumerate(zip(depths, values, good)):
        if not g or not lo <= d <= hi:
            continue
        k = (abs(d - std), d, v)
        if best is None or k < best[0]:
            best = (k, i)
    return None if best is None else best[1]


def _bin(d: float) -> tuple[int, int]:
    if d < 100:
        return 0, int(d // 5)
    if d < 500:
        return 1, int(d // 10)
    if d < 1000:
        return 2, int(d // 25)
    if d < 2000:
        return 3, int(d // 50)
    return 4, int(d // 100)


def thin_levels(depths, adj, good, raw, keep) -> list[int]:
    """Indices to store: one level per depth bin (good adjusted > any adjusted > raw only; then shallowest),
    plus every index in `keep` (the window picks, so the stored profile shows what the map coloured)."""
    best: dict[tuple[int, int], tuple[tuple[int, float], int]] = {}
    for i, d in enumerate(depths):
        if adj[i] is None and raw[i] is None:
            continue
        rank = 0 if good[i] else 1 if adj[i] is not None else 2
        b = _bin(d)
        cur = best.get(b)
        if cur is None or (rank, d) < cur[0]:
            best[b] = ((rank, d), i)
    mandatory = set(keep)
    reps = sorted((i for _, i in best.values() if i not in mandatory), key=lambda i: (depths[i], i))
    # Never raise on the size of a profile (a bad-pressure scatter can fill 190 bins): keep every window pick, then
    # the shallowest bin representatives, i.e. drop the DEEPEST bins first. Real Deep Argo (<= 6000 dbar) needs none.
    idx = mandatory | set(reps[:max(0, MAX_STORED_LEVELS - len(mandatory))])
    return sorted(idx, key=lambda i: (depths[i], i))


def profile_stamp(row: IndexRow, sprof_update: datetime | None) -> datetime:
    """The gdac_date_update to store with a profile (or an 'empty' marker). It is the INDEX's stamp only when the Sprof
    we read is at least that new; a Sprof that lags its index stores its own older stamp, so the planner finds the
    profile changed again on the next run and retries it."""
    if sprof_update is not None and sprof_update >= row.date_update:
        return row.date_update
    return sprof_update or ARGO_EPOCH


def build_profile(raw: dict, row: IndexRow, sprof_update: datetime | None) -> dict | None:
    """One stored row (keys = PROFILE_COLUMNS) from one Sprof profile, or None when it carries no DOXY value."""
    mode = raw["doxy_mode"]
    lat, lon = clean(raw["lat"]), lon180(raw["lon"])
    if lat is None or lon is None or not -90.0 <= lat <= 90.0:
        lat = lon = None
    t = juld_to_time(raw["juld"])
    jqc, pqc = qc_int(raw["juld_qc"]), qc_int(raw["position_qc"])
    lat_for_depth = lat if lat is not None else 0.0
    lv = []                     # (depth, pres, pres_is_adjusted, raw, raw_qc, adj, adj_qc)
    for j, (p_raw, p_adj, rv, av) in enumerate(zip(raw["pres"], raw["pres_adj"], raw["doxy"], raw["doxy_adj"])):
        pa, pr = clean(p_adj), clean(p_raw)
        p = pa if pa is not None else pr
        if p is None or not MIN_PRES_DBAR <= p <= MAX_PRES_DBAR:
            continue
        # The pressure that sets the depth is PRES_ADJUSTED where present, so its flag is PRES_ADJUSTED_QC;
        # otherwise PRES_QC. A missing/blank flag (or an absent variable) keeps the level: only 3/4 drop it.
        if _qc_at(raw.get("pres_adj_qc" if pa is not None else "pres_qc") or "", j) in BAD_PRES_QC:
            continue
        rv, av = clean(rv), clean(av)
        if rv is None and av is None:
            continue
        lv.append((depth_from_pressure(p, lat_for_depth), p, pa is not None,
                   rv, _qc_at(raw["doxy_qc"], j) if rv is not None else None,
                   av, _qc_at(raw["doxy_adj_qc"], j) if av is not None else None))
    if not lv:
        return None
    lv.sort(key=lambda x: (x[0], x[1]))
    depths = [x[0] for x in lv]
    adj = [x[5] for x in lv]
    rawv = [x[3] for x in lv]
    adjusted = mode in ADJUSTED_MODES
    good = [adjusted and a is not None and q in GOOD_ADJ_QC for a, q in zip(adj, (x[6] for x in lv))]
    picks = {std: pick_index(depths, adj, good, std) for std in DISPLAY_DEPTHS}
    keep = thin_levels(depths, adj, good, rawv, [i for i in picks.values() if i is not None])
    n_good = sum(good)
    flags = [x[2] for x in lv]
    stamp = profile_stamp(row, sprof_update)
    drawable = bool(adjusted and n_good > 0 and lat is not None and pqc not in BAD_POSITION_QC
                    and t is not None and jqc not in BAD_TIME_QC)
    return {
        "profile_key": row.key, "argo_profile_id": argo_profile_id(row.wmo, row.cycle, row.descending),
        "dac": row.dac, "platform_number": row.wmo, "cycle_number": row.cycle,
        "direction": "D" if row.descending else "A", "gdac_file": row.gdac_file, "gdac_date_update": stamp,
        "profile_time": t, "juld_qc": jqc, "year": t.year if t else None, "lat": lat, "lon": lon,
        "position_qc": pqc, "doxy_mode": mode,
        "pres_source": "adjusted" if all(flags) else "raw" if not any(flags) else "mixed",
        "n_levels_source": len(lv), "n_good": n_good, "n_levels": len(keep),
        "pres_dbar": [lv[i][1] for i in keep], "depth_m": [lv[i][0] for i in keep],
        "doxy_adj": [lv[i][5] for i in keep], "doxy_adj_qc": [lv[i][6] for i in keep],
        "doxy_raw": [lv[i][3] for i in keep], "doxy_raw_qc": [lv[i][4] for i in keep],
        "at_depth": [adj[picks[s]] if picks[s] is not None else None for s in DISPLAY_DEPTHS],
        "at_depth_m": [depths[picks[s]] if picks[s] is not None else None for s in DISPLAY_DEPTHS],
        "drawable": drawable,
    }
