# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""DDL for OBIS plankton occurrences (stage 1: the records) and the stage-2 map aggregates.

The worker never upserts: it builds `<table>_new` from the same DDL and swaps
names in one transaction (ingestion/plankton_obis.py). That is why the DDL is a
function of the table name — the production tables and the staging tables must
be identical, constraint for constraint.
"""
from __future__ import annotations

GROUPS = ("copepoda", "euphausiacea", "diatoms", "coccolithophores", "dinoflagellates")
# sync_log marker written when an import starts (see ingestion/plankton_obis.py). Lives here, a leaf
# module, because the API (domains/plankton.py) and the worker both need it and neither may import the other.
STARTED_PREFIX = "started"
STARTED_STALE_HOURS = 12       # = plankton-obis.service TimeoutStartSec
# A swap that went through but lost some datasets writes this into sync_log.skipped_reason, with the
# count in a fixed-format token. /v1/plankton/meta parses ONLY that token (an int); no other sync_log text.
SWAPPED_PARTIAL_PREFIX = "swapped with failed datasets"
FAILED_TOKEN_RE = r"failed_datasets=(\d+)"
# No 'restricted': restricted datasets are never stored.
LICENCES = ("cc0", "cc-by", "cc-by-sa", "cc-by-nc", "unknown")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def datasets_ddl(table: str) -> list[str]:
    return [
        f"""CREATE TABLE IF NOT EXISTS {table} (
            dataset_id   UUID PRIMARY KEY,
            title        TEXT,
            institution  TEXT,
            licence      TEXT NOT NULL CHECK (licence IN ({_in(LICENCES)})),
            licence_raw  TEXT,
            url          TEXT,
            citation     TEXT,
            record_count INTEGER NOT NULL DEFAULT 0,
            imported_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
        f"ALTER TABLE {table} OWNER TO abyssal_user",
    ]


def occurrences_ddl(table: str, datasets_table: str) -> list[str]:
    return [
        f"""CREATE TABLE IF NOT EXISTS {table} (
            id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            taxon_group     TEXT NOT NULL CHECK (taxon_group IN ({_in(GROUPS)})),
            scientific_name TEXT,
            aphia_id        INTEGER,
            taxon_order     TEXT,
            dataset_id      UUID NOT NULL REFERENCES {datasets_table} (dataset_id),
            licence         TEXT NOT NULL CHECK (licence IN ({_in(LICENCES)})),
            is_edna         BOOLEAN NOT NULL,
            depth_m         REAL CHECK (depth_m IS NULL OR (depth_m >= 0 AND depth_m <= 11000)),
            event_date      DATE,
            year            SMALLINT,
            month           SMALLINT CHECK (month IS NULL OR month BETWEEN 1 AND 12),
            lon             DOUBLE PRECISION NOT NULL CHECK (lon BETWEEN -180 AND 180),
            lat             DOUBLE PRECISION NOT NULL CHECK (lat BETWEEN -90 AND 90),
            geom            geometry(Point, 4326)
                            GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(lon, lat), 4326)) STORED NOT NULL
        )""",
        f"ALTER TABLE {table} OWNER TO abyssal_user",
    ]


