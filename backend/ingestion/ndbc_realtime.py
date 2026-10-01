# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Latest reading for an OceanSITES mooring from NOAA NDBC.

⛔ NDBC knows a buoy by its 5-digit WMO number; ``oceansites_stations.ref`` is
the OceanOPS reference. Until 2026-10-01 the sync asked NDBC for the OceanOPS
reference (``…/latest_obs/1500009.txt``), which NDBC has never heard of — every
request was a 404 and NDBC fed 0 of ~67 operational moorings. OceanOPS does not
hand out the WMO number (``fields=wmo`` comes back empty, see
``oceansites_ingest``), but for the 7-digit references it is written inside the
reference itself: drop the two zeros in the middle. ``1500009`` → ``15009``.

Measured 2026-10-01 on the live feeds: the derived number found a station on
NDBC for 9 operational moorings, and for all 9 the position NDBC prints next to
the station matched the OceanOPS position to within 0.06°. Because the rule is
inferred, not published, every reading is still accepted only when NDBC's own
position for the station agrees with ours (``position_matches``) — a wrong
number must not hand one mooring another buoy's weather.

Two files per station:
  latest_obs/<wmo>.txt  — human-readable; read ONLY for the position line
  realtime2/<wmo>.txt   — the last 45 days, newest row first; the values
"""
from __future__ import annotations

import logging
import math
import re
from typing import Any

import httpx

log = logging.getLogger(__name__)

_BASE = "https://www.ndbc.noaa.gov/data"

_WMO_IN_REF = re.compile(r"^(\d{2})00(\d{3})$")

#: How far NDBC's position for a station may sit from ours and still be the
#: same mooring. The 9 matches measured on 2026-10-01 were all within 0.06°.
MAX_POSITION_DEG = 0.5

# "12° 0.0' S  65° 0.0' E". The degree sign arrives as Latin-1 0xB0, so the
# pattern does not depend on it.
_POSITION = re.compile(
    r"(\d+)\D{1,3}?(\d+(?:\.\d+)?)'\s*([NS])\s+(\d+)\D{1,3}?(\d+(?:\.\d+)?)'\s*([EW])"
)

#: realtime2 column → our obs key. Read by HEADER NAME, not position, so a
#: column NDBC adds or reorders cannot shift a pressure into a temperature.
_COLUMNS = {
    "WDIR": "wdir",
    "WSPD": "wspd",
    "WVHT": "wvht",
    "PRES": "pres",
    "ATMP": "atmp",
    "WTMP": "wtmp",
}


def wmo_id_from_ref(ref: str) -> str | None:
    """``1500009`` → ``15009``; None for references that do not carry one."""
    m = _WMO_IN_REF.match(ref.strip())
    return m[1] + m[2] if m else None


def parse_position(latest_obs_text: str) -> tuple[float, float] | None:
    """The station position NDBC prints in latest_obs, as (lat, lon)."""
    m = _POSITION.search(latest_obs_text)
    if not m:
        return None
    lat = (int(m[1]) + float(m[2]) / 60.0) * (1 if m[3] == "N" else -1)
    lon = (int(m[4]) + float(m[5]) / 60.0) * (1 if m[6] == "E" else -1)
    return lat, lon


def position_matches(ndbc: tuple[float, float], ours: tuple[float, float],
                     max_deg: float = MAX_POSITION_DEG) -> bool:
    dlon = (ndbc[1] - ours[1] + 180.0) % 360.0 - 180.0
    return math.hypot(ndbc[0] - ours[0], dlon) <= max_deg


def _value(token: str) -> float | None:
    # realtime2 writes "MM" for a missing value. ⛔ No numeric sentinels here:
    # 999.0 hPa is a real storm pressure, not "missing".
    if token == "MM":
        return None
    try:
        v = float(token)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def parse_realtime2(text: str) -> dict[str, Any] | None:
    """The newest row of a realtime2 file that carries at least one value."""
    header: list[str] | None = None
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith("#"):
            if header is None:
                header = line.lstrip("#").split()
            continue
        if header is None:
            return None
        parts = line.split()
        if len(parts) != len(header):
            continue
        row = dict(zip(header, parts))
        obs: dict[str, Any] = {
            "obs_time": f"{row['YY']}-{row['MM']}-{row['DD']} {row['hh']}:{row['mm']}Z",
        }
        for col, key in _COLUMNS.items():
            if col in row:
                obs[key] = _value(row[col])
        if any(v is not None for k, v in obs.items() if k != "obs_time"):
            return obs
    return None


async def fetch_ndbc_observation(
    client: httpx.AsyncClient, ref: str, lat: float | None, lon: float | None
) -> dict[str, Any] | None:
    """Latest NDBC reading for one mooring, or None.

    None when the reference carries no WMO number, NDBC has no such station,
    NDBC's position for it disagrees with ours, or no row has a value.
    """
    wmo = wmo_id_from_ref(ref)
    if wmo is None or lat is None or lon is None:
        return None
    try:
        r = await client.get(f"{_BASE}/latest_obs/{wmo}.txt", timeout=12)
        if r.status_code != 200:
            return None
        pos = parse_position(r.content.decode("latin-1"))
        if pos is None or not position_matches(pos, (lat, lon)):
            if pos is not None:
                log.warning(
                    "NDBC %s (from OceanOPS %s) sits at %.2f,%.2f, ours is %.2f,%.2f — not used",
                    wmo, ref, pos[0], pos[1], lat, lon,
                )
            return None
        r = await client.get(f"{_BASE}/realtime2/{wmo}.txt", timeout=12)
        if r.status_code != 200:
            return None
        obs = parse_realtime2(r.content.decode("latin-1"))
        if obs is not None:
            # The number a reader types into NDBC to check the reading — the
            # OceanOPS reference shown elsewhere in the panel is not it.
            obs["ndbc_station"] = wmo
        return obs
    except Exception as exc:
        log.debug("NDBC fetch %s (%s): %s", wmo, ref, exc)
        return None
