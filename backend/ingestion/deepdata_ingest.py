# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Fetch ISA DeepData occurrences via the OBIS REST API.

Source: ISA's environmental contractor reports, mirrored into OBIS as
Darwin Core archives (per `iobis/notebook-deepdata`). The OBIS node id
"OBIS ISA" is `9d2d95be-32eb-4d81-8911-32cb8bc641c8`.

Why via OBIS, not directly from data.isa.org.jm:
- OBIS has already done the LTC-template → DwC parsing.
- A stable REST API with `nodeid` filter exists (`/v3/occurrence`).
- Records get UUID `id` fields (raw `occurrenceID` is NOT unique within
  the node, see IOBIS notebook).

Pagination: OBIS limits offset-based paging to ~10k results. For a 200k
node we use the documented `after` cursor — the response includes the
last `_id`, which we pass as `after` in the next call.

Volume snapshot (2026-05-05): ~201,323 occurrences, 153 datasets,
~10 distinct contractor codes parseable from dataset titles.
"""
import logging
import re
from datetime import datetime
from typing import Any, AsyncIterator

import httpx

log = logging.getLogger(__name__)

ISA_NODE_ID = "9d2d95be-32eb-4d81-8911-32cb8bc641c8"
OBIS_OCCURRENCE_URL = "https://api.obis.org/v3/occurrence"
OBIS_DATASET_URL = "https://api.obis.org/v3/dataset"
PAGE_SIZE = 10000

# Contract-code prefix (verified via live API): NORI, TOML, BGR, UKSRL,
# IFREMER, OMS, COMRA, GSR, YUZ, KOREA, IOM, DORD, CMM, YUZH, JOGMEC.
# Dataset titles encode the prefix as <CONTRACTOR>[<digit>](PMN|PMS|CFC|CRFC)<digit>…
# e.g. "NORIPMN12022 Env Template BIO", "UKSRL1PMN Env Template 2022",
#      "JOGMECCRFC12024 Env Template 2024".
# Non-greedy prefix + optional iteration digit + required contract marker.
_CONTRACTOR_RE = re.compile(r"^([A-Z]+?)\d?(?:PMN|PMS|CRFC|CFC)", re.IGNORECASE)


def parse_contractor_code(dataset_title: str | None) -> str | None:
    """Extract contractor code (NORI, BGR, …) from an ISA dataset title."""
    if not dataset_title:
        return None
    m = _CONTRACTOR_RE.match(dataset_title)
    return m.group(1).upper() if m else None


async def _fetch_dataset_map(client: httpx.AsyncClient) -> dict[str, str]:
    """Build {dataset_id: title} for all ISA-node datasets.

    Occurrence records carry `dataset_id` but not the title — we need
    the title to parse the contractor code (NORI, BGR, …).
    """
    dataset_map: dict[str, str] = {}
    offset = 0
    while True:
        r = await client.get(OBIS_DATASET_URL, params={
            "nodeid": ISA_NODE_ID, "size": 200, "offset": offset,
        })
        r.raise_for_status()
        data = r.json()
        results = data.get("results", [])
        if not results:
            break
        for ds in results:
            ds_id = ds.get("id")
            title = ds.get("title") or ""
            if ds_id:
                dataset_map[ds_id] = title
        offset += len(results)
        if offset >= data.get("total", 0):
            break
    log.info("deepdata: %d datasets in ISA node", len(dataset_map))
    return dataset_map


async def fetch_deepdata_records() -> AsyncIterator[list[dict[str, Any]]]:
    """Async iterator yielding page-sized lists of canonical-shape dicts,
    ready for upsert into `deepdata_occurrences`. Skips rows with missing
    coordinates or a missing `id`.

    Same shape as `noaa_corals_ingest.fetch_noaa_corals_records` — at
    ~201,323 rows the old `list[dict]` return held ~250-350MB in memory for
    the whole run, on a process that also runs every other sync (measured
    peaking at 6GB cgroup / 3.3GB swap on a 15GB box, 2026-09-18). Streaming
    lets the caller upsert each page as it arrives instead of buffering the
    full result set first.
    """
    after: str | None = None
    page_num = 0
    total_yielded = 0

    async with httpx.AsyncClient(timeout=120) as client:
        dataset_map = await _fetch_dataset_map(client)

        while True:
            params: dict[str, Any] = {
                "nodeid": ISA_NODE_ID,
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
            cleaned: list[dict[str, Any]] = []
            for occ in results:
                lat = occ.get("decimalLatitude")
                lon = occ.get("decimalLongitude")
                if lat is None or lon is None:
                    continue
                obis_id = occ.get("id")
                if not obis_id:
                    continue
                ds_id = occ.get("dataset_id")
                dataset_title = dataset_map.get(ds_id, "") if ds_id else ""
                contractor = parse_contractor_code(dataset_title)

                cleaned.append({
                    "obis_id":         obis_id,
                    "occurrence_id":   occ.get("occurrenceID") or None,
                    "dataset_id":      ds_id,
                    "dataset_title":   dataset_title or None,
                    "contractor_code": contractor,
                    "rights_holder":   occ.get("rightsHolder") or None,
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

            total_yielded += len(cleaned)
            log.info("deepdata: page %d — %d records (cumulative %d)",
                     page_num, len(cleaned), total_yielded)
            if cleaned:
                yield cleaned

            # OBIS paginates by `after`, which expects the last record's `id`
            # from the previous response.
            if len(results) < PAGE_SIZE:
                break
            after = results[-1].get("id")
            if not after:
                break

    log.info("deepdata: fetch complete — %d records across %d pages",
              total_yielded, page_num)


def _safe_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_event_date(v: Any) -> datetime | None:
    """OBIS returns eventDate as an ISO string ('2013-04-21T11:57:00') or
    sometimes a date-only ('2013-04-21'). asyncpg's TIMESTAMPTZ codec needs
    a datetime instance, not a string."""
    if not v or not isinstance(v, str):
        return None
    s = v.strip()
    # Some records use "/" separators or include a Z suffix.
    s = s.replace("Z", "+00:00")
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    # Last resort — fromisoformat handles most reasonable variants in Py3.11+.
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None