def progress_ddl(table: str) -> list[str]:
    """The exact per-dataset ledger of an import run (resume): a row exists IFF that dataset's rows are
    completely in the matching `plankton_occurrences_new` (written in the SAME transaction as its load).
    No FK on purpose: a ledger row must never block a staging drop or a cleanup."""
    return [
        f"""CREATE TABLE IF NOT EXISTS {table} (
            dataset_id  UUID PRIMARY KEY,
            rows        INTEGER NOT NULL,
            finished_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
        f"ALTER TABLE {table} OWNER TO abyssal_user",
    ]


# ---------------------------------------------------------------------------
# Stage 2 (map layer): aggregates of plankton_occurrences, built from the `_new` staging pair and swapped
# in with it (ingestion/plankton_aggregates.py, ingestion/plankton_obis.py). Fixed vocabulary shared by the
# SQL, the tile/site API validation (services/plankton_tiles.py) and the UI (frontend/src/utils/plankton.ts).
# ---------------------------------------------------------------------------
GROUP_BITS = {g: 1 << i for i, g in enumerate(GROUPS)}
# -1 = no date (NULL year OR a year after the build's UTC year — 94 rows with a future year exist), 1940 = before 1950.
DECADES = (-1, 1940, 1950, 1960, 1970, 1980, 1990, 2000, 2010, 2020)
# 0 = 0-200 m (200 included), 1 = above 200 up to 1000 m (1000 included), 2 = deeper than 1000 m, 3 = no depth.
DEPTH_BANDS = (0, 1, 2, 3)
GRID_RES = (1.0, 0.25)
MERC_LAT = 85.05112878   # Web-Mercator limit: geom_3857 is clamped here, geom keeps the true latitude
SITES, SITE_FACETS, GRID_FACETS, TILE_VERSION = (
    "plankton_sites", "plankton_site_facets", "plankton_grid_facets", "plankton_tile_version")
AGG_TABLES = (SITES, SITE_FACETS, GRID_FACETS, TILE_VERSION)
CUTOFF_NOW_SQL = "extract(year FROM (now() AT TIME ZONE 'UTC'))::int"


def _ints(values) -> str:
    return ", ".join(str(v) for v in values)


def decade_sql(year: str, cutoff: str) -> str:
    """SQL decade class of `year`. NULL and years after `cutoff` -> -1 (never 0, never a real decade).
    A year of 2030+ that the cutoff allows buckets to its own decade (DECADE_CHECK admits them up to 2100);
    the UI vocabulary DECADES (and so the default map filter) must be extended then, never clamp."""
    return (f"(CASE WHEN {year} IS NULL OR {year} > {cutoff} THEN -1 "
            f"WHEN {year} < 1950 THEN 1940 ELSE ({year} / 10) * 10 END)::smallint")


def band_sql(depth: str) -> str:
    """SQL depth band of `depth` (metres). NULL -> 3 ("no depth"), never 0 ("surface")."""
    return (f"(CASE WHEN {depth} IS NULL THEN 3 WHEN {depth} <= 200 THEN 0 "
            f"WHEN {depth} <= 1000 THEN 1 ELSE 2 END)::smallint")


# DECADES is the UI vocabulary; the CHECK must not be: from 2030 the cutoff (this year) lets 2030s rows in, and
# a CHECK limited to 2020 would fail every import with the staging kept. Any decade up to 2100 is valid.
DECADE_CHECK = "decade = -1 OR (decade % 10 = 0 AND decade BETWEEN 1940 AND 2100)"

_FACETS = f"""taxon_group TEXT NOT NULL CHECK (taxon_group IN ({_in(GROUPS)})),
            decade      SMALLINT NOT NULL CHECK ({DECADE_CHECK}),
            depth_band  SMALLINT NOT NULL CHECK (depth_band IN ({_ints(DEPTH_BANDS)})),
            is_edna     BOOLEAN NOT NULL,
            n           INTEGER NOT NULL CHECK (n > 0)"""


def sites_ddl(table: str) -> list[str]:
    """One row per place (lon/lat rounded to 6 decimals). site_id is regenerated by every build; site_key
    is the stable name share links use."""
    return [
        f"""CREATE TABLE IF NOT EXISTS {table} (
            site_id   INTEGER PRIMARY KEY,
            site_key  TEXT NOT NULL UNIQUE,
            lon       DOUBLE PRECISION NOT NULL,
            lat       DOUBLE PRECISION NOT NULL,
            geom      geometry(Point, 4326) NOT NULL,
            geom_3857 geometry(Point, 3857) NOT NULL
        )""",
        f"ALTER TABLE {table} OWNER TO abyssal_user",
    ]


def site_facets_ddl(table: str) -> list[str]:
    return [
        f"""CREATE TABLE IF NOT EXISTS {table} (
            site_id     INTEGER NOT NULL,
            {_FACETS},
            PRIMARY KEY (site_id, taxon_group, decade, depth_band, is_edna)
        )""",
        f"ALTER TABLE {table} OWNER TO abyssal_user",
    ]


def grid_facets_ddl(table: str) -> list[str]:
    return [
        f"""CREATE TABLE IF NOT EXISTS {table} (
            res         REAL NOT NULL CHECK (res IN ({_ints(GRID_RES)})),
            cell_x      INTEGER NOT NULL,
            cell_y      INTEGER NOT NULL,
            geom        geometry(Point, 4326) NOT NULL,
            geom_3857   geometry(Point, 3857) NOT NULL,
            {_FACETS},
            PRIMARY KEY (res, cell_x, cell_y, taxon_group, decade, depth_band, is_edna)
        )""",
        f"ALTER TABLE {table} OWNER TO abyssal_user",
    ]


def tile_version_ddl(table: str) -> list[str]:
    """Exactly one row: the data version tiles are filed and cached under. Changes on every swap."""
    return [
        f"""CREATE TABLE IF NOT EXISTS {table} (
            id       SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
            version  TEXT NOT NULL CHECK (version ~ '^[0-9]{{14}}-[0-9a-f]{{6}}$'),
            built_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
        f"ALTER TABLE {table} OWNER TO abyssal_user",
    ]


def aggregates_index_ddl(suffix: str = "") -> list[str]:
    """Built after the bulk INSERTs, like occurrences_index_ddl."""
    return [
        f"CREATE INDEX IF NOT EXISTS {SITES}{suffix}_geom3857_gix ON {SITES}{suffix} USING GIST (geom_3857)",
        f"CREATE INDEX IF NOT EXISTS {GRID_FACETS}{suffix}_geom3857_gix ON {GRID_FACETS}{suffix} USING GIST (geom_3857)",
    ]


AGG_DDL = ((SITES, sites_ddl), (SITE_FACETS, site_facets_ddl), (GRID_FACETS, grid_facets_ddl),
           (TILE_VERSION, tile_version_ddl))


def occurrences_index_ddl(table: str) -> list[str]:
    """Separate so the loader can build indexes AFTER the bulk COPY (much faster)."""
    return [
        f"CREATE INDEX IF NOT EXISTS {table}_geom_gix ON {table} USING GIST (geom)",
        f"CREATE INDEX IF NOT EXISTS {table}_group_licence_idx ON {table} (taxon_group, licence)",
        f"CREATE INDEX IF NOT EXISTS {table}_dataset_idx ON {table} (dataset_id)",
    ]


async def ensure_plankton(conn) -> None:
    """plankton_datasets, plankton_occurrences (empty until the worker's first swap), and the four stage-2
    aggregate tables (empty, no version row, until the first swap or `--aggregates-only`)."""
    for sql in datasets_ddl("plankton_datasets"):
        await conn.execute(sql)
    for sql in occurrences_ddl("plankton_occurrences", "plankton_datasets"):
        await conn.execute(sql)
    for sql in occurrences_index_ddl("plankton_occurrences"):
        await conn.execute(sql)
    for table, ddl in AGG_DDL:
        for sql in ddl(table):
            await conn.execute(sql)
    for sql in aggregates_index_ddl():
        await conn.execute(sql)
