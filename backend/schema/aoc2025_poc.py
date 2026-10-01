# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""DDL for the AOC2025 POC preview layer (dev-only, `greenland-sea-poc-aoc2025`).

Storage is 1:1 with the source, same discipline as schema/pangaea_water.py: one
column per CSV field plus `raw TEXT[]` of every cell verbatim. Versioned by
SHA-256 so a changed source file adds a version and deletes nothing; readers use
the `_current` view.
"""


async def ensure_aoc2025_poc(conn) -> None:
    """aoc2025_poc_version, aoc2025_poc_samples + the *_current view."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS aoc2025_poc_version (
            version_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            is_current     BOOLEAN NOT NULL DEFAULT false,
            doi            TEXT NOT NULL,
            source_url     TEXT NOT NULL,
            sha256         TEXT NOT NULL UNIQUE,
            rows_in_source INTEGER NOT NULL,
            citation       TEXT NOT NULL,
            license        TEXT NOT NULL,
            fetched_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    await conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS aoc2025_poc_version_one_current
            ON aoc2025_poc_version (is_current) WHERE is_current
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS aoc2025_poc_samples (
            version_id    BIGINT NOT NULL REFERENCES aoc2025_poc_version (version_id),
            row_no        INTEGER NOT NULL,
            cruise_id     TEXT,
            station       TEXT,
            sample_date   TIMESTAMPTZ,
            lat           DOUBLE PRECISION,
            lon           DOUBLE PRECISION,
            prespr01_db   DOUBLE PRECISION,
            pressure_db   DOUBLE PRECISION,
            activity      TEXT,
            sample_id     TEXT,
            salinity      DOUBLE PRECISION,
            temp_c        DOUBLE PRECISION,
            d15n_permil   DOUBLE PRECISION,
            d13c_permil   DOUBLE PRECISION,
            poc_mg_dm3    DOUBLE PRECISION,
            pn_mg_dm3     DOUBLE PRECISION,
            raw           TEXT[] NOT NULL,
            geom          geometry(Point, 4326),
            PRIMARY KEY (version_id, row_no)
        )
    """)
    await conn.execute(
        "COMMENT ON COLUMN aoc2025_poc_samples.raw IS "
        "'All 15 source CSV cells verbatim, in source order. Storage is 1:1 with the source.'"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS aoc2025_poc_samples_geom_gix ON aoc2025_poc_samples USING GIST (geom)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS aoc2025_poc_samples_station_idx ON aoc2025_poc_samples (version_id, station)"
    )
    await conn.execute("""
        CREATE OR REPLACE VIEW aoc2025_poc_samples_current AS
        SELECT s.* FROM aoc2025_poc_samples s
        JOIN aoc2025_poc_version v ON v.version_id = s.version_id
        WHERE v.is_current
    """)
    for table in ("aoc2025_poc_version", "aoc2025_poc_samples"):
        await conn.execute(f"ALTER TABLE {table} OWNER TO abyssal_user")
    await conn.execute("ALTER VIEW aoc2025_poc_samples_current OWNER TO abyssal_user")
