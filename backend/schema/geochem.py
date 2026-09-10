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
    """geotraces_stations, geotraces_samples, geotraces_param_units,
    geotraces_params, geotraces_values.

    geotraces_params / geotraces_values (2026-09-08) are ADDITIVE: the full
    1178-column IDP2025 CSV carries 386 measured parameters, and until now
    build_samples() kept only the 5 legacy metals (mn/fe/co/ni/cu). These two
    tables hold everything else in long format. They do NOT replace, rename
    or stop-populating any legacy geotraces_samples/geotraces_stations column
    — see rules/subsystems (geotraces) and the 2026-09-08 audit doc.

    ⚠️ geotraces_values.sample_id is BIGINT and is a FK-BY-CONVENTION to
    geotraces_samples.csv_row (the row's ordinal position in the IDP2025 CSV,
    assigned in geotraces_ingest.stream_samples) — NOT to
    geotraces_samples.sample_id, which stays BIGSERIAL/bigint (the legacy
    internal PK), and NOT to geotraces_sample_id (see that column's own
    comment below). csv_row is used because it is the only key in this file
    that is actually unique — see DEFECT 1, 2026-09-08 audit:
    "GEOTRACES Sample ID" is empty on 41% of rows and only 29,944 of the
    76,056 non-empty values are distinct (46,112 duplicates); every other
    natural key tried (cruise+station+depth, BODC event+bottle, ...) also
    collides. Any code joining geotraces_values must join on csv_row.
    """

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

        -- ⛔ What the SOURCE gave, recorded at parse time by which format
        -- matched — not derived from the value. 59,295 of 218,271 samples sit
        -- at exactly 00:00 and 8,822 of those on the first of a month;
        -- midnight is a real time and the first is a real day, so the value
        -- alone cannot tell a precise cast from a padded date.
        ALTER TABLE memento_samples ADD COLUMN IF NOT EXISTS time_precision TEXT;
        ALTER TABLE memento_casts   ADD COLUMN IF NOT EXISTS time_precision TEXT;
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
        CREATE TABLE IF NOT EXISTS geotraces_params (
            param_code TEXT PRIMARY KEY,
            label TEXT,
            unit TEXT,
            family TEXT,
            n_values INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS geotraces_values (
            sample_id BIGINT NOT NULL,
            param_code TEXT NOT NULL,
            value DOUBLE PRECISION NOT NULL,
            stddev DOUBLE PRECISION,
            qc_flag SMALLINT,
            PRIMARY KEY (sample_id, param_code)
        );
        CREATE INDEX IF NOT EXISTS geotraces_stations_geom_gix ON geotraces_stations USING GIST (geom);
        CREATE INDEX IF NOT EXISTS geotraces_samples_geom_gix ON geotraces_samples USING GIST (geom);
        CREATE INDEX IF NOT EXISTS geotraces_samples_station_idx ON geotraces_samples (station_id);
        CREATE INDEX IF NOT EXISTS geotraces_stations_decade_idx ON geotraces_stations (decade);
        CREATE INDEX IF NOT EXISTS geotraces_values_param_idx ON geotraces_values (param_code);

        -- Migration for tables created before 2026-09-08 with the broken TEXT
        -- keying (DEFECT 1): geotraces_values is always fully TRUNCATEd and
        -- reloaded by load()/load_values_from_csv() on every sync, so there is
        -- no data to preserve here — just fix the column type. Guarded so it
        -- only runs once, against a pre-existing wrong-typed column.
        DO $mig$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'geotraces_values' AND column_name = 'sample_id'
                  AND data_type <> 'bigint'
            ) THEN
                TRUNCATE geotraces_values;
                ALTER TABLE geotraces_values ALTER COLUMN sample_id TYPE BIGINT USING NULL;
            END IF;
        END $mig$;

        ALTER TABLE geotraces_samples ADD COLUMN IF NOT EXISTS geotraces_sample_id TEXT;
        -- ⚠️ NOT unique, NOT a key — 41% of rows (53,092 / 129,148) have this
        -- column empty, and of the 76,056 that do, only 29,944 are distinct
        -- (46,112 duplicates). Measured against the real IDP2025 CSV,
        -- 2026-09-08 audit. Informational source metadata only; join
        -- geotraces_values on geotraces_samples.csv_row instead.
        ALTER TABLE geotraces_samples ADD COLUMN IF NOT EXISTS csv_row BIGINT;
        ALTER TABLE geotraces_samples ADD COLUMN IF NOT EXISTS sampling_device TEXT;
        ALTER TABLE geotraces_samples ADD COLUMN IF NOT EXISTS cast_identifier TEXT;
        ALTER TABLE geotraces_samples ADD COLUMN IF NOT EXISTS bodc_event_number INTEGER;
        ALTER TABLE geotraces_samples ADD COLUMN IF NOT EXISTS bodc_bottle_number INTEGER;
        ALTER TABLE geotraces_samples ADD COLUMN IF NOT EXISTS rosette_bottle_number INTEGER;
        ALTER TABLE geotraces_samples ADD COLUMN IF NOT EXISTS bottle_flag TEXT;
        ALTER TABLE geotraces_samples ADD COLUMN IF NOT EXISTS ship_name TEXT;
        ALTER TABLE geotraces_samples ADD COLUMN IF NOT EXISTS cruise_period TEXT;
        ALTER TABLE geotraces_samples ADD COLUMN IF NOT EXISTS chief_scientist TEXT;
        ALTER TABLE geotraces_samples ADD COLUMN IF NOT EXISTS geotraces_scientist TEXT;
        ALTER TABLE geotraces_samples ADD COLUMN IF NOT EXISTS operators_cruise_name TEXT;
        ALTER TABLE geotraces_samples ADD COLUMN IF NOT EXISTS cruise_information_link TEXT;
        ALTER TABLE geotraces_samples ADD COLUMN IF NOT EXISTS bodc_cruise_number INTEGER;
        ALTER TABLE geotraces_samples ADD COLUMN IF NOT EXISTS ncbi_metagenome_biosample TEXT;
        ALTER TABLE geotraces_samples ADD COLUMN IF NOT EXISTS ncbi_single_cell_genome_bioproject TEXT;
        ALTER TABLE geotraces_samples ADD COLUMN IF NOT EXISTS ncbi_rrna_biosample TEXT;
        ALTER TABLE geotraces_samples ADD COLUMN IF NOT EXISTS embl_ebi_metagenome_analysis TEXT;

        CREATE UNIQUE INDEX IF NOT EXISTS geotraces_samples_csv_row_uidx ON geotraces_samples (csv_row);
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


