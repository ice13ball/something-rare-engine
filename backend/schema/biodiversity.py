# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Schema DDL — biodiversity domain. Extracted verbatim from the former backend/schema.py.
"""
from __future__ import annotations
import logging

# Restored 2026-08-21. The split of schema.py into this package left `log`
# behind in the original module while nine `log.debug(...)` calls came across —
# every one of them inside an `except` clause. A tolerated DDL failure would
# therefore raise NameError from its own handler and take the boot down with it.
# The DDL snapshot test could not see this: it compares statements, not error paths.
log = logging.getLogger(__name__)

async def ensure_biodiversity_enrichment(conn) -> None:
    """biodiversity_hotspots iucn/enrichment + obis_species_check."""

    # Add iucn_category to biodiversity_hotspots (idempotent — no bare except)
    await conn.execute(
        "ALTER TABLE biodiversity_hotspots "
        "ADD COLUMN IF NOT EXISTS iucn_category TEXT DEFAULT 'NE'"
    )

    # OBIS `_id` (stored as obis_id) is NOT stable: it is regenerated whenever a
    # contributor republishes a dataset, so every republication used to orphan a
    # full generation of rows — duplicating the records and leaving
    # obis.org/occurrence/<id> pointing at a page that no longer resolves.
    # dataset_id + occurrence_id are the provider-stable pair. Which rows the
    # current snapshot still carries is tracked per-run in the UNLOGGED
    # `obis_seen` side table (see obis_sync._SEEN_DDL), not in a column here —
    # stamping a column every pass would rewrite every row under MVCC.
    await conn.execute("""
        ALTER TABLE biodiversity_hotspots
            ADD COLUMN IF NOT EXISTS dataset_id    TEXT,
            ADD COLUMN IF NOT EXISTS occurrence_id TEXT
    """)

    # Partial GIST index for CR/EN records — used by two-pass hotspot query
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS bh_cr_en_geom_gix
        ON biodiversity_hotspots USING GIST(geom)
        WHERE iucn_category IN ('CR','EN')
    """)

    # btree index on scientific_name — required by biodiversity.backfill_iucn_categories'
    # per-species UPDATE (WHERE scientific_name = $2). Without it, each
    # UPDATE seq-scans 5M+ rows and a 500-batch backfill pegs one CPU core
    # for ~30 min. With the index, per-row update is ~1s (mostly write I/O).
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bh_scientific_name
        ON biodiversity_hotspots (scientific_name)
    """)

    # Trigram GIN index on lower(scientific_name) powers the species name
    # search endpoint (/v1/search/species). Without it, a substring ILIKE
    # over 5M+ rows is a ~14 s parallel seq scan. CREATE EXTENSION is wrapped
    # so a missing-privilege role doesn't abort schema setup (prod creates it
    # manually as superuser; the IF NOT EXISTS index build is owner-safe).
    try:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    except Exception as exc:
        log.warning("pg_trgm extension not available (%s) — species search will be slow", exc)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bh_scientific_name_trgm
        ON biodiversity_hotspots USING gin (lower(scientific_name) gin_trgm_ops)
    """)

    # Per-species probe tracking for staggered weekly OBIS sync
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS obis_species_check (
            scientific_name  TEXT PRIMARY KEY,
            last_check_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_remote_count INTEGER
        )
    """)
    try:
        await conn.execute("ALTER TABLE obis_species_check OWNER TO abyssal_user")
    except Exception:
        pass


async def ensure_hotspot_grid(conn) -> None:
    """hotspot_grid."""

    # hotspot_grid table for pre-computed aggregation
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS hotspot_grid (
            id SERIAL PRIMARY KEY,
            resolution TEXT NOT NULL,
            cell_lon DOUBLE PRECISION NOT NULL,
            cell_lat DOUBLE PRECISION NOT NULL,
            total_count INT NOT NULL,
            species_count INT NOT NULL,
            endangered_count INT DEFAULT 0,
            cr_en_count INT DEFAULT 0,
            top_species JSONB,
            geom GEOMETRY(Point, 4326)
        );
        CREATE INDEX IF NOT EXISTS idx_hotspot_grid_res ON hotspot_grid(resolution);
        CREATE INDEX IF NOT EXISTS idx_hotspot_grid_geom ON hotspot_grid USING GIST(geom);
    """)


