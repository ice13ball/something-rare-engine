# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The OceanSITES GDAC file catalogue, and the link from a mooring to its files.

``oceansites_stations`` is the OceanOPS register: 1,038 moorings, of which only
~50 transmit now. What the other ~970 measured, where it was published at all,
sits in the OceanSITES GDAC. The GDAC publishes ONE index file listing every
NetCDF it holds (~21 MB, ~60,000 lines, refreshed daily):

    ftp://ftp.ifremer.fr/ifremer/oceansites/oceansites_index.txt

This module is pure parsing and pure matching — no database, no clock. The only
I/O is :func:`fetch_index`. ``domains/oceansites_history.py`` owns the tables.

⛔ Every parser rule below answers a row that exists in the real index
(checked 2026-10-01, fixtures in ``tests/fixtures/oceansites_gdac/``):

* ``DATE_UPDATE`` is ``unknown`` on 40,068 of 60,130 rows; ``GDAC_UPDATE_DATE``
  is ``50``, ``void`` or ``unknown`` on the ALOHA chunks (the columns are
  shifted there — ``GDAC_CREATION_DATE`` carries ``4726``, a depth).
* Timestamps arrive as ``T24:00:00Z``, ``18:29:60Z`` and ``03:42:0000Z``.
* WHOTS/NTAS/Stratus rows repeat the latitude in the longitude columns (22.70
  four times; WHOTS sits at -158). E1M3A rows carry ``0`` for the south/west
  corner and ``-99.999`` as a fill. SATS carries ``10000.00`` as a latitude.
* Five lines are continuation fragments of a ``PARAMETERS`` cell that contained
  a newline; they have one column.
* ``DATA_GRIDDED/`` (366 files) are derived products, not mooring records.

Matching is by position AND by name. Position alone put CTD and ship stations
(CALCOFI beside CCE2, OFP beside BATS) and ADCP files on moorings that did not
make them. Precision over recall: an unlinked mooring is correct, a mooring
shown with its neighbour's record is not.
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
import statistics
import urllib.request
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

# FTP, not HTTPS: no HTTPS mirror of the index could be verified to return the
# same file (tds0 has no fileServer entry for it, data-gdac does not resolve,
# the NDBC mirror timed out). The FTP file is anonymous — nothing to protect.
INDEX_URL = "ftp://ftp.ifremer.fr/ifremer/oceansites/oceansites_index.txt"
OPENDAP_BASE = "https://tds0.ifremer.fr/thredds/dodsC/CORIOLIS-OCEANSITES-GDAC-OBS"

MAX_LINK_KM = 25.0

# A mooring record spans metres; a file whose extent exceeds this is a track,
# a ship section or a corrupt corner pair, not a position. PAP legitimately
# reports 48-50N, -17..-16 (2 degrees) for a mooring at 48.9N 16.5W.
_MAX_EXTENT_DEG = 2.0

# Literal fills seen in the position columns of the real index.
_POSITION_FILLS = {-99.999, -999.0, -9999.0, -99999.0, 99999.0, 9999.0, 99.999}

_DATA_MODES = {"D", "P", "R", "M"}
# PARAMETERS is meant to be CF standard names (lower-case, underscore-joined) but
# some files put free text there ("Standard deviation of", "chlorophyll-a",
# "BactTaxaAbundWater"). Keep CF-shaped tokens and the bare coordinate names.
_PARAM_TOKEN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")
_COORD_NAMES = {"time", "latitude", "longitude", "depth", "height"}
_TS = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?\d*Z?)?$"
)


# ─────────────────────────────────────────────────────────────────────────────
# Fetch
# ─────────────────────────────────────────────────────────────────────────────

def _download_index(url: str, timeout: float) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (fixed ftp URL)
        chunks = []
        while True:
            block = resp.read(1 << 20)
            if not block:
                break
            chunks.append(block)
    return b"".join(chunks)


async def fetch_index(url: str = INDEX_URL, timeout: float = 90.0) -> str | None:
    """The index text, or ``None`` when the GDAC could not be reached.

    ⛔ ``None`` means "could not look", never "empty": an unreachable server is
    not a catalogue with no files. On 2026-10-01 the GDAC answered 503 to
    everything for about an hour. The caller must leave stored rows alone.
    A body that is not the index (no ``DATA/`` line) is treated the same way.
    """
    try:
        raw = await asyncio.to_thread(_download_index, url, timeout)
    except Exception as exc:  # urllib raises OSError/URLError/ftplib errors
        log.warning("OceanSITES index fetch failed: %s", type(exc).__name__)
        return None
    text = raw.decode("utf-8", errors="replace")
    if "\nDATA/" not in text:
        log.warning("OceanSITES index fetch returned a body with no DATA/ lines")
        return None
    return text


