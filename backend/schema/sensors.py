# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Schema DDL — sensors domain. Extracted verbatim from the former backend/schema.py.
"""
from __future__ import annotations

async def ensure_plume_paths(conn) -> None:
    """plume_paths."""

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS plume_paths (
            id               SERIAL PRIMARY KEY,
            profile_id       TEXT NOT NULL REFERENCES argo_profiles(profile_id) ON DELETE CASCADE,
            platform_id      TEXT NOT NULL,
            profile_date     TIMESTAMPTZ NOT NULL,
            origin_lon       DOUBLE PRECISION NOT NULL,
            origin_lat       DOUBLE PRECISION NOT NULL,
            path_coords      JSONB NOT NULL,
            speed_cms        DOUBLE PRECISION,
            steps_completed  INTEGER,
            source_dataset   TEXT,
            contractor_name  TEXT,
            computed_at      TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(profile_id)
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS plume_paths_contractor_idx
            ON plume_paths(contractor_name)
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS plume_paths_profile_date_idx
            ON plume_paths(profile_date DESC)
    """)
    await conn.execute("ALTER TABLE plume_paths OWNER TO abyssal_user")


async def ensure_wod_oxygen(conn) -> None:
    """wod_oxygen_profiles."""

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS wod_oxygen_profiles (
            id            SERIAL PRIMARY KEY,
            wod_cast_id   TEXT UNIQUE,
            lat           DOUBLE PRECISION,
            lon           DOUBLE PRECISION,
            geom          geometry(Point, 4326),
            profile_date  DATE,
            decade        SMALLINT,
            cruise        TEXT,
            dataset       TEXT,
            country       TEXT,
            probe_type    TEXT,
            max_depth_m   DOUBLE PRECISION,
            n_levels      SMALLINT,
            o2_profile    JSONB,
            o2_units      TEXT,
            qc_flag       SMALLINT,
            qc_note       TEXT
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS wod_oxygen_geom_gix ON wod_oxygen_profiles USING GIST (geom)")
    await conn.execute("CREATE INDEX IF NOT EXISTS wod_oxygen_decade_idx ON wod_oxygen_profiles (decade)")
    await conn.execute("CREATE INDEX IF NOT EXISTS wod_oxygen_date_idx ON wod_oxygen_profiles (profile_date)")
    await conn.execute("ALTER TABLE wod_oxygen_profiles OWNER TO abyssal_user")


async def ensure_oceansites(conn) -> None:
    """oceansites_stations."""

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS oceansites_stations (
            ref          TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            lat          DOUBLE PRECISION NOT NULL,
            lon          DOUBLE PRECISION NOT NULL,
            status       TEXT DEFAULT 'OPERATIONAL',
            network      TEXT DEFAULT '',
            deploy_date  DATE,
            geom         GEOMETRY(Point, 4326),
            updated_at   TIMESTAMPTZ DEFAULT NOW(),
            latest_obs   JSONB,
            obs_fetched_at TIMESTAMPTZ
        )
    """)
    for col, defn in [
        ("latest_obs",     "JSONB"),
        ("obs_fetched_at", "TIMESTAMPTZ"),
        ("age_days",       "DOUBLE PRECISION"),
        ("model",          "TEXT"),
        ("obs_source",     "TEXT"),  # NDBC | PMEL | CMEMS | GDAC
        # 2026-09-09 widening. OceanOPS was already being asked for wigosId and
        # answered on 5,063 of 5,795 records — under `identifiers.wigos_id`,
        # which nothing read. `country` and `sensors` are two request names that
        # were never sent at all; they carry the operating country (5,792) and
        # the instrument models on the mooring (4,113).
        ("wigos_id",       "TEXT"),
        ("country",        "TEXT"),
        ("sensor_models",  "TEXT"),
        ("deploy_ship",    "TEXT"),
        ("deployment_count", "INTEGER"),
    ]:
        try:
            await conn.execute(
                f"ALTER TABLE oceansites_stations ADD COLUMN IF NOT EXISTS {col} {defn}"
            )
        except Exception:
            pass
    # 2026-09-08: deploy_date was TEXT and always NULL (the ingest never
    # populated it). The OceanOPS widening starts writing real ISO dates —
    # convert the column so callers get a DATE, not a string to re-parse.
    # A pre-existing non-empty TEXT value that fails the cast is left NULL
    # rather than aborting the whole ALTER (USING with a defensive CASE).
    try:
        await conn.execute("""
            ALTER TABLE oceansites_stations
            ALTER COLUMN deploy_date TYPE DATE
            USING CASE
                WHEN deploy_date IS NULL OR deploy_date = '' THEN NULL
                WHEN deploy_date ~ '^\\d{4}-\\d{2}-\\d{2}' THEN deploy_date::DATE
                ELSE NULL
            END
        """)
    except Exception:
        pass
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS oceansites_geom_idx
        ON oceansites_stations USING GIST(geom)
    """)
    # ⛔ One row per DEPLOYMENT, against oceansites_stations' one row per
    # STATION. OceanOPS returns 5,795 platform records with 5,795 distinct
    # refs — there are no duplicates to remove. The station table keeps the
    # highest _NNN per base ref, which is right for a map point and wrong as a
    # place to stop: one mooring (5100007) has 61 deployments from 1988-05-27
    # to 2026-03-27, each with its own WIGOS identifier, ship and position,
    # and 31 base refs hold deployments more than a degree apart.
    # Additive by design — nothing that reads oceansites_stations changed.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS oceansites_deployments (
            ref            TEXT PRIMARY KEY,
            base_ref       TEXT NOT NULL,
            deploy_num     INTEGER NOT NULL DEFAULT 0,
            name           TEXT,
            lat            DOUBLE PRECISION,
            lon            DOUBLE PRECISION,
            geom           GEOMETRY(Point, 4326),
            position_flag  TEXT,
            status         TEXT,
            network        TEXT,
            deploy_date    DATE,
            deploy_ship    TEXT,
            age_days       DOUBLE PRECISION,
            model          TEXT,
            wigos_id       TEXT,
            country        TEXT,
            sensor_models  TEXT,
            oceanops_id    BIGINT,
            updated_at     TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS oceansites_depl_base_idx
        ON oceansites_deployments (base_ref, deploy_num)
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS oceansites_depl_geom_idx
        ON oceansites_deployments USING GIST(geom)
    """)
    # A WIGOS id is how WMO systems refer to this platform, so it is the key
    # an outside dataset will join on. Not UNIQUE: 732 of 5,795 records carry
    # none, and this ingest does not get to assert uniqueness on a field it
    # does not mint.
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS oceansites_depl_wigos_idx
        ON oceansites_deployments (wigos_id) WHERE wigos_id IS NOT NULL
    """)
    try:
        await conn.execute("ALTER TABLE oceansites_deployments OWNER TO abyssal_user")
    except Exception:
        pass
    try:
        await conn.execute("ALTER TABLE oceansites_stations OWNER TO abyssal_user")
    except Exception:
        pass


