# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""GLODAPv3 bottle rules — pure, no I/O. Every number here was measured on the real
GLODAPv3_Merged_Master_File.csv on 2026-10-06 (see the plan's Phase 0 table)."""
from __future__ import annotations
import math, re
from datetime import date, datetime, timedelta, timezone

# ── Run-state vocabulary shared by the loader, the worker and the API's health read ───────────────────
# Lives HERE (pure, no I/O) so the API can read it without importing the loader (duckdb) or the worker.
SOURCE = "glodap-bottles"                # sync_log.source
# sync_log.skipped_reason on a SUCCESS row (last_synced_at stays the success): rows/casts the loader
# had to leave out. Same device as plankton's "swapped with failed datasets".
SWAPPED_WITH_REJECTS_PREFIX = "swapped with rejected rows"
STARTED_PREFIX = "started"               # marker an import writes when it begins
STARTED_STALE = timedelta(hours=6)       # = the unit's TimeoutStartSec: an older marker means the process was killed
# Skip markers that mean "a due import did not happen", NOT "the last import failed" (cf. plankton's
# LOW_MEMORY_PREFIX). The health read must not classify these as errors.
LOW_MEMORY_PREFIX = "low memory"
DISK_PREFIX = "disk above"
HEAD_FAILED_PREFIX = "head failed"
TRANSIENT_PREFIXES = (LOW_MEMORY_PREFIX, DISK_PREFIX, HEAD_FAILED_PREFIX)
FAILED_OUTCOMES = ("blocked", "error", "schema")   # what the loader returns for a persistent failure

FILL = -9999.0
GOOD_FLAG = 2           # GLODAP simplified WOCE scheme: 2 acceptable, 0 approximated, 9 no data
VARIABLES = ("temperature", "salinity", "oxygen", "nitrate", "silicate", "phosphate",
             "tco2", "talk", "phts25p0", "phtsinsitutp", "fco2")
QC_VARIABLES = ("temperature", "salinity", "oxygen", "nitrate", "silicate", "phosphate", "tco2", "talk")
BOTTLE_UNITS = {"temperature": "°C", "salinity": "PSU", "oxygen": "µmol/kg", "nitrate": "µmol/kg",
                "silicate": "µmol/kg", "phosphate": "µmol/kg", "tco2": "µmol/kg", "talk": "µmol/kg",
                "phts25p0": "", "phtsinsitutp": "", "fco2": "µatm"}
# field key (services/glodap_carbon.CARBON_VARS) -> bottle column. pH: in-situ total scale, as the field.
FIELD_TO_BOTTLE: dict[str, str | None] = {"dic": "tco2", "talk": "talk", "ph": "phtsinsitutp", "cant": None}
LEVEL_DECIMALS = {"tco2": 1, "talk": 1, "phtsinsitutp": 4}
# half-way to the field's neighbouring standard levels; surface widened to 10 m (median shallowest bottle = 5 m)
DEPTH_WINDOWS: dict[int, tuple[float, float]] = {
    0: (0.0, 10.0), 200: (175.0, 225.0), 500: (450.0, 550.0), 1000: (950.0, 1050.0),
    2000: (1875.0, 2250.0), 3000: (2750.0, 3250.0), 4000: (3750.0, 4250.0)}
REQUIRED_COLUMNS = ("expocode", "station", "cast", "year", "month", "day", "hour", "minute",
                    "latitude", "longitude", "bottomdepth", "maxsampdepth", "bottle", "pressure",
                    "depth", "region", "doi",
                    *VARIABLES, *(f"{v}f" for v in VARIABLES), *(f"{v}qc" for v in QC_VARIABLES))
_EXPO_RE = re.compile(r"^[0-9A-Z]{4}\d{8}$")


def clean(v) -> float | None:
    if v is None or v == "":
        return None
    f = float(v)
    if math.isnan(f) or f == FILL:
        return None
    return f


def clean_or_none(v) -> float | None:
    """clean() that maps unparseable text to None instead of raising (classification only)."""
    try:
        return clean(v)
    except (ValueError, TypeError, OverflowError):
        return None


def row_problem(row: dict) -> str | None:
    """Why a depth-bearing row cannot become part of a cast, or None if it can: "key" (no
    expocode or station; a missing CAST number is not a reason: see cast_key), "position" (lat/lon fill, NaN, junk or out of range), "date"
    (year/month/day fill, NaN, junk or not a calendar day). The loader rejects and COUNTS such a
    row; it never crashes on it and never stores fill as data (decision 2026-10-06)."""
    if not row.get("expocode") or not row.get("station"):
        return "key"
    lat, lon = clean_or_none(row.get("latitude")), clean_or_none(row.get("longitude"))
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return "position"
    y, m, d = (clean_or_none(row.get(k)) for k in ("year", "month", "day"))
    if y is None or m is None or d is None:
        return "date"
    try:
        date(int(y), int(m), int(d))
    except ValueError:
        return "date"
    return None


def _flag(v) -> int:
    # Flags are float text in the source ("2.0", "9.0"): compare numerically, never as strings.
    f = clean(v)
    return 9 if f is None else int(f)


NO_CAST = "nc"     # key component of a cast the source gives no number for (cast = -9999 / NaN / empty)


def cast_number(cast) -> int | None:
    """The cast number, or None when the source gives none (fill, NaN, empty, junk, infinite)."""
    f = clean_or_none(cast)
    if f is None or math.isinf(f):
        return None
    return int(f)


def cast_key(expocode: str, station: str, cast) -> str:
    """EXPOCODE_station_N. A missing cast number becomes the component `nc` ("no cast"): stable across
    reloads, URL-safe, and it cannot collide with a real number (those are digits). Rows of one station
    that all lack a number therefore form ONE cast (decision 2026-10-06: 178 measured rows had been dropped)."""
    n = cast_number(cast)
    return f"{expocode}_{station}_{NO_CAST if n is None else n}"


def platform_code(expocode: str) -> str | None:
    return expocode[:4] if _EXPO_RE.match(expocode) else None


def pick_level(depths, values, flags, bottles, std_depth: int):
    lo, hi = DEPTH_WINDOWS[std_depth]
    best = None
    for d, v, f, b in zip(depths, values, flags, bottles):
        if v is None or f != GOOD_FLAG or d is None or not (lo <= d <= hi):
            continue
        k = (abs(d - std_depth), d, b if b is not None else math.inf, v)
        if best is None or k < best[0]:
            best = (k, v, d)
    return None if best is None else (best[1], best[2])


def _km(lat1, lon1, lat2, lon2) -> float:
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 12742.0 * math.asin(math.sqrt(min(1.0, a)))


def build_cast(rows: list[dict]) -> dict | None:
    rows = [r for r in rows if clean(r["depth"]) is not None]
    if not rows:
        return None
    rows.sort(key=lambda r: (clean(r["depth"]), clean(r["bottle"]) if clean(r["bottle"]) is not None else math.inf))
    top = rows[0]
    lat, lon = float(top["latitude"]), float(top["longitude"])
    y, m, d = int(float(top["year"])), int(float(top["month"])), int(float(top["day"]))
    hh, mm = clean(top["hour"]), clean(top["minute"])
    if hh is None or mm is None or not (0 <= hh < 24 and 0 <= mm < 60):
        hh = mm = None                                  # fill/NaN/impossible clock = date-only precision
    out: dict = {
        "cast_key": cast_key(top["expocode"], top["station"], top["cast"]),
        "expocode": top["expocode"], "station": top["station"], "cast_no": cast_number(top["cast"]),
        "platform_code": platform_code(top["expocode"]),
        "lat": lat, "lon": lon, "year": y, "obs_date": date(y, m, d),
        "obs_time": datetime(y, m, d, int(hh), int(mm), tzinfo=timezone.utc) if hh is not None and mm is not None else None,
        "time_precision": "minute" if hh is not None and mm is not None else "day",
        "region": int(float(top["region"])), "doi": top["doi"] or None,
        "bottom_depth_m": clean(top["bottomdepth"]), "max_samp_depth_m": clean(top["maxsampdepth"]),
        "pos_spread_km": round(max(_km(lat, lon, float(r["latitude"]), float(r["longitude"])) for r in rows), 3),
        "depth_m": [clean(r["depth"]) for r in rows],
        "pressure_dbar": [clean(r["pressure"]) for r in rows],
        "bottle": [clean(r["bottle"]) for r in rows],
    }
    for v in VARIABLES:
        out[v] = [clean(r[v]) for r in rows]
        out[f"{v}_f"] = [_flag(r[f"{v}f"]) for r in rows]
    for v in QC_VARIABLES:
        # A fill/NaN qc is NULL, never data. Measured: constant within every cast; if rows disagree -> NULL.
        qcs = {int(q) for r in rows if clean(r[v]) is not None and (q := clean(r[f"{v}qc"])) is not None}
        out[f"{v}_qc"] = qcs.pop() if len(qcs) == 1 else None
    out["n_samples"] = len(rows)
    out["n_good"] = sum(1 for v in VARIABLES for f in out[f"{v}_f"] if f == GOOD_FLAG)
    levels: dict = {}
    for field_key, col in FIELD_TO_BOTTLE.items():
        if col is None:
            continue
        per = {}
        for std in DEPTH_WINDOWS:
            hit = pick_level(out["depth_m"], out[col], out[f"{col}_f"], out["bottle"], std)
            if hit is not None:
                per[str(std)] = [round(hit[0], LEVEL_DECIMALS[col]), hit[1]]
        if per:
            levels[field_key] = per
    out["levels"] = levels
    return out
