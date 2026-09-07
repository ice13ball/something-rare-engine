#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""
Ingest cetacean sightings from OBIS v3 into cetacean_cells table.
Run standalone: cd ~/something-rare/backend && source .venv/bin/activate && python3 ingestion/cetacean_ingest.py

Uses OBIS v3 REST API (https://api.obis.org/v3/occurrence):
  - Fetches up to 10 batches × 10 000 records (100 000) for general Cetacea (infraorderid=2688)
  - Then fetches targeted records for each curated IUCN species to ensure they're represented
  - Aggregates to 1° grid cells with IUCN species weights
  - Upserts into cetacean_cells table
"""
import asyncio
import os
import asyncpg
import httpx
import math
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL", "postgresql://abyssal_user:CHANGE_ME@localhost/abyssal")

# OBIS v3 API — Cetacea infraorder taxonID = 2688
OBIS_API  = "https://api.obis.org/v3/occurrence"
CETACEA_ID = 2688
BATCH_SIZE = 10000
MAX_BATCHES = 10   # 100 000 general records — sufficient for global grid coverage

GRID_DEG = 1.0

# Curated IUCN weight lookup — scientific name (lowercase) → (category, weight)
# Source: IUCN Red List 2024, cetacean species only
IUCN_LOOKUP: dict[str, tuple[str, float]] = {
    # CR — 2.0
    "eubalaena japonica":      ("CR", 2.0),   # North Pacific Right Whale
    "eubalaena glacialis":     ("CR", 2.0),   # North Atlantic Right Whale
    "lipotes vexillifer":      ("CR", 2.0),   # Baiji (functionally extinct)
    "phocoena sinus":          ("CR", 2.0),   # Vaquita
    # EN — 1.5
    "balaenoptera musculus":   ("EN", 1.5),   # Blue Whale
    "balaenoptera physalus":   ("EN", 1.5),   # Fin Whale
    "balaenoptera borealis":   ("EN", 1.5),   # Sei Whale
    "eschrichtius robustus":   ("EN", 1.5),   # Grey Whale (W Pacific)
    "sousa chinensis":         ("EN", 1.5),   # Indo-Pacific Humpback
    "orcaella brevirostris":   ("EN", 1.5),   # Irrawaddy Dolphin
    # VU — 1.2
    "physeter macrocephalus":  ("VU", 1.2),   # Sperm Whale
    "balaena mysticetus":      ("VU", 1.2),   # Bowhead Whale
    "megaptera novaeangliae":  ("VU", 1.2),   # Humpback Whale (some pops)
    "orcinus orca":            ("VU", 1.2),   # Killer Whale (some pops)
    "phocoena phocoena":       ("VU", 1.2),   # Harbour Porpoise (Baltic)
    "platanista gangetica":    ("VU", 1.2),   # Ganges River Dolphin
    # NT/LC — 1.0 (default)
}


def snap(val: float, step: float = GRID_DEG) -> float:
    return math.floor(val / step) * step


def iucn_weight(species: str) -> tuple[str | None, float]:
    return IUCN_LOOKUP.get(species.strip().lower(), (None, 1.0))


def accumulate(cells: dict, lon: float, lat: float, obs_count: int, species: str) -> None:
    """Add a sighting to the grid cell aggregation."""
    clon, clat = snap(lon), snap(lat)
    key = f"{clon}_{clat}"
    cat, wt = iucn_weight(species)
    if key not in cells:
        cells[key] = {
            "clon": clon, "clat": clat,
            "count": 0,
            "max_weight": 1.0, "max_cat": None, "top_species": None,
        }
    cells[key]["count"] += obs_count
    if wt > cells[key]["max_weight"]:
        cells[key]["max_weight"]  = wt
        cells[key]["max_cat"]     = cat
        cells[key]["top_species"] = species


async def fetch_batch(client: httpx.AsyncClient, params: dict) -> list[dict]:
    """Fetch one page of OBIS occurrences."""
    try:
        r = await client.get(OBIS_API, params=params, timeout=60)
        r.raise_for_status()
        return r.json().get("results", [])
    except Exception as e:
        log.warning("OBIS fetch failed (params=%s): %s", params, e)
        return []


def parse_record(rec: dict) -> tuple[float, float, int, str] | None:
    """Extract (lon, lat, count, species) from an OBIS occurrence record."""
    lon = rec.get("decimalLongitude")
    lat = rec.get("decimalLatitude")
    if lon is None or lat is None:
        return None
    try:
        lon, lat = float(lon), float(lat)
    except (TypeError, ValueError):
        return None
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return None
    raw_count = rec.get("individualCount")
    try:
        obs_count = int(raw_count) if raw_count else 1
    except (TypeError, ValueError):
        obs_count = 1
    species = str(rec.get("scientificName") or "")
    return lon, lat, obs_count, species


async def main():
    cells: dict[str, dict] = {}
    total_records = 0

    async with httpx.AsyncClient() as client:
        # --- Phase 1: general Cetacea batches ---
        log.info("Phase 1: fetching general Cetacea from OBIS v3 (%d batches × %d)...",
                 MAX_BATCHES, BATCH_SIZE)
        for batch_num in range(MAX_BATCHES):
            skip = batch_num * BATCH_SIZE
            params = {
                "taxonid": CETACEA_ID,
                "size":    BATCH_SIZE,
                "skip":    skip,
                "fields":  "decimalLongitude,decimalLatitude,scientificName,individualCount",
            }
            records = await fetch_batch(client, params)
            if not records:
                log.info("  Batch %d returned 0 records — stopping early", batch_num)
                break
            for rec in records:
                parsed = parse_record(rec)
                if parsed:
                    accumulate(cells, *parsed)
                    total_records += 1
            log.info("  Batch %d/%d: %d records, %d cells so far",
                     batch_num + 1, MAX_BATCHES, len(records), len(cells))

        # --- Phase 2: targeted IUCN species fetches ---
        log.info("Phase 2: targeted fetch for %d IUCN-listed cetacean species...",
                 len(IUCN_LOOKUP))
        for sci_name in IUCN_LOOKUP:
            params = {
                "scientificname": sci_name,
                "size":           BATCH_SIZE,
                "fields":         "decimalLongitude,decimalLatitude,scientificName,individualCount",
            }
            records = await fetch_batch(client, params)
            for rec in records:
                parsed = parse_record(rec)
                if parsed:
                    accumulate(cells, *parsed)
                    total_records += 1
            log.info("  %s: %d records", sci_name, len(records))

    log.info("Fetched %d total OBIS records → %d grid cells", total_records, len(cells))

    conn = await asyncpg.connect(DB_URL)
    for key, c in cells.items():
        await conn.execute("""
            INSERT INTO cetacean_cells
              (geom, cell_lon, cell_lat, cell_key, sighting_count, max_iucn_weight, max_iucn_cat, top_species, source, updated_at)
            VALUES
              (ST_SetSRID(ST_MakePoint($1,$2),4326), $1, $2, $3, $4, $5, $6, $7, 'obis', NOW())
            ON CONFLICT (cell_key) DO UPDATE SET
              sighting_count  = EXCLUDED.sighting_count,
              max_iucn_weight = GREATEST(cetacean_cells.max_iucn_weight, EXCLUDED.max_iucn_weight),
              max_iucn_cat    = COALESCE(EXCLUDED.max_iucn_cat, cetacean_cells.max_iucn_cat),
              top_species     = COALESCE(EXCLUDED.top_species, cetacean_cells.top_species),
              updated_at      = NOW()
        """, c["clon"], c["clat"], key,
             c["count"], c["max_weight"], c["max_cat"], c["top_species"])

    db_total = await conn.fetchval("SELECT COUNT(*) FROM cetacean_cells")
    log.info("Done. cetacean_cells total: %d", db_total)
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
