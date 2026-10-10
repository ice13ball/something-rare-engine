# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""--aggregates-only: aggregates rebuilt from the LIVE table and swapped alone (real PostGIS)."""
import asyncpg
import pytest

import plankton_obis_worker as w
from ingestion import plankton_aggregates as agg
from ingestion import plankton_obis as p
from plankton_helpers import DS_T, RecordingConn, _PoolFromConn, conn, needs_db, row, seed_live  # noqa: F401
from schema.plankton import AGG_TABLES

LOCKED = ("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND objid::bigint = $1 "
          "AND pid = pg_backend_pid()")


@needs_db
async def test_rebuild_from_live_swaps_only_the_aggregates(conn):
    v1 = await seed_live(conn, [row("copepoda", 10.2, 50.2, year=1995), row("diatoms", 10.2, 50.2, year=2015)])
    assert await conn.fetchval("SELECT sum(n) FROM plankton_site_facets") == 2
    await conn.execute("INSERT INTO plankton_occurrences (taxon_group, dataset_id, licence, is_edna, lon, lat) "
                       "VALUES ('copepoda', $1::uuid, 'cc-by', false, 11.0, 51.0)", DS_T)
    v2 = await p.rebuild_aggregates_from_live(conn, backoff=())
    assert v2 != v1 and await conn.fetchval("SELECT version FROM plankton_tile_version") == v2
    assert await conn.fetchval("SELECT sum(n) FROM plankton_site_facets") == 3
    assert await conn.fetchval("SELECT count(*) FROM plankton_sites") == 2
    assert await conn.fetchval("SELECT count(*) FROM plankton_occurrences") == 3     # rows untouched
    assert await conn.fetchval("SELECT count(*) FROM plankton_datasets") == 2
    for t in AGG_TABLES:
        assert await conn.fetchval("SELECT to_regclass($1)", f"{t}_new") is None


@needs_db
async def test_an_invalid_rebuild_is_blocked_and_keeps_the_live_aggregates(conn, monkeypatch):
    v1 = await seed_live(conn, [row("copepoda", 10.2, 50.2, year=1995)])

    async def bad(c, source):
        raise agg.AggregatesInvalid(["synthetic: sums differ"])
    monkeypatch.setattr(agg, "require_valid_aggregates", bad)
    with pytest.raises(p.SwapBlocked) as ei:
        await p.rebuild_aggregates_from_live(conn, backoff=())
    assert ei.value.reasons == ["synthetic: sums differ"]
    assert await conn.fetchval("SELECT version FROM plankton_tile_version") == v1
    assert await conn.fetchval("SELECT sum(n) FROM plankton_site_facets") == 1
    for t in AGG_TABLES:
        assert await conn.fetchval("SELECT to_regclass($1)", f"{t}_new") is None   # half-built set dropped


@needs_db
async def test_an_infrastructure_error_propagates_and_keeps_the_live_aggregates(conn, monkeypatch):
    v1 = await seed_live(conn, [row("copepoda", 10.2, 50.2, year=1995)])

    async def boom(c, source):
        await c.execute("SELECT 1 / 0")
    monkeypatch.setattr(agg, "build_aggregates", boom)
    with pytest.raises(asyncpg.exceptions.DataError):       # NOT SwapBlocked: not a verdict on the data
        await p.rebuild_aggregates_from_live(conn, backoff=())
    assert await conn.fetchval("SELECT version FROM plankton_tile_version") == v1
    assert await conn.fetchval("SELECT sum(n) FROM plankton_site_facets") == 1


@needs_db
async def test_lock_timeout_leaves_the_live_aggregates(conn, monkeypatch):
    v1 = await seed_live(conn, [row("copepoda", 10.2, 50.2, year=1995)])

    async def locked(c):
        raise asyncpg.exceptions.LockNotAvailableError("x")
    monkeypatch.setattr(p, "_swap_aggregates_in_tx", locked)
    with pytest.raises(p.SwapLockTimeout):
        await p.rebuild_aggregates_from_live(conn, backoff=(0,))
    assert await conn.fetchval("SELECT version FROM plankton_tile_version") == v1


@needs_db
async def test_rebuild_writes_no_sync_log_row(conn):
    await seed_live(conn, [row("copepoda", 10.2, 50.2, year=1995)])
    assert await conn.fetchval("SELECT count(*) FROM sync_log WHERE source = $1", p.SOURCE) == 0


def test_aggregates_only_is_its_own_cli_mode():
    ns = w.parse_args(["--aggregates-only"])
    assert ns.aggregates_only is True and ns.force is False
    for bad in (["--aggregates-only", "--resume"], ["--aggregates-only", "--force"]):
        with pytest.raises(SystemExit):
            w.parse_args(bad)


@needs_db
async def test_rebuild_map_runs_under_the_import_lock_and_releases_it(conn, monkeypatch):
    seen = []

    async def spy(c, **kw):
        seen.append(await c.fetchval(LOCKED, w.LOCK_KEY))
        return "20261007120000-a1b2c3"

    monkeypatch.setattr(w, "rebuild_aggregates_from_live", spy)
    assert await w.rebuild_map(_PoolFromConn(conn)) == "aggregates"
    assert seen == [1]
    assert await conn.fetchval(LOCKED, w.LOCK_KEY) == 0


@needs_db
async def test_a_deadlock_is_retried_like_a_lock_timeout_and_leaves_live_intact(conn, monkeypatch):
    v1 = await seed_live(conn, [row("copepoda", 10.2, 50.2, year=1995)])
    calls = []

    async def deadlocked(c):
        calls.append(1)
        raise asyncpg.exceptions.DeadlockDetectedError("x")
    monkeypatch.setattr(p, "_swap_aggregates_in_tx", deadlocked)
    with pytest.raises(p.SwapLockTimeout):
        await p.rebuild_aggregates_from_live(conn, backoff=(0, 0))
    assert len(calls) == 3
    assert await conn.fetchval("SELECT version FROM plankton_tile_version") == v1


@needs_db
async def test_the_aggregates_swap_takes_its_tables_in_one_lock_statement_in_the_fixed_order(conn):
    await seed_live(conn, [row("copepoda", 10.2, 50.2, year=1995)])
    rec = RecordingConn(conn)
    await p.rebuild_aggregates_from_live(rec, backoff=())
    locks = [q for q in rec.executed if q.startswith("LOCK TABLE")]
    assert locks == ["LOCK TABLE " + ", ".join(t for t in p.SWAP_LOCK_ORDER if t in AGG_TABLES)
                     + " IN ACCESS EXCLUSIVE MODE"]
    at = next(i for i, q in enumerate(rec.executed) if q.startswith("SET LOCAL lock_timeout"))
    assert rec.executed[at + 1] == locks[0]            # the very first thing after the timeout, before any DDL


@needs_db
async def test_aggregates_only_bakes_after_the_rebuild_still_under_the_lock(conn, monkeypatch):
    order = []

    async def rebuilt(c, **kw):
        order.append("rebuild")
        return "20261007120000-a1b2c3"

    async def baked():
        order.append(("bake", await conn.fetchval(LOCKED, w.LOCK_KEY)))
    monkeypatch.setattr(w, "rebuild_aggregates_from_live", rebuilt)
    monkeypatch.setattr(w, "bake_tiles", baked)
    await w.rebuild_map(_PoolFromConn(conn))
    assert order == ["rebuild", ("bake", 1)]
