# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Schema DDL — core domain. Extracted verbatim from the former backend/schema.py.
"""
from __future__ import annotations

async def ensure_core(conn) -> None:
    """isa_contract_lookup, sync_log, paused_syncs, admin_audit, reserved_areas, isa_apeis, argo_profiles, hydrothermal_vents, relinquished_areas, maritime_boundaries, protected_marine_sites."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS isa_contract_lookup (
            contract_id     TEXT PRIMARY KEY,
            contractor_name TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sync_log (
            source          TEXT PRIMARY KEY,
            last_synced_at  TIMESTAMPTZ,
            records_added   INTEGER NOT NULL DEFAULT 0,
            total_records   INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS paused_syncs (
            action TEXT PRIMARY KEY,
            paused_at TIMESTAMPTZ DEFAULT NOW(),
            reason TEXT
        );

        CREATE TABLE IF NOT EXISTS admin_audit (
            id      BIGSERIAL PRIMARY KEY,
            ts      TIMESTAMPTZ NOT NULL DEFAULT now(),
            actor   TEXT NOT NULL,
            action  TEXT NOT NULL,
            target  TEXT,
            detail  JSONB
        );
        CREATE INDEX IF NOT EXISTS admin_audit_ts_idx ON admin_audit (ts DESC);

        CREATE TABLE IF NOT EXISTS reserved_areas (
            arcgis_id   INTEGER PRIMARY KEY,
            contract_id TEXT,
            area_type   TEXT,
            area_km2    DOUBLE PRECISION,
            status      TEXT,
            remarks     TEXT,
            geom        GEOMETRY(GEOMETRY, 4326),
            synced_at   TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS reserved_areas_geom_idx
            ON reserved_areas USING GIST(geom);

        CREATE TABLE IF NOT EXISTS isa_apeis (
            arcgis_id INTEGER PRIMARY KEY,
            area_km2  DOUBLE PRECISION,
            status    TEXT,
            remarks   TEXT,

            geom      GEOMETRY(GEOMETRY, 4326),
            synced_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS isa_apeis_geom_idx
            ON isa_apeis USING GIST(geom);

        CREATE TABLE IF NOT EXISTS argo_profiles (
            profile_id       TEXT PRIMARY KEY,
            platform_id      TEXT,
            profile_date     TIMESTAMPTZ NOT NULL,
            max_depth_m      DOUBLE PRECISION,
            surface_temp_c   DOUBLE PRECISION,
            surface_salinity DOUBLE PRECISION,
            deep_temp_c      DOUBLE PRECISION,
            deep_salinity    DOUBLE PRECISION,
            deep_pressure_m  DOUBLE PRECISION,
            oxygen_umol_kg   DOUBLE PRECISION,
            ph               DOUBLE PRECISION,
            temp_qc          SMALLINT,
            sal_qc           SMALLINT,
            oxygen_qc        SMALLINT,
            ph_qc            SMALLINT,
            near_mining           BOOLEAN NOT NULL DEFAULT FALSE,
            mining_zone           TEXT,
            mining_dist_km        FLOAT,
            nearest_contract_lon  FLOAT,
            nearest_contract_lat  FLOAT,
            mining_zones          JSONB DEFAULT '[]'::jsonb,
            geom                  GEOMETRY(Point, 4326) NOT NULL,

            synced_at        TIMESTAMPTZ DEFAULT NOW()
        );
        COMMENT ON COLUMN argo_profiles.max_depth_m IS
          'Max of the Argo profile''s PRES (pressure, dbar) readings, taken as metres. '
          'The Argo GDAC format documents PRES as sea pressure, conventionally positive '
          'and increasing with depth, but we have not confirmed this column''s sign in '
          'production - treat "positive down" here as unverified, not a claim.';
        CREATE INDEX IF NOT EXISTS argo_profiles_geom_idx
            ON argo_profiles USING GIST(geom);
        CREATE INDEX IF NOT EXISTS argo_profiles_date_idx
            ON argo_profiles (profile_date);
        ALTER TABLE argo_profiles ADD COLUMN IF NOT EXISTS temp_qc   SMALLINT;
        ALTER TABLE argo_profiles ADD COLUMN IF NOT EXISTS sal_qc    SMALLINT;
        ALTER TABLE argo_profiles ADD COLUMN IF NOT EXISTS oxygen_qc SMALLINT;
        ALTER TABLE argo_profiles ADD COLUMN IF NOT EXISTS ph_qc     SMALLINT;
        ALTER TABLE argo_profiles ADD COLUMN IF NOT EXISTS woa_surface_temp_c     DOUBLE PRECISION;
        ALTER TABLE argo_profiles ADD COLUMN IF NOT EXISTS woa_surface_sal        DOUBLE PRECISION;
        ALTER TABLE argo_profiles ADD COLUMN IF NOT EXISTS woa_deep_temp_c        DOUBLE PRECISION;
        ALTER TABLE argo_profiles ADD COLUMN IF NOT EXISTS woa_deep_sal           DOUBLE PRECISION;
        ALTER TABLE argo_profiles ADD COLUMN IF NOT EXISTS woa_deep_oxygen_umol_kg DOUBLE PRECISION;
        ALTER TABLE argo_profiles ADD COLUMN IF NOT EXISTS woa_deep_aou           DOUBLE PRECISION;
        ALTER TABLE argo_profiles ADD COLUMN IF NOT EXISTS woa_deep_o2sat         DOUBLE PRECISION;
        ALTER TABLE argo_profiles ADD COLUMN IF NOT EXISTS woa_deep_phosphate     DOUBLE PRECISION;
        ALTER TABLE argo_profiles ADD COLUMN IF NOT EXISTS woa_deep_silicate      DOUBLE PRECISION;
        ALTER TABLE argo_profiles ADD COLUMN IF NOT EXISTS woa_deep_nitrate       DOUBLE PRECISION;

        CREATE TABLE IF NOT EXISTS hydrothermal_vents (
            id          SERIAL PRIMARY KEY,
            name        TEXT NOT NULL,
            status      TEXT NOT NULL CHECK (status IN ('Active', 'Inactive', 'Extinct')),
            depth_m     FLOAT,
            latitude    FLOAT NOT NULL,
            longitude   FLOAT NOT NULL,
            geom        GEOGRAPHY(POINT, 4326) NOT NULL,
            source_url  TEXT,
            created_at  TIMESTAMPTZ DEFAULT now(),
            UNIQUE (name, latitude, longitude)
        );
        COMMENT ON COLUMN hydrothermal_vents.depth_m IS
          'Pass-through of the InterRidge Vents Database v3.4 "Maximum or Single Reported '
          'Depth" column (Beaulieu & Szafranski 2020, doi:10.1594/PANGAEA.917894). That '
          'source''s own column-header definitions file was not checked for a stated sign '
          'convention, and production values have not been range-checked here - treat '
          '"positive down" as unverified, not a claim.';
        CREATE INDEX IF NOT EXISTS hydrothermal_vents_geom_idx
            ON hydrothermal_vents USING GIST(geom);
        CREATE INDEX IF NOT EXISTS hydrothermal_vents_status_idx
            ON hydrothermal_vents (status);

        CREATE TABLE IF NOT EXISTS relinquished_areas (
            arcgis_id   INTEGER PRIMARY KEY,
            contract_id TEXT,
            area_type   TEXT,
            area_km2    DOUBLE PRECISION,
            act_date    TIMESTAMPTZ,
            status      TEXT,
            geom        GEOMETRY(GEOMETRY, 4326),
            synced_at   TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS relinquished_areas_geom_idx
            ON relinquished_areas USING GIST(geom);

        CREATE TABLE IF NOT EXISTS maritime_boundaries (
            mrgid       INTEGER PRIMARY KEY,
            geoname     TEXT NOT NULL,
            sovereign1  TEXT,
            iso_ter1    TEXT,
            area_km2    DOUBLE PRECISION,
            geom        GEOMETRY(MULTIPOLYGON, 4326) NOT NULL,
            synced_at   TIMESTAMPTZ DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS maritime_boundaries_geom_idx
            ON maritime_boundaries USING GIST(geom);

        CREATE TABLE IF NOT EXISTS protected_marine_sites (
            site_id     INTEGER PRIMARY KEY,
            name        TEXT NOT NULL,
            country     TEXT,
            lat_whc     DOUBLE PRECISION,
            lon_whc     DOUBLE PRECISION,
            area_km2    DOUBLE PRECISION,
            geom        GEOMETRY(MULTIPOLYGON, 4326),
            synced_at   TIMESTAMPTZ DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS protected_marine_sites_geom_idx
            ON protected_marine_sites USING GIST(geom);
    """)


async def ensure_argo_long_form(conn) -> None:
    """argo_profile_values, argo_params, argo_backfill_state.

    2026-09-09: additive alongside argo_profiles (which keeps its existing
    two-level summary columns unchanged — this is scope, not a replacement).
    A long-form table so a future widening beyond the current 5 requested
    Argovis parameters (of 35 offered) doesn't require another ALTER; see
    `rules/subsystems/units-and-passthrough.md` for why no unit is invented
    below when the source doesn't publish one.
    """

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS argo_profile_values (
            profile_id  TEXT NOT NULL,
            level       TEXT NOT NULL,
            param       TEXT NOT NULL,
            value       DOUBLE PRECISION NOT NULL,
            qc          SMALLINT,
            PRIMARY KEY (profile_id, level, param)
        );
        CREATE INDEX IF NOT EXISTS argo_profile_values_param_idx
            ON argo_profile_values (param);

        CREATE TABLE IF NOT EXISTS argo_params (
            param     TEXT PRIMARY KEY,
            label     TEXT,
            unit      TEXT,
            n_values  INTEGER
        );

        CREATE TABLE IF NOT EXISTS argo_backfill_state (
            id            INTEGER PRIMARY KEY CHECK (id = 1),
            done_through  DATE,
            updated_at    TIMESTAMPTZ
        );
    """)
    try:
        await conn.execute("ALTER TABLE argo_profile_values OWNER TO abyssal_user")
        await conn.execute("ALTER TABLE argo_params OWNER TO abyssal_user")
        await conn.execute("ALTER TABLE argo_backfill_state OWNER TO abyssal_user")
    except Exception:
        pass


async def ensure_core_tables(conn) -> None:
    """mining_contracts + biodiversity_hotspots (the two original core tables)."""

    # ── The two core tables ─────────────────────────────────────────────
    # `mining_contracts` (ISA concessions) and `biodiversity_hotspots` (OBIS
    # occurrences) were the project's first two tables and their CREATE was
    # never carried into this function — only their later ALTERs were. On an
    # established DB nothing notices, because `ADD COLUMN IF NOT EXISTS`
    # succeeds on a table that already exists. On a FRESH DB the first ALTER
    # below raised UndefinedTableError, which propagated straight out of the
    # schema step and crash-looped the API — so the platform could not
    # provision an empty database at all. Columns here are the base
    # set as it exists in production; everything added by an `IF NOT EXISTS`
    # ALTER further down is deliberately left to that ALTER.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS mining_contracts (
            id              SERIAL PRIMARY KEY,
            isa_id          TEXT UNIQUE,
            contractor_name TEXT,
            resource_type   TEXT,
            area_km2        DOUBLE PRECISION,
            expiry_date     TIMESTAMPTZ,
            region          TEXT,
            is_high_risk    BOOLEAN DEFAULT FALSE,
            geom            geometry(MultiPolygon, 4326),
            created_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            act_date        TIMESTAMPTZ
        );

        CREATE INDEX IF NOT EXISTS idx_mining_contracts_geom
            ON mining_contracts USING GIST(geom);

        CREATE TABLE IF NOT EXISTS biodiversity_hotspots (
            id              SERIAL PRIMARY KEY,
            obis_id         TEXT UNIQUE,
            scientific_name TEXT,
            vernacular_name TEXT,
            category        TEXT,
            is_endangered   BOOLEAN DEFAULT FALSE,
            geom            geometry(Point, 4326),
            created_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            phylum          TEXT,
            class_name      TEXT,
            order_name      TEXT,
            family          TEXT,
            depth           NUMERIC,
            description     TEXT,
            image_url       TEXT,
            iucn_category   TEXT DEFAULT 'NE'
        );

        CREATE INDEX IF NOT EXISTS idx_biodiversity_hotspots_geom
            ON biodiversity_hotspots USING GIST(geom);
    """)


async def ensure_ownership_grants(conn) -> None:
    """OWNER TO abyssal_user sweep for the early core tables."""

    for table in ("isa_contract_lookup", "reserved_areas", "isa_apeis", "relinquished_areas", "argo_profiles", "sync_log", "hydrothermal_vents", "maritime_boundaries", "protected_marine_sites"):
        await conn.execute(f"ALTER TABLE {table} OWNER TO abyssal_user")


async def ensure_pageviews(conn) -> None:
    """pageviews."""

    # Cookieless page-view counter — aggregate only, no personal data
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS pageviews (
            date  DATE NOT NULL,
            path  TEXT NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (date, path)
        )
    """)
    await conn.execute("ALTER TABLE pageviews OWNER TO abyssal_user")


async def ensure_feedback(conn) -> None:
    """feedback_submissions."""

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS feedback_submissions (
            id           SERIAL PRIMARY KEY,
            submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            kind         TEXT NOT NULL CHECK (kind IN ('positive', 'bug', 'suggestion', 'api_key')),
            message      TEXT NOT NULL,
            contact      TEXT,
            user_agent   TEXT,
            ip_hash      TEXT,
            page_url     TEXT,
            resolved     BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS feedback_submissions_submitted_idx
        ON feedback_submissions (submitted_at DESC)
    """)
    await conn.execute("ALTER TABLE feedback_submissions OWNER TO abyssal_user")
    # Migration: widen the kind CHECK to include 'api_key' (added to the
    # router + UI after the table shipped). CREATE TABLE IF NOT EXISTS won't
    # alter an existing constraint, so an api_key submission violates the old
    # CHECK and 500s — drop + re-add the constraint idempotently.
    await conn.execute(
        "ALTER TABLE feedback_submissions "
        "DROP CONSTRAINT IF EXISTS feedback_submissions_kind_check"
    )
    await conn.execute(
        "ALTER TABLE feedback_submissions "
        "ADD CONSTRAINT feedback_submissions_kind_check "
        "CHECK (kind IN ('positive', 'bug', 'suggestion', 'api_key'))"
    )


