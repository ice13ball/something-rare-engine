# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""DDL for OBIS plankton occurrences (stage 1: data only, no layer yet).

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


def occurrences_index_ddl(table: str) -> list[str]:
    """Separate so the loader can build indexes AFTER the bulk COPY (much faster)."""
    return [
        f"CREATE INDEX IF NOT EXISTS {table}_geom_gix ON {table} USING GIST (geom)",
        f"CREATE INDEX IF NOT EXISTS {table}_group_licence_idx ON {table} (taxon_group, licence)",
        f"CREATE INDEX IF NOT EXISTS {table}_dataset_idx ON {table} (dataset_id)",
    ]


async def ensure_plankton(conn) -> None:
    """plankton_datasets, plankton_occurrences (empty until the worker's first swap)."""
    for sql in datasets_ddl("plankton_datasets"):
        await conn.execute(sql)
    for sql in occurrences_ddl("plankton_occurrences", "plankton_datasets"):
        await conn.execute(sql)
    for sql in occurrences_index_ddl("plankton_occurrences"):
        await conn.execute(sql)