async def ensure_noise_cetacean_grids(conn) -> None:
    """noise_cells, cetacean_cells, noise_risk_grid."""

    # noise_cells — per-cell noise measurements (ICES / EMODnet)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS noise_cells (
            id          SERIAL PRIMARY KEY,
            geom        GEOMETRY(Point, 4326) NOT NULL,
            lon         FLOAT NOT NULL,
            lat         FLOAT NOT NULL,
            cell_key    TEXT NOT NULL UNIQUE,
            impulsive_pbd   FLOAT,
            continuous_spl  FLOAT,
            pbd_norm        FLOAT,   -- ICES / EMODnet INER pulse-block days, 0-1
            spl_norm        FLOAT,   -- EMODnet continuous SPL (dB re 1uPa), 0-1
            source      TEXT NOT NULL,
            region      TEXT,
            updated_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS noise_cells_geom_idx
        ON noise_cells USING GIST(geom)
    """)
    await conn.execute("ALTER TABLE noise_cells OWNER TO abyssal_user")
    # Migrate older deployments that pre-date pbd_norm/spl_norm — CREATE TABLE
    # IF NOT EXISTS above is a no-op once the table already exists in production.
    await conn.execute(
        "ALTER TABLE noise_cells ADD COLUMN IF NOT EXISTS pbd_norm FLOAT"
    )
    await conn.execute(
        "ALTER TABLE noise_cells ADD COLUMN IF NOT EXISTS spl_norm FLOAT"
    )
    # noise_norm blended pulse-block days and continuous SPL — two
    # non-commensurable quantities — into one column. Every reader now uses
    # pbd_norm/spl_norm directly (backend/domains/acoustic.py,
    # backend/ingestion/noise_risk_compute.py), so the column is retired here.
    await conn.execute(
        "ALTER TABLE noise_cells DROP COLUMN IF EXISTS noise_norm"
    )

    # cetacean_cells — per-cell cetacean sighting aggregates (OBIS-SEAMAP)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS cetacean_cells (
            id           SERIAL PRIMARY KEY,
            geom         GEOMETRY(Point, 4326) NOT NULL,
            cell_lon     FLOAT NOT NULL,
            cell_lat     FLOAT NOT NULL,
            cell_key     TEXT NOT NULL UNIQUE,
            sighting_count  INTEGER NOT NULL DEFAULT 0,
            max_iucn_weight FLOAT NOT NULL DEFAULT 1.0,
            max_iucn_cat    TEXT,
            top_species  TEXT,
            source       TEXT NOT NULL DEFAULT 'obis_seamap',
            updated_at   TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS cetacean_cells_geom_idx
        ON cetacean_cells USING GIST(geom)
    """)
    await conn.execute("ALTER TABLE cetacean_cells OWNER TO abyssal_user")

    # noise_risk_grid — combined noise × cetacean risk index. pbd_norm and
    # spl_norm are both nullable, deliberately: noise_risk_compute.py emits one
    # grid row per underlying noise measure (never blends the two), so a given
    # row carries exactly one of them — neither column can be declared NOT NULL
    # without breaking the other measure's rows. This mirrors noise_cells,
    # which has carried the same split as nullable columns since Task 9.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS noise_risk_grid (
            id              SERIAL PRIMARY KEY,
            geom            GEOMETRY(Point, 4326) NOT NULL,
            lon             FLOAT NOT NULL,
            lat             FLOAT NOT NULL,
            cell_key        TEXT NOT NULL UNIQUE,
            pbd_norm        FLOAT,
            spl_norm        FLOAT,
            cetacean_norm   FLOAT,
            species_weight  FLOAT NOT NULL DEFAULT 1.0,
            risk_index      FLOAT NOT NULL,
            risk_level      TEXT NOT NULL,
            data_gap        BOOLEAN NOT NULL DEFAULT FALSE,
            noise_source    TEXT,
            cetacean_count  INTEGER,
            max_species     TEXT,
            computed_at     TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS noise_risk_geom_idx
        ON noise_risk_grid USING GIST(geom)
    """)
    await conn.execute("ALTER TABLE noise_risk_grid OWNER TO abyssal_user")
    # Migrate deployments that pre-date the pbd_norm/spl_norm split — CREATE
    # TABLE IF NOT EXISTS above is a no-op once the table already exists.
    await conn.execute(
        "ALTER TABLE noise_risk_grid ADD COLUMN IF NOT EXISTS pbd_norm FLOAT"
    )
    await conn.execute(
        "ALTER TABLE noise_risk_grid ADD COLUMN IF NOT EXISTS spl_norm FLOAT"
    )
    # noise_norm here was the same blended, NOT NULL column noise_cells used to
    # have. The table is fully TRUNCATEd and rebuilt by noise_risk_compute.py
    # on every run, so there is no historical data to preserve across the drop.
    await conn.execute(
        "ALTER TABLE noise_risk_grid DROP COLUMN IF EXISTS noise_norm"
    )


async def ensure_vents_and_chess(conn) -> None:
    """drop deprecated GBIF table; chess_occurrences; hydrothermal_vents InterRidge/ChEssBase enrichment."""

    try:
        for tbl in ("onc_sparklines", "onc_adcp_strips",
                    "onc_ctd_profiles", "usgs_earthquakes"):
            await conn.execute(f"ALTER TABLE {tbl} OWNER TO abyssal_user")
    except Exception:
        pass

    # Drop the deprecated GBIF deep-sea occurrence table — its coverage was a strict
    # subset of OBIS at the same depth filter, and GBIF citation guidelines required a
    # per-download DOI tracking layer we did not implement. ChEssBase remains.
    await conn.execute("DROP TABLE IF EXISTS gbif_occurrences CASCADE")

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS chess_occurrences (
            id               SERIAL PRIMARY KEY,
            occurrence_id    TEXT UNIQUE NOT NULL,
            species          TEXT,
            phylum           TEXT,
            class_name       TEXT,
            family           TEXT,
            depth_m          DOUBLE PRECISION,
            lat              DOUBLE PRECISION NOT NULL,
            lon              DOUBLE PRECISION NOT NULL,
            locality         TEXT,
            institution_code TEXT,
            habitat_type     TEXT NOT NULL,
            geom             GEOMETRY(Point, 4326)
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS chess_habitat_idx
        ON chess_occurrences (habitat_type)
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS chess_occurrences_geom_idx
        ON chess_occurrences USING GIST(geom)
    """)
    # InterRidge enrichment columns (added 2026-04)
    for col, defn in [
        ("max_temp_c",         "FLOAT"),
        ("temp_category",      "TEXT"),
        ("min_depth_m",        "FLOAT"),
        ("ocean",              "TEXT"),
        ("region",             "TEXT"),
        ("jurisdiction",       "TEXT"),
        ("tectonic_setting",   "TEXT"),
        ("discovery_year",     "TEXT"),
        ("biology_notes",      "TEXT"),
        ("description_notes",  "TEXT"),
    ]:
        try:
            await conn.execute(
                f"ALTER TABLE hydrothermal_vents ADD COLUMN IF NOT EXISTS {col} {defn}"
            )
        except Exception:
            pass
    # Enrich hydrothermal_vents with ChEssBase species data
    for col, defn in [
        ("chess_count",   "INTEGER DEFAULT 0"),
        ("chess_species", "JSONB DEFAULT '[]'"),
    ]:
        try:
            await conn.execute(
                f"ALTER TABLE hydrothermal_vents ADD COLUMN IF NOT EXISTS {col} {defn}"
            )
        except Exception:
            pass

    try:
        await conn.execute("ALTER TABLE chess_occurrences OWNER TO abyssal_user")
    except Exception:
        pass