# ─────────────────────────────────────────────────────────────────────────────
# Parsing
# ─────────────────────────────────────────────────────────────────────────────

def _parse_ts(value: str) -> datetime | None:
    """ISO-ish timestamp → aware UTC datetime; None for ``unknown``/blank/garbage.

    ``T24:00:00Z`` is midnight of the next day, ``:60`` seconds roll the minute
    (timedelta does both), and ``03:42:0000Z`` is 03:42:00 with junk appended.
    """
    m = _TS.match(value.strip())
    if not m:
        return None
    y, mo, d, hh, mi, ss = m.groups()
    try:
        base = datetime(int(y), int(mo), int(d), tzinfo=timezone.utc)
    except ValueError:
        return None
    return base + timedelta(hours=int(hh or 0), minutes=int(mi or 0), seconds=int(ss or 0))


def _num(value: str) -> float | None:
    try:
        v = float(value.strip())
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def _depth(value: str) -> float | None:
    v = _num(value)
    if v is None or abs(v) >= 99999.0:  # 99999 closes D-mode CIS rows
        return None
    return v


def _size(value: str) -> int | None:
    v = _num(value)
    return int(v) if v is not None and v >= 0 else None


def _lon180(lon: float) -> float:
    return ((lon + 180.0) % 360.0) - 180.0


def _lon_gap(w: float, e: float) -> float:
    d = abs(w - e) % 360.0
    return min(d, 360.0 - d)


def _position(s: float | None, n: float | None, w: float | None, e: float | None):
    """Midpoint of the file's bounding box plus the box itself
    ``(lat, lon, south, north, west, east)``, or None when it is not a position.

    The four ways the real index lies about it: a column is ``unknown``; a
    column holds a fill (``-99.999``, ``10000.00``); the longitudes repeat the
    latitudes (WHOTS 22.70 x4); the box spans more than ``_MAX_EXTENT_DEG``
    (E1M3A's ``0`` corner reads as a 35-degree box). Dateline-safe.
    """
    if None in (s, n, w, e):
        return None
    if s in _POSITION_FILLS or n in _POSITION_FILLS or w in _POSITION_FILLS or e in _POSITION_FILLS:
        return None
    if abs(s) > 90 or abs(n) > 90 or abs(w) > 360 or abs(e) > 360:
        return None
    if w == s and e == n:  # longitudes are the latitudes
        return None
    if abs(n - s) > _MAX_EXTENT_DEG or _lon_gap(w, e) > _MAX_EXTENT_DEG:
        return None
    lat = (s + n) / 2.0
    gap = (_lon180(e) - _lon180(w) + 180.0) % 360.0 - 180.0  # signed, shortest way
    west = _lon180(w) if gap >= 0 else _lon180(e)            # the box runs west -> east
    width = abs(gap)
    lon = _lon180(west + width / 2.0)
    return (round(lat, 5), round(lon, 5), min(s, n), max(s, n),
            round(west, 5), round(_lon180(west + width), 5))


def platform_from_filename(path: str) -> str | None:
    """``DATA/CCE1/OS_CCE1_200511_D_CTD.nc`` → ``CCE1``.

    Layout is ``OS_<PLATFORM>_<DEPLOYMENT>_<MODE>_<SUFFIX>.nc`` but the token
    count varies 4-9 (R-only names have five parts, e.g. ``OS_MBARI-M1_20260619_R_TS``,
    some have none of the suffix: ``OS_E1M3A_2007_R``). The platform is always
    the second token.
    """
    base = path.rsplit("/", 1)[-1]
    if base.lower().endswith(".nc"):
        base = base[:-3]
    toks = base.split("_")
    if len(toks) < 2 or toks[0] != "OS" or not toks[1]:
        return None
    return toks[1]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(a)))


