# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""claim_species_cache rebuild — v2 (data-pipeline only, not a report endpoint).

Lives outside backend/routers/reports.py so the v1 report stack stays a
frozen, untouched restore path. Both the weekly chain and the admin
'species-cache' Force Sync button call refresh_species_cache() from here.

Fixes the long-standing UniqueViolationError that left
claim_species_cache permanently empty: v1's INSERT grouped by
(isa_id, scientific_name, phylum), but the same species can appear
under multiple phylum classifications in OBIS, producing duplicate
(isa_id, scientific_name) rows that collide with the table's PK and
roll back the whole transaction. This rebuild groups on the actual PK
columns and aggregates phylum with max().
"""
from __future__ import annotations

import logging

import db

log = logging.getLogger(__name__)

REBUILD_TIMEOUT_MS = 600_000  # 10 min — matches v1 rebuild budget


async def refresh_species_cache() -> int:
    """Atomically clear + repopulate claim_species_cache from
    biodiversity_hotspots × mining_contracts. Returns the inserted row count.

    Idempotent. Safe to run from the admin dashboard or the weekly chain.
    """
    if db.pool is None:
        raise RuntimeError("db.pool not initialised")

    async with db.pool.acquire() as conn:
        # One transaction so readers never see a half-built table. Since the
        # 2026-07-26 change that moved SEO species counts onto this cache instead
        # of a live spatial join, the public (bot-facing) SEO pages read
        # claim_species_cache directly, so
        # the old TRUNCATE-then-INSERT — each autocommitting on its own — exposed
        # an EMPTY table to crawlers for the whole ~10-min rebuild ("0 species").
        # DELETE (not TRUNCATE) inside the transaction: MVCC keeps concurrent
        # readers on the OLD rows until COMMIT, then flips atomically to the new
        # set. TRUNCATE would instead take ACCESS EXCLUSIVE and block those
        # readers for the entire rebuild. SET LOCAL scopes to this transaction
        # and auto-resets on commit, so no session-level leak / no finally reset.
        async with conn.transaction():
            await conn.execute(f"SET LOCAL statement_timeout = {REBUILD_TIMEOUT_MS}")
            await conn.execute("SET LOCAL max_parallel_workers_per_gather = 0")
            await conn.execute("DELETE FROM claim_species_cache")
            await conn.execute("""
                INSERT INTO claim_species_cache
                    (isa_id, scientific_name, phylum, vernacular_name,
                     image_url, records, is_endangered, iucn_category)
                SELECT mc.isa_id,
                       bh.scientific_name,
                       max(bh.phylum),
                       max(bh.vernacular_name),
                       max(bh.image_url),
                       count(*)::int,
                       bool_or(COALESCE(bh.iucn_category, 'NE') IN ('CR','EN','VU')),
                       COALESCE(max(CASE WHEN bh.iucn_category IN ('CR','EN','VU','NT','LC','DD')
                                         THEN bh.iucn_category END), 'NE')
                FROM mining_contracts mc
                JOIN biodiversity_hotspots bh
                  -- Claim-focused 10 km radius. The degree clause (≈13 km)
                  -- is an index-friendly pre-filter on the bh.geom GIST index;
                  -- the geography clause refines it to an exact 10 km at any
                  -- latitude. (Was 0.5° ≈ 55 km — far too wide for "near claim".)
                  ON ST_DWithin(bh.geom, mc.geom, 0.12)
                 AND ST_DWithin(bh.geom::geography, mc.geom::geography, 10000)
                GROUP BY mc.isa_id, bh.scientific_name
            """)
            cnt = await conn.fetchval("SELECT count(*) FROM claim_species_cache")

    log.info("species_cache: refreshed — %d rows", cnt or 0)
    return int(cnt or 0)
