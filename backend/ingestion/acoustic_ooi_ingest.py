# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""OOI (Ocean Observatories Initiative) hydrophone ingest.

Stations: fetched from public GitHub raw CSVs in oceanobservatories/asset-management.
⚠️ Scope is "every deployment file that carries a hydrophone" — measured, not
assumed: 9 of the 185 files do, and all 9 are listed in
`DEPLOYMENT_ARRAYS_WITH_HYDROPHONES` below. Four were listed before 2026-09-18.
Soundscape: not a first-party aggregated product; returns []. Phase 2 may add
on-the-fly SPL computation from raw M2M streams.

"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, date
from typing import Any

import httpx
from ingestion.http_retry import get_with_retry

log = logging.getLogger(__name__)

_DEPLOY_BASE = (
    "https://raw.githubusercontent.com/oceanobservatories/asset-management/"
    "master/deployment/"
)

# Arrays whose deployment CSV contains at least one HYDBBA / HYDLFA row.
#
# ⚠️ Measured 2026-09-18 by downloading the whole `deployment/` directory of
# oceanobservatories/asset-management@master and grepping every file:
# **185 CSVs, of which exactly 9 mention a hydrophone.** Until that date this
# list named only the four Regional Cabled Array sites (RS01SBPS, RS01SLBS,
# RS03AXPS, RS03AXBS); the other five were never fetched, so six instruments —
# half the layer — were missing with nothing logged. They are not obscure: two
# sit on the Coastal Endurance array (CE02SHBP, CE04OSBP) and three are
# low-frequency seismic-site hydrophones (RS01SUM1, RS03CCAL, RS03ECAL).
#
# ⛔ "Regional Cabled Array" was the old comment's own justification and it was
# wrong twice over: CE* arrays are not RCA, and RS01SUM1/RS03CCAL/RS03ECAL are.
# The scope is "every deployment file that carries a hydrophone", nothing else.
DEPLOYMENT_ARRAYS_WITH_HYDROPHONES: list[str] = [
    "CE02SHBP",   # measured 2026-09-18: 13 rows -> 1 instrument (HYDBBA106, 77-81 m)
    "CE04OSBP",   # 14 rows -> 2 instruments (HYDBBA105, HYDBBA110, ~580 m)
    "RS01SBPS",   # 12 rows -> 1 (HYDBBA103, ~191 m)
    "RS01SLBS",   #  8 rows -> 2 (HYDBBA102, HYDLFA101, ~2 900 m)
    "RS01SUM1",   #  1 row  -> 1 (HYDLFA104, 774 m)
    "RS03AXBS",   #  6 rows -> 2 (HYDBBA302, HYDLFA301, ~2 600 m)
    "RS03AXPS",   # 11 rows -> 1 (HYDBBA303, ~187 m)
    "RS03CCAL",   #  1 row  -> 1 (HYDLFA305, 1 527 m)
    "RS03ECAL",   #  1 row  -> 1 (HYDLFA304, 1 518 m)
]

# ⭐ The registry IS the wiring: the URLs are derived, never hand-written, so a
# name added above cannot be left unfetched.
_ARRAY_CSV_URLS = [f"{_DEPLOY_BASE}{a}_Deploy.csv" for a in DEPLOYMENT_ARRAYS_WITH_HYDROPHONES]

# Every hydrophone the 2026-09-18 sweep found, per array. Snapshot, not a
# filter: the parser still reads whatever the CSV holds. It exists so a test
# can state what "complete" meant on that date — an upstream addition changes
# the live count, and the comparison against this list is what makes the
# difference visible instead of invisible.
HYDROPHONES_SEEN: dict[str, tuple[str, ...]] = {
    "CE02SHBP": ("CE02SHBP-LJ01D-11-HYDBBA106",),
    "CE04OSBP": ("CE04OSBP-LJ01C-11-HYDBBA105", "CE04OSBP-LJ01C-11-HYDBBA110"),
    "RS01SBPS": ("RS01SBPS-PC01A-08-HYDBBA103",),
    "RS01SLBS": ("RS01SLBS-LJ01A-09-HYDBBA102", "RS01SLBS-MJ01A-05-HYDLFA101"),
    "RS01SUM1": ("RS01SUM1-LJ01B-05-HYDLFA104",),
    "RS03AXBS": ("RS03AXBS-LJ03A-09-HYDBBA302", "RS03AXBS-MJ03A-05-HYDLFA301"),
    "RS03AXPS": ("RS03AXPS-PC03A-08-HYDBBA303",),
    "RS03CCAL": ("RS03CCAL-MJ03F-06-HYDLFA305",),
    "RS03ECAL": ("RS03ECAL-MJ03E-09-HYDLFA304",),
}
_TIMEOUT = httpx.Timeout(60.0, connect=20.0)


def _is_hydrophone(designator: str) -> bool:
    return "HYDBBA" in designator or "HYDLFA" in designator


def _parse_iso(value: str | None) -> date | None:
    if not value:
        return None
    try:
        # OOI uses ISO 8601 with optional trailing "Z" or space-separated formats
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return None


def _hz_range_for(designator: str) -> tuple[float, float]:
    if "HYDBBA" in designator:
        return (10.0, 80_000.0)
    # HYDLFA
    return (0.008, 100.0)


def _model_for(designator: str) -> str:
    if "HYDBBA" in designator:
        return "HYDBBA (broadband, 10 Hz-80 kHz)"
    return "HYDLFA (low-frequency, 8 mHz-100 Hz)"


