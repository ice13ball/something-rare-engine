# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""The aggregates are built from staging and go live in the SAME transaction as the occurrences."""
import asyncpg
import pytest

from domains.plankton import _classify
from ingestion import plankton_aggregates as agg
from ingestion import plankton_obis as p
from plankton_helpers import RecordingConn, conn, needs_db, stage_fixture  # noqa: F401
from schema.plankton import AGG_TABLES
from test_plankton_sync_db import _run, _setup, _split_fixture, alerts  # noqa: F401


async def _version(conn):
    return await conn.fetchval("SELECT version FROM plankton_tile_version WHERE id = 1")


async def _sums(conn):
    return (await conn.fetchval("SELECT count(*) FROM plankton_occurrences"),
            await conn.fetchval("SELECT coalesce(sum(n), 0) FROM plankton_site_facets"),
            await conn.fetchval("SELECT coalesce(sum(n), 0) FROM plankton_grid_facets WHERE res = 1.0::real"))


async def _restage_from_live(conn):
    """A second import holding exactly the live rows (passes every stage-1 validation)."""
    await p.build_staging(conn)
    await conn.execute("INSERT INTO plankton_datasets_new SELECT * FROM plankton_datasets")
    await conn.execute(
        "INSERT INTO plankton_occurrences_new (taxon_group, scientific_name, aphia_id, taxon_order, dataset_id, "
        "licence, is_edna, depth_m, event_date, year, month, lon, lat) SELECT taxon_group, scientific_name, "
        "aphia_id, taxon_order, dataset_id, licence, is_edna, depth_m, event_date, year, month, lon, lat "
        "FROM plankton_occurrences")


async def _no_new_tables(conn):
    for t in ("plankton_occurrences", "plankton_datasets", *AGG_TABLES):
        assert await conn.fetchval("SELECT to_regclass($1)", f"{t}_new") is None, t


async def _staging_survives(conn):
    for t in ("plankton_occurrences_new", "plankton_datasets_new", "plankton_progress_new"):
        assert await conn.fetchval("SELECT to_regclass($1)", t) is not None, t


async def _agg_index_names(conn):
    return sorted(r[0] for r in await conn.fetch(
        "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema() AND tablename = ANY($1::text[])",
        list(AGG_TABLES)))


@needs_db
async def test_a_swap_puts_aggregates_and_a_new_version_live_with_the_rows(conn, tmp_path):
    await stage_fixture(conn, tmp_path)
    await p.swap_validated(conn)
    rows, sites, grid = await _sums(conn)
    assert rows > 0 and rows == sites == grid
    v1 = await _version(conn)
    assert v1
    await _no_new_tables(conn)
    leftover = await conn.fetch(
        "SELECT indexname FROM pg_indexes WHERE indexname LIKE 'plankton\\_%' AND indexname LIKE '%\\_new\\_%'")
    assert leftover == []                       # every index carries its live name again
    constraints = await conn.fetch(
        "SELECT conname FROM pg_constraint WHERE conname LIKE 'plankton\\_%\\_new%'")
    assert constraints == []
    indexes_1 = await _agg_index_names(conn)
    assert "plankton_sites_geom3857_gix" in indexes_1 and "plankton_grid_facets_geom3857_gix" in indexes_1
    await _restage_from_live(conn)
    # the second build must create its OWN _new indexes (a name collision would skip them silently)
    seen = []
    real_build = agg.build_aggregates

    async def spy(c, source):
        v = await real_build(c, source)
        seen.extend(r[0] for r in await c.fetch(
            "SELECT indexname FROM pg_indexes WHERE indexname LIKE 'plankton\\_%\\_new\\_%3857\\_gix'"))
        return v
    agg_build, agg.build_aggregates = agg.build_aggregates, spy
    try:
        await p.swap_validated(conn)
    finally:
        agg.build_aggregates = agg_build
    assert sorted(seen) == ["plankton_grid_facets_new_geom3857_gix", "plankton_sites_new_geom3857_gix"]
    assert await _sums(conn) == (rows, sites, grid)
    assert await _agg_index_names(conn) == indexes_1       # exactly the expected set, nothing added or lost
    assert await _version(conn) not in (None, v1)


@needs_db
async def test_an_invalid_aggregate_build_blocks_the_swap_and_keeps_live_rows_and_version(conn, tmp_path, monkeypatch):
    await stage_fixture(conn, tmp_path)
    await p.swap_validated(conn)
    before, v1 = await _sums(conn), await _version(conn)
    await _restage_from_live(conn)

    async def invalid(c, source):
        raise agg.AggregatesInvalid(["aggregates: injected"])
    monkeypatch.setattr(agg, "build_aggregates", invalid)
    with pytest.raises(p.SwapBlocked) as ei:
        await p.swap_validated(conn)
    assert ei.value.reasons == ["aggregates: injected"]
    assert await _sums(conn) == before and await _version(conn) == v1
    await _no_new_tables(conn)                  # staging dropped