async def ensure_sio_bic(conn) -> None:
    """sio_bic_records."""

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS sio_bic_records (
            catalog_id          BIGINT PRIMARY KEY,
            higher_taxa_code    TEXT,
            catalog_no          TEXT,
            phylum              TEXT,
            class_              TEXT,
            order_              TEXT,
            family              TEXT,
            genus               TEXT,
            species             TEXT,
            authority           TEXT,
            identifier          TEXT,
            type_status         TEXT,
            count               INTEGER,
            collection_type_raw TEXT,
            specimen_type       TEXT,
            fixative            TEXT,
            preservative        TEXT,
            storage_location    TEXT,
            reference_id        TEXT,
            loan_id             TEXT,
            gift_id             TEXT,
            catalog_notes       TEXT,
            genbank             TEXT,
            accession_no        TEXT,
            accession_id        TEXT,
            accession_date      DATE,
            station             TEXT,
            locality            TEXT,
            country             TEXT,
            ocean               TEXT,
            lat                 DOUBLE PRECISION NOT NULL,
            lon                 DOUBLE PRECISION NOT NULL,
            end_lat             DOUBLE PRECISION,
            end_lon             DOUBLE PRECISION,
            begin_depth_m       REAL,
            end_depth_m         REAL,
            depth_unit          TEXT,
            collection_date     DATE,
            collection_time     TEXT,
            gear                TEXT,
            ship                TEXT,
            collector           TEXT,
            remarks             TEXT,
            geom                GEOGRAPHY(POINT, 4326) GENERATED ALWAYS AS (
                                    ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography
                                ) STORED,
            fetched_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS sio_bic_records_geom_idx "
        "ON sio_bic_records USING GIST (geom)"
    )
    try:
        await conn.execute("ALTER TABLE sio_bic_records OWNER TO abyssal_user")
    except Exception:
        pass


