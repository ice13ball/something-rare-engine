# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

# backend/ingestion/chess_ingest.py
"""Fetch ChEssBase occurrences from GBIF and classify habitat type.

Source: ChEssBase dataset on GBIF (dc5abc9f-84d5-4046-a3ef-9ab24ae53756)
~3,700 records of chemosynthetic ecosystem species (vents, seeps, whale falls, OMZs).
"""
import re
from typing import Any
import httpx

CHESS_GBIF_DATASET_KEY = "dc5abc9f-84d5-4046-a3ef-9ab24ae53756"
CHESS_GBIF_URL = "https://api.gbif.org/v1/occurrence/search"
CHESS_PAGE_SIZE = 300

_WHALE_FALL = re.compile(r"\b(whale.?fall|carcass)\b", re.IGNORECASE)
_SEEP       = re.compile(r"\b(seep|hydrate|mud.?volcano|brine|cold.?seep)\b", re.IGNORECASE)
_VENT       = re.compile(r"\b(ridge|rise|vent|hydrothermal|smoker|mound|field)\b", re.IGNORECASE)

# Known bad coordinates in ChEssBase/GBIF source data.
# Key: locality prefix (case-insensitive match). Value: corrected (lat, lon).
# Sources: Smith & Baco 2003 (San Diego Trough whale fall: 32°35'N, 117°29'W).
_COORD_OVERRIDES: dict[str, tuple[float, float]] = {
    "grey whale carcass, san diego trough": (32.5833, -117.4833),
}


#: What `classify_habitat` can return. ⛔ Read by the guard that checks every
#: label, colour and weight map handles all of them.
HABITAT_TYPES = ("whale_fall", "seep", "vent", "unclassified")


def classify_habitat(locality: str) -> str:
    """Keyword-match the locality string → habitat_type.

    ⛔ This is OUR derivation, not a ChEssBase or GBIF field. The source ships a
    free-text locality; the three patterns above are ours, and so is anything
    this returns.

    Priority: whale_fall > seep > vent > unclassified.

    ⛔ The fallback used to be "omz", which read as a positive finding — an
    oxygen-minimum-zone community. It never was one: there is no OMZ pattern
    here at all, so "omz" only ever meant "none of my three keywords matched".
    Measured on production 2026-09-10: 3,605 of 3,715 records (97.0%) carried
    it, and NONE of them had an empty locality — every one was the fallback.
    Labelling 97% of a layer with a habitat we never detected is the same
    defect as letting "missing" and "broken" share a code path, and the value
    reached the API and Area Export, not just the panel.

    'vent' records are used only for hydrothermal_vents enrichment — they never
    appear as standalone map dots.
    """
    if not locality:
        return "unclassified"
    if _WHALE_FALL.search(locality):
        return "whale_fall"
    if _SEEP.search(locality):
        return "seep"
    if _VENT.search(locality):
        return "vent"
    return "unclassified"


async def fetch_chess_occurrences() -> list[dict[str, Any]]:
    """Fetch all ChEssBase GBIF occurrences and return classified records."""
    records: list[dict[str, Any]] = []
    offset = 0

    async with httpx.AsyncClient(timeout=60) as client:
        while True:
            r = await client.get(CHESS_GBIF_URL, params={
                "datasetKey": CHESS_GBIF_DATASET_KEY,
                "limit":      CHESS_PAGE_SIZE,
                "offset":     offset,
            })
            r.raise_for_status()
            data = r.json()
            results = data.get("results", [])
            if not results:
                break

            for occ in results:
                lat = occ.get("decimalLatitude")
                lon = occ.get("decimalLongitude")
                if lat is None or lon is None:
                    continue
                occ_id = str(occ.get("gbifID") or occ.get("key") or "")
                if not occ_id:
                    continue
                locality = occ.get("locality") or occ.get("verbatimLocality") or ""
                depth = occ.get("depth")
                if depth is None:
                    depth = occ.get("minimumDepthInMeters")
                # Apply coordinate overrides for known bad source data
                override = _COORD_OVERRIDES.get(locality.lower().strip())
                if override:
                    lat, lon = override
                records.append({
                    "occurrence_id":    occ_id,
                    "species":          occ.get("species") or occ.get("scientificName") or "",
                    "phylum":           occ.get("phylum") or "",
                    "class_name":       occ.get("class") or "",
                    "family":           occ.get("family") or "",
                    "depth_m":          float(depth) if depth is not None else None,
                    "lat":              float(lat),
                    "lon":              float(lon),
                    "locality":         locality,
                    "institution_code": occ.get("institutionCode") or "",
                    "habitat_type":     classify_habitat(locality),
                })

            offset += CHESS_PAGE_SIZE
            if data.get("endOfRecords", True):
                break

    return records