def _safe_float(v: Any) -> float | None:
    if v is None or str(v).strip() == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


async def fetch_ooi_stations() -> list[dict[str, Any]]:
    """Fetch hydrophone stations from OOI deployment CSVs, deduped by Reference Designator.

    Returns a list of acoustic_stations row dicts. Each unique designator yields one row
    with deploy_start = MIN(startDateTime) and deploy_end = MAX(stopDateTime) across all
    deployment cycles for that designator. A cycle with empty stopDateTime marks the
    designator as currently active (deploy_end = None).
    """
    rows_by_designator: dict[str, dict[str, Any]] = {}

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for array, url in zip(DEPLOYMENT_ARRAYS_WITH_HYDROPHONES, _ARRAY_CSV_URLS):
            try:
                resp = await get_with_retry(client, url, label="ooi asset")
                resp.raise_for_status()
            except Exception as exc:
                log.warning("fetch_ooi_stations: %s failed: %s", url, exc)
                continue
            found_here: set[str] = set()
            reader = csv.DictReader(io.StringIO(resp.text))
            for row in reader:
                designator = (row.get("Reference Designator") or "").strip()
                if not designator or not _is_hydrophone(designator):
                    continue
                found_here.add(designator)
                lat = _safe_float(row.get("lat"))
                lon = _safe_float(row.get("lon"))
                if lat is None or lon is None:
                    log.warning(
                        "fetch_ooi_stations: %s in %s has no position (lat=%r lon=%r) "
                        "— dropped. The source published a deployment cycle without "
                        "coordinates; every row of this file carried them on 2026-09-18.",
                        designator, array, row.get("lat"), row.get("lon"))
                    continue
                start = _parse_iso(row.get("startDateTime"))
                stop = _parse_iso(row.get("stopDateTime"))
                # is this cycle still active? (empty stopDateTime in the source)
                stop_is_open = (row.get("stopDateTime") or "").strip() == ""

                existing = rows_by_designator.get(designator)
                if existing is None:
                    hz_lo, hz_hi = _hz_range_for(designator)
                    existing = {
                        "station_id":   f"ooi:{designator}",
                        "source":       "ooi",
                        "name":         designator,
                        "operator":     "Ocean Observatories Initiative",
                        "lat":          lat,
                        "lon":          lon,
                        "depth_m":      _safe_float(row.get("deployment_depth")),
                        "deploy_start": start,
                        "deploy_end":   None if stop_is_open else stop,
                        "_has_open_cycle": stop_is_open,
                        "model":        _model_for(designator),
                        "hz_range_lo":  hz_lo,
                        "hz_range_hi":  hz_hi,
                        "portal_url":   f"https://ooinet.oceanobservatories.org/data_access/?search={designator}",
                    }
                    rows_by_designator[designator] = existing
                else:
                    # MIN(deploy_start)
                    if start is not None and (existing["deploy_start"] is None or start < existing["deploy_start"]):
                        existing["deploy_start"] = start
                    # deploy_end logic: if any cycle is open, the designator is active
                    if stop_is_open:
                        existing["_has_open_cycle"] = True
                        existing["deploy_end"] = None
                    elif not existing["_has_open_cycle"] and stop is not None:
                        if existing["deploy_end"] is None or stop > existing["deploy_end"]:
                            existing["deploy_end"] = stop
                    # take the most recent lat/lon/depth (last cycle wins) — these rarely move but
                    # if they do, the latest deployment metadata is canonical
                    existing["lat"] = lat
                    existing["lon"] = lon
                    existing["depth_m"] = _safe_float(row.get("deployment_depth"))

            # ⛔ An array in the registry that yields nothing is a CHANGE at the
            # source, not a quiet zero. Without this, a renamed designator
            # family (HYDBBA -> something else) would shrink the layer and the
            # only visible sign would be a smaller number nobody was watching.
            expected = set(HYDROPHONES_SEEN.get(array, ()))
            if not found_here:
                log.warning(
                    "fetch_ooi_stations: %s yielded NO hydrophone rows; %d were "
                    "measured there on 2026-09-18 (%s). The file parsed, so this "
                    "is the source changing, not a fetch failure.",
                    array, len(expected), ", ".join(sorted(expected)) or "?")
            elif expected - found_here:
                log.warning("fetch_ooi_stations: %s no longer lists %s",
                            array, ", ".join(sorted(expected - found_here)))
            elif found_here - expected:
                log.info("fetch_ooi_stations: %s gained %s since the 2026-09-18 sweep",
                         array, ", ".join(sorted(found_here - expected)))

    rows = []
    for r in rows_by_designator.values():
        r.pop("_has_open_cycle", None)
        rows.append(r)
    log.info("fetch_ooi_stations: %d unique hydrophone stations across %d arrays",
             len(rows), len(_ARRAY_CSV_URLS))
    return rows


async def fetch_ooi_soundscape(station_id: str, days: int = 90) -> list[dict[str, Any]]:
    """Return [] — OOI doesn't publish a first-party pre-aggregated SPL/decade-band product.

    Even with an M2M API token, OOI only exposes raw audio waveforms. Computing daily SPL
    would require downloading NetCDF audio chunks and running FFT/decade-band binning
    ourselves — out of scope for Phase 1.

    The acoustic_soundscape table + sync orchestrator + endpoint stay in place so the API
    contract is stable; Phase 2 will populate this function when we tackle SPL computation.
    """
    return []
