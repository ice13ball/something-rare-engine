# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Schema DDL — arctic domain. Extracted verbatim from the former backend/schema.py.
"""
from __future__ import annotations

async def ensure_mosaic(conn) -> None:
    """mosaic_cores, mosaic_samples."""

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS mosaic_cores (
            core_id INTEGER PRIMARY KEY,
            core_name TEXT,
            latitude DOUBLE PRECISION NOT NULL,
            longitude DOUBLE PRECISION NOT NULL,
            water_depth_m DOUBLE PRECISION,
            sampling_year INTEGER,
            decade INTEGER,
            sampling_date   DATE,
            sampling_month  SMALLINT,
            sampling_day    SMALLINT,
            campaign_name   TEXT,
            campaign_start  DATE,
            campaign_end    DATE,
            core_comment    TEXT,
            date_precision  TEXT,
            sampling_method TEXT,
            research_vessel TEXT,
            seas TEXT,
            eez TEXT,
            longhurst TEXT,
            has_toc BOOLEAN, has_tn BOOLEAN, has_d13c BOOLEAN, has_d14c BOOLEAN,
            toc_surf DOUBLE PRECISION, tn_surf DOUBLE PRECISION,
            d13c_surf DOUBLE PRECISION, d14c_surf DOUBLE PRECISION,
            geom geometry(Point, 4326),
            synced_at TIMESTAMPTZ DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS mosaic_samples (
            sample_id INTEGER PRIMARY KEY,
            core_id INTEGER NOT NULL,
            depth_upper_cm DOUBLE PRECISION,
            depth_bottom_cm DOUBLE PRECISION,
            depth_avg_cm DOUBLE PRECISION,
            material_analyzed TEXT,
            replicate INTEGER,
            toc DOUBLE PRECISION, tn DOUBLE PRECISION,
            d13c DOUBLE PRECISION, d14c DOUBLE PRECISION, fm14c DOUBLE PRECISION,
            provenance JSONB,
            geom geometry(Point, 4326)
        );
        CREATE INDEX IF NOT EXISTS mosaic_cores_geom_gix ON mosaic_cores USING GIST (geom);
        CREATE INDEX IF NOT EXISTS mosaic_cores_decade_idx ON mosaic_cores (decade);
        CREATE INDEX IF NOT EXISTS mosaic_samples_core_idx ON mosaic_samples (core_id);
        ALTER TABLE mosaic_cores OWNER TO abyssal_user;
        ALTER TABLE mosaic_samples OWNER TO abyssal_user;
    """)
    await conn.execute("ALTER TABLE mosaic_cores ADD COLUMN IF NOT EXISTS sampling_date DATE")
    await conn.execute("ALTER TABLE mosaic_cores ADD COLUMN IF NOT EXISTS sampling_month SMALLINT")
    await conn.execute("ALTER TABLE mosaic_cores ADD COLUMN IF NOT EXISTS sampling_day SMALLINT")
    await conn.execute("ALTER TABLE mosaic_cores ADD COLUMN IF NOT EXISTS campaign_name TEXT")
    await conn.execute("ALTER TABLE mosaic_cores ADD COLUMN IF NOT EXISTS campaign_start DATE")
    await conn.execute("ALTER TABLE mosaic_cores ADD COLUMN IF NOT EXISTS campaign_end DATE")
    await conn.execute("ALTER TABLE mosaic_cores ADD COLUMN IF NOT EXISTS core_comment TEXT")
    await conn.execute("ALTER TABLE mosaic_cores ADD COLUMN IF NOT EXISTS date_precision TEXT")


