# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Schema DDL — seafloor domain. Extracted verbatim from the former backend/schema.py.
"""
from __future__ import annotations

async def ensure_bathymetry_cache(conn) -> None:
    """bathymetry_cache."""

    # Persistent cache for /v1/bathymetry/lookup so cold lookups against
    # Open-Topo-Data (300-1500 ms) only happen ONCE per (lat,lon) tile
    # across all users + survive backend restarts. Keys are lat/lon
    # rounded to 0.01° (~1 km), matching the in-memory cache precision.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bathymetry_cache (
            lat_round  NUMERIC(4,2) NOT NULL,
            lon_round  NUMERIC(5,2) NOT NULL,
            depth_m    DOUBLE PRECISION,
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (lat_round, lon_round)
        )
    """)
    # Verified against production 2026-09: 1,976 negative and 184 positive
    # values. This is raw GEBCO elevation, not a depth despite the column
    # name - a positive value is a real land height, not a defect.
    await conn.execute("""
        COMMENT ON COLUMN bathymetry_cache.depth_m IS
          'GEBCO elevation in metres: NEGATIVE below sea level. Despite the column name '
          'this is not a depth - 184 of 2,160 production rows are positive land heights.'
    """)


async def ensure_bathymetry_stats(conn) -> None:
    """bathymetry_stats, gmrt_area_cache."""

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bathymetry_stats (
            feature_type      TEXT NOT NULL,
            feature_id        TEXT NOT NULL,
            gebco_version     TEXT NOT NULL,
            n_cells           INT,
            pct_measured      DOUBLE PRECISION,
            pct_indirect      DOUBLE PRECISION,
            pct_unknown       DOUBLE PRECISION,
            pct_multibeam     DOUBLE PRECISION,
            mapped_confidence TEXT,
            depth_min_m       DOUBLE PRECISION,
            depth_median_m    DOUBLE PRECISION,
            depth_max_m       DOUBLE PRECISION,
            slope_median_deg  DOUBLE PRECISION,
            ruggedness        DOUBLE PRECISION,
            computed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (feature_type, feature_id)
        );
        COMMENT ON COLUMN bathymetry_stats.depth_min_m IS
          'Metres below sea level, positive down. Verified from services/bathymetry_stats.py '
          'summarize(): land cells are dropped via the TID mask, then depth = -elevation, '
          'filtered to >0 (ocean only).';
        COMMENT ON COLUMN bathymetry_stats.depth_median_m IS
          'Metres below sea level, positive down. Same computation as depth_min_m.';
        COMMENT ON COLUMN bathymetry_stats.depth_max_m IS
          'Metres below sea level, positive down. Same computation as depth_min_m.';
        CREATE TABLE IF NOT EXISTS gmrt_area_cache (
            area_hash       TEXT PRIMARY KEY,
            bbox            DOUBLE PRECISION[],
            meters_per_node DOUBLE PRECISION,
            nodes           BIGINT,
            gmrt_version    TEXT,
            raw             JSONB,
            fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    await conn.execute("ALTER TABLE bathymetry_stats OWNER TO abyssal_user")
    await conn.execute("ALTER TABLE gmrt_area_cache OWNER TO abyssal_user")


