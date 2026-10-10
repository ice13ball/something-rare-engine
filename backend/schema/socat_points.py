# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""SOCAT v2026 observation points. DDL is a function of the table name so the worker can build
`<table>_new` from the same text and swap names in one transaction (pattern: schema/glodap_bottles.py).

Every index name is derived from the table name (`{table}_bbox_gix`, ...), so after the swap renames
`socat_segments_new` -> `socat_segments` the worker renames each index by the same derivation and a
second build finds the names free again. See `index_names()`.

Rulings: C1 geometry is built in SQL (the loader COPYs plain typed arrays), C2 `bbox` is always a
5-vertex polygon (ST_MakeEnvelope(min, max) in SQL, never ST_Envelope: a 1-obs or flat segment would be
a POINT/LINESTRING and fail the typmod), C4 rejected rows are stored with `qc_flag` and filtered in
the tile SQL, not at load time. Elements of sst/sal that are NaN in the source are NULL.
"""
from __future__ import annotations

LOD_LEVELS = (0, 1, 2, 3)

# Column order for copy_records_to_table into the per-batch staging (bbox is built by INSERT...SELECT).
SEGMENT_COLUMNS = ("expocode", "qc_flag", "ord0", "n_obs", "t0", "lon", "lat", "dt_s", "fco2",
                   "sst", "sal", "fco2_src", "fco2_flag", "year_min", "year_max")

_SEGMENTS = """
CREATE TABLE IF NOT EXISTS {t} (
  seg_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  expocode text NOT NULL,
  qc_flag char(1) NOT NULL,  -- cruise QC A-E, copied per segment (C4)
  ord0 integer NOT NULL,  -- 0-based ordinal of the first observation within the cruise
  n_obs smallint NOT NULL CHECK (n_obs BETWEEN 1 AND 512),
  t0 timestamptz NOT NULL,  -- UTC time of the first observation
  lon real[] NOT NULL,  -- degrees east, folded to [-180,180)
  lat real[] NOT NULL,  -- degrees north
  dt_s integer[] NOT NULL,  -- seconds after t0 (UTC)
  fco2 real[] NOT NULL,  -- fCO2rec, microatmospheres (uatm)
  sst real[] NOT NULL,  -- deg C, NULL element = NaN in the source
  sal real[] NOT NULL,  -- PSS-78, NULL element = NaN in the source
  fco2_src smallint[] NOT NULL,  -- source code of the fCO2 value (as in the file)
  fco2_flag smallint[] NOT NULL,  -- WOCE flag, 2 = good (tiles draw only 2)
  year_min smallint NOT NULL,  -- UTC years
  year_max smallint NOT NULL,
  bbox geometry(Polygon, 3857) NOT NULL  -- EPSG:3857 metres, ST_MakeEnvelope, always 5 vertices (C2)
)"""

_LOD = """
CREATE TABLE IF NOT EXISTS {t} (
  level smallint NOT NULL CHECK (level BETWEEN 0 AND 3),
  expocode text NOT NULL,
  qc_flag char(1) NOT NULL,  -- cruise QC A-E, copied per segment (C4)
  n0 integer NOT NULL,  -- observations in the first source piece
  n_obs integer NOT NULL,  -- observations represented by this piece
  year smallint NOT NULL,  -- UTC year
  fco2 real,  -- mean uatm over the piece, NULL when none
  sst real,  -- mean deg C, NULL when none
  sal real,  -- mean PSS-78, NULL when none
  geom geometry(Geometry, 3857) NOT NULL CHECK (GeometryType(geom) IN ('POINT','LINESTRING'))
)"""

_CRUISES = """
CREATE TABLE IF NOT EXISTS {t} (
  expocode text PRIMARY KEY,
  version text,
  dataset_name text,
  platform_name text,
  pis text,
  source_doi text,
  source_reference text,
  qc_flag char(1) NOT NULL CHECK (qc_flag IN ('A','B','C','D','E')),
  metadata_docs text,
  first_time timestamptz NOT NULL,  -- UTC
  last_time timestamptz NOT NULL,
  n_obs integer NOT NULL,  -- observations stored for the cruise (rejected rows included)
  n_segments integer NOT NULL,
  n_rejected integer NOT NULL,  -- rows stored but not drawn (QC E or WOCE flag not 2)
  west real,  -- degrees, bounding box of valid points
  east real,
  south real,
  north real,
  crosses_antimeridian boolean NOT NULL
)"""

_SOURCE = """
CREATE TABLE IF NOT EXISTS socat_points_source (
  id smallint PRIMARY KEY CHECK (id = 1),
  source_url text, etag text, content_length bigint, last_modified text, sha256 text, release text,
  report_created text, loaded_at timestamptz, last_checked_at timestamptz, refresh_requested_at timestamptz,
  n_rows_source integer, n_rows_stored integer, n_rows_rejected integer, n_cruises integer,
  n_datasets_listed integer, n_segments integer, lod_counts jsonb, qc_counts jsonb,
  year_min smallint, year_max smallint, tile_version text, tile_built_at timestamptz,
  last_run_at timestamptz, last_decision text, last_failed_at timestamptz, last_failure text,
  last_rejects jsonb, last_rejects_at timestamptz,
  staging_sha256 text, staging_last_expocode text, staging_rows integer, staging_started_at timestamptz,
  interrupted_expocode text, interrupt_count integer
)"""


def _fmt(tpl: str, table: str) -> str:
    return tpl.replace("{t}", table)


def _owner(table: str) -> str:
    return f"ALTER TABLE {table} OWNER TO abyssal_user"


def segments_ddl(table: str) -> list[str]:
    return [_fmt(_SEGMENTS, table), _owner(table)]


def segments_index_ddl(table: str) -> list[str]:
    return [f"CREATE INDEX IF NOT EXISTS {table}_bbox_gix ON {table} USING gist (bbox)",
            f"CREATE INDEX IF NOT EXISTS {table}_expocode_ord0_idx ON {table} (expocode, ord0)"]


def lod_ddl(table: str) -> list[str]:
    return [_fmt(_LOD, table), _owner(table)]


def lod_index_ddl(table: str) -> list[str]:
    return [f"CREATE INDEX IF NOT EXISTS {table}_l{lv}_gix ON {table} USING gist (geom) WHERE level = {lv}"
            for lv in LOD_LEVELS]


def cruises_ddl(table: str) -> list[str]:
    return [_fmt(_CRUISES, table), _owner(table)]


def staging_autovacuum_off(table: str) -> str:
    """For `<table>_new` ONLY; the swap re-enables it (autovacuum must not chew a half-built staging)."""
    return f"ALTER TABLE {table} SET (autovacuum_enabled = false)"


def index_names(table: str) -> list[str]:
    """Every index the three tables carry, derived from the table name (for the swap's rename)."""
    if table.startswith("socat_segments"):
        return [f"{table}_bbox_gix", f"{table}_expocode_ord0_idx"]
    if table.startswith("socat_lod"):
        return [f"{table}_l{lv}_gix" for lv in LOD_LEVELS]
    return []


def source_ddl() -> list[str]:
    return [_SOURCE, "INSERT INTO socat_points_source (id) VALUES (1) ON CONFLICT (id) DO NOTHING",
            _owner("socat_points_source")]


async def ensure_socat_points(conn) -> None:
    """socat_segments, socat_lod, socat_cruises (empty until the worker's first swap), socat_points_source."""
    for sql in (segments_ddl("socat_segments") + segments_index_ddl("socat_segments")
                + lod_ddl("socat_lod") + lod_index_ddl("socat_lod")
                + cruises_ddl("socat_cruises") + source_ddl()):
        await conn.execute(sql)
