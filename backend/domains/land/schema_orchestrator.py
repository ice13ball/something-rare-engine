# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Schema DDL and the cross-family sync orchestrator for land layers,
extracted verbatim from `land_layers.py`.

- `ensure_land_schema` — creates every land-layer table (356 lines of DDL).
  Imported by name from `main.py` (`from land_layers import ... ensure_land_schema
  ...`) and called from `main.py` lifespan after `schema.ensure_schema()`.
  DDL correctness here is provable only by a live boot; this move is a pure
  relocation of the function body (byte-identical), not a re-verification of
  the DDL itself.
- `sync_all_land_sources` — a CROSS-FAMILY orchestrator (same shape as
  `_sync_all_sources`): runs 9 of the ~20 land syncs then
  `land_overlaps.refresh_overlap_views`, and DELIBERATELY omits
  arctic-rivers, permafrost-thaw and all 7 DataCite syncs. That membership
  list is preserved exactly — do not "complete" it.
"""

from __future__ import annotations

import logging

import db
from sync_log import is_sync_paused
from domains.land.extractive import (
    _sync_mining_footprints,
    _sync_kbas,
    _sync_wdpa,
    _sync_tailings,
    _enrich_tailings_from_grid,
    _sync_dams,
)
from domains.land.hazards import (
    _sync_active_fires,
    _sync_air_quality,
    _sync_landslides,
    _sync_water_risk,
)

log = logging.getLogger("land_layers")


# ── Schema ─────────────────────────────────────────────────────────────────

async def ensure_land_schema():
    """Create land-layer tables. Called from main.py lifespan after schema.ensure_schema()."""
    async with db.pool.acquire() as conn:
        # ── Phase 1 ────────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS mining_footprints (
                id          SERIAL PRIMARY KEY,
                country     TEXT,
                area_km2    DOUBLE PRECISION,
                ftype       TEXT,
                source      TEXT,
                geom        geometry(MultiPolygon, 4326),
                created_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_mining_footprints_geom ON mining_footprints USING GIST (geom)")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS key_biodiversity_areas (
                id          SERIAL PRIMARY KEY,
                site_name   TEXT,
                country     TEXT,
                status      TEXT,
                criteria    TEXT,
                area_km2    DOUBLE PRECISION,
                geom        geometry(MultiPolygon, 4326),
                created_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_kbas_geom ON key_biodiversity_areas USING GIST (geom)")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS wdpa (
                id          SERIAL PRIMARY KEY,
                wdpa_id     INTEGER,
                name        TEXT,
                desig       TEXT,
                desig_type  TEXT,
                iucn_cat    TEXT,
                country     TEXT,
                status      TEXT,
                area_km2    DOUBLE PRECISION,
                geom        geometry(MultiPolygon, 4326),
                created_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_wdpa_geom ON wdpa USING GIST (geom)")

        # forest-loss: raster tiles served from GFW — no DB table

        # ── Phase 2 ────────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tailings_dams (
                id              SERIAL PRIMARY KEY,
                dam_name        TEXT,
                mine_name       TEXT,
                country         TEXT,
                dam_type        TEXT,
                height_m        DOUBLE PRECISION,
                volume_m3       DOUBLE PRECISION,
                risk_class      TEXT,
                status          TEXT,
                owner_company   TEXT,
                operator        TEXT,
                construction_year INTEGER,
                hazard_raw      TEXT,
                raise_type      TEXT,
                data_source     TEXT DEFAULT 'wapha',
                geom            geometry(Point, 4326),
                created_at      TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        # ⛔ GRID-Arendal's own key for the facility an enriched dam's
        # attributes came from. Before this column the link was re-derived from
        # bare 5 km proximity on every run, so nobody could tell which facility
        # a dam's hazard rating actually describes — and 224 dams carried a
        # neighbour's rating (measured 2026-09-10, 473 overwrites in one pass).
        await conn.execute(
            "ALTER TABLE tailings_dams ADD COLUMN IF NOT EXISTS grid_facility_id TEXT")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_tailings_geom ON tailings_dams USING GIST (geom)")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS active_fires (
                id          SERIAL PRIMARY KEY,
                latitude    DOUBLE PRECISION,
                longitude   DOUBLE PRECISION,
                brightness  DOUBLE PRECISION,
                confidence  TEXT,
                frp         DOUBLE PRECISION,
                instrument  TEXT,
                acq_date    DATE,
                geom        geometry(Point, 4326),
                created_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_fires_geom ON active_fires USING GIST (geom)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_fires_date ON active_fires (acq_date)")
        # ⛔ FIRMS publishes acq_time (HHMM UTC) beside acq_date on EVERY row —
        # confirmed against the live CSV 2026-09-10, whose columns are:
        # acq_date, acq_time, bright_ti4, bright_ti5, confidence, daynight, frp,
        # instrument, latitude, longitude, satellite, scan, track, version.
        # We kept a bare DATE while four locales promised "click for exact
        # date/time". It also publishes `instrument` and `satellite` as separate
        # fields; the `instrument` column held OUR composite ("VIIRS_SNPP"),
        # which is a label we invented, not one NASA gave us.
        for ddl in (
            "ALTER TABLE active_fires ADD COLUMN IF NOT EXISTS acq_time    TEXT",
            "ALTER TABLE active_fires ADD COLUMN IF NOT EXISTS observed_at TIMESTAMPTZ",
            "ALTER TABLE active_fires ADD COLUMN IF NOT EXISTS satellite   TEXT",
        ):
            await conn.execute(ddl)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS air_quality_stations (
                id          SERIAL PRIMARY KEY,
                location_id INTEGER UNIQUE,
                name        TEXT,
                city        TEXT,
                country     TEXT,
                pm25        DOUBLE PRECISION,
                so2         DOUBLE PRECISION,
                no2         DOUBLE PRECISION,
                o3          DOUBLE PRECISION,
                co          DOUBLE PRECISION,
                last_updated TIMESTAMPTZ,
                geom        geometry(Point, 4326),
                created_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_air_quality_geom ON air_quality_stations USING GIST (geom)")

        # ADDITIVE (2026-09-08): OpenAQ /v3/parameters reports 44 parameters;
        # air_quality_stations has 16 named columns. Rather than widen the
        # table to 44 columns, every parameter a sensor reports lands here in
        # long form, verbatim unit included — same shape as geotraces_values.
        # The 16 legacy columns keep being populated unchanged (frontend/SEO
        # read them by name); this table is additive, not a replacement.
        #
        # FIXED (2026-09-09): one OpenAQ location can carry several sensors
        # reporting the SAME parameter (reference-grade + low-cost monitoring
        # the same thing is the ordinary case) — under (location_id,
        # parameter) alone they collided on the primary key and one reading
        # was silently lost. sensor_id joins the key. Also added per-sensor
        # datetimeFirst/datetimeLast, summary (min/max/sd/expectedCount/
        # observedCount) and coverage.percentComplete — cheap fields the
        # source gives that were being read (or not even read) and dropped.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS air_quality_params (
                location_id     INTEGER NOT NULL,
                sensor_id       INTEGER NOT NULL DEFAULT 0,
                parameter       TEXT NOT NULL,
                value           DOUBLE PRECISION,
                unit            TEXT,
                last_updated    TIMESTAMPTZ,
                datetime_first  TIMESTAMPTZ,
                datetime_last   TIMESTAMPTZ,
                value_min       DOUBLE PRECISION,
                value_max       DOUBLE PRECISION,
                value_sd        DOUBLE PRECISION,
                expected_count  INTEGER,
                observed_count  INTEGER,
                coverage_pct    DOUBLE PRECISION,
                PRIMARY KEY (location_id, sensor_id, parameter)
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_air_quality_params_parameter "
            "ON air_quality_params (parameter)"
        )

        # Migrate an existing table created under the old (location_id,
        # parameter) key. DEFAULT 0 on the new sensor_id column keeps every
        # row unique under the new key too (the old key was already unique),
        # so no row is lost. Idempotent: only runs when the old PK is found.
        for col_sql in [
            "ALTER TABLE air_quality_params ADD COLUMN IF NOT EXISTS sensor_id INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE air_quality_params ADD COLUMN IF NOT EXISTS datetime_first TIMESTAMPTZ",
            "ALTER TABLE air_quality_params ADD COLUMN IF NOT EXISTS datetime_last TIMESTAMPTZ",
            "ALTER TABLE air_quality_params ADD COLUMN IF NOT EXISTS value_min DOUBLE PRECISION",
            "ALTER TABLE air_quality_params ADD COLUMN IF NOT EXISTS value_max DOUBLE PRECISION",
            "ALTER TABLE air_quality_params ADD COLUMN IF NOT EXISTS value_sd DOUBLE PRECISION",
            "ALTER TABLE air_quality_params ADD COLUMN IF NOT EXISTS expected_count INTEGER",
            "ALTER TABLE air_quality_params ADD COLUMN IF NOT EXISTS observed_count INTEGER",
            "ALTER TABLE air_quality_params ADD COLUMN IF NOT EXISTS coverage_pct DOUBLE PRECISION",
        ]:
            await conn.execute(col_sql)

        old_pk = await conn.fetchrow("""
            SELECT tc.constraint_name,
                   array_agg(kcu.column_name ORDER BY kcu.ordinal_position) AS cols
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON kcu.constraint_name = tc.constraint_name
             AND kcu.table_schema = tc.table_schema
            WHERE tc.table_name = 'air_quality_params'
              AND tc.constraint_type = 'PRIMARY KEY'
            GROUP BY tc.constraint_name
        """)
        if old_pk and list(old_pk["cols"]) == ["location_id", "parameter"]:
            await conn.execute(
                f'ALTER TABLE air_quality_params DROP CONSTRAINT "{old_pk["constraint_name"]}"'
            )
            await conn.execute(
                "ALTER TABLE air_quality_params ADD PRIMARY KEY (location_id, sensor_id, parameter)"
            )
            log.info("air_quality_params: migrated primary key to (location_id, sensor_id, parameter)")

        # Enrich schema — safe to run on populated table
        for col_sql in [
            # Rotation key for the readings sweep. ⛔ Without it the queue was
            # ordered by "has no readings yet", so the ~4% of OpenAQ locations
            # whose /sensors endpoint returns HTTP 500 (measured 2026-09-09,
            # their fault) stayed candidates forever and blocked the head of
            # every run. readings_error keeps an upstream failure telling itself
            # apart from a station that genuinely reports nothing.
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS readings_attempted_at TIMESTAMPTZ",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS readings_error TEXT",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS locality TEXT",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS timezone TEXT",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS is_mobile BOOLEAN DEFAULT FALSE",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS is_monitor BOOLEAN DEFAULT FALSE",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS provider TEXT",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS owner TEXT",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS datetime_first TIMESTAMPTZ",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS datetime_last TIMESTAMPTZ",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS pm10 DOUBLE PRECISION",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS bc DOUBLE PRECISION",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS no DOUBLE PRECISION",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS nox DOUBLE PRECISION",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS humidity DOUBLE PRECISION",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS temperature DOUBLE PRECISION",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS co2 DOUBLE PRECISION",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS pm1 DOUBLE PRECISION",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS pm4 DOUBLE PRECISION",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS ch4 DOUBLE PRECISION",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS ufp DOUBLE PRECISION",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS coverage_pct DOUBLE PRECISION",
        ]:
            await conn.execute(col_sql)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS landslides (
                id           SERIAL PRIMARY KEY,
                event_date   DATE,
                event_type   TEXT,
                country      TEXT,
                location     TEXT,
                fatalities   INTEGER,
                trigger      TEXT,
                source       TEXT,
                geom         geometry(Point, 4326),
                created_at   TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_landslides_geom ON landslides USING GIST (geom)")

        # ── Phase 3 ────────────────────────────────────────────────────
        # surface-water, carbon-flux, soil-carbon: raster tiles — no DB tables

        await conn.execute("""
            -- GDW v1.0 barriers (figshare doi:10.6084/m9.figshare.25988293, CC BY 4.0).
            -- ⛔ Until 2026-09-11 this table held GOODD, which publishes four fields,
            -- so six of these columns were NULL on all 38,667 rows.
            CREATE TABLE IF NOT EXISTS dams (
                id          SERIAL PRIMARY KEY,
                gdw_id      INTEGER,
                dam_name    TEXT,
                river       TEXT,
                country     TEXT,
                main_basin  TEXT,
                height_m    DOUBLE PRECISION,
                purpose     TEXT,
                dam_type    TEXT,
                year_built  INTEGER,
                volume_mcm  DOUBLE PRECISION,
                area_skm    DOUBLE PRECISION,
                power_mw    INTEGER,
                grand_id    INTEGER,
                quality     TEXT,
                geom        geometry(Point, 4326),
                created_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_dams_geom ON dams USING GIST (geom)")
        await conn.execute("ALTER TABLE dams ADD COLUMN IF NOT EXISTS gdw_id INTEGER")
        await conn.execute("ALTER TABLE dams ADD COLUMN IF NOT EXISTS dam_type TEXT")
        await conn.execute("ALTER TABLE dams ADD COLUMN IF NOT EXISTS power_mw INTEGER")
        await conn.execute("ALTER TABLE dams ADD COLUMN IF NOT EXISTS grand_id INTEGER")
        await conn.execute("ALTER TABLE dams ADD COLUMN IF NOT EXISTS main_basin TEXT")
        await conn.execute("ALTER TABLE dams ADD COLUMN IF NOT EXISTS area_skm DOUBLE PRECISION")
        await conn.execute("ALTER TABLE dams ADD COLUMN IF NOT EXISTS quality TEXT")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_dams_gdw_id ON dams (gdw_id)")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS water_risk (
                id                   SERIAL PRIMARY KEY,
                string_id            TEXT UNIQUE,
                pfaf_id              BIGINT,
                gid_0                TEXT,
                name_0               TEXT,
                name_1               TEXT,
                area_km2             DOUBLE PRECISION,
                bws_score            DOUBLE PRECISION,
                bws_label            TEXT,
                bwd_score            DOUBLE PRECISION,
                drr_score            DOUBLE PRECISION,
                rfr_score            DOUBLE PRECISION,
                w_awr_min_tot_score  DOUBLE PRECISION,
                w_awr_min_tot_cat    INTEGER,
                w_awr_min_tot_label  TEXT,
                geom                 geometry(MultiPolygon, 4326),
                created_at           TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_water_risk_geom ON water_risk USING GIST (geom)")

        # ── Monitoring density point sources ───────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS wod_profiles (
                id          SERIAL PRIMARY KEY,
                lon         DOUBLE PRECISION NOT NULL,
                lat         DOUBLE PRECISION NOT NULL,
                year        INTEGER,
                dataset     TEXT,
                region      TEXT,
                UNIQUE (lon, lat, year, dataset)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS pangaea_records (
                id          SERIAL PRIMARY KEY,
                pangaea_id  TEXT UNIQUE,
                lon         DOUBLE PRECISION NOT NULL,
                lat         DOUBLE PRECISION NOT NULL,
                year        INTEGER,
                title       TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bco_dmo_datasets (
                id         SERIAL PRIMARY KEY,
                doi        TEXT UNIQUE,
                lon        DOUBLE PRECISION NOT NULL,
                lat        DOUBLE PRECISION NOT NULL,
                year       INTEGER,
                title      TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS noaa_datasets (
                id         SERIAL PRIMARY KEY,
                doi        TEXT UNIQUE,
                lon        DOUBLE PRECISION NOT NULL,
                lat        DOUBLE PRECISION NOT NULL,
                year       INTEGER,
                title      TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS obis_seamap_records (
                id         SERIAL PRIMARY KEY,
                lon        DOUBLE PRECISION NOT NULL,
                lat        DOUBLE PRECISION NOT NULL,
                year       INTEGER,
                UNIQUE (lon, lat, year)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ncei_icoads_files (
                id            SERIAL PRIMARY KEY,
                file_path     TEXT UNIQUE,
                lon           DOUBLE PRECISION NOT NULL,
                lat           DOUBLE PRECISION NOT NULL,
                year          INTEGER,
                station_count INTEGER,
                data_types    TEXT[]
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS cchdo_stations (
                id         SERIAL PRIMARY KEY,
                expocode   TEXT NOT NULL,
                ship       TEXT,
                country    TEXT,
                year       INTEGER,
                woce_line  TEXT,
                lon        DOUBLE PRECISION NOT NULL,
                lat        DOUBLE PRECISION NOT NULL,
                -- ⛔ A row here is NOT a station, whatever the table name says: it is a
                -- vertex of the cruise track LineString, subsampled to 30 points per
                -- cruise. The track carries lon/lat only — no per-point time exists at
                -- the source — so the honest sample time for these rows is the CRUISE
                -- WINDOW, never a day. That is why these are campaign_* and not
                -- sample_date. `year` stays because the map filter and ORDER BY use it;
                -- it is derived from campaign_start, not a second claim.
                campaign_start DATE,
                campaign_end   DATE,
                -- date_precision doubles as the backfill sentinel: NULL means "this row
                -- predates the date columns and has never been asked about", which is
                -- what _backfill_cchdo_dates() looks for. A cruise the API dates as
                -- 'none' is therefore not re-fetched on every sync forever.
                date_precision TEXT,
                UNIQUE (expocode, lon, lat)
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_ncei_icoads_year ON ncei_icoads_files(year)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_cchdo_stations_expocode ON cchdo_stations(expocode)")
        # Additive for the 41,102 rows that already exist; the CREATE above only runs
        # on a fresh database.
        for stmt in (
            "ALTER TABLE cchdo_stations ADD COLUMN IF NOT EXISTS campaign_start DATE",
            "ALTER TABLE cchdo_stations ADD COLUMN IF NOT EXISTS campaign_end   DATE",
            "ALTER TABLE cchdo_stations ADD COLUMN IF NOT EXISTS date_precision TEXT",
        ):
            await conn.execute(stmt)

        # ── Arctic River Stations ──────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS arctic_river_stations (
                station_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                river_name TEXT NOT NULL,
                site_label TEXT,
                lat DOUBLE PRECISION NOT NULL,
                lon DOUBLE PRECISION NOT NULL,
                geom geometry(Point, 4326),
                record_start DATE,
                record_end DATE,
                mean_annual_discharge_km3 DOUBLE PRECISION,
                summary_stats JSONB NOT NULL DEFAULT '{}'::jsonb,
                units JSONB,
                discharge_monthly JSONB,
                biogeochem_monthly JSONB NOT NULL DEFAULT '{}'::jsonb,
                annual_fluxes JSONB,
                citation TEXT,
                CONSTRAINT arctic_river_stations_source_check
                    CHECK (source IN ('arcticgro','pangaea_lena','pangaea_caa'))
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS arctic_river_stations_geom_gix "
            "ON arctic_river_stations USING GIST (geom)"
        )
        # Idempotent CHECK migration so adding future sub-sources never needs a destructive change
        await conn.execute(
            "ALTER TABLE arctic_river_stations "
            "DROP CONSTRAINT IF EXISTS arctic_river_stations_source_check"
        )
        await conn.execute(
            "ALTER TABLE arctic_river_stations ADD CONSTRAINT arctic_river_stations_source_check "
            "CHECK (source IN ('arcticgro','pangaea_lena','pangaea_caa'))"
        )
        # Per-param source units (verbatim from the dataset), added 2026-06 after the
        # ArcticGRO provider flagged that values are mass concentration (mg/L), not molar.
        await conn.execute(
            "ALTER TABLE arctic_river_stations ADD COLUMN IF NOT EXISTS units JSONB"
        )

        # ── Permafrost Thaw Features ───────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS permafrost_thaw_features (
                id SERIAL PRIMARY KEY,
                source TEXT NOT NULL,
                unique_id TEXT NOT NULL,
                feature_name TEXT,
                feature_type TEXT,
                feature_category TEXT,
                thaw_type TEXT,
                data_source_type TEXT,
                authors TEXT,
                source_doi TEXT,
                imagery TEXT,
                -- WHEN the feature was actually observed. Both sources date every
                -- feature and both were burying it in `imagery` above, where nothing
                -- could query it. ⛔ It is an imagery WINDOW, not a sampling day: a
                -- thaw slump is mapped from imagery spanning a period.
                --
                -- Years are the primary form because that is what most of the source
                -- gives (Alaska Webb writes "1985 through 2015" on 88% of its rows);
                -- the DATE columns are filled only where the source gave full dates,
                -- so a consumer can tell which it got by whether they are null. ⛔ A
                -- bare year must never be widened into 1 January here.
                obs_start_year INTEGER,
                obs_end_year   INTEGER,
                obs_start      DATE,
                obs_end        DATE,
                date_precision TEXT,
                -- ⛔ NOT an observation date: ARTS records when the digitisation was
                -- contributed, which ran years after the imagery was taken (2024 for
                -- 2020 imagery in the sampled data). Kept apart so it can never be
                -- mistaken for one.
                contribution_date DATE,
                lat DOUBLE PRECISION NOT NULL,
                lon DOUBLE PRECISION NOT NULL,
                geom GEOMETRY(Point, 4326),
                synced_at TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT permafrost_thaw_features_source_check
                    CHECK (source IN ('alaska_webb','arts_panarctic'))
            )
        """)
        # Additive for the 47,239 rows already in place; the CREATE above only runs
        # on a fresh database.
        for stmt in (
            "ALTER TABLE permafrost_thaw_features ADD COLUMN IF NOT EXISTS obs_start_year INTEGER",
            "ALTER TABLE permafrost_thaw_features ADD COLUMN IF NOT EXISTS obs_end_year   INTEGER",
            "ALTER TABLE permafrost_thaw_features ADD COLUMN IF NOT EXISTS obs_start      DATE",
            "ALTER TABLE permafrost_thaw_features ADD COLUMN IF NOT EXISTS obs_end        DATE",
            "ALTER TABLE permafrost_thaw_features ADD COLUMN IF NOT EXISTS date_precision TEXT",
            "ALTER TABLE permafrost_thaw_features ADD COLUMN IF NOT EXISTS contribution_date DATE",
        ):
            await conn.execute(stmt)
        await conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS permafrost_thaw_features_src_uid_uidx "
            "ON permafrost_thaw_features (source, unique_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS permafrost_thaw_features_geom_gix "
            "ON permafrost_thaw_features USING GIST (geom)"
        )
        # Idempotent CHECK migration — adding the pan-Arctic ARTS source later needs
        # only 'arts_panarctic' added to this list, no destructive change.
        await conn.execute(
            "ALTER TABLE permafrost_thaw_features "
            "DROP CONSTRAINT IF EXISTS permafrost_thaw_features_source_check"
        )
        await conn.execute(
            "ALTER TABLE permafrost_thaw_features ADD CONSTRAINT permafrost_thaw_features_source_check "
            "CHECK (source IN ('alaska_webb','arts_panarctic'))"
        )
        await conn.execute("ALTER TABLE permafrost_thaw_features OWNER TO abyssal_user")

    log.info("Land layer schema ready")



# ═══════════════════════════════════════════════════════════════════════════
# Sync orchestration — called from main.py
# ═══════════════════════════════════════════════════════════════════════════

async def sync_all_land_sources():
    """Run all land layer syncs sequentially, then refresh overlap views."""
    for name, action, fn in [
        ("mining_footprints", "land-mining", _sync_mining_footprints),
        ("kbas", "land-kbas", _sync_kbas),
        ("wdpa", "land-wdpa", _sync_wdpa),
        ("tailings", "land-tailings", _sync_tailings),
        ("tailings_enrich", "land-tailings-enrich", _enrich_tailings_from_grid),
        ("active_fires", "land-fires", _sync_active_fires),
        ("air_quality", "land-air-quality", _sync_air_quality),
        ("landslides", "land-landslides", _sync_landslides),
        ("dams", "land-dams", _sync_dams),
        ("water_risk", "land-water-risk", _sync_water_risk),
    ]:
        try:
            if await is_sync_paused(action):
                log.info("%s: skipped (paused)", name)
                continue
            await fn()
        except Exception as e:
            log.error("%s sync failed: %s", name, e)

    # Refresh overlap materialized views after all syncs complete
    try:
        from land_overlaps import refresh_overlap_views
        await refresh_overlap_views()
    except Exception as e:
        log.error("Overlap view refresh failed: %s", e)