async def ensure_deepdata(conn) -> None:
    """deepdata_occurrences, deepdata_dwc_archives, deepdata_stations."""

    # ── ISA DeepData (contractor environmental reports, via OBIS) ─────────
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS deepdata_occurrences (
            obis_id          UUID PRIMARY KEY,
            occurrence_id    TEXT,
            dataset_id       UUID,
            dataset_title    TEXT,
            contractor_code  TEXT,
            rights_holder    TEXT,
            scientific_name  TEXT,
            phylum           TEXT,
            class_           TEXT,
            order_           TEXT,
            family           TEXT,
            genus            TEXT,
            species          TEXT,
            basis_of_record  TEXT,
            depth_m          REAL,
            lat              DOUBLE PRECISION NOT NULL,
            lon              DOUBLE PRECISION NOT NULL,
            event_date       TIMESTAMPTZ,
            locality         TEXT,
            geom             GEOGRAPHY(POINT, 4326) GENERATED ALWAYS AS (
                                 ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography
                             ) STORED,
            fetched_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS deepdata_occurrences_geom_gix "
        "ON deepdata_occurrences USING GIST (geom)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS deepdata_occurrences_contractor_idx "
        "ON deepdata_occurrences (contractor_code)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS deepdata_occurrences_dataset_idx "
        "ON deepdata_occurrences (dataset_id)"
    )
    try:
        await conn.execute("ALTER TABLE deepdata_occurrences OWNER TO abyssal_user")
    except Exception:
        pass

    # ── ISA DeepData ANALYTICS tier (platform-derived sampling stations) ──
    # Tier 2 in our DeepData architecture; tier 1 is `deepdata_occurrences`
    # which is the raw OBIS-REST mirror and stays untouched. These two
    # tables are populated from the OBIS-hosted DwC archives and feed the
    # `deepdata-stations` map layer + per-contractor coverage view.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS deepdata_dwc_archives (
            slug             TEXT PRIMARY KEY,
            title            TEXT,
            citation         TEXT,
            license          TEXT,
            rights_holder    TEXT,
            pub_date         DATE,
            last_modified    TIMESTAMPTZ,
            etag             TEXT,
            content_length   BIGINT,
            occurrence_count INTEGER,
            station_count    INTEGER,
            last_fetched_at  TIMESTAMPTZ,
            last_parsed_at   TIMESTAMPTZ,
            parse_error      TEXT
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS deepdata_stations (
            station_id          TEXT PRIMARY KEY,
            archive_slug        TEXT NOT NULL REFERENCES deepdata_dwc_archives(slug) ON DELETE CASCADE,
            contractor_code     TEXT,
            event_id_raw        TEXT,
            location_id         TEXT,
            sampling_protocol   TEXT,
            lat                 DOUBLE PRECISION NOT NULL,
            lon                 DOUBLE PRECISION NOT NULL,
            depth_m_min         REAL,
            depth_m_max         REAL,
            coord_uncertainty_m REAL,
            first_event_date    TIMESTAMPTZ,
            last_event_date     TIMESTAMPTZ,
            occurrence_count    INTEGER NOT NULL,
            species_count       INTEGER,
            top_species         TEXT[],
            top_phyla           TEXT[],
            sediment_horizons   TEXT[],
            geom                GEOGRAPHY(POINT, 4326) GENERATED ALWAYS AS (
                                    ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography
                                ) STORED,
            derived_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS deepdata_stations_geom_gix "
        "ON deepdata_stations USING GIST (geom)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS deepdata_stations_contractor_idx "
        "ON deepdata_stations (contractor_code)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS deepdata_stations_archive_idx "
        "ON deepdata_stations (archive_slug)"
    )
    # Migrate older deployments that pre-date top_species/top_phyla.
    await conn.execute(
        "ALTER TABLE deepdata_stations ADD COLUMN IF NOT EXISTS top_species TEXT[]"
    )
    await conn.execute(
        "ALTER TABLE deepdata_stations ADD COLUMN IF NOT EXISTS top_phyla TEXT[]"
    )
    try:
        await conn.execute("ALTER TABLE deepdata_dwc_archives OWNER TO abyssal_user")
        await conn.execute("ALTER TABLE deepdata_stations OWNER TO abyssal_user")
    except Exception:
        pass


