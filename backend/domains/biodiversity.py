# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Biodiversity domain — species occurrence sources (OBIS, ChEssBase, SIO-BIC,
DeepData, MBARI VARS, NOAA Deep-Sea Coral & Sponge), the WoRMS taxonomic
resolver, GBIF/iNaturalist image + IUCN enrichment, and the hotspot density
grid.

Moved verbatim out of backend/main.py (Task 4 of the backend vertical-split
refactor, Phase 4 — the last domain extraction). Only permitted edits applied:
`@app.` -> `@router.`, `_pool` -> `db.pool`, dropping the leading underscore
on sync/enrichment functions (matching the convention every other domain
module already uses — `main.py` calls them as `biodiversity.<name>`), and
imports. `_grid_cache` / `_chess_cache` and the four `GBIF_*` / `INAT_TAXA_URL`
constants keep their original names, same as every prior domain's caches and
module constants.

Not moved: `_sio_bic_sync_task`, `_worms_sync_task` and
`_monitoring_density_refresh_task` stay in main.py — they are lifespan
orchestration, like every other `*_task`, and merely call into this domain.
`GBIF_SPECIES_URL` and `_hotspot_grid_lock` were left in main.py: both are
dead (unused anywhere in the codebase), so neither is part of this move.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math

import db
import httpx
from auth import get_api_key, require_admin_token
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sync_log import log_sync as _log_sync

log = logging.getLogger(__name__)
router = APIRouter()

# ── GBIF / iNaturalist enrichment URLs ─────────────────────────────────────

GBIF_MATCH_URL   = "https://api.gbif.org/v1/species/match"

GBIF_IUCN_URL    = "https://api.gbif.org/v1/species/{key}/iucnRedListCategory"

GBIF_MEDIA_URL   = "https://api.gbif.org/v1/species/{key}/media"

INAT_TAXA_URL    = "https://api.inaturalist.org/v1/taxa"


# ── Caches ──────────────────────────────────────────────────────────────────

_grid_cache: dict[str, str] = {}  # resolution → GeoJSON string

_chess_cache:          str | None = None


def clear_caches() -> None:
    """Sweep this domain's caches. Called via domains.CACHE_CLEARING_DOMAINS."""
    global _chess_cache
    _grid_cache.clear()
    _chess_cache = None


# ── Species / occurrence syncs ─────────────────────────────────────────────

async def refresh_species_cache_logged() -> int:
    """Admin-triggered species-cache rebuild — logs success/failure to sync_log.

    Same call site used by /admin/sync/species-cache. The weekly chain
    has its own try/except + _log_sync in run_weekly_sync(); this wrapper
    handles the admin-trigger path so a silent failure can't leave
    claim_species_cache empty without anyone noticing.

    Calls services/species_cache.py (NOT routers/reports.py — that file
    is the frozen v1 restore path and its rebuild SQL has a
    UniqueViolationError bug from grouping by phylum).
    """
    try:
        from services.species_cache import refresh_species_cache
        cnt = await refresh_species_cache()
        await _log_sync("species-cache", cnt, cnt)
        return cnt
    except Exception as exc:
        log.warning("species_cache (admin): refresh failed — %s", exc)
        try:
            await _log_sync("species-cache", 0, 0)
        except Exception:
            pass
        raise


async def sync_biodiversity_hotspots() -> int:
    """OBIS biodiversity sync — delegates to ingestion/obis_sync.py.

    The sync runs as its own systemd service (obis-sync.service) on a weekly
    schedule. This wrapper exists so the admin force-sync endpoint
    (/admin/sync/obis) still works from within abyssal-api.
    """
    from ingestion.obis_sync import sync_obis
    return await sync_obis(db.pool)


async def sync_chess() -> int:
    """Fetch ChEssBase OBIS records, upsert, and enrich hydrothermal_vents."""
    from ingestion.chess_ingest import fetch_chess_occurrences
    records = await fetch_chess_occurrences()
    if not records:
        return 0

    async with db.pool.acquire() as conn:
        await conn.executemany(
            """INSERT INTO chess_occurrences
               (occurrence_id, species, phylum, class_name, family,
                depth_m, lat, lon, locality, institution_code, habitat_type,
                geom)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
                       ST_SetSRID(ST_MakePoint($8, $7), 4326))
               ON CONFLICT (occurrence_id) DO UPDATE
               SET species=EXCLUDED.species, phylum=EXCLUDED.phylum,
                   depth_m=EXCLUDED.depth_m, habitat_type=EXCLUDED.habitat_type,
                   locality=EXCLUDED.locality,
                   geom=EXCLUDED.geom""",
            [(r["occurrence_id"], r["species"], r["phylum"], r["class_name"],
              r["family"], r["depth_m"], r["lat"], r["lon"],
              r["locality"], r["institution_code"], r["habitat_type"])
             for r in records],
        )
        count = await conn.fetchval("SELECT COUNT(*) FROM chess_occurrences")

        # Enrich hydrothermal_vents: aggregate chess records within 5 km
        await conn.execute("""
            UPDATE hydrothermal_vents v
            SET
                chess_count = (
                    SELECT COUNT(*) FROM chess_occurrences c
                    WHERE c.habitat_type = 'vent'
                    AND ST_DWithin(v.geom,
                                  c.geom::geography, 5000)
                ),
                chess_species = (
                    SELECT COALESCE(
                        json_agg(json_build_object(
                            'species',     c.species,
                            'phylum',      c.phylum,
                            'depth_m',     c.depth_m,
                            'institution', c.institution_code
                        )),
                        '[]'::json
                    )
                    FROM chess_occurrences c
                    WHERE c.habitat_type = 'vent'
                    AND ST_DWithin(v.geom,
                                  c.geom::geography, 5000)
                )
        """)

    global _chess_cache
    _chess_cache = None
    await _log_sync("chess", len(records), count)
    return count


