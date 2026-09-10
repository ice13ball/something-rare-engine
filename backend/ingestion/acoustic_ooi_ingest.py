# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""OOI (Ocean Observatories Initiative) hydrophone ingest.

Stations: fetched from public GitHub raw CSVs in oceanobservatories/asset-management.
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

# Regional Cabled Array sites that host HYDBBA / HYDLFA instruments.
_ARRAY_CSV_URLS = [
    "https://raw.githubusercontent.com/oceanobservatories/asset-management/master/deployment/RS01SBPS_Deploy.csv",
    "https://raw.githubusercontent.com/oceanobservatories/asset-management/master/deployment/RS01SLBS_Deploy.csv",
    "https://raw.githubusercontent.com/oceanobservatories/asset-management/master/deployment/RS03AXPS_Deploy.csv",
    "https://raw.githubusercontent.com/oceanobservatories/asset-management/master/deployment/RS03AXBS_Deploy.csv",
]
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
        for url in _ARRAY_CSV_URLS:
            try:
                resp = await get_with_retry(client, url, label="ooi asset")
                resp.raise_for_status()
            except Exception as exc:
                log.warning("fetch_ooi_stations: %s failed: %s", url, exc)
                continue
            reader = csv.DictReader(io.StringIO(resp.text))
            for row in reader:
                designator = (row.get("Reference Designator") or "").strip()
                if not designator or not _is_hydrophone(designator):
                    continue
                lat = _safe_float(row.get("lat"))
                lon = _safe_float(row.get("lon"))
                if lat is None or lon is None:
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
