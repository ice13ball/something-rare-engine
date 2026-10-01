# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""DDL for the two PANGAEA water-column layers.

Storage is 1:1 with the source: one column per source position (names carry the
unit), every row including those without coordinates, and `raw` — every cell
verbatim, in source order. Serving hides fields; storage never does.

Versions: every sample row carries `version_id`. A changed source file inserts a
NEW version and flips `is_current` in one transaction; nothing is ever deleted.
Readers use the *_current views, so old versions never leak into the API.
"""


async def ensure_pangaea_water(conn) -> None:
    """pangaea_dataset_version, coastdom_samples, greenland_pp_stations + *_current views."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS pangaea_dataset_version (
            version_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            layer_id         TEXT NOT NULL,
            is_current       BOOLEAN NOT NULL DEFAULT false,
            doi              TEXT NOT NULL,
            date_published   DATE,
            sha256           TEXT NOT NULL,
            rows_in_source   INTEGER NOT NULL,
            rows_unmappable  INTEGER NOT NULL,
            data_points      INTEGER NOT NULL,
            header           TEXT[] NOT NULL,
            citation         TEXT,
            related_citation TEXT,
            license          TEXT,
            ingested_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (layer_id, sha256)
        )
    """)
    await conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS pangaea_dataset_version_one_current
            ON pangaea_dataset_version (layer_id) WHERE is_current
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS coastdom_samples (
            version_id      BIGINT NOT NULL REFERENCES pangaea_dataset_version (version_id),
            row_no          INTEGER NOT NULL,
            location        TEXT,
            sample_id       TEXT,
            sample_date     DATE,
            lat             DOUBLE PRECISION,
            lon             DOUBLE PRECISION,
            elevation_m     DOUBLE PRECISION,
            depth_m         DOUBLE PRECISION,
            temp_c          DOUBLE PRECISION,
            sal             DOUBLE PRECISION,
            tss_mg_l        DOUBLE PRECISION,
            chl_a_ug_l      DOUBLE PRECISION,
            qf_chl_a        SMALLINT,
            no3_no2_umol_l  DOUBLE PRECISION,
            qf_no3_no2      SMALLINT,
            nh4_umol_l      DOUBLE PRECISION,
            qf_nh4          SMALLINT,
            hpo4_umol_l     DOUBLE PRECISION,
            qf_hpo4         SMALLINT,
            doc_umol_l      DOUBLE PRECISION,
            doc_method      TEXT,
            qf_doc          SMALLINT,
            don_umol_l      DOUBLE PRECISION,
            tdn_umol_l      DOUBLE PRECISION,
            tdn_method      TEXT,
            qf_tdn          SMALLINT,
            dop_umol_l      DOUBLE PRECISION,
            tdp_umol_l      DOUBLE PRECISION,
            tdp_method      TEXT,
            qf_tdp          SMALLINT,
            poc_umol_l      DOUBLE PRECISION,
            poc_method      TEXT,
            qf_poc          SMALLINT,
            pn_umol_l       DOUBLE PRECISION,
            pn_method       TEXT,
            qf_tpn          SMALLINT,
            pp_umol_l       DOUBLE PRECISION,
            pp_method       TEXT,
            qf_pp           SMALLINT,
            dic_umol_kg     DOUBLE PRECISION,
            qf_dic          SMALLINT,
            at_umol_kg      DOUBLE PRECISION,
            qf_at           SMALLINT,
            pi              TEXT,
            institution     TEXT,
            pi_email        TEXT,
            ref_1           TEXT,
            ref_2           TEXT,
            ref_3           TEXT,
            comment         TEXT,
            raw             TEXT[] NOT NULL,
            geom            geometry(Point, 4326),
            PRIMARY KEY (version_id, row_no)
        )
    """)
    await conn.execute(
        "COMMENT ON COLUMN coastdom_samples.pi_email IS "
        "'Stored because storage is 1:1 with the source. Never served: HIDDEN_FIELDS in domains/pangaea_water.py.'"
    )
    await conn.execute(
        "COMMENT ON COLUMN coastdom_samples.raw IS "
        "'All 49 source cells verbatim, in source order. Contains the pi_email cell, so never served.'"
    )
    await conn.execute("CREATE INDEX IF NOT EXISTS coastdom_samples_geom_gix ON coastdom_samples USING GIST (geom)")
    await conn.execute("CREATE INDEX IF NOT EXISTS coastdom_samples_pos_idx ON coastdom_samples (version_id, lat, lon)")
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS greenland_pp_stations (
            version_id       BIGINT NOT NULL REFERENCES pangaea_dataset_version (version_id),
            row_no           INTEGER NOT NULL,
            event            TEXT,
            event_2          TEXT,
            lat              DOUBLE PRECISION,
            lon              DOUBLE PRECISION,
            sample_date      DATE,
            gpp_c_mg_m2_day  DOUBLE PRECISION,
            raw              TEXT[] NOT NULL,
            geom             geometry(Point, 4326),
            PRIMARY KEY (version_id, row_no)
        )
    """)
    await conn.execute(
        "COMMENT ON COLUMN greenland_pp_stations.gpp_c_mg_m2_day IS "
        "'GPP C [mg/m**2/day] — an areal rate, never a concentration.'"
    )
    await conn.execute("CREATE INDEX IF NOT EXISTS greenland_pp_stations_geom_gix ON greenland_pp_stations USING GIST (geom)")
    await conn.execute("""
        CREATE OR REPLACE VIEW coastdom_samples_current AS
        SELECT s.* FROM coastdom_samples s
        JOIN pangaea_dataset_version v ON v.version_id = s.version_id
        WHERE v.is_current AND v.layer_id = 'coastdom'
    """)
    await conn.execute("""
        CREATE OR REPLACE VIEW greenland_pp_stations_current AS
        SELECT s.* FROM greenland_pp_stations s
        JOIN pangaea_dataset_version v ON v.version_id = s.version_id
        WHERE v.is_current AND v.layer_id = 'greenland-primary-production'
    """)
    for table in ("pangaea_dataset_version", "coastdom_samples", "greenland_pp_stations"):
        await conn.execute(f"ALTER TABLE {table} OWNER TO abyssal_user")
    for view in ("coastdom_samples_current", "greenland_pp_stations_current"):
        await conn.execute(f"ALTER VIEW {view} OWNER TO abyssal_user")
