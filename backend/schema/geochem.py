# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Schema DDL — geochem domain. Extracted verbatim from the former backend/schema.py.
"""
from __future__ import annotations

async def ensure_memento(conn) -> None:
    """memento_samples, memento_casts."""

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS memento_samples (
            id          BIGSERIAL PRIMARY KEY,
            cast_id     TEXT NOT NULL,
            set_name    TEXT,
            station     TEXT,
            sample_time TIMESTAMPTZ,
            lat         DOUBLE PRECISION NOT NULL,
            lon         DOUBLE PRECISION NOT NULL,
            depth_m     DOUBLE PRECISION,
            label       TEXT,
            decade      INTEGER,
            ch4         DOUBLE PRECISION,
            n2o         DOUBLE PRECISION,
            n2o_perc    DOUBLE PRECISION,
            o2          DOUBLE PRECISION,
            temp        DOUBLE PRECISION,
            sal         DOUBLE PRECISION,
            params      JSONB,
            geom        geometry(Point, 4326)
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS memento_casts (
            cast_id     TEXT PRIMARY KEY,
            set_name    TEXT,
            station     TEXT,
            sample_time TIMESTAMPTZ,
            lat         DOUBLE PRECISION NOT NULL,
            lon         DOUBLE PRECISION NOT NULL,
            decade      INTEGER,
            n_samples   INTEGER,
            min_depth_m DOUBLE PRECISION,
            max_depth_m DOUBLE PRECISION,
            has_ch4     BOOLEAN,
            has_n2o     BOOLEAN,
            ch4_surf    DOUBLE PRECISION,
            n2o_surf    DOUBLE PRECISION,
            geom        geometry(Point, 4326)
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS memento_samples_cast_idx ON memento_samples (cast_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS memento_samples_geom_gix ON memento_samples USING GIST (geom)")
    await conn.execute("CREATE INDEX IF NOT EXISTS memento_casts_geom_gix ON memento_casts USING GIST (geom)")
    await conn.execute("CREATE INDEX IF NOT EXISTS memento_casts_decade_idx ON memento_casts (decade)")
    # Derived per-gas flags (NOT upstream values). MEMENTO publishes dissolved and
    # atmospheric gas under one column name; see _recompute_memento_atmospheric().
    await conn.execute("""
        ALTER TABLE memento_samples
          ADD COLUMN IF NOT EXISTS ch4_is_atmospheric BOOLEAN,
          ADD COLUMN IF NOT EXISTS n2o_is_atmospheric BOOLEAN
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS memento_samples_atm_idx "
        "ON memento_samples (ch4_is_atmospheric, n2o_is_atmospheric)"
    )
    await conn.execute("ALTER TABLE memento_samples OWNER TO abyssal_user")
    await conn.execute("ALTER TABLE memento_casts OWNER TO abyssal_user")


async def ensure_geotraces(conn) -> None:
    """geotraces_stations, geotraces_samples, geotraces_param_units."""

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS geotraces_stations (
            station_id TEXT PRIMARY KEY,
            cruise TEXT, station TEXT,
            sample_time TIMESTAMPTZ,
            lat DOUBLE PRECISION NOT NULL,
            lon DOUBLE PRECISION NOT NULL,
            decade INTEGER,
            n_samples INTEGER,
            min_depth_m DOUBLE PRECISION,
            max_depth_m DOUBLE PRECISION,
            bottom_depth_m DOUBLE PRECISION,
            has_mn BOOLEAN, has_fe BOOLEAN, has_co BOOLEAN, has_ni BOOLEAN, has_cu BOOLEAN,
            mn_max DOUBLE PRECISION, fe_max DOUBLE PRECISION, co_max DOUBLE PRECISION,
            ni_max DOUBLE PRECISION, cu_max DOUBLE PRECISION,
            geom geometry(Point, 4326)
        );
        CREATE TABLE IF NOT EXISTS geotraces_samples (
            sample_id BIGSERIAL PRIMARY KEY,
            station_id TEXT NOT NULL,
            cruise TEXT, station TEXT,
            sample_time TIMESTAMPTZ,
            lat DOUBLE PRECISION NOT NULL,
            lon DOUBLE PRECISION NOT NULL,
            depth_m DOUBLE PRECISION,
            bottom_depth_m DOUBLE PRECISION,
            mn_d DOUBLE PRECISION, fe_d DOUBLE PRECISION, co_d DOUBLE PRECISION,
            ni_d DOUBLE PRECISION, cu_d DOUBLE PRECISION,
            mn_d_qc SMALLINT, fe_d_qc SMALLINT, co_d_qc SMALLINT,
            ni_d_qc SMALLINT, cu_d_qc SMALLINT,
            params JSONB,
            geom geometry(Point, 4326)
        );
        CREATE TABLE IF NOT EXISTS geotraces_param_units (
            param TEXT PRIMARY KEY,
            unit TEXT
        );
        CREATE INDEX IF NOT EXISTS geotraces_stations_geom_gix ON geotraces_stations USING GIST (geom);
        CREATE INDEX IF NOT EXISTS geotraces_samples_geom_gix ON geotraces_samples USING GIST (geom);
        CREATE INDEX IF NOT EXISTS geotraces_samples_station_idx ON geotraces_samples (station_id);
        CREATE INDEX IF NOT EXISTS geotraces_stations_decade_idx ON geotraces_stations (decade);
    """)


async def ensure_seaflea(conn) -> None:
    """seaflea_seeps."""

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS seaflea_seeps (
            id            SERIAL PRIMARY KEY,
            ext_id        TEXT UNIQUE,
            lat           DOUBLE PRECISION,
            lon           DOUBLE PRECISION,
            depth_m       DOUBLE PRECISION,
            obs_year      INTEGER,
            loc_uncert_m  DOUBLE PRECISION,
            feature_types TEXT[],
            primary_type  TEXT,
            type_raw      JSONB,
            source_ref    TEXT,
            source_url    TEXT,
            pockmark_depth_m  DOUBLE PRECISION,
            pockmark_radius_m DOUBLE PRECISION,
            geom          GEOMETRY(Point, 4326),
            synced_at     TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    # idempotent column adds (table pre-exists on dev/prod — CREATE alone won't add them)
    await conn.execute("ALTER TABLE seaflea_seeps ADD COLUMN IF NOT EXISTS pockmark_depth_m  DOUBLE PRECISION")
    await conn.execute("ALTER TABLE seaflea_seeps ADD COLUMN IF NOT EXISTS pockmark_radius_m DOUBLE PRECISION")
    await conn.execute("CREATE INDEX IF NOT EXISTS seaflea_seeps_geom_idx ON seaflea_seeps USING GIST(geom)")
    await conn.execute("ALTER TABLE seaflea_seeps OWNER TO abyssal_user")