async def ensure_mbari(conn) -> None:
    """mbari_vars_records."""

    # ── MBARI VARS deep-sea ROV observations (density-source mirror) ──
    # Already in our biodiversity_hotspots via OBIS parquet; surfaced
    # separately here so the panel can credit MBARI by name.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS mbari_vars_records (
            obis_id          UUID PRIMARY KEY,
            occurrence_id    TEXT,
            dataset_id       UUID,
            scientific_name  TEXT,
            phylum           TEXT,
            class_           TEXT,
            order_           TEXT,
            family           TEXT,
            genus            TEXT,
            species          TEXT,
            basis_of_record  TEXT,
            depth_m          REAL,
            lat              DOUBLE PRECISION NOT NULL,
            lon              DOUBLE PRECISION NOT NULL,
            event_date       TIMESTAMPTZ,
            locality         TEXT,
            geom             GEOGRAPHY(POINT, 4326) GENERATED ALWAYS AS (
                                 ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography
                             ) STORED,
            fetched_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS mbari_vars_records_geom_gix "
        "ON mbari_vars_records USING GIST (geom)"
    )
    try:
        await conn.execute("ALTER TABLE mbari_vars_records OWNER TO abyssal_user")
    except Exception:
        pass


async def ensure_noaa_corals(conn) -> None:
    """noaa_corals_records."""

    # ── NOAA Deep-Sea Coral & Sponge (DSCRTP) — density-source ──
    # ~1.5 M records via NOAA's ArcGIS FeatureServer. Public domain.
    # Surfaced separately so the density panel can credit NOAA DSCRTP
    # by name in NW Atlantic / Gulf / Pacific NW cells where it dominates.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS noaa_corals_records (
            catalog_number          TEXT PRIMARY KEY,
            object_id               BIGINT,
            sample_id               TEXT,
            event_id                TEXT,
            dataset_id              TEXT,
            data_provider           TEXT,
            scientific_name         TEXT,
            verbatim_scientific_name TEXT,
            synonyms                TEXT,
            vernacular_name_category TEXT,
            identification_qualifier TEXT,
            phylum                  TEXT,
            class_                  TEXT,
            order_                  TEXT,
            family                  TEXT,
            genus                   TEXT,
            aphia_id                INTEGER,
            taxon_rank              TEXT,
            depth_m                 REAL,
            lat                     DOUBLE PRECISION NOT NULL,
            lon                     DOUBLE PRECISION NOT NULL,
            locality                TEXT,
            ocean_code              TEXT,
            fish_council_region     TEXT,
            vessel                  TEXT,
            sampling_equipment      TEXT,
            pi                      TEXT,
            survey_id               TEXT,
            image_url               TEXT,
            highlight_image_url     TEXT,
            temperature             REAL,   -- DSCRTP 'Temperature'; source states no unit
            salinity                REAL,   -- DSCRTP 'Salinity'; source states no unit
            oxygen                  REAL,   -- DSCRTP 'Oxygen'; source states no unit
            observation_year        INTEGER,
            event_date              TIMESTAMPTZ,
            geom                    GEOGRAPHY(POINT, 4326) GENERATED ALWAYS AS (
                                        ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography
                                    ) STORED,
            fetched_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS noaa_corals_records_geom_gix "
        "ON noaa_corals_records USING GIST (geom)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS noaa_corals_records_event_date_idx "
        "ON noaa_corals_records (event_date)"
    )
    try:
        await conn.execute("ALTER TABLE noaa_corals_records OWNER TO abyssal_user")
    except Exception:
        pass

    # Existing tables carry the old unit-asserting column names; a fresh
    # CREATE TABLE IF NOT EXISTS is a no-op against them, so rename explicitly.
    await conn.execute("""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM information_schema.columns
                     WHERE table_name='noaa_corals_records' AND column_name='oxygen_ml_l')
          AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='noaa_corals_records' AND column_name='oxygen')
          THEN ALTER TABLE noaa_corals_records RENAME COLUMN oxygen_ml_l TO oxygen;
          END IF;
        END $$
    """)
    await conn.execute("""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM information_schema.columns
                     WHERE table_name='noaa_corals_records' AND column_name='salinity_psu')
          AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='noaa_corals_records' AND column_name='salinity')
          THEN ALTER TABLE noaa_corals_records RENAME COLUMN salinity_psu TO salinity;
          END IF;
        END $$
    """)
    await conn.execute("""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM information_schema.columns
                     WHERE table_name='noaa_corals_records' AND column_name='temperature_c')
          AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='noaa_corals_records' AND column_name='temperature')
          THEN ALTER TABLE noaa_corals_records RENAME COLUMN temperature_c TO temperature;
          END IF;
        END $$
    """)