def _parse_line(line: str) -> dict | None:
    cols = line.split(",")
    if len(cols) != 16:  # continuation fragments and any torn line
        return None
    path = cols[0].strip()
    if not path.startswith("DATA/"):  # DATA_GRIDDED/ are derived products
        return None
    parts = path.split("/")
    if len(parts) < 3 or not path.endswith(".nc"):
        return None
    pos = _position(*(_num(c) for c in cols[4:8]))
    mode = cols[14].strip().upper()
    return {
        "file": path,
        "site_dir": parts[1],
        "platform_code": platform_from_filename(path),
        "data_mode": mode if mode in _DATA_MODES else None,
        "start_time": _parse_ts(cols[2]),
        "end_time": _parse_ts(cols[3]),
        "lat": pos[0] if pos else None,
        "lon": pos[1] if pos else None,
        # The box the matcher measures to. A mooring file's box is a few metres
        # to 2 degrees wide (PAP): its midpoint can sit ~55 km from a mooring
        # that is inside it, so distance is taken to the box, not the midpoint.
        "bbox_south": pos[2] if pos else None,
        "bbox_north": pos[3] if pos else None,
        "bbox_west": pos[4] if pos else None,
        "bbox_east": pos[5] if pos else None,
        "position_source": "index" if pos else None,
        "min_depth": _depth(cols[8]),
        "max_depth": _depth(cols[9]),
        "parameters": [t for t in cols[15].split() if t in _COORD_NAMES or _PARAM_TOKEN.match(t)],
        "size_bytes": _size(cols[11]),
        # Two honest change markers. GDAC_UPDATE_DATE is garbage on the ALOHA
        # chunks (50, void); DATE_UPDATE is unknown on two thirds of all rows.
        "gdac_update_date": _parse_ts(cols[13]),
        "date_update": _parse_ts(cols[1]),
    }


def _median_position(rows: list[dict]) -> tuple[float, float] | None:
    """Median of the valid positions, only when they agree with each other.

    The median is not allowed to be a place nobody ever was: at least 90% of
    the valid rows must lie within 50 km of it. LINE-W holds W1..W5 in one
    directory, and a median across them would sit between moorings.
    """
    pts = [(r["lat"], r["lon"]) for r in rows if r["lat"] is not None]
    if not pts:
        return None
    lat = statistics.median(p[0] for p in pts)
    # Longitudes are unwrapped around the first one so a mooring on the
    # dateline does not get a median of 0.
    ref = pts[0][1]
    lon = _lon180(ref + statistics.median(((p[1] - ref + 180.0) % 360.0) - 180.0 for p in pts))
    close = sum(1 for p in pts if haversine_km(lat, lon, p[0], p[1]) <= 50.0)
    if close < 0.9 * len(pts):
        return None
    return round(lat, 5), round(lon, 5)


def _apply_site_median(rows: list[dict]) -> None:
    """Give a row with no valid position its mooring's median position.

    Same ``(site_dir, platform)`` first — a directory can hold several
    moorings — then the whole ``site_dir``. Recorded as
    ``position_source = 'site_median'`` so it is never read as a measurement.
    """
    by_platform: dict[tuple, list[dict]] = {}
    by_site: dict[str, list[dict]] = {}
    for r in rows:
        by_platform.setdefault((r["site_dir"], r["platform_code"]), []).append(r)
        by_site.setdefault(r["site_dir"], []).append(r)
    pmed = {k: _median_position(v) for k, v in by_platform.items()}
    smed = {k: _median_position(v) for k, v in by_site.items()}
    for r in rows:
        if r["lat"] is not None:
            continue
        med = pmed[(r["site_dir"], r["platform_code"])] or smed[r["site_dir"]]
        if med:
            r["lat"], r["lon"] = med
            # a borrowed position is a point, never a box
            r["bbox_south"] = r["bbox_north"] = med[0]
            r["bbox_west"] = r["bbox_east"] = med[1]
            r["position_source"] = "site_median"


def parse_index(text: str) -> list[dict]:
    """The GDAC index → one dict per ``DATA/`` file. Comments, fragments and
    ``DATA_GRIDDED/`` are skipped; positions the index got wrong are repaired
    or left ``None`` (see the module docstring)."""
    rows: dict[str, dict] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        row = _parse_line(line)
        if row is not None:
            rows[row["file"]] = row  # the file is the key: a repeat keeps the last
    out = list(rows.values())
    _apply_site_median(out)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Names
# ─────────────────────────────────────────────────────────────────────────────

_TOKEN_SPLIT = re.compile(r"[-_ ./\s]+")
_PREFIXES = ("T", "P", "R")  # TAO/TRITON, PIRATA, RAMA directories: T0N140W, P12N23W


def _norm(x: str | None) -> str:
    """Upper-case alphanumerics only — also drops the trailing \\xa0 some
    OceanOPS names carry."""
    return re.sub(r"[^A-Z0-9]", "", (x or "").upper())