async def ensure_cascade(conn) -> None:
    """cascade_stations."""

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS cascade_stations (
            id INTEGER PRIMARY KEY,
            station TEXT,
            lat DOUBLE PRECISION,
            lon DOUBLE PRECISION,
            water_depth_m DOUBLE PRECISION,
            expedition TEXT,
            year INTEGER,
            decade INTEGER,
            oc_pct DOUBLE PRECISION,
            tn_pct DOUBLE PRECISION,
            oc_tn DOUBLE PRECISION,
            d13c DOUBLE PRECISION,
            d14c DOUBLE PRECISION,
            hmw_alkanes DOUBLE PRECISION,
            hmw_acids DOUBLE PRECISION,
            lignin DOUBLE PRECISION,
            params JSONB,
            geom geometry(Point, 4326)
        );
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS cascade_stations_geom_gix ON cascade_stations USING GIST(geom);")
    await conn.execute("CREATE INDEX IF NOT EXISTS cascade_stations_decade_idx ON cascade_stations(decade);")
    await conn.execute("ALTER TABLE cascade_stations OWNER TO abyssal_user;")


async def ensure_sios(conn) -> None:
    """sios_datasets."""

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS sios_datasets (
            id             SERIAL PRIMARY KEY,
            metadata_id    TEXT UNIQUE NOT NULL,
            title          TEXT,
            abstract       TEXT,
            is_core_data   BOOLEAN NOT NULL DEFAULT FALSE,
            collections    TEXT[],
            activity_type  TEXT,
            iso_topic      TEXT,
            keywords       TEXT[],
            platform_short TEXT,
            platform_long  TEXT,
            platform_url   TEXT,
            institution    TEXT,
            pi_name        TEXT,
            time_start     TIMESTAMPTZ,
            time_end       TIMESTAMPTZ,
            license        TEXT,
            license_url    TEXT,
            url_http       TEXT,
            url_opendap    TEXT,
            url_wms        TEXT,
            url_landing    TEXT,
            lat            DOUBLE PRECISION,
            lon            DOUBLE PRECISION,
            geom           geometry(Point, 4326),
            synced_at      TIMESTAMPTZ DEFAULT now(),
            series         JSONB,
            series_var     TEXT,
            series_units   TEXT,
            series_long_name TEXT
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS sios_datasets_geom_gix ON sios_datasets USING GIST (geom)")
    await conn.execute("CREATE INDEX IF NOT EXISTS sios_datasets_core_idx ON sios_datasets (is_core_data)")
    await conn.execute("ALTER TABLE sios_datasets OWNER TO abyssal_user")
    await conn.execute("ALTER TABLE sios_datasets ADD COLUMN IF NOT EXISTS series JSONB")
    await conn.execute("ALTER TABLE sios_datasets ADD COLUMN IF NOT EXISTS series_var TEXT")
    await conn.execute("ALTER TABLE sios_datasets ADD COLUMN IF NOT EXISTS series_units TEXT")
    await conn.execute("ALTER TABLE sios_datasets ADD COLUMN IF NOT EXISTS series_long_name TEXT")


async def ensure_arctic_catchments(conn) -> None:
    """arctic_catchments."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS arctic_catchments (
            gid INTEGER PRIMARY KEY,
            name TEXT,
            stream_order INTEGER,
            continent TEXT,
            area_km2 DOUBLE PRECISION,
            center_lat DOUBLE PRECISION,
            center_lon DOUBLE PRECISION,
            ocs_mean DOUBLE PRECISION,
            oc_tot DOUBLE PRECISION,
            runoff_mean DOUBLE PRECISION,
            pf_frac DOUBLE PRECISION,
            t_2m_mean DOUBLE PRECISION,
            params JSONB,
            geom geometry(MultiPolygon, 4326),
            geom_3857 geometry GENERATED ALWAYS AS (ST_Transform(geom, 3857)) STORED
        );
        CREATE INDEX IF NOT EXISTS arctic_catchments_geom_gix ON arctic_catchments USING GIST (geom);
        CREATE INDEX IF NOT EXISTS arctic_catchments_geom3857_gix ON arctic_catchments USING GIST (geom_3857);
    """)
    await conn.execute("ALTER TABLE arctic_catchments OWNER TO abyssal_user")