async def sync_sio_bic() -> int:
    """Bulk-fetch SIO Benthic Invertebrate Collection catalogue (CSV export),
    upsert deep-sea records (depth >= 200 m) into sio_bic_records."""
    from ingestion.sio_bic_ingest import fetch_sio_bic_records
    records = await fetch_sio_bic_records()
    if not records:
        return 0

    cols = [
        "catalog_id", "higher_taxa_code", "catalog_no", "phylum", "class_",
        "order_", "family", "genus", "species", "authority", "identifier",
        "type_status", "count", "collection_type_raw", "specimen_type",
        "fixative", "preservative", "storage_location", "reference_id",
        "loan_id", "gift_id", "catalog_notes", "genbank",
        "accession_no", "accession_id", "accession_date", "station",
        "locality", "country", "ocean", "lat", "lon", "end_lat", "end_lon",
        "begin_depth_m", "end_depth_m", "depth_unit", "collection_date",
        "collection_time", "gear", "ship", "collector", "remarks",
    ]
    placeholders = ", ".join(f"${i + 1}" for i in range(len(cols)))
    update_set = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in cols if c != "catalog_id"
    )
    sql = (
        f"INSERT INTO sio_bic_records ({', '.join(cols)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT (catalog_id) DO UPDATE SET {update_set}, fetched_at = NOW()"
    )
    async with db.pool.acquire() as conn:
        for i in range(0, len(records), 500):
            chunk = records[i:i + 500]
            await conn.executemany(sql, [tuple(r[c] for c in cols) for r in chunk])
        total = await conn.fetchval("SELECT COUNT(*) FROM sio_bic_records")
    await _log_sync("sio-bic", len(records), total)
    log.info("sio_bic: %d upserted, %d total", len(records), total)
    return total


async def sync_deepdata() -> int:
    """Pull ISA DeepData occurrences via OBIS REST (nodeid filter) and upsert
    into deepdata_occurrences.

    Source: contractor environmental reports submitted to ISA, mirrored
    into OBIS as DwC archives. ~201k records across ~153 datasets, ~10
    contractor codes (NORI, TOML, BGR, UKSRL, …).
    """
    from ingestion.deepdata_ingest import fetch_deepdata_records
    records = await fetch_deepdata_records()
    if not records:
        log.info("deepdata: no records fetched")
        return 0

    cols = [
        "obis_id", "occurrence_id", "dataset_id", "dataset_title",
        "contractor_code", "rights_holder", "scientific_name", "phylum",
        "class_", "order_", "family", "genus", "species", "basis_of_record",
        "depth_m", "lat", "lon", "event_date", "locality",
    ]
    placeholders = ", ".join(f"${i + 1}" for i in range(len(cols)))
    sql = (
        f"INSERT INTO deepdata_occurrences ({', '.join(cols)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT (obis_id) DO NOTHING"
    )
    async with db.pool.acquire() as conn:
        for i in range(0, len(records), 1000):
            chunk = records[i:i + 1000]
            await conn.executemany(sql, [tuple(r[c] for c in cols) for r in chunk])
        total = await conn.fetchval("SELECT COUNT(*) FROM deepdata_occurrences")
    await _log_sync("deepdata", len(records), total)
    log.info("deepdata: %d processed, %d total in table", len(records), total)
    return total


async def sync_mbari_vars() -> int:
    """Pull MBARI VARS deep-sea ROV occurrences via OBIS REST (datasetid filter)
    and upsert into `mbari_vars_records`.

    Source: MBARI VARS subset published to OBIS as a single DwC dataset
    (`a419c8da-…`). ~175k records, mostly NE Pacific. Same records also arrive
    via the broader OBIS parquet sync into `biodiversity_hotspots`; surfaced
    separately here so the density panel can credit MBARI by name.
    """
    from ingestion.mbari_vars_ingest import fetch_mbari_records
    records = await fetch_mbari_records()
    if not records:
        log.info("mbari-vars: no records fetched")
        return 0

    cols = [
        "obis_id", "occurrence_id", "dataset_id",
        "scientific_name", "phylum", "class_", "order_", "family",
        "genus", "species", "basis_of_record",
        "depth_m", "lat", "lon", "event_date", "locality",
    ]
    placeholders = ", ".join(f"${i + 1}" for i in range(len(cols)))
    sql = (
        f"INSERT INTO mbari_vars_records ({', '.join(cols)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT (obis_id) DO NOTHING"
    )
    async with db.pool.acquire() as conn:
        for i in range(0, len(records), 1000):
            chunk = records[i:i + 1000]
            await conn.executemany(sql, [tuple(r[c] for c in cols) for r in chunk])
        total = await conn.fetchval("SELECT COUNT(*) FROM mbari_vars_records")
    await _log_sync("mbari-vars", len(records), total)
    log.info("mbari-vars: %d processed, %d total in table", len(records), total)
    return total


async def sync_noaa_corals() -> int:
    """Stream NOAA Deep-Sea Coral & Sponge (DSCRTP) records from NOAA's
    ArcGIS FeatureServer and upsert into `noaa_corals_records`.

    Volume snapshot: ~1.5 M records. The ingest yields page-sized chunks
    (PAGE_SIZE = 1000) so we never hold the full result set in memory —
    each page is upserted before the next is requested.

    A single full sync takes ~60-75 minutes on the VPS (~1.5-5s/page,
    deeper offsets slower). Re-runs are safe: ON CONFLICT DO NOTHING on
    `catalog_number`.

    Returns the total row count in the table after the run.
    """
    from ingestion.noaa_corals_ingest import fetch_noaa_corals_records

    cols = [
        "catalog_number", "object_id", "sample_id", "event_id", "dataset_id",
        "data_provider",
        "scientific_name", "verbatim_scientific_name", "synonyms",
        "vernacular_name_category", "identification_qualifier",
        "phylum", "class_", "order_", "family", "genus",
        "aphia_id", "taxon_rank",
        "depth_m", "lat", "lon", "locality", "ocean_code",
        "fish_council_region", "vessel", "sampling_equipment", "pi", "survey_id",
        "image_url", "highlight_image_url",
        "temperature", "salinity", "oxygen",
        "observation_year", "event_date",
    ]
    placeholders = ", ".join(f"${i + 1}" for i in range(len(cols)))
    sql = (
        f"INSERT INTO noaa_corals_records ({', '.join(cols)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT (catalog_number) DO NOTHING"
    )

    fetched = 0
    async with db.pool.acquire() as conn:
        async for page in fetch_noaa_corals_records():
            fetched += len(page)
            await conn.executemany(sql, [tuple(r[c] for c in cols) for r in page])
        total = await conn.fetchval("SELECT COUNT(*) FROM noaa_corals_records")

    await _log_sync("noaa-corals", fetched, total)
    log.info("noaa-corals: %d fetched, %d total in table", fetched, total)
    return total


