# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Fetch MBARI VARS deep-sea ROV observations via the OBIS REST API.

Source: Monterey Bay Aquarium Research Institute's Video Annotation and
Reference System (VARS) — ~30 years of deep-sea ROV dives, mostly NE
Pacific. MBARI publishes a curated subset to OBIS as a single DwC dataset.

Why via OBIS:
- MBARI's internal M3/annosaurus stack is not publicly exposed.
- The OBIS subset (dataset_id `a419c8da-…`) is already DwC-compliant and
  pinned with stable UUID `id`s.
- Same REST shape as our DeepData ingest — just a different filter.

Volume snapshot (2026-05-05): ~175,476 occurrence records.

Pagination: same `after` cursor strategy as deepdata_ingest.py — OBIS's
offset-based paging is capped at ~10k.

Coverage caveat: these records ARE already in our `biodiversity_hotspots`
table via the OBIS parquet sync. Surfacing MBARI as its own density
source is a credit/transparency benefit, not new coverage. Documented
in the legend's `limitations` block.
"""
import logging
from datetime import datetime
from typing import Any

import httpx

log = logging.getLogger(__name__)

VARS_DATASET_ID = "a419c8da-35ed-4b62-9709-39b56369c44e"
OBIS_OCCURRENCE_URL = "https://api.obis.org/v3/occurrence"
PAGE_SIZE = 10000


async def fetch_mbari_records() -> list[dict[str, Any]]:
    """Fetch all OBIS occurrences in MBARI's VARS dataset.

    Returns canonical-shape dicts ready for upsert into `mbari_vars_records`.
    Skips rows with missing coordinates.
    """
    out: list[dict[str, Any]] = []
    after: str | None = None
    page_num = 0

    async with httpx.AsyncClient(timeout=120) as client:
        while True:
            params: dict[str, Any] = {
                "datasetid": VARS_DATASET_ID,
                "size": PAGE_SIZE,
            }
            if after:
                params["after"] = after

            r = await client.get(OBIS_OCCURRENCE_URL, params=params)
            r.raise_for_status()
            data = r.json()
            results = data.get("results", [])
            if not results:
                break

            page_num += 1
            for occ in results:
                lat = occ.get("decimalLatitude")
                lon = occ.get("decimalLongitude")
                if lat is None or lon is None:
                    continue
                obis_id = occ.get("id")
                if not obis_id:
                    continue

                out.append({
                    "obis_id":         obis_id,
                    "occurrence_id":   occ.get("occurrenceID") or None,
                    "dataset_id":      occ.get("dataset_id") or None,
                    "scientific_name": occ.get("scientificName") or None,
                    "phylum":          occ.get("phylum") or None,
                    "class_":          occ.get("class") or None,
                    "order_":          occ.get("order") or None,
                    "family":          occ.get("family") or None,
                    "genus":           occ.get("genus") or None,
                    "species":         occ.get("species") or None,
                    "basis_of_record": occ.get("basisOfRecord") or None,
                    "depth_m":         _safe_float(occ.get("minimumDepthInMeters")),
                    "lat":             float(lat),
                    "lon":             float(lon),
                    "event_date":      _parse_event_date(occ.get("eventDate")),
                    "locality":        occ.get("locality") or None,
                })

            log.info("mbari_vars: page %d — %d records (cumulative %d)",
                     page_num, len(results), len(out))

            if len(results) < PAGE_SIZE:
                break
            after = results[-1].get("id")
            if not after:
                break

    log.info("mbari_vars: fetched %d total records across %d pages", len(out), page_num)
    return out


def _safe_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_event_date(v: Any) -> datetime | None:
    """OBIS returns eventDate as an ISO string or None. asyncpg's TIMESTAMPTZ
    codec needs a datetime instance, not a string. Same logic as
    deepdata_ingest._parse_event_date."""
    if not v or not isinstance(v, str):
        return None
    s = v.strip().replace("Z", "+00:00")
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None
