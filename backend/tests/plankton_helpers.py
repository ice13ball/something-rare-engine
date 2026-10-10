# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""Shared by the plankton DB tests: a rolled-back connection standing in for db.pool."""
import math
import os
import pathlib

import asyncpg
import duckdb
import httpx
import pytest

import db

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")


class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _PoolFromConn:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _Acquire(self._conn)


@pytest.fixture
async def conn():
    """One connection inside one transaction, rolled back at the end."""
    c = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
    tx = c.transaction()
    await tx.start()
    previous = db.pool
    db.pool = _PoolFromConn(c)
    try:
        yield c
    finally:
        db.pool = previous
        await tx.rollback()
        await c.close()


FIX = pathlib.Path(__file__).parent / "fixtures" / "plankton_obis" / "occurrences.parquet"
DS_T = "00000000-0000-0000-0000-0000000000aa"    # synthetic rows: CC-BY
DS_NC = "00000000-0000-0000-0000-0000000000ab"   # synthetic rows: CC-BY-NC


def row(group, lon, lat, *, year=None, depth=None, edna=False, name=None, ds=DS_T, licence="cc-by"):
    """One synthetic plankton_occurrences row (only the columns stage 2 reads)."""
    return {"g": group, "lon": lon, "lat": lat, "year": year, "depth": depth, "edna": edna,
            "name": name, "ds": ds, "licence": licence}


def _extract(tmp_path):
    from ingestion import plankton_obis as p
    con = p.connect_duckdb(tmp_path)
    dest = tmp_path / "x.parquet"
    p.extract_dataset(con, str(FIX), dest)
    return dest


def _ds(ids, licence="cc-by"):
    return [dict(dataset_id=i, title=f"t{i}", institution=None, licence=licence,
                 licence_raw="x", url=None, citation=None) for i in ids]


def _fixture_ids():
    return [r[0] for r in duckdb.sql(f"SELECT DISTINCT dataset_id FROM read_parquet('{FIX}')").fetchall()]


async def reset_plankton(conn):
    """Drop every plankton table (live, staging, aggregates) and recreate the live set empty."""
    from schema.plankton import AGG_TABLES, ensure_plankton
    for t in ("plankton_occurrences_new", "plankton_datasets_new", "plankton_progress_new",
              "plankton_occurrences", "plankton_datasets", *AGG_TABLES, *(f"{t}_new" for t in AGG_TABLES)):
        await conn.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    await ensure_plankton(conn)


async def _datasets(conn, table):
    await conn.execute(
        f"INSERT INTO {table} (dataset_id, title, licence, licence_raw, citation, url) VALUES "
        f"($1::uuid, 'Synthetic CC-BY dataset', 'cc-by', 'CC-BY', 'Synthetic citation A', 'https://example.org/a'), "
        f"($2::uuid, 'Synthetic CC-BY-NC dataset', 'cc-by-nc', 'CC-BY-NC', 'Synthetic citation B', "
        f"'https://example.org/b') ON CONFLICT (dataset_id) DO NOTHING", DS_T, DS_NC)


async def _insert(conn, table, rows):
    await conn.executemany(
        f"INSERT INTO {table} (taxon_group, scientific_name, dataset_id, licence, is_edna, "
        "depth_m, year, lon, lat) VALUES ($1, $2, $3::uuid, $4, $5, $6, $7, $8, $9)",
        [(r["g"], r["name"], r["ds"], r["licence"], r["edna"], r["depth"], r["year"], r["lon"], r["lat"])
         for r in rows])


async def insert_staged(conn, rows):
    await _insert(conn, "plankton_occurrences_new", rows)


async def stage_fixture(conn, tmp_path):
    """Fresh tables; the real OBIS fixture extracted and loaded into the `_new` staging pair, plus the two
    synthetic datasets so insert_staged() rows have a parent."""
    from ingestion import plankton_obis as p
    await reset_plankton(conn)
    await p.build_staging(conn)
    ids = _fixture_ids()
    await p.load_datasets(conn, _ds(ids))
    await p.load_extract(conn, _extract(tmp_path), {i: "cc-by" for i in ids})
    await _datasets(conn, "plankton_datasets_new")


async def seed_live(conn, rows):
    """Fresh LIVE tables holding exactly `rows` (datasets DS_T / DS_NC), aggregates built from them and
    swapped in through the --aggregates-only path. Returns the tile version."""
    from ingestion import plankton_obis as p
    await reset_plankton(conn)
    await _datasets(conn, "plankton_datasets")
    await _insert(conn, "plankton_occurrences", rows)
    return await p.rebuild_aggregates_from_live(conn, backoff=())


def tile_of(lon, lat, z):
    """Slippy-map tile (x, y) containing lon/lat at zoom z."""
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    lat_r = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n)
    return min(x, n - 1), min(y, n - 1)


class RecordingConn:
    """Delegates to a real connection and remembers every statement passed to execute()."""

    def __init__(self, conn):
        self._conn = conn
        self.executed = []

    def __getattr__(self, name):
        return getattr(self._conn, name)

    async def execute(self, query, *args, **kw):
        self.executed.append(query)
        return await self._conn.execute(query, *args, **kw)


async def api_get(path):
    """GET through the real ASGI app with get_api_key bypassed (the test connection is one transaction); the
    real dependency is exercised by test_plankton_meta_db.test_meta_without_api_key_is_rejected."""
    import main
    from auth import get_api_key
    main.app.dependency_overrides[get_api_key] = lambda: "test"
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
            return await c.get(path)
    finally:
        main.app.dependency_overrides.pop(get_api_key, None)