def _tokens(x: str) -> list[str]:
    return [t for t in _TOKEN_SPLIT.split(x.strip().upper()) if t]


# ── Explicit alias table ─────────────────────────────────────────────────────
# OceanOPS names some moorings by a deployment code that shares no characters
# with the GDAC platform, so no general rule can link them without also linking
# neighbours. These three families were found by hand in the 2026-10-01 audit
# (each cost 6-170 files of recall) and are closed one by one, not by loosening
# the rules above:
#
#   (station-name regex, GDAC site_dir, allowed platforms, file-id regex,
#    file must name the deployment)
#
#   SOFS-11, SOFS-12 ...  Southern Ocean Flux Station -> directory SOTS, platform
#                         SOTS, files ...SOFS09_D_ASIMET / ...SOFS11_D_ASIMET.
#                         The directory also holds SAZ47 sediment traps and
#                         PULSE moorings 20-40 km away that are NOT this station,
#                         so here the file has to name the SOFS deployment.
#   KE003, KE019, KE015a  KEO (Kuroshio Extension Observatory) -> directory KEO,
#                         platforms KEO and KEOK7 (not KEOSED).
#   PA011, PA018 ...      Station Papa deployments PA001..PA018 -> directory PAPA,
#                         platform PAPA (files ...2007PA001_D_MET).
#
# Position still has to agree (<= 25 km, enforced by match_files). And a deployment
# code is not a family: when a file names a deployment (SOFS11, PA001, KE016) the
# number must equal the station's, so SOFS-12 does not take SOFS11's data 24 km away.
_ALIASES = (
    (re.compile(r"^SOFS[-_ ]?0*(\d+)"), "SOTS", {"SOTS"}, re.compile(r"SOFS0*(\d+)"), True),
    (re.compile(r"^KE0*(\d+)[A-Z]?$"), "KEO", {"KEO", "KEOK7"}, re.compile(r"(?<![A-Z])KE0*(\d+)"), False),
    (re.compile(r"^PA0*(\d+)$"), "PAPA", {"PAPA"}, re.compile(r"(?<![A-Z])PA0*(\d+)"), False),
)


def _alias_rule(
    station_name: str, platform: str | None, site_dir: str | None, file_path: str | None,
) -> str | None:
    clean = re.sub(r"\s+", "", station_name.upper())
    for name_re, alias_dir, platforms, file_re, must_name in _ALIASES:
        m = name_re.match(clean)
        if not m or site_dir != alias_dir or platform not in platforms:
            continue
        rest = ""
        if file_path:
            base = file_path.rsplit("/", 1)[-1]
            parts = (base[:-3] if base.lower().endswith(".nc") else base).split("_", 2)
            rest = parts[2] if len(parts) > 2 else ""  # after OS_<PLATFORM>_
        f = file_re.search(rest.upper())
        if f is None:
            if must_name:
                return None
        elif int(f.group(1)) != int(m.group(1)):
            return None
        return "alias"
    return None


_ID_TOKEN = re.compile(r"^([A-Z]+)(\d+)$")


def _ids(tokens: list[str], skip: set[str]) -> set[tuple[str, int]]:
    """Mooring ids such as F3, EAC4700, NTAS20 → ``{("F", 3), ...}``."""
    out = set()
    for t in tokens:
        m = _ID_TOKEN.match(t)
        if m and t not in skip:
            out.add((m[1], int(m[2])))
    return out


def _id_conflict(station_name: str, platform: str | None, file_path: str | None) -> bool:
    """True when the file names a DIFFERENT mooring of the same array than the
    station does — ``FRAM_F3-18`` vs ``OS_FRAM_F4-1_D.nc`` or ``..._FEVI15_D.nc``
    (platform FRAM, ~20 km apart), ``IMOS-EAC4700`` vs a file named ``EAC4800``.

    Only fires when the station carries an id (letters + number) that is not
    the platform itself, the file carries ids too, and none of them is the
    station's. A file with no comparable id says nothing, and a station with
    no id (``CCE1-17``: the 17 is a bare number) is never vetoed.
    """
    if not file_path:
        return False
    base = file_path.rsplit("/", 1)[-1]
    if base.lower().endswith(".nc"):
        base = base[:-3]
    skip = set(_tokens(platform or ""))
    f_ids = _ids(_tokens(base)[1:], skip)  # [0] is "OS"
    if not f_ids:
        return False
    return any(i not in f_ids for i in _ids(_tokens(station_name), skip))