async def sync_worms_taxa(force: bool = False) -> int:
    """Resolve DISTINCT free-text species names to canonical WoRMS AphiaIDs.

    Incremental: only names absent from taxon_name_map are queried (steady
    state ~0 API calls). Never truncates; WoRMS outage => returns current total.
    `force` re-queries names previously stored as match_type='none'.
    """
    from ingestion import worms_ingest as wi  # runtime path is rooted in backend/

    name_sources = [
        ("biodiversity_hotspots", "SELECT DISTINCT scientific_name FROM biodiversity_hotspots WHERE scientific_name IS NOT NULL"),
        ("mbari_vars",            "SELECT DISTINCT scientific_name FROM mbari_vars_records   WHERE scientific_name IS NOT NULL"),
        ("noaa_corals",           "SELECT DISTINCT scientific_name FROM noaa_corals_records  WHERE scientific_name IS NOT NULL"),
        ("deepdata_isa",          "SELECT DISTINCT scientific_name FROM deepdata_occurrences WHERE scientific_name IS NOT NULL"),
        ("deepdata_stations",     "SELECT DISTINCT unnest(top_species) AS scientific_name FROM deepdata_stations WHERE top_species IS NOT NULL"),
    ]

    # 1. Gather distinct normalized names + first source seen.
    seen: dict[str, str] = {}
    async with db.pool.acquire() as conn:
        for src, sql in name_sources:
            for r in await conn.fetch(sql):
                nm = wi.normalize_name(r["scientific_name"])
                if nm and nm not in seen:
                    seen[nm] = src
        # 2. Incremental: drop names already resolved (unless force re-does 'none').
        existing = {r["raw_name"]: r["match_type"]
                    for r in await conn.fetch("SELECT raw_name, match_type FROM taxon_name_map")}
    todo = [n for n in seen
            if n not in existing or (force and existing.get(n) == "none")]

    if not todo:
        async with db.pool.acquire() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM taxon_name_map")
        await _log_sync("worms", 0, total)
        log.info("worms: nothing new to resolve (%d names mapped)", total)
        return total

    # 3. Resolve + PERSIST PER BATCH so progress is durable/resumable. The full
    #    backfill is ~75k names (~2 h); committing each <=50-name batch means a
    #    restart resumes via the incremental anti-join (step 2) instead of losing
    #    everything. worms_taxa is upserted before taxon_name_map (FK order).
    tcols = ["aphia_id", "scientificname", "authority", "rank", "status",
             "kingdom", "phylum", "class_name", "order_name", "family", "genus",
             "is_marine", "is_brackish", "is_freshwater", "is_terrestrial",
             "citation", "url", "worms_modified"]
    placeholders = ", ".join(f"${i+1}" for i in range(len(tcols)))
    updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in tcols if c != "aphia_id")
    worms_upsert = (
        f"INSERT INTO worms_taxa ({', '.join(tcols)}, fetched_at) "
        f"VALUES ({placeholders}, NOW()) "
        f"ON CONFLICT (aphia_id) DO UPDATE SET {updates}, fetched_at=NOW()"
    )
    map_upsert = (
        "INSERT INTO taxon_name_map (raw_name, matched_aphia_id, match_type, verified, first_source, resolved_at) "
        "VALUES ($1, $2, $3, $4, $5, NOW()) "
        "ON CONFLICT (raw_name) DO UPDATE SET "
        "matched_aphia_id=EXCLUDED.matched_aphia_id, match_type=EXCLUDED.match_type, "
        "verified=EXCLUDED.verified, resolved_at=NOW()"
    )

    added = 0
    nbatches = (len(todo) + wi.MAX_BATCH - 1) // wi.MAX_BATCH
    async with db.pool.acquire() as conn:
        for bi, i in enumerate(range(0, len(todo), wi.MAX_BATCH)):
            batch = todo[i:i + wi.MAX_BATCH]
            try:
                groups = await wi.match_names(batch)
            except Exception:
                log.exception("worms: match batch failed (%d names) — skipping", len(batch))
                continue
            resolutions: list[dict] = []
            valid_ids: set[int] = set()
            for name, group in zip(batch, groups):
                res = wi.resolution_from_candidate(name, wi.pick_best_candidate(group))
                res["first_source"] = seen.get(name)
                resolutions.append(res)
                if res["matched_aphia_id"]:
                    valid_ids.add(res["matched_aphia_id"])

            # Authoritative valid records for this batch (<=50 ids → one call).
            taxa_rows: list[dict] = []
            ids = sorted(valid_ids)
            for j in range(0, len(ids), wi.MAX_BATCH):
                try:
                    recs = await wi.records_by_ids(ids[j:j + wi.MAX_BATCH])
                except Exception:
                    log.exception("worms: records_by_ids batch failed — skipping")
                    continue
                taxa_rows.extend(wi.worms_row_from_record(rec) for rec in recs)

            fetched_ids = {row["aphia_id"] for row in taxa_rows}
            insert_rows = [r for r in resolutions
                           if r["matched_aphia_id"] is None or r["matched_aphia_id"] in fetched_ids]
            try:
                async with conn.transaction():
                    if taxa_rows:
                        await conn.executemany(
                            worms_upsert,
                            [tuple(coerce_worms_modified(row, c) for c in tcols) for row in taxa_rows],
                        )
                    await conn.executemany(
                        map_upsert,
                        [(r["raw_name"], r["matched_aphia_id"], r["match_type"], r["verified"], r["first_source"])
                         for r in insert_rows],
                    )
            except Exception:
                log.exception("worms: persist batch failed — skipping")
                continue
            added += len(insert_rows)
            if bi % 25 == 0:
                log.info("worms: progress batch %d/%d (%d names resolved so far)",
                         bi + 1, nbatches, added)

        total = await conn.fetchval("SELECT COUNT(*) FROM taxon_name_map")

    await _log_sync("worms", added, total)
    log.info("worms: resolved %d new names, %d total mapped", added, total)
    return total


