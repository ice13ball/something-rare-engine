# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""BGC-Argo DOXY storage DDL and write statements — a LEAF module (imports only argo_doxy_rules).

It lives under ingestion/, not schema/, so the loader and the worker can use it without executing
schema/__init__.py, which imports the whole API stack (fastapi, domains, ...). schema/argo_doxy.py re-exports it.

BGC-Argo DOXY profiles — the Argo storage family's oxygen extension (2026-10-06).

⛔ A child table, deliberately NOT columns on argo_profiles: that table holds only what the ArgoVis sync wrote
(ArgoVis misses 5-10 % of the GDAC's DOXY profiles per day, measured), its writer is the API-process sync, and
the existing Argo layer reads it. `argo_profile_id` is the same WMO_CCC[D] id, so the two join; there is no
foreign key, because not every DOXY profile has an argo_profiles row. Filled only by argo_doxy_worker."""
from __future__ import annotations

from ingestion.argo_doxy_rules import DISPLAY_DEPTHS, MAX_STORED_LEVELS, PROFILE_COLUMNS

_N = len(DISPLAY_DEPTHS)

PROFILES_DDL = [f"""
CREATE TABLE IF NOT EXISTS argo_doxy_profiles (
  profile_key text PRIMARY KEY CHECK (profile_key ~ '^[a-z]+_[0-9]{{4,8}}_[0-9]{{3,4}}D?$'),
  argo_profile_id text NOT NULL,
  dac text NOT NULL,
  platform_number text NOT NULL,
  cycle_number integer NOT NULL,
  direction char(1) NOT NULL CHECK (direction IN ('A','D')),
  gdac_file text NOT NULL,
  gdac_date_update timestamptz NOT NULL,
  profile_time timestamptz,
  juld_qc smallint,
  year smallint,
  lat double precision CHECK (lat BETWEEN -90 AND 90),
  lon double precision CHECK (lon BETWEEN -180 AND 180),
  position_qc smallint,
  doxy_mode char(1) NOT NULL,
  pres_source text NOT NULL CHECK (pres_source IN ('adjusted','raw','mixed')),
  n_levels_source integer NOT NULL,
  n_good integer NOT NULL,
  n_levels smallint NOT NULL CHECK (n_levels BETWEEN 1 AND {MAX_STORED_LEVELS}),
  pres_dbar real[] NOT NULL,
  depth_m real[] NOT NULL,
  doxy_adj real[] NOT NULL,
  doxy_adj_qc smallint[] NOT NULL,
  doxy_raw real[] NOT NULL,
  doxy_raw_qc smallint[] NOT NULL,
  at_depth real[] NOT NULL CHECK (cardinality(at_depth) = {_N}),
  at_depth_m real[] NOT NULL CHECK (cardinality(at_depth_m) = {_N}),
  drawable boolean NOT NULL,
  rules_version smallint NOT NULL DEFAULT 0,
  updated_at timestamptz NOT NULL DEFAULT now()
)""",
    "CREATE INDEX IF NOT EXISTS argo_doxy_profiles_float_idx ON argo_doxy_profiles (dac, platform_number)",
    "CREATE INDEX IF NOT EXISTS argo_doxy_profiles_argo_id_idx ON argo_doxy_profiles (argo_profile_id)",
    "CREATE INDEX IF NOT EXISTS argo_doxy_profiles_drawn_idx ON argo_doxy_profiles "
    "(dac, platform_number, cycle_number, direction) WHERE drawable",
    "ALTER TABLE argo_doxy_profiles OWNER TO abyssal_user",
]

# `rules_version` (rows and empty markers) is the RULES_VERSION of the rules that built the row (0 = unknown). The
# planner re-reads every float holding a row built under another version, so a change to OUR rules reaches stored
# rows and empty markers, and a half-finished re-read resumes instead of starting over. The source row's
# `rules_version` is the version of the last COMPLETE run: "every row is current".
#
# Profiles the index lists with DOXY whose Sprof carries no usable DOXY value (every level fill, or every level
# dropped by a pressure flag). Without a row of their own the planner would see them as "never stored" and download
# their float again on every run; the stamp is the same gdac_date_update the profile table uses.
EMPTY_DDL = [
    """
CREATE TABLE IF NOT EXISTS argo_doxy_empty (
  profile_key text PRIMARY KEY CHECK (profile_key ~ '^[a-z]+_[0-9]{4,8}_[0-9]{3,4}D?$'),
  gdac_date_update timestamptz NOT NULL,
  rules_version smallint NOT NULL DEFAULT 0,
  updated_at timestamptz NOT NULL DEFAULT now()
)""",
    "ALTER TABLE argo_doxy_empty OWNER TO abyssal_user",
]

SOURCE_DDL = ["""
CREATE TABLE IF NOT EXISTS argo_doxy_source (
  id smallint PRIMARY KEY CHECK (id = 1),
  index_bytes bigint, index_date_update_max timestamptz,
  loaded_at timestamptz, last_complete_at timestamptz, refresh_requested_at timestamptz,
  rules_version smallint,
  n_index_doxy integer, n_profiles integer, n_drawable integer, pending_floats integer NOT NULL DEFAULT 0,
  last_run_at timestamptz, last_decision text, last_failed_at timestamptz, last_failure text,
  last_rejects jsonb, last_rejects_at timestamptz
)""", "INSERT INTO argo_doxy_source (id) VALUES (1) ON CONFLICT (id) DO NOTHING",
    "ALTER TABLE argo_doxy_source OWNER TO abyssal_user"]

# ── map tiles (2026-10-10). Both tables are rebuilt by the worker as `<name>_new` and swapped in with a new
# argo_doxy_source.tile_version (ingestion/argo_doxy_tiles.py), so every name is derived from the table name.
# ensure_schema creates the empty live tables, so the tile route answers 503 "not built", never a missing table.
# No statement contains a semicolon or a -- comment: the DDL snapshot splits on ";".
TILE_POINT_COLUMNS = ("profile_key", "year", "key", "x", "y", "d")


def tile_points_ddl(t: str) -> list[str]:
    """One row per drawable profile: key = wod_casts_rules.morton_key over EPSG:3857 x/y (latitude clamped),
    d = the 8 display-depth values in whole µmol/kg, NULL element = no good adjusted value in that window."""
    return [f"""
CREATE TABLE IF NOT EXISTS {t} (
  profile_key text NOT NULL,
  year smallint NOT NULL,
  key bigint NOT NULL,
  x real NOT NULL,
  y real NOT NULL,
  d smallint[] NOT NULL CHECK (cardinality(d) = {_N})
)""", f"ALTER TABLE {t} OWNER TO abyssal_user"]


def tile_points_index_ddl(t: str) -> list[str]:
    return [f"CREATE INDEX IF NOT EXISTS {t}_key_idx ON {t} (key)"]


def tile_points_index_names(t: str) -> list[str]:
    return [f"{t}_key_idx"]


def cells_ddl(t: str) -> list[str]:
    """Per (LOD level, cell, year): n profiles, rep = max(profile_key) (a real profile of the cell and year), sums of
    EPSG:3857 x / y, per display depth the sum (s) and count (c) of the whole-µmol/kg values, NULL when none."""
    return [f"""
CREATE TABLE IF NOT EXISTS {t} (
  level smallint NOT NULL,
  cell integer NOT NULL,
  year smallint NOT NULL,
  n integer NOT NULL,
  rep text NOT NULL,
  sx double precision NOT NULL,
  sy double precision NOT NULL,
  s double precision[] NOT NULL,
  c integer[] NOT NULL,
  CONSTRAINT {t}_pkey PRIMARY KEY (level, cell, year)
)""", f"ALTER TABLE {t} OWNER TO abyssal_user"]


def cells_index_names(t: str) -> list[str]:
    return [f"{t}_pkey"]


# The source row predates the tiles: the columns are added, not part of the CREATE (production already has the table).
SOURCE_TILE_COLUMNS = ["ALTER TABLE argo_doxy_source ADD COLUMN IF NOT EXISTS tile_version text",
                       "ALTER TABLE argo_doxy_source ADD COLUMN IF NOT EXISTS tile_built_at timestamptz"]

_COLS = ", ".join(PROFILE_COLUMNS)
_VALS = ", ".join(f"${i + 1}" for i in range(len(PROFILE_COLUMNS)))
_SET = ", ".join(f"{c} = EXCLUDED.{c}" for c in PROFILE_COLUMNS if c != "profile_key")
UPSERT_SQL = (f"INSERT INTO argo_doxy_profiles ({_COLS}) VALUES ({_VALS}) "
              f"ON CONFLICT (profile_key) DO UPDATE SET {_SET}, updated_at = now()")
# The version is stamped by a second statement in the same transaction (the loader reads RULES_VERSION at call time).
STAMP_PROFILES_SQL = "UPDATE argo_doxy_profiles SET rules_version = $1 WHERE profile_key = ANY($2::text[])"
UPSERT_EMPTY_SQL = ("INSERT INTO argo_doxy_empty (profile_key, gdac_date_update, rules_version) VALUES ($1, $2, $3) "
                    "ON CONFLICT (profile_key) DO UPDATE SET gdac_date_update = EXCLUDED.gdac_date_update, "
                    "rules_version = EXCLUDED.rules_version, updated_at = now()")


async def ensure_argo_doxy(conn) -> None:
    for sql in (PROFILES_DDL + EMPTY_DDL + SOURCE_DDL + SOURCE_TILE_COLUMNS
                + tile_points_ddl("argo_doxy_tile_points") + tile_points_index_ddl("argo_doxy_tile_points")
                + cells_ddl("argo_doxy_cells")):
        await conn.execute(sql)