def name_rule(
    station_name: str, platform: str | None, site_dir: str | None, file_path: str | None = None,
) -> str | None:
    """Which naming rule says this station and this file are the same mooring,
    or None. Rules, strictest first: ``exact`` · ``tao-prefix`` ·
    ``token-prefix`` · ``prefix`` · ``alias`` · ``site-token``.

    ⛔ A sibling is not the same mooring. ``PAP-1`` must not take ``PAP-2``
    files, ``MBARI-M1`` must not take ``MBARI-M0``, ``ESTOC-1`` is not
    ``ESTOC-C`` — they share a directory and sit within 25 km. That is why
    ``site-token`` only fires when the directory name sits INSIDE the station
    name (``60N_40W_CIS_14`` in directory CIS), never at its start, where the
    station name is already a platform identifier and must match as one.

    With ``file_path`` the looser rules (everything but ``exact`` and
    ``tao-prefix``) also veto a file that names another mooring of the same
    array (:func:`_id_conflict`).
    """
    name = _norm(station_name)
    plat = _norm(platform)
    n_tok = _tokens(station_name)
    p_tok = _tokens(platform or "")
    if name and plat:
        if name == plat:
            return "exact"
        if any(plat == p + name for p in _PREFIXES):
            return "tao-prefix"
        # CCE1-17 / EC1_23 / SATS_2023_001: platform + deployment number.
        short, long_ = sorted((n_tok, p_tok), key=len)
        if short and len(_norm("".join(short))) >= 3 and long_[:len(short)] == short:
            return None if _id_conflict(station_name, platform, file_path) else "token-prefix"
        short_s, long_s = sorted((name, plat), key=len)
        if len(short_s) >= 3 and long_s.startswith(short_s):
            # CCE1 is not CCE17: when the shorter side ends in a digit the
            # remainder must not carry on the number.
            if not (short_s[-1].isdigit() and long_s[len(short_s)].isdigit()):
                return None if _id_conflict(station_name, platform, file_path) else "prefix"
    alias = _alias_rule(station_name, platform, site_dir, file_path)
    if alias:
        return alias
    if site_dir:
        d = _tokens(site_dir)
        if d and len(_norm(site_dir)) >= 3:
            for i in range(1, len(n_tok) - len(d) + 1):
                if n_tok[i:i + len(d)] == d:
                    return None if _id_conflict(station_name, platform, file_path) else "site-token"
    return None


def names_compatible(
    station_name: str, platform: str | None, site_dir: str | None, file_path: str | None = None,
) -> bool:
    return name_rule(station_name, platform, site_dir, file_path) is not None


# ─────────────────────────────────────────────────────────────────────────────
# Matching
# ─────────────────────────────────────────────────────────────────────────────

_CELL_DEG = 0.5
_CELL_LO = int(math.floor(-180 / _CELL_DEG))
_CELL_WRAP = int(360 / _CELL_DEG)


def _file_box(f: dict) -> tuple[float, float, float, float] | None:
    """(south, north, west, width) of a file; a point when it carries no box."""
    if f.get("lat") is None or f.get("lon") is None:
        return None
    if f.get("bbox_south") is None:
        return f["lat"], f["lat"], _lon180(f["lon"]), 0.0
    west = f["bbox_west"]
    return f["bbox_south"], f["bbox_north"], west, (f["bbox_east"] - west) % 360.0


def distance_to_box_km(lat: float, lon: float, box: tuple[float, float, float, float]) -> float:
    """Station position to the nearest point of the file's bbox: 0 inside, else
    the distance to the nearest edge point. Dateline-safe."""
    south, north, west, width = box
    plat = min(max(lat, south), north)
    rel = (lon - west) % 360.0
    if rel <= width:
        plon = lon
    elif rel - width <= 360.0 - rel:      # nearer the east edge
        plon = west + width
    else:
        plon = west
    return haversine_km(lat, lon, plat, plon)


def _box_cells(box: tuple[float, float, float, float]):
    """Every grid cell a file box touches (a point -> one cell)."""
    south, north, west, width = box
    w180 = _lon180(west)
    c0, c1 = int(math.floor(w180 / _CELL_DEG)), int(math.floor((w180 + width) / _CELL_DEG))
    for r in range(int(math.floor(south / _CELL_DEG)), int(math.floor(north / _CELL_DEG)) + 1):
        for c in range(c0, c1 + 1):
            yield r, ((c - _CELL_LO) % _CELL_WRAP) + _CELL_LO