def coerce_worms_modified(row: dict, col: str):
    """worms_modified arrives as an ISO string from WoRMS; asyncpg wants a datetime."""
    val = row.get(col)
    if col == "worms_modified" and isinstance(val, str) and val:
        from datetime import datetime
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except ValueError:
            return None
    return val


async def sync_deepdata_stations() -> int:
    """ANALYTICS tier: derive sampling-deployment stations from OBIS-hosted
    DwC archives. Incremental — uses ETag/Content-Length HEAD probes so a
    typical re-run downloads nothing.

    Returns total stations in the table after the run.
    """
    import time
    from datetime import datetime
    from ingestion.deepdata_dwc_ingest import (
        list_remote_slugs, head_probe_all, fetch_archive, parse_archive,
    )

    t0 = time.monotonic()
    headers = {"User-Agent": "abyssal-claims/1.0 (+https://something-rare.com)"}
    async with httpx.AsyncClient(timeout=120, headers=headers, follow_redirects=True) as client:
        # Discovery
        try:
            slugs_remote = await list_remote_slugs(client)
        except Exception as e:
            log.error("deepdata-stations: failed to fetch index — %s", e)
            return 0
        log.info("deepdata-stations: %d archives in remote index", len(slugs_remote))

        # Local state
        async with db.pool.acquire() as conn:
            local_rows = await conn.fetch(
                "SELECT slug, etag, content_length FROM deepdata_dwc_archives"
            )
        local_by_slug = {r["slug"]: r for r in local_rows}

        # HEAD-probe ALL remote slugs in one pass — both new and existing.
        # Probing new slugs too lets us persist the etag/last_modified on first
        # ingest, so the NEXT run can short-circuit cleanly.
        gone = [s for s in local_by_slug if s not in slugs_remote]
        if gone:
            log.warning("deepdata-stations: %d archives no longer in index (kept): %s",
                        len(gone), ", ".join(sorted(gone)[:5]))

        head_results = await head_probe_all(client, slugs_remote)
        head_by_slug = {h["slug"]: h for h in head_results}

        new_slugs: list[str] = []
        changed_slugs: list[str] = []
        skipped_slugs: list[str] = []
        for slug in slugs_remote:
            h = head_by_slug.get(slug, {"slug": slug, "error": "no head"})
            if "error" in h:
                log.warning("deepdata-stations: HEAD failed for %s — %s", slug, h["error"])
                continue
            row = local_by_slug.get(slug)
            if row is None:
                new_slugs.append(slug)
            elif h["etag"] == row["etag"] and h["content_length"] == row["content_length"]:
                skipped_slugs.append(slug)
            else:
                changed_slugs.append(slug)

        queue = new_slugs + changed_slugs
        log.info("deepdata-stations: %d new, %d changed, %d unchanged",
                 len(new_slugs), len(changed_slugs), len(skipped_slugs))

        if not queue:
            async with db.pool.acquire() as conn:
                total = await conn.fetchval("SELECT COUNT(*) FROM deepdata_stations")
            await _log_sync("deepdata-stations", 0, total or 0)
            log.info("deepdata-stations: nothing to do; %d stations in table (%.1fs)",
                     total or 0, time.monotonic() - t0)
            return total or 0

        # Fetch + parse + write — one archive at a time so failures are isolated.
        stations_added = 0
        failed = 0
        for slug in queue:
            try:
                head = head_by_slug.get(slug, {})
                zip_bytes = await fetch_archive(client, slug)
                archive_meta, stations = parse_archive(slug, zip_bytes)
                # Stamp HTTP cache validators + fetched-at on the archive row
                archive_meta["last_modified"]  = head.get("last_modified")
                archive_meta["etag"]           = head.get("etag")
                archive_meta["content_length"] = head.get("content_length") or len(zip_bytes)
                archive_meta["last_fetched_at"] = datetime.utcnow()
                archive_meta["last_parsed_at"]  = datetime.utcnow()
                archive_meta["parse_error"]     = None

                await upsert_dwc_archive_and_stations(archive_meta, stations)
                stations_added += len(stations)
                log.info("deepdata-stations: %s → %d stations (%d occ, %s)",
                         slug, len(stations), archive_meta["occurrence_count"],
                         archive_meta.get("title") or "<no title>")
            except Exception as e:
                failed += 1
                log.exception("deepdata-stations: failed processing %s", slug)
                # Persist the error so we can see it in the dashboard
                async with db.pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO deepdata_dwc_archives (slug, last_fetched_at, parse_error)
                        VALUES ($1, NOW(), $2)
                        ON CONFLICT (slug) DO UPDATE SET
                            last_fetched_at = NOW(),
                            parse_error     = EXCLUDED.parse_error
                    """, slug, str(e)[:500])

        async with db.pool.acquire() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM deepdata_stations")
        await _log_sync("deepdata-stations", stations_added, total or 0)
        # Invalidate the GeoJSON endpoint cache so the next request re-renders.
        try:
            from domains.land.density import clear_deepdata_stations_cache
            clear_deepdata_stations_cache()
        except Exception:
            pass
        log.info("deepdata-stations: processed %d archives (%d failed), %d stations added, %d total (%.1fs)",
                 len(queue), failed, stations_added, total or 0, time.monotonic() - t0)
        return total or 0


async def upsert_dwc_archive_and_stations(
    archive_meta: dict,
    stations: list[dict],
) -> None:
    """Replace stations for a single slug in one transaction.

    Cascade FK from deepdata_stations.archive_slug means an UPDATE of
    the parent + DELETE+INSERT of the children is the simplest path.
    """
    arch_cols = [
        "slug", "title", "citation", "license", "rights_holder",
        "pub_date", "last_modified", "etag", "content_length",
        "occurrence_count", "station_count", "last_fetched_at",
        "last_parsed_at", "parse_error",
        # ⛔ Adding a column here without adding it to the archive_meta dict
        # writes NULL forever, silently — the INSERT is built from this list.
        "measurement_count", "measurement_types",
    ]
    arch_placeholders = ", ".join(f"${i+1}" for i in range(len(arch_cols)))
    arch_update = ", ".join(f"{c} = EXCLUDED.{c}" for c in arch_cols if c != "slug")
    arch_sql = (
        f"INSERT INTO deepdata_dwc_archives ({', '.join(arch_cols)}) "
        f"VALUES ({arch_placeholders}) "
        f"ON CONFLICT (slug) DO UPDATE SET {arch_update}"
    )

    sta_cols = [
        "station_id", "archive_slug", "contractor_code",
        "event_id_raw", "location_id", "sampling_protocol",
        "lat", "lon", "depth_m_min", "depth_m_max", "coord_uncertainty_m",
        "first_event_date", "last_event_date",
        "occurrence_count", "species_count",
        "top_species", "top_phyla", "sediment_horizons",
    ]
    sta_placeholders = ", ".join(f"${i+1}" for i in range(len(sta_cols)))
    sta_sql = (
        f"INSERT INTO deepdata_stations ({', '.join(sta_cols)}) "
        f"VALUES ({sta_placeholders}) "
        f"ON CONFLICT (station_id) DO UPDATE SET "
        + ", ".join(f"{c} = EXCLUDED.{c}" for c in sta_cols if c != "station_id")
        + ", derived_at = NOW()"
    )

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(arch_sql, *(archive_meta.get(c) for c in arch_cols))
            # Delete old stations for this slug (cleaner than per-row diff;
            # the volume per archive is small enough — at most ~1000 stations).
            await conn.execute(
                "DELETE FROM deepdata_stations WHERE archive_slug = $1",
                archive_meta["slug"],
            )
            if stations:
                await conn.executemany(
                    sta_sql,
                    [tuple(s.get(c) for c in sta_cols) for s in stations],
                )


# ── Enrichment ──────────────────────────────────────────────────────────────

async def enrich_species_images(batch_size: int = 500) -> int:
    """Enrich biodiversity_hotspots with image_url and vernacular_name from GBIF/iNaturalist.

    Looks up each distinct scientific_name that lacks an image_url, tries GBIF first
    (higher-quality curated images), then falls back to iNaturalist. Updates all rows
    for the species in one UPDATE statement. Also fills vernacular_name if missing.

    batch_size caps how many species are processed per invocation so weekly syncs
    make gradual progress without blocking for hours.
    """
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT DISTINCT scientific_name
               FROM biodiversity_hotspots
               WHERE scientific_name IS NOT NULL
                 AND image_url IS NULL
               LIMIT $1""",
            batch_size,
        )
    names = [r["scientific_name"] for r in rows]
    if not names:
        log.info("species images: nothing to enrich")
        return 0

    log.info("species images: enriching up to %d species", len(names))
    enriched = 0

    async with httpx.AsyncClient(timeout=15) as client:
        for name in names:
            image_url: str | None = None
            vernacular: str | None = None
            iucn_cat: str | None = None

            # ── GBIF lookup ──────────────────────────────────────────────
            try:
                match = await client.get(GBIF_MATCH_URL, params={"name": name, "strict": "false"})
                if match.status_code == 200:
                    match_data = match.json()
                    # Strict verification: only accept the match if the returned taxon name
                    # equals our input name (case-insensitive). Fuzzy matching can return a
                    # completely different taxon (e.g. querying a fish gets a bird).
                    matched_name = (match_data.get("species") or match_data.get("canonicalName") or "").strip().lower()
                    if matched_name != name.strip().lower():
                        log.debug("GBIF name mismatch for %r: got %r — skipping", name, matched_name)
                    else:
                        key = match_data.get("usageKey")
                        if key:
                            media = await client.get(
                                GBIF_MEDIA_URL.format(key=key),
                                params={"limit": 3, "type": "StillImage"},
                            )
                            if media.status_code == 200:
                                for item in media.json().get("results", []):
                                    url = item.get("identifier", "")
                                    # Prefer https; skip SVG/audio/video
                                    if url and not url.endswith((".svg", ".gif")) and "audio" not in url:
                                        image_url = url
                                        break
                            # Vernacular from match response
                            vernacular = match_data.get("vernacularName") or match_data.get("canonicalName")
                            # ── IUCN Red List category via dedicated endpoint ──
                            try:
                                iucn_resp = await client.get(GBIF_IUCN_URL.format(key=key))
                                if iucn_resp.status_code == 200:
                                    iucn_raw = iucn_resp.json().get("code")
                                    if iucn_raw in ("CR", "EN", "VU", "NT", "LC", "DD"):
                                        iucn_cat = iucn_raw
                            except httpx.HTTPError:
                                pass
            except httpx.HTTPError as e:
                log.debug("GBIF lookup failed for %s: %s", name, e)

            # ── iNaturalist fallback ──────────────────────────────────────
            if not image_url:
                try:
                    inat = await client.get(
                        INAT_TAXA_URL,
                        params={"q": name, "per_page": 5, "rank": "species,subspecies,variety"},
                    )
                    if inat.status_code == 200:
                        results = inat.json().get("results", [])
                        # Strict verification: only accept a result whose taxon name equals
                        # our input name exactly. Don't blindly take results[0].
                        matched_taxon = None
                        for result in results:
                            if (result.get("name") or "").strip().lower() == name.strip().lower():
                                matched_taxon = result
                                break
                        if matched_taxon is None:
                            log.debug("iNat: no exact name match for %r in top-5 results — skipping", name)
                        else:
                            photo = matched_taxon.get("default_photo") or {}
                            image_url = photo.get("medium_url") or photo.get("square_url")
                            if not vernacular:
                                vernacular = matched_taxon.get("preferred_common_name")
                except httpx.HTTPError as e:
                    log.debug("iNaturalist lookup failed for %s: %s", name, e)

            if not image_url and not iucn_cat:
                continue

            # ── UPDATE all rows for this species ─────────────────────────
            async with db.pool.acquire() as conn:
                await conn.execute(
                    """UPDATE biodiversity_hotspots
                       SET image_url       = COALESCE($1, image_url),
                           vernacular_name = COALESCE(vernacular_name, $2),
                           iucn_category   = COALESCE($3, iucn_category, 'NE'),
                           is_endangered   = COALESCE($3, iucn_category, 'NE') IN ('CR', 'EN', 'VU')
                       WHERE scientific_name = $4
                         AND (image_url IS NULL OR iucn_category IN ('NE', 'DD') OR iucn_category IS NULL)""",
                    image_url,
                    vernacular,
                    iucn_cat,
                    name,
                )
            enriched += 1
            await asyncio.sleep(0.2)  # gentle rate-limit: ~5 req/s to GBIF

    log.info("species images: enriched %d / %d species in this batch", enriched, len(names))
    return enriched