async def ensure_worms(conn) -> None:
    """worms_taxa, taxon_name_map."""

    # ── WoRMS taxonomic backbone (crosswalk; never mutates source tables) ──
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS worms_taxa (
            aphia_id        INTEGER PRIMARY KEY,
            scientificname  TEXT,
            authority       TEXT,
            rank            TEXT,
            status          TEXT,
            kingdom         TEXT,
            phylum          TEXT,
            class_name      TEXT,
            order_name      TEXT,
            family          TEXT,
            genus           TEXT,
            is_marine       SMALLINT,
            is_brackish     SMALLINT,
            is_freshwater   SMALLINT,
            is_terrestrial  SMALLINT,
            citation        TEXT,
            url             TEXT,
            worms_modified  TIMESTAMPTZ,
            fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    await conn.execute("ALTER TABLE worms_taxa OWNER TO abyssal_user")
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS taxon_name_map (
            raw_name          TEXT PRIMARY KEY,
            matched_aphia_id  INTEGER REFERENCES worms_taxa(aphia_id) ON DELETE SET NULL,
            match_type        TEXT NOT NULL DEFAULT 'none',
            verified          BOOLEAN NOT NULL DEFAULT FALSE,
            first_source      TEXT,
            resolved_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS taxon_name_map_aphia_idx "
        "ON taxon_name_map(matched_aphia_id) WHERE verified"
    )
    await conn.execute("ALTER TABLE taxon_name_map OWNER TO abyssal_user")