def _neighbour_cells(lat: float, lon: float, km: float):
    """Every grid cell that can hold a point within ``km`` of (lat, lon)."""
    dlat = km / 111.0
    dlon = 180.0 if abs(lat) + dlat >= 89.0 else dlat / max(math.cos(math.radians(lat)), 0.01)
    r0, r1 = int(math.floor((lat - dlat) / _CELL_DEG)), int(math.floor((lat + dlat) / _CELL_DEG))
    if dlon >= 180.0:
        c_all = range(int(math.floor(-180 / _CELL_DEG)), int(math.floor(180 / _CELL_DEG)))
        for r in range(r0, r1 + 1):
            for c in c_all:
                yield r, c
        return
    c0, c1 = int(math.floor((lon - dlon) / _CELL_DEG)), int(math.floor((lon + dlon) / _CELL_DEG))
    wrap = int(360 / _CELL_DEG)
    lo = int(math.floor(-180 / _CELL_DEG))
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            yield r, ((c - lo) % wrap) + lo


def match_files(
    stations: list[dict],
    deployments: list[dict],
    files: list[dict],
    max_km: float = MAX_LINK_KM,
) -> tuple[list[dict], list[dict]]:
    """Link catalogue files to stations.

    ``stations``: ``{ref, name, lat, lon}``. ``deployments``: ``{base_ref, name,
    lat, lon}`` — every deployment position of a base ref counts, because 31
    base refs hold deployments more than a degree apart.

    A file links to a station iff some (position, name) pair of that station —
    the station row or one of its deployments — lies within ``max_km`` of the
    file's bounding box (0 km when inside it; a file without a box is a point)
    AND its name is compatible with the file's platform / directory
    (:func:`name_rule`). A pair carries its own name: deployments of one CVOO
    mooring are called ``18N_24W_CVOO_03`` while the station row says ``_12``.

    Returns ``(links, rejected_nearby)``. ``links`` are ``{station_ref, file,
    rule, distance_km}``, one per (station, file). ``rejected_nearby`` are
    ``{station_ref, file, station_name, platform, site_dir, distance_km}`` for
    station/file pairs within ``max_km`` whose names disagree and that no other
    pair linked — the CTD cast beside a mooring, the ADCP on someone else's
    buoy. It exists so precision can be reviewed, not to be acted on.
    """
    by_base: dict[str, list[dict]] = {}
    for d in deployments:
        if d.get("lat") is not None and d.get("lon") is not None:
            by_base.setdefault(d["base_ref"], []).append(d)

    grid: dict[tuple[int, int], list[tuple[dict, tuple]]] = {}
    for f in files:
        box = _file_box(f)
        if box is not None:
            for cell in _box_cells(box):
                grid.setdefault(cell, []).append((f, box))

    links: dict[tuple[str, str], dict] = {}
    near: dict[tuple[str, str], dict] = {}
    for st in stations:
        pairs = []
        if st.get("lat") is not None and st.get("lon") is not None:
            pairs.append((st["lat"], st["lon"], st.get("name") or ""))
        for d in by_base.get(st["ref"], []):
            pairs.append((d["lat"], d["lon"], d.get("name") or st.get("name") or ""))
        seen_pos: set[tuple] = set()
        for lat, lon, name in pairs:
            if (round(lat, 4), round(lon, 4), name) in seen_pos:
                continue
            seen_pos.add((round(lat, 4), round(lon, 4), name))
            for cell in _neighbour_cells(lat, lon, max_km):
                for f, box in grid.get(cell, ()):
                    dist = distance_to_box_km(lat, lon, box)
                    if dist > max_km:
                        continue
                    key = (st["ref"], f["file"])
                    rule = name_rule(name, f.get("platform_code"), f.get("site_dir"), f["file"])
                    if rule is None:
                        if key not in near or dist < near[key]["distance_km"]:
                            near[key] = {
                                "station_ref": st["ref"], "file": f["file"],
                                "station_name": name, "platform": f.get("platform_code"),
                                "site_dir": f.get("site_dir"), "distance_km": round(dist, 2),
                            }
                        continue
                    cur = links.get(key)
                    if cur is None or dist < cur["distance_km"]:
                        links[key] = {
                            "station_ref": st["ref"], "file": f["file"],
                            "rule": rule, "distance_km": round(dist, 2),
                        }
    rejected = [v for k, v in near.items() if k not in links]
    return list(links.values()), rejected