async def reset_inat_images_for_reverification() -> int:
    """One-shot: NULL image_url and vernacular_name for biodiversity_hotspots rows
    whose images came from iNaturalist before the strict-verification fix landed.

    Returns the number of rows reset. The next enrich_species_images cycle will
    re-fetch with the new strict logic; verifiable matches get correct images,
    unverifiable ones stay NULL.
    """
    async with db.pool.acquire() as conn:
        result = await conn.execute(
            """UPDATE biodiversity_hotspots
                  SET image_url = NULL,
                      vernacular_name = NULL,
                      iucn_category = NULL
                WHERE image_url LIKE '%inaturalist-open-data%'"""
        )
        # asyncpg execute returns 'UPDATE N' string
        n = int(result.split()[-1]) if result.startswith("UPDATE") else 0
        log.info("reset %d biodiversity_hotspots rows for image re-verification", n)
        return n


async def backfill_iucn_categories(batch_size: int = 500) -> int:
    """Backfill IUCN categories for species that already have images but no IUCN data."""
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT DISTINCT scientific_name
               FROM biodiversity_hotspots
               WHERE scientific_name IS NOT NULL
                 AND image_url IS NOT NULL
                 AND (iucn_category IS NULL OR iucn_category = 'NE' OR iucn_category = 'DD')
               LIMIT $1""",
            batch_size,
        )
    names = [r["scientific_name"] for r in rows]
    if not names:
        log.info("iucn backfill: all species already have IUCN data")
        return 0

    log.info("iucn backfill: processing %d species", len(names))
    updated = 0

    async with httpx.AsyncClient(timeout=15) as client:
        for name in names:
            iucn_cat: str | None = None
            try:
                match = await client.get(GBIF_MATCH_URL, params={"name": name, "strict": "false"})
                if match.status_code == 200:
                    key = match.json().get("usageKey")
                    if key:
                        iucn_resp = await client.get(GBIF_IUCN_URL.format(key=key))
                        if iucn_resp.status_code == 200:
                            iucn_raw = iucn_resp.json().get("code")
                            if iucn_raw in ("CR", "EN", "VU", "NT", "LC", "DD"):
                                iucn_cat = iucn_raw
            except httpx.HTTPError as e:
                log.debug("GBIF lookup failed for %s: %s", name, e)

            if not iucn_cat:
                # Mark as DD (Data Deficient) so we don't re-check this species
                iucn_cat = "DD"

            async with db.pool.acquire() as conn:
                await conn.execute(
                    """UPDATE biodiversity_hotspots
                       SET iucn_category = $1,
                           is_endangered = $1 IN ('CR', 'EN', 'VU')
                       WHERE scientific_name = $2
                         AND (iucn_category IS NULL OR iucn_category = 'NE' OR iucn_category = 'DD')""",
                    iucn_cat,
                    name,
                )
            updated += 1
            await asyncio.sleep(0.2)

    log.info("iucn backfill: updated %d / %d species", updated, len(names))
    return updated


async def rebuild_hotspot_grid() -> int:
    """Rebuild the pre-computed hotspot_grid table for map rendering at low zoom.

    Delegates to ingestion/obis_sync.py. The in-process lock in that module
    prevents concurrent rebuilds within the same process; the 20h sync_log
    guard prevents cross-process double-runs.
    """
    from ingestion.obis_sync import rebuild_hotspot_grid as _rebuild
    result = await _rebuild(db.pool)
    _grid_cache.clear()
    return result


# ── API endpoints ───────────────────────────────────────────────────────────

@router.get("/v1/map/biodiversity/hotspots", dependencies=[Depends(get_api_key)])
async def get_biodiversity_hotspots(
    min_lon: float = Query(default=-180.0),
    min_lat: float = Query(default=-90.0),
    max_lon: float = Query(default=180.0),
    max_lat: float = Query(default=90.0),
    zoom: int = Query(default=2),
):
    # Below zoom 3 there is no point rendering individual species observations
    if zoom < 3:
        return Response(
            content='{"type":"FeatureCollection","features":[]}',
            media_type="application/json",
        )

    # Two-pass query: endangered records first (partial GIST index bh_cr_en_geom_gix),
    # then background records without sorting. Each sub-query terminates after its LIMIT
    # without sorting the full result set — fixes a 4+ s sequential sort of 700K rows.
    limit = 500 if zoom < 6 else (1500 if zoom < 8 else 3000)
    limit_cr_en = min(300, limit // 4)
    limit_rest  = limit - limit_cr_en

    feat_expr = """json_build_object(
                'type', 'Feature',
                'geometry', ST_AsGeoJSON(bh.geom)::json,
                'properties', json_build_object(
                    'obis_id', bh.obis_id,
                    'scientific_name', bh.scientific_name,
                    'vernacular_name', bh.vernacular_name,
                    'phylum', bh.phylum,
                    'class_name', bh.class_name,
                    'order_name', bh.order_name,
                    'family', bh.family,
                    'depth', bh.depth,
                    'description', bh.description,
                    'image_url', bh.image_url,
                    'is_endangered', bh.is_endangered,
                    'iucn_category', bh.iucn_category,
                    'aphia_id', tnm.matched_aphia_id,
                    'valid_name', wt.scientificname,
                    'worms_verified', COALESCE(tnm.verified, FALSE),
                    'worms_url', wt.url,
                    'worms_is_marine', wt.is_marine
                ))"""

    sql = f"""
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', coalesce(json_agg(feat ORDER BY is_cr_en DESC), '[]'::json)
        ) AS geojson
        FROM (
            (SELECT {feat_expr} AS feat, true AS is_cr_en
               FROM biodiversity_hotspots bh
               LEFT JOIN taxon_name_map tnm ON tnm.raw_name = regexp_replace(trim(bh.scientific_name), '\\s+', ' ', 'g')
               LEFT JOIN worms_taxa     wt  ON wt.aphia_id = tnm.matched_aphia_id
              WHERE bh.iucn_category IN ('CR','EN')
                AND bh.geom IS NOT NULL
                AND ST_Intersects(bh.geom, ST_MakeEnvelope($1, $2, $3, $4, 4326))
              LIMIT $5)
            UNION ALL
            (SELECT {feat_expr} AS feat, false AS is_cr_en
               FROM biodiversity_hotspots bh
               LEFT JOIN taxon_name_map tnm ON tnm.raw_name = regexp_replace(trim(bh.scientific_name), '\\s+', ' ', 'g')
               LEFT JOIN worms_taxa     wt  ON wt.aphia_id = tnm.matched_aphia_id
              WHERE bh.iucn_category NOT IN ('CR','EN')
                AND bh.geom IS NOT NULL
                AND ST_Intersects(bh.geom, ST_MakeEnvelope($1, $2, $3, $4, 4326))
              LIMIT $6)
        ) sub
    """
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(sql, min_lon, min_lat, max_lon, max_lat, limit_cr_en, limit_rest)
    return Response(content=row["geojson"], media_type="application/json")


@router.get("/v1/map/biodiversity/hotspots/grid", dependencies=[Depends(get_api_key)])
async def get_biodiversity_hotspots_grid(zoom: int = Query(default=5)):
    """Return pre-computed grid cells for biodiversity hotspot density at low zoom."""
    if zoom < 3 or zoom >= 8:
        return Response(
            content='{"type":"FeatureCollection","features":[]}',
            media_type="application/json",
        )

    resolution = "coarse" if zoom <= 5 else "fine"

    # Check in-memory cache
    if resolution in _grid_cache:
        return Response(content=_grid_cache[resolution], media_type="application/json")

    sql = """
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', coalesce(json_agg(feat), '[]'::json)
        ) AS geojson
        FROM (
            SELECT json_build_object(
                'type', 'Feature',
                'geometry', json_build_object(
                    'type', 'Point',
                    'coordinates', json_build_array(cell_lon, cell_lat)
                ),
                'properties', json_build_object(
                    'total_count', total_count,
                    'species_count', species_count,
                    'endangered_count', endangered_count,
                    'cr_en_count', cr_en_count,
                    'top_species', top_species
                )
            ) AS feat
            FROM hotspot_grid
            WHERE resolution = $1
        ) sub
    """
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(sql, resolution)

    geojson = row["geojson"] if row else '{"type":"FeatureCollection","features":[]}'
    _grid_cache[resolution] = geojson
    return Response(content=geojson, media_type="application/json")


@router.get("/v1/search/species", dependencies=[Depends(get_api_key)])
async def search_species(q: str = Query(..., min_length=2, max_length=80)):
    """Server-side species-name search over biodiversity_hotspots.

    The hotspots layer holds ~700K occurrences fetched per-viewport-tile, so the
    browser only ever has a viewport sample loaded — name search can't be done
    client-side. This returns up to 8 distinct species (one representative
    occurrence each) so any species is findable regardless of map state.
    """
    term = q.strip()
    if len(term) < 2:
        return []
    # Match on lower(scientific_name) so the pg_trgm GIN index
    # (idx_bh_scientific_name_trgm) handles the substring scan — without it this
    # is a 14 s parallel seq scan over 5M+ rows. Pattern is lowercased to match.
    pattern = f"%{term.lower()}%"
    # Return the full set of fields BiodiversityPanel renders so the client can
    # open a complete popup for the representative occurrence (not just fly).
    sql = """
        SELECT DISTINCT ON (lower(scientific_name))
               obis_id, scientific_name, vernacular_name, phylum, class_name,
               order_name, family, depth, description, image_url,
               is_endangered, iucn_category,
               ST_Y(geom) AS lat, ST_X(geom) AS lon
          FROM biodiversity_hotspots
         WHERE lower(scientific_name) LIKE $1
           AND geom IS NOT NULL
         ORDER BY lower(scientific_name)
         LIMIT 8
    """
    try:
        async with db.pool.acquire() as conn:
            rows = await conn.fetch(sql, pattern, timeout=3.0)
    except Exception as exc:  # asyncpg.TimeoutError or query error — degrade gracefully
        log.warning("search_species(%r) failed: %s", term, exc)
        return []

    def _clean(v):
        # Some occurrences store depth as NaN; bare NaN is invalid JSON and
        # breaks the client's response.json(). Coerce non-finite floats to None.
        return None if isinstance(v, float) and not math.isfinite(v) else v

    return [
        {
            "obis_id": r["obis_id"],
            "scientific_name": r["scientific_name"],
            "vernacular_name": r["vernacular_name"],
            "phylum": r["phylum"],
            "class_name": r["class_name"],
            "order_name": r["order_name"],
            "family": r["family"],
            "depth": _clean(r["depth"]),
            "description": r["description"],
            "image_url": r["image_url"],
            "is_endangered": r["is_endangered"],
            "iucn_category": r["iucn_category"],
            "lat": _clean(r["lat"]),
            "lon": _clean(r["lon"]),
        }
        for r in rows
    ]


@router.get("/v1/map/chess", dependencies=[Depends(get_api_key)])
async def get_chess():
    """Return ChEssBase chemosynthetic sites (non-vent) as GeoJSON, grouped by locality."""
    global _chess_cache
    if _chess_cache:
        return Response(content=_chess_cache, media_type="application/json")

    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                locality,
                habitat_type,
                AVG(lat)      AS lat,
                AVG(lon)      AS lon,
                AVG(depth_m)  AS depth_m,
                COUNT(DISTINCT species)::INTEGER AS species_count,
                json_agg(DISTINCT phylum) FILTER (WHERE phylum IS NOT NULL AND phylum != '') AS phyla,
                json_agg(json_build_object(
                    'species',     species,
                    'phylum',      phylum,
                    'depth_m',     depth_m,
                    'institution', institution_code
                )) AS species_list
            FROM chess_occurrences
            WHERE habitat_type != 'vent' AND locality IS NOT NULL AND locality != ''
            GROUP BY locality, habitat_type
            ORDER BY locality
        """)

    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(r["lon"]), float(r["lat"])]},
            "properties": {
                "locality":      r["locality"],
                "habitat_type":  r["habitat_type"],
                "lat":           float(r["lat"]),
                "lon":           float(r["lon"]),
                "depth_m":       float(r["depth_m"]) if r["depth_m"] is not None else None,
                "species_count": r["species_count"],
                "phyla":        (json.loads(r["phyla"]) if isinstance(r["phyla"], str) else r["phyla"]) if r["phyla"] is not None else [],
                "species_list": (json.loads(r["species_list"]) if isinstance(r["species_list"], str) else r["species_list"]) if r["species_list"] is not None else [],
            },
        }
        for r in rows
    ]
    result = json.dumps({"type": "FeatureCollection", "features": features})
    _chess_cache = result
    return Response(content=result, media_type="application/json")