@needs_db
async def test_an_infrastructure_error_in_the_build_keeps_the_staging_and_propagates(conn, tmp_path, monkeypatch):
    await stage_fixture(conn, tmp_path)
    await p.swap_validated(conn)
    before, v1 = await _sums(conn), await _version(conn)
    await _restage_from_live(conn)
    real = agg.build_aggregates

    async def boom(c, source):
        await real(c, source)
        await c.execute("SELECT 1 / 0")
    monkeypatch.setattr(agg, "build_aggregates", boom)
    with pytest.raises(asyncpg.PostgresError):
        await p.swap_validated(conn)
    await _staging_survives(conn)
    assert await conn.fetchval("SELECT count(*) FROM plankton_occurrences_new") == before[0]
    assert await _sums(conn) == before and await _version(conn) == v1
    for t in AGG_TABLES:                        # the failed build left no half-built aggregate behind
        assert await conn.fetchval("SELECT to_regclass($1)", f"{t}_new") is None, t


@needs_db
async def test_a_lossy_build_is_caught_by_the_check_not_shipped(conn, tmp_path, monkeypatch):
    await stage_fixture(conn, tmp_path)
    await p.swap_validated(conn)
    v1 = await _version(conn)
    await _restage_from_live(conn)
    real = agg.build_aggregates

    async def lossy(c, source):
        version = await real(c, source)
        await c.execute("DELETE FROM plankton_site_facets_new "
                        "WHERE ctid = (SELECT ctid FROM plankton_site_facets_new LIMIT 1)")
        return version
    monkeypatch.setattr(agg, "build_aggregates", lossy)
    with pytest.raises(p.SwapBlocked) as ei:
        await p.swap_validated(conn)
    assert any(r.startswith("aggregates: site facets hold") for r in ei.value.reasons)
    assert await _version(conn) == v1
    await _no_new_tables(conn)


@needs_db
async def test_the_orchestrator_keeps_the_staging_after_an_infrastructure_error_in_the_build(
        conn, tmp_path, monkeypatch, alerts):
    await _setup(conn)
    src = _split_fixture(tmp_path)
    assert (await _run(tmp_path, src))["outcome"] == "swapped"
    before, v1 = await _sums(conn), await _version(conn)

    async def boom(c, source):
        await c.execute("SELECT 1 / 0")
    monkeypatch.setattr(agg, "build_aggregates", boom)
    res = await _run(tmp_path, src)
    assert res["outcome"] == "error"
    await _staging_survives(conn)
    assert await _sums(conn) == before and await _version(conn) == v1
    assert len(alerts) == 1


@needs_db
async def test_the_orchestrator_blocks_and_drops_the_staging_on_an_invalid_aggregate(
        conn, tmp_path, monkeypatch, alerts):
    await _setup(conn)
    src = _split_fixture(tmp_path)
    await _run(tmp_path, src)
    before, v1 = await _sums(conn), await _version(conn)

    async def invalid(c, source):
        raise agg.AggregatesInvalid(["aggregates: injected"])
    monkeypatch.setattr(agg, "build_aggregates", invalid)
    res = await _run(tmp_path, src)
    assert res["outcome"] == "blocked" and res["reasons"] == ["aggregates: injected"]
    await _no_new_tables(conn)
    assert await _sums(conn) == before and await _version(conn) == v1


def test_meta_names_the_aggregate_check_and_never_its_text():
    assert _classify("swap blocked — aggregates: injected", None) == ("blocked", ["aggregates"])


@needs_db
async def test_a_deadlock_in_the_swap_is_retried_like_a_lock_timeout_and_keeps_staging(conn, tmp_path, monkeypatch):
    await stage_fixture(conn, tmp_path)
    await p.swap_validated(conn)
    before, v1 = await _sums(conn), await _version(conn)
    await _restage_from_live(conn)
    calls = []

    async def deadlocked(c):
        calls.append(1)
        raise asyncpg.exceptions.DeadlockDetectedError("x")
    monkeypatch.setattr(p, "_swap_aggregates_in_tx", deadlocked)
    with pytest.raises(p.SwapLockTimeout):
        await p.swap(conn, backoff=(0,))
    assert len(calls) == 2                                  # one retry
    assert await _sums(conn) == before and await _version(conn) == v1
    await _staging_survives(conn)


@needs_db
async def test_the_full_swap_takes_all_six_tables_in_one_lock_statement_in_the_fixed_order(conn, tmp_path):
    await stage_fixture(conn, tmp_path)
    rec = RecordingConn(conn)
    await p.swap_validated(rec)
    locks = [q for q in rec.executed if q.startswith("LOCK TABLE")]
    assert locks == ["LOCK TABLE " + ", ".join(p.SWAP_LOCK_ORDER) + " IN ACCESS EXCLUSIVE MODE"]
    at = next(i for i, q in enumerate(rec.executed) if q.startswith("SET LOCAL lock_timeout"))
    assert rec.executed[at + 1] == locks[0]            # the very first thing after the timeout, before any DDL
