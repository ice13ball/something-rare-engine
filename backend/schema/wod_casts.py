# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""World Ocean Database casts (OSD, CTD, PFL): DDL as text. Units and NULL semantics sit in the column comments.

`{t}` appears only in the wod_cells text: that table is built as `wod_cells_new` and swapped, so every index
name is derived from the table name (`cells_index_names`). `wod_casts` is never built as `_new`, its index
names are fixed. The unlogged staging tables are NOT part of `ensure_wod_casts`: the loader creates them
itself through `staging_ddl()` (an unlogged CREATE inside ensure_schema would also be a second DDL surface
for the snapshot). No statement contains a semicolon, the DDL snapshot splits on it.
"""
from __future__ import annotations

WOD_CASTS = """
CREATE TABLE IF NOT EXISTS wod_casts (
  cast_id integer PRIMARY KEY,  -- WOD wod_unique_cast (unique across the WOD files)
  file_id smallint NOT NULL,  -- wod_files.file_id this row was loaded from
  instrument text NOT NULL CHECK (instrument IN ('osd','ctd','pfl')),
  dataset text,  -- WOD dataset as in the file: CTD, XCTD, bottle/rosette/net, profiling float, ...
  lat real NOT NULL,  -- degrees north as in the file
  lon real NOT NULL,  -- degrees east as in the file (-180..180)
  cast_date date,  -- UTC, precision in time_precision
  cast_time timestamptz,  -- only when the time of day was recorded (time_precision = 'second')
  time_precision text CHECK (time_precision IN ('second','day','month','year')),
  year smallint,  -- UTC year of cast_date, NULL = no date in the source (stored, never drawn)
  cruise text, orig_cruise text, platform text, vehicle text, wmo_id text, institute text, project text,
  country text, t_instrument text, o2_instrument text, real_time text,
  access_no integer,  -- NCEI accession of the originator's data
  depth real[] NOT NULL,  -- metres below the sea surface (WOD z, positive down): union of the kept levels
  depth_flag bytea NOT NULL,  -- z_WODflag per depth element
  t real[],  -- degree_C (file attribute), element NULL = no value at that depth, column NULL = not measured
  s real[],  -- practical salinity, WOD declares NO unit for Salinity
  o real[],  -- umol/kg (file attribute)
  p real[],  -- phosphate, umol/kg
  i real[],  -- silicate, umol/kg
  n real[],  -- nitrate, umol/kg
  t_f bytea, s_f bytea, o_f bytea, p_f bytea, i_f bytea, n_f bytea,  -- Var_WODflag per depth element, 255 = no value
  pflag smallint[] NOT NULL,  -- Var_WODprofileflag in t,s,o,p,i,n order, NULL element = variable absent
  n_src integer[] NOT NULL,  -- non-fill levels per variable in the source, before thinning
  n_good integer NOT NULL  -- values with flag 0, depth flag 0 and profile flag 0, all variables
)"""

POINTS = """
CREATE TABLE IF NOT EXISTS wod_cast_points (
  cast_id integer NOT NULL,  -- = wod_casts.cast_id, only drawable casts (n_good > 0 and a year)
  file_id smallint NOT NULL,
  year smallint NOT NULL,  -- UTC
  key bigint NOT NULL,  -- Morton key, 2^20 x 2^20 grid over EPSG:3857 (wod_casts_rules.morton_key)
  x real NOT NULL, y real NOT NULL,  -- EPSG:3857 metres, latitude clamped to +-85.0511
  picks smallint[] NOT NULL  -- 56 = 7 variables x 8 depths, scaled (wod_casts_rules.SCALES), NULL = no good value
)"""

CELLS = """
CREATE TABLE IF NOT EXISTS {t} (
  level smallint NOT NULL,  -- LOD level L: cells of 2^(6+2L) per axis
  cell integer NOT NULL,  -- key >> 2*(20 - (6+2L))
  year smallint NOT NULL,
  n integer NOT NULL,  -- drawable casts
  rep integer NOT NULL,  -- max(cast_id): a real cast of this cell and year
  sx double precision NOT NULL, sy double precision NOT NULL,  -- sums of EPSG:3857 x / y
  s real[] NOT NULL,  -- per pick slot: sum of the scaled picks, NULL when none
  c integer[] NOT NULL,  -- per pick slot: count of picks, NULL when none
  CONSTRAINT {t}_pkey PRIMARY KEY (level, cell, year)
)"""

FILES = """
CREATE TABLE IF NOT EXISTS wod_files (
  file_id smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  url text NOT NULL UNIQUE, instrument text NOT NULL, year smallint NOT NULL,
  content_length bigint, last_modified text, seen_at timestamptz,  -- latest HEAD
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','loaded','failed','blocked','missing')),
  loaded_content_length bigint, loaded_last_modified text, loaded_at timestamptz,
  n_casts_source integer, n_stored integer, n_drawn integer, rejects jsonb,  -- rejects: per-file reject counters incl. bad_coords
  failure text, failed_at timestamptz
)"""

SOURCE_ROW = """
CREATE TABLE IF NOT EXISTS wod_casts_source (
  id smallint PRIMARY KEY CHECK (id = 1),
  tile_version text, tile_built_at timestamptz, loaded_at timestamptz, point_min_zoom smallint,
  last_checked_at timestamptz, refresh_requested_at timestamptz,
  last_run_at timestamptz, last_decision text, last_failed_at timestamptz, last_failure text,
  interrupted_file smallint, interrupt_count integer,
  n_stored integer, n_drawn integer, year_min smallint, year_max smallint,
  lod_counts jsonb, flag_meanings jsonb, last_rejects jsonb, last_rejects_at timestamptz
)"""


def cells_ddl(t: str) -> list[str]:
    return [CELLS.replace("{t}", t), f"ALTER TABLE {t} OWNER TO abyssal_user"]


def cells_index_names(t: str) -> list[str]:
    return [f"{t}_pkey"]


def staging_ddl() -> list[str]:
    """Unlogged staging tables, created by the loader (never by ensure_wod_casts)."""
    return [
        "CREATE UNLOGGED TABLE IF NOT EXISTS wod_casts_stage (LIKE wod_casts INCLUDING DEFAULTS)",
        "CREATE UNLOGGED TABLE IF NOT EXISTS wod_points_stage (LIKE wod_cast_points INCLUDING DEFAULTS)",
        "ALTER TABLE wod_casts_stage OWNER TO abyssal_user",
        "ALTER TABLE wod_points_stage OWNER TO abyssal_user",
    ]


async def ensure_wod_casts(conn) -> None:
    for sql in ([WOD_CASTS, "ALTER TABLE wod_casts OWNER TO abyssal_user",
                 "CREATE INDEX IF NOT EXISTS wod_casts_file_idx ON wod_casts (file_id)",
                 POINTS, "ALTER TABLE wod_cast_points OWNER TO abyssal_user",
                 "CREATE INDEX IF NOT EXISTS wod_cast_points_key_idx ON wod_cast_points (key)",
                 "CREATE INDEX IF NOT EXISTS wod_cast_points_file_idx ON wod_cast_points (file_id)"]
                + cells_ddl("wod_cells")
                + [FILES, "ALTER TABLE wod_files OWNER TO abyssal_user", SOURCE_ROW,
                   "INSERT INTO wod_casts_source (id) VALUES (1) ON CONFLICT (id) DO NOTHING",
                   "ALTER TABLE wod_casts_source OWNER TO abyssal_user"]):
        await conn.execute(sql)
