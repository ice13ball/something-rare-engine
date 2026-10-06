# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""GLODAPv3 bottle casts. DDL is a function of the table name so the worker can build
`<table>_new` from the same text and swap names in one transaction (pattern: schema/plankton.py)."""
from __future__ import annotations

from ingestion.glodap_bottles_rules import VARIABLES, QC_VARIABLES

_VAR_COLS = ",\n".join(f"  {v} real[], {v}_f smallint[]" for v in VARIABLES)
_QC_COLS = ",\n".join(f"  {v}_qc smallint" for v in QC_VARIABLES)

# Column order for copy_records_to_table (geom and id are generated, so absent).
CAST_COLUMNS = ("cast_key", "expocode", "station", "cast_no", "platform_code", "lat", "lon", "year",
                "obs_date", "obs_time", "time_precision", "region", "doi", "bottom_depth_m",
                "max_samp_depth_m", "pos_spread_km", "n_samples", "n_good", "depth_m", "pressure_dbar",
                "bottle", *[c for v in VARIABLES for c in (v, f"{v}_f")], *[f"{v}_qc" for v in QC_VARIABLES],
                "levels")


def casts_ddl(table: str) -> list[str]:
    return [f"""
CREATE TABLE IF NOT EXISTS {table} (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cast_key text NOT NULL UNIQUE,
  expocode text NOT NULL,
  station text NOT NULL,
  cast_no integer,                       -- NULL: the source gives this cast no number (key suffix `nc`)
  platform_code text,
  lat double precision NOT NULL CHECK (lat BETWEEN -90 AND 90),
  lon double precision NOT NULL CHECK (lon BETWEEN -180 AND 180),
  geom geometry(Point, 4326) GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(lon, lat), 4326)) STORED NOT NULL,
  year smallint NOT NULL,
  obs_date date NOT NULL,
  obs_time timestamptz,
  time_precision text NOT NULL CHECK (time_precision IN ('minute','day')),
  region smallint NOT NULL,
  doi text,
  bottom_depth_m real,
  max_samp_depth_m real,
  pos_spread_km real NOT NULL,
  n_samples smallint NOT NULL,
  n_good integer NOT NULL,
  depth_m real[] NOT NULL,
  pressure_dbar real[],
  bottle real[],
{_VAR_COLS},
{_QC_COLS},
  levels jsonb NOT NULL
)""", f"ALTER TABLE {table} OWNER TO abyssal_user"]


def casts_index_ddl(table: str) -> list[str]:
    return [f"CREATE INDEX IF NOT EXISTS {table}_expocode_idx ON {table} (expocode)",
            f"CREATE INDEX IF NOT EXISTS {table}_year_idx ON {table} (year)",
            f"CREATE INDEX IF NOT EXISTS {table}_geom_gix ON {table} USING gist (geom)"]


def cruises_ddl(table: str) -> list[str]:
    return [f"""
CREATE TABLE IF NOT EXISTS {table} (
  expocode text PRIMARY KEY,
  platform_code text,
  ship_name text,
  doi text,
  first_date date NOT NULL,
  last_date date NOT NULL,
  n_casts integer NOT NULL,
  first_cast_key text NOT NULL,
  lat double precision NOT NULL,
  lon double precision NOT NULL
)""", f"ALTER TABLE {table} OWNER TO abyssal_user"]


def source_ddl() -> list[str]:
    return ["""
CREATE TABLE IF NOT EXISTS glodap_bottle_source (
  id smallint PRIMARY KEY CHECK (id = 1),
  source_url text, etag text, content_length bigint, last_modified text, sha256 text,
  loaded_at timestamptz, last_checked_at timestamptz, refresh_requested_at timestamptz,
  n_rows_source integer, n_rows_depthless integer, n_casts integer, n_casts_drawn integer,
  n_samples integer, ship_lookup_failed integer
)""", "INSERT INTO glodap_bottle_source (id) VALUES (1) ON CONFLICT (id) DO NOTHING",
            "ALTER TABLE glodap_bottle_source OWNER TO abyssal_user",
            # Worker health and the last load's rejects live HERE, not in sync_log.skipped_reason, which the
            # daily timer would overwrite. last_failed_at starts a 7-day back-off (see glodap_bottles_worker).
            "ALTER TABLE glodap_bottle_source ADD COLUMN IF NOT EXISTS last_failed_at timestamptz, "
            "ADD COLUMN IF NOT EXISTS last_failure text, ADD COLUMN IF NOT EXISTS last_run_at timestamptz, "
            "ADD COLUMN IF NOT EXISTS last_decision text, ADD COLUMN IF NOT EXISTS last_rejects jsonb, "
            "ADD COLUMN IF NOT EXISTS last_rejects_at timestamptz"]


async def ensure_glodap_bottles(conn) -> None:
    """glodap_casts, glodap_cruises (empty until the worker's first swap), glodap_bottle_source."""
    for sql in (casts_ddl("glodap_casts") + casts_index_ddl("glodap_casts")
                + cruises_ddl("glodap_cruises") + source_ddl()):
        await conn.execute(sql)