@router.get("/v1/citations/chess", dependencies=[Depends(get_api_key)])
async def get_chess_citation():
    """Recommended GBIF/ChEssBase citation with the date of last sync as 'accessed on'.
    DOI is the static dataset DOI for ChEssBase v1.0 — only the access date changes."""
    async with db.pool.acquire() as conn:
        accessed_at = await conn.fetchval(
            "SELECT last_synced_at FROM sync_log WHERE source = 'chess'"
        )
    accessed_iso = accessed_at.date().isoformat() if accessed_at else None
    return {
        "doi":          "10.15468/6v6ug8",
        "doi_url":      "https://doi.org/10.15468/6v6ug8",
        "accessed_on":  accessed_iso,
        "citation":     (
            f"Ramirez-Llodra E (2025). ChEssBase. Version 1.0. Flanders Marine Institute. "
            f"Occurrence dataset https://doi.org/10.15468/6v6ug8 accessed via GBIF.org"
            + (f" on {accessed_iso}." if accessed_iso else ".")
        ),
    }


@router.post("/admin/enrich-species-images", dependencies=[Depends(require_admin_token)])
async def admin_enrich_species_images(batch_size: int = Query(default=500, ge=1, le=5000)):
    """Trigger a species image enrichment run on-demand.

    Processes up to batch_size species that currently lack an image_url.
    Safe to call multiple times — only updates rows where image_url IS NULL.
    """
    enriched = await enrich_species_images(batch_size=batch_size)
    async with db.pool.acquire() as conn:
        total_with_image = await conn.fetchval(
            "SELECT COUNT(DISTINCT scientific_name) FROM biodiversity_hotspots WHERE image_url IS NOT NULL"
        )
        total_species = await conn.fetchval(
            "SELECT COUNT(DISTINCT scientific_name) FROM biodiversity_hotspots"
        )
    return {
        "enriched_this_run": enriched,
        "species_with_images": total_with_image,
        "total_species": total_species,
    }


@router.post("/v1/admin/rebuild-hotspot-grid", dependencies=[Depends(require_admin_token)])
async def api_rebuild_hotspot_grid():
    """Manually trigger hotspot grid rebuild."""
    asyncio.create_task(rebuild_hotspot_grid())
    return {"status": "started", "message": "Hotspot grid rebuild started in background"}


@router.post("/v1/admin/backfill-iucn", dependencies=[Depends(require_admin_token)])
async def api_backfill_iucn(batch_size: int = Query(default=500, ge=1, le=5000)):
    """Manually trigger IUCN backfill for species missing conservation status."""
    asyncio.create_task(backfill_iucn_categories(batch_size=batch_size))
    return {"status": "started", "message": f"IUCN backfill started for up to {batch_size} species"}
