# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Fetch NOAA Deep-Sea Coral & Sponge (DSCRTP) observations.

Source: NOAA Deep Sea Coral Research & Technology Program's National
Database, hosted as a public ArcGIS FeatureServer:

    https://services2.arcgis.com/C8EMgrsFcRFL6LrL/arcgis/rest/services/DSCRTP_NatDB/FeatureServer/0

Volume snapshot (2026-05-06): 1,508,706 records, growing slowly.
CatalogNumber is unique across the full dataset (verified via groupBy
distinct count).

Why an async iterator (not a list):
    1.5 M records × ~30 fields can't sit in memory at once during the
    sync. Yielding page-sized chunks lets the orchestrator stream-insert
    page-by-page.

Pagination: ArcGIS offset/limit (`resultOffset` + `resultRecordCount`).
Server caps each request at 1000 rows. Pagination support is advertised
in the FeatureServer's `advancedQueryCapabilities`.

Coverage caveat: some DSCRTP records are also mirrored into OBIS and
will eventually be folded into our broader `obis` density source. We
surface NOAA separately for credit/transparency, not unique coverage.
Documented in the legend's `limitations` block (same pattern as MBARI).
"""
import logging
from datetime import datetime
from typing import Any, AsyncIterator

import httpx

log = logging.getLogger(__name__)

DSCRTP_QUERY_URL = (
    "https://services2.arcgis.com/C8EMgrsFcRFL6LrL/arcgis/rest/services/"
    "DSCRTP_NatDB/FeatureServer/0/query"
)
PAGE_SIZE = 1000  # ArcGIS server cap; verified during 2026-05-06 bench
PAGE_TIMEOUT_S = 180.0  # deep offsets observed at 5s, headroom for slow days

# All real field names verified via outFields=* probe (2026-05-06).
# `Species` does NOT exist on this layer (use ScientificName/Genus).
# `FishCouncilRegionCode` is the actual name (NOT FishCouncilRegion).
_OUT_FIELDS = ",".join([
    "CatalogNumber", "ObjectId", "SampleID", "EventID", "DatasetID",
    "DataProvider", "ScientificName", "VerbatimScientificName", "Synonyms",
    "VernacularNameCategory", "IdentificationQualifier",
    "Phylum", "Class", "Order_", "Family", "Genus", "AphiaID", "TaxonRank",
    "DepthInMeters", "Latitude", "Longitude", "Locality", "OceanCode",
    "FishCouncilRegionCode", "Vessel", "SamplingEquipment", "PI", "SurveyID",
    "ImageURL", "HighlightImageURL",
    "Temperature", "Salinity", "Oxygen",
    "ObservationYear", "ObservationDate",
])


async def fetch_noaa_corals_records() -> AsyncIterator[list[dict[str, Any]]]:
    """Async iterator yielding page-sized lists of canonical-shape dicts.

    Each yielded list contains up to PAGE_SIZE records ready for upsert
    into `noaa_corals_records`. Rows with missing CatalogNumber or
    missing coordinates are skipped silently.
    """
    offset = 0
    page_num = 0
    total_yielded = 0

    async with httpx.AsyncClient(timeout=PAGE_TIMEOUT_S) as client:
        while True:
            params = {
                "where": "1=1",
                "outFields": _OUT_FIELDS,
                "resultOffset": str(offset),
                "resultRecordCount": str(PAGE_SIZE),
                "f": "json",
                "returnGeometry": "false",
            }
            r = await client.get(DSCRTP_QUERY_URL, params=params)
            r.raise_for_status()
            data = r.json()
            features = data.get("features", [])
            if not features:
                break

            page_num += 1
            cleaned: list[dict[str, Any]] = []
            for feat in features:
                a = feat.get("attributes") or {}
                cn = a.get("CatalogNumber")
                lat = a.get("Latitude")
                lon = a.get("Longitude")
                if cn is None or lat is None or lon is None:
                    continue
                cleaned.append({
                    "catalog_number":           str(cn),
                    "object_id":                _safe_int(a.get("ObjectId")),
                    "sample_id":                _str_or_none(a.get("SampleID")),
                    "event_id":                 _str_or_none(a.get("EventID")),
                    "dataset_id":               _str_or_none(a.get("DatasetID")),
                    "data_provider":            _str_or_none(a.get("DataProvider")),
                    "scientific_name":          _str_or_none(a.get("ScientificName")),
                    "verbatim_scientific_name": _str_or_none(a.get("VerbatimScientificName")),
                    "synonyms":                 _str_or_none(a.get("Synonyms")),
                    "vernacular_name_category": _str_or_none(a.get("VernacularNameCategory")),
                    "identification_qualifier": _str_or_none(a.get("IdentificationQualifier")),
                    "phylum":                   _str_or_none(a.get("Phylum")),
                    "class_":                   _str_or_none(a.get("Class")),
                    "order_":                   _str_or_none(a.get("Order_")),
                    "family":                   _str_or_none(a.get("Family")),
                    "genus":                    _str_or_none(a.get("Genus")),
                    "aphia_id":                 _safe_int(a.get("AphiaID")),
                    "taxon_rank":               _str_or_none(a.get("TaxonRank")),
                    "depth_m":                  _safe_float(a.get("DepthInMeters")),
                    "lat":                      float(lat),
                    "lon":                      float(lon),
                    "locality":                 _str_or_none(a.get("Locality")),
                    "ocean_code":               _str_or_none(a.get("OceanCode")),
                    "fish_council_region":      _str_or_none(a.get("FishCouncilRegionCode")),
                    "vessel":                   _str_or_none(a.get("Vessel")),
                    "sampling_equipment":       _str_or_none(a.get("SamplingEquipment")),
                    "pi":                       _str_or_none(a.get("PI")),
                    "survey_id":                _str_or_none(a.get("SurveyID")),
                    "image_url":                _str_or_none(a.get("ImageURL")),
                    "highlight_image_url":      _str_or_none(a.get("HighlightImageURL")),
                    "temperature":              _safe_float(a.get("Temperature")),
                    "salinity":                 _safe_float(a.get("Salinity")),
                    "oxygen":                   _safe_float(a.get("Oxygen")),
                    "observation_year":         _safe_int(a.get("ObservationYear")),
                    "event_date":               _parse_obs_date(a.get("ObservationDate")),
                })

            total_yielded += len(cleaned)
            log.info(
                "noaa_corals: page %d (offset %d) — %d raw, %d kept (cumulative %d)",
                page_num, offset, len(features), len(cleaned), total_yielded,
            )
            if cleaned:
                yield cleaned

            # ArcGIS doesn't always set exceededTransferLimit; rely on the
            # full-page heuristic (same as how the KBA sync terminates).
            if len(features) < PAGE_SIZE:
                break
            offset += PAGE_SIZE

    log.info(
        "noaa_corals: fetch complete — %d records across %d pages",
        total_yielded, page_num,
    )


def _str_or_none(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _safe_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _safe_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_obs_date(v: Any) -> datetime | None:
    """DSCRTP returns ObservationDate two ways depending on response format:
    `f=json` gives epoch milliseconds (int), while a stringified ISO form
    is also possible. Handle both — TIMESTAMPTZ wants a datetime instance.
    """
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        try:
            return datetime.utcfromtimestamp(float(v) / 1000.0)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(v, str):
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
    return None
