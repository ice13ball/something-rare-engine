# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""DDL for the Svalbard fjords primary-production preview layer (dev-only,
`svalbard-fjords-primary-production`).

Storage is 1:1 with the source, same discipline as schema/aoc2025_poc.py: one
column per CSV field plus `raw TEXT[]` of every cell verbatim. Versioned by
SHA-256 so a changed source file adds a version and deletes nothing; readers use
the `_current` view.
"""


async def ensure_svalbard_fjords_pp(conn) -> None:
    """svalbard_fjords_pp_version, svalbard_fjords_pp_samples + the *_current view."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS svalbard_fjords_pp_version (
            version_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            is_current     BOOLEAN NOT NULL DEFAULT false,
            doi            TEXT NOT NULL,
            source_url     TEXT NOT NULL,
            sha256         TEXT NOT NULL UNIQUE,
            rows_in_source INTEGER NOT NULL,
            citation       TEXT NOT NULL,
            licence        TEXT NOT NULL,
            fetched_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    await conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS svalbard_fjords_pp_version_one_current
            ON svalbard_fjords_pp_version (is_current) WHERE is_current
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS svalbard_fjords_pp_samples (
            version_id        BIGINT NOT NULL REFERENCES svalbard_fjords_pp_version (version_id),
            row_no            INTEGER NOT NULL,
            exposition_no     TEXT,
            sample_date       DATE,
            region_code       TEXT,
            fjord_part        TEXT,
            station           TEXT,
            lat               DOUBLE PRECISION,
            lon               DOUBLE PRECISION,
            depth_m           DOUBLE PRECISION,
            temperature_degc  DOUBLE PRECISION,
            salinity          DOUBLE PRECISION,
            ca_mg_m3          DOUBLE PRECISION,
            pe_mgc_m3_h       DOUBLE PRECISION,
            pi_mgc_m2_day     DOUBLE PRECISION,
            water_mass        TEXT,
            raw               TEXT[] NOT NULL,
            geom              geometry(Point, 4326),
            PRIMARY KEY (version_id, row_no)
        )
    """)
    await conn.execute(
        "COMMENT ON COLUMN svalbard_fjords_pp_samples.raw IS "
        "'All 14 source CSV cells verbatim, in source order. Storage is 1:1 with the source.'"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS svalbard_fjords_pp_samples_geom_gix "
        "ON svalbard_fjords_pp_samples USING GIST (geom)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS svalbard_fjords_pp_samples_expo_idx "
        "ON svalbard_fjords_pp_samples (version_id, exposition_no)"
    )
    await conn.execute("""
        CREATE OR REPLACE VIEW svalbard_fjords_pp_samples_current AS
        SELECT s.* FROM svalbard_fjords_pp_samples s
        JOIN svalbard_fjords_pp_version v ON v.version_id = s.version_id
        WHERE v.is_current
    """)
    for table in ("svalbard_fjords_pp_version", "svalbard_fjords_pp_samples"):
        await conn.execute(f"ALTER TABLE {table} OWNER TO abyssal_user")
    await conn.execute("ALTER VIEW svalbard_fjords_pp_samples_current OWNER TO abyssal_user")
