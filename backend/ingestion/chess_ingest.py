# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

# backend/ingestion/chess_ingest.py
"""Fetch ChEssBase occurrences from GBIF and pass them through unchanged.

Source: ChEssBase dataset on GBIF (dc5abc9f-84d5-4046-a3ef-9ab24ae53756)
3,715 records of chemosynthetic-ecosystem species. ⭐ We take what the source
publishes — taxonomy, coordinates, depth, locality, institution — and add nothing.
See the note below for the habitat label that used to live here and why it does not.
"""
from typing import Any
import httpx

CHESS_GBIF_DATASET_KEY = "dc5abc9f-84d5-4046-a3ef-9ab24ae53756"
CHESS_GBIF_URL = "https://api.gbif.org/v1/occurrence/search"
CHESS_PAGE_SIZE = 300

#: ⛔ There was a `habitat_type` here until 2026-09-21: three regexes over the
#: free-text `locality`, whose output we stored, served, coloured, filtered and fed
#: into Impact Report severity. It is gone, and nothing replaces it, because
#: **the source publishes no habitat field at all**. Sampled from the GBIF API on
#: 2026-09-21: `habitat`, `waterBody`, `occurrenceRemarks`, `samplingProtocol` and
#: `dynamicProperties` are empty in 100/100 records. ChEssBase gives taxonomy,
#: coordinates, depth and a locality string — and deliberately makes no such claim.
#:
#: Measured before removal, on production:
#:   · 3,605 of 3,715 rows (97.0%) came out `unclassified`
#:   · `Blake Ridge` (a gas-hydrate seep province) was labelled `vent` because the
#:     word "ridge" appears in it, and `Mediterranean Ridge` likewise
#:   · `\bfield\b` never matched `Mariana fields`, losing 225 rows to a plural
#:   · the `habitat_type = 'vent'` filter on the hydrothermal-vent enrichment kept
#:     19 of the 1,205 chess records that actually lie within 5 km of a catalogued
#:     vent, so 1 vent of 721 carried any species at all
#:
#: ⛔ Do not reintroduce a derived habitat label without Michal's decision. The
#: species list is better evidence than any label we could compute: Bathymodiolus
#: azoricus says "vent" more precisely than a word in a place name ever did.
#: → `docs/methods/data-passthrough.md`

#: ⛔ There was a `_COORD_OVERRIDES` table here from 2026-04-07 until
#: 2026-09-22: one hard-coded coordinate, rewriting the whale-fall record
#: `Grey Whale Carcass, San Diego Trough` from the 33.350 / -117.300 the source
#: ships to 32.5833 / -117.4833 (Smith & Baco 2003). It is gone on Michal's
#: decision, and nothing replaces it.
#:
#: The correction was not wrong on the facts. The source coordinate is inland
#: California, +122 m above sea level on GEBCO 2020, while the same record
#: states a depth of 1240 m; the override's target is -1220 m, which matches
#: that stated depth almost exactly. It was wrong on the PRINCIPLE: this
#: platform reproduces sources unchanged, and on 2026-09-22 we told EurOBIS
#: exactly that while this line quietly said otherwise.
#:
#: ⛔ Do not reintroduce a coordinate override. A source error is reported to
#: the publisher, not patched here — the ChEssBase coordinate errors found so
#: far were reported to EurOBIS, which tracks them as ticket `EUROBIS-959`.
#: Consequence, accepted deliberately: this one record now renders on land.
#: → `docs/methods/data-passthrough.md`


async def fetch_chess_occurrences() -> list[dict[str, Any]]:
    """Fetch every ChEssBase GBIF occurrence, as the source ships it."""
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
                })

            offset += CHESS_PAGE_SIZE
            if data.get("endOfRecords", True):
                break

    return records
