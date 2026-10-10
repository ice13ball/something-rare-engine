# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Load, validate, swap of the plankton tables — real PostGIS (needs TEST_DATABASE_URL)."""
import os
import uuid

import asyncpg
import duckdb
import pytest

from ingestion import plankton_obis as p
from plankton_helpers import (  # noqa: F401  (conn is a fixture)
    _ds, _extract, _fixture_ids, conn, needs_db, reset_plankton as _fresh_live)
from schema.plankton import GROUPS, ensure_plankton


async def _staged(conn, tmp_path, licence="cc-by"):
    await _fresh_live(conn)
    await p.build_staging(conn)
    ids = _fixture_ids()
    await p.load_datasets(conn, _ds(ids, licence))
    stats = await p.load_extract(conn, _extract(tmp_path), {i: licence for i in ids})
    return ids, stats


@needs_db
async def test_load_keeps_only_filtered_rows_and_counts_every_drop_reason(conn, tmp_path):
    _, stats = await _staged(conn, tmp_path)
    total = duckdb.sql(f"SELECT count(*) FROM read_parquet('{_extract(tmp_path)}')").fetchone()[0]
    assert stats["kept"] > 0
    assert sum(stats.values()) == total          # every extract row lands in exactly one bucket
    assert set(stats) == {"kept", *p.DROP_REASONS}
    assert sum(v for k, v in stats.items() if k != "kept") > 0
    assert await conn.fetchval("SELECT count(*) FROM plankton_occurrences_new") == stats["kept"]
    assert await conn.fetchval("SELECT count(*) FROM plankton_occurrences_new WHERE depth_m < 0") == 0


@needs_db
async def test_first_run_swaps_into_an_empty_production_table(conn, tmp_path):
    _, stats = await _staged(conn, tmp_path)
    reasons = await p.validate_staging(conn)
    assert reasons == [] or all("group" in r for r in reasons)   # no live rows -> no drop rule
    await p.swap(conn)
    assert await conn.fetchval("SELECT count(*) FROM plankton_occurrences") == stats["kept"]
    assert await conn.fetchval("SELECT to_regclass('plankton_occurrences_new')") is None
    assert await conn.fetchval("SELECT to_regclass('plankton_datasets_new')") is None
    assert await conn.fetchval("SELECT sum(record_count) FROM plankton_datasets") == stats["kept"]


@needs_db
async def test_a_drop_of_more_than_ten_percent_blocks_the_swap(conn, tmp_path):
    await _staged(conn, tmp_path)
    await p.swap(conn)
    before = await conn.fetchval("SELECT count(*) FROM plankton_occurrences")
    await p.build_staging(conn)
    ids = [r["dataset_id"] for r in await conn.fetch("SELECT dataset_id FROM plankton_datasets")]
    await p.load_datasets(conn, _ds(ids))
    await conn.execute(f"""INSERT INTO plankton_occurrences_new (taxon_group, dataset_id, licence, is_edna, lon, lat)
        SELECT taxon_group, dataset_id, licence, is_edna, lon, lat FROM plankton_occurrences
        LIMIT {int(before * 0.85)}""")
    assert any("dropped" in r for r in await p.validate_staging(conn))


@needs_db
async def test_a_missing_group_blocks_the_swap(conn, tmp_path):
    await _staged(conn, tmp_path)
    await conn.execute("DELETE FROM plankton_occurrences_new WHERE taxon_group = 'copepoda'")
    assert any("copepoda" in r for r in await p.validate_staging(conn))


@needs_db
async def test_leftover_staging_from_a_killed_run_is_rebuilt(conn, tmp_path):
    await ensure_plankton(conn)
    await p.build_staging(conn)
    ghost = uuid.uuid4()
    await conn.execute("INSERT INTO plankton_datasets_new (dataset_id, licence) VALUES ($1, 'cc0')", ghost)
    await conn.execute("INSERT INTO plankton_occurrences_new (taxon_group, dataset_id, licence, is_edna, lon, lat) "
                       "VALUES ('copepoda', $1, 'cc0', false, 1, 1)", ghost)       # the killed run's loaded rows
    await p.build_staging(conn)     # second call must not fail and must start empty
    assert await conn.fetchval("SELECT count(*) FROM plankton_datasets_new") == 0
    assert await conn.fetchval("SELECT count(*) FROM plankton_occurrences_new") == 0


@needs_db
async def test_restricted_datasets_are_never_stored(conn, tmp_path):
    ids, _ = await _staged(conn, tmp_path)
    await p.build_staging(conn)
    await p.load_datasets(conn, _ds(ids[1:]))
    stats = await p.load_extract(conn, _extract(tmp_path),
                                 {ids[0]: "restricted", **{i: "cc-by" for i in ids[1:]}})
    assert stats["restricted"] > 0
    assert await conn.fetchval("SELECT count(*) FROM plankton_occurrences_new WHERE dataset_id = $1",
                               uuid.UUID(ids[0])) == 0
    # a dataset flagged restricted is not stored in the datasets table either
    await p.build_staging(conn)
    await p.load_datasets(conn, _ds(ids[:1], licence="restricted"))
    assert await conn.fetchval("SELECT count(*) FROM plankton_datasets_new") == 0


@needs_db
async def test_licence_comes_from_the_mapping_and_empty_means_unknown(conn, tmp_path):
    ids, _ = await _staged(conn, tmp_path)
    await p.build_staging(conn)
    await p.load_datasets(conn, _ds(ids))
    mapping = {ids[0]: "CC BY-NC 4.0", **{i: None for i in ids[1:]}}
    await p.load_extract(conn, _extract(tmp_path), mapping)
    got = {str(r["dataset_id"]): r["licence"] for r in await conn.fetch(
        "SELECT dataset_id, licence FROM plankton_occurrences_new GROUP BY 1, 2")}
    assert got.get(ids[0], "cc-by-nc") == "cc-by-nc"
    assert all(v == "unknown" for k, v in got.items() if k != ids[0])


def _synthetic(tmp_path, rows):
    """An extract file of hand-made rows (all keep=true) in the Task 8 column layout."""
    dest = tmp_path / "syn.parquet"
    con = duckdb.connect()
    con.execute("""CREATE TABLE t (dataset_id VARCHAR, grp VARCHAR, keep BOOLEAN, sciname VARCHAR,
        aphiaid BIGINT, ord VARCHAR, genus VARCHAR, lat DOUBLE, lon DOUBLE, depth DOUBLE, dmin DOUBLE,
        dmax DOUBLE, month VARCHAR, eventdate VARCHAR, basis VARCHAR, edna_struct BOOLEAN,
        absence BOOLEAN, dropped BOOLEAN, flags VARCHAR[])""")
    for r in rows:
        con.execute("INSERT INTO t VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", r)
    con.execute(f"COPY t TO '{dest}' (FORMAT PARQUET)")
    return dest


@needs_db
async def test_values_that_would_violate_a_check_become_null_or_drop_the_row(conn, tmp_path):
    ds = str(uuid.uuid4())
    await ensure_plankton(conn)
    await p.build_staging(conn)
    await p.load_datasets(conn, _ds([ds]))

    def row(**kw):
        base = dict(dataset_id=ds, grp="copepoda", keep=True, sciname="x", aphiaid=1, ord="Calanoida",
                    genus="g", lat=10.0, lon=10.0, depth=5.0, dmin=None, dmax=None, month="6",
                    eventdate=None, basis="x", edna_struct=False, absence=False, dropped=False, flags=[])
        base.update(kw)
        return tuple(base.values())

    path = _synthetic(tmp_path, [
        row(depth=-5.0, sciname="neg"),
        row(depth=20000.0, sciname="deep"),
        row(month="13", sciname="m13"),
        row(lon=200.0, sciname="lon200"),
        row(lat=None, sciname="nolat"),
        row(sciname="ok"),
    ])
    stats = await p.load_extract(conn, path, {ds: "cc0"})
    assert stats["kept"] == 4 and stats["bad_coords"] == 2
    got = {r["scientific_name"]: r for r in await conn.fetch("SELECT * FROM plankton_occurrences_new")}
    assert set(got) == {"neg", "deep", "m13", "ok"}
    assert got["neg"]["depth_m"] is None and got["deep"]["depth_m"] is None
    assert got["m13"]["month"] is None and got["ok"]["month"] == 6 and got["ok"]["depth_m"] == 5.0


@needs_db
async def test_aphia_outside_int32_becomes_null_and_nul_bytes_are_stripped(conn, tmp_path):
    ds = str(uuid.uuid4())
    await _fresh_live(conn)
    await p.build_staging(conn)
    await p.load_datasets(conn, _ds([ds]))
    base = dict(dataset_id=ds, grp="copepoda", keep=True, sciname="x", aphiaid=1, ord="Calanoida",
                genus="g", lat=10.0, lon=10.0, depth=5.0, dmin=None, dmax=None, month="6",
                eventdate=None, basis="x", edna_struct=False, absence=False, dropped=False, flags=[])
    rows = [tuple({**base, "aphiaid": 3_000_000_000, "sciname": "big"}.values()),
            tuple({**base, "sciname": "nu\x00l", "ord": "Cal\x00anoida"}.values())]
    stats = await p.load_extract(conn, _synthetic(tmp_path, rows), {ds: "cc0"})
    assert stats["kept"] == 2
    got = {r["scientific_name"]: r for r in await conn.fetch("SELECT * FROM plankton_occurrences_new")}
    assert got["big"]["aphia_id"] is None
    assert got["nul"]["taxon_order"] == "Calanoida" and got["nul"]["aphia_id"] == 1


@needs_db
async def test_failed_validation_drops_staging_and_leaves_live_untouched(conn, tmp_path):
    _, stats = await _staged(conn, tmp_path)
    await p.swap(conn)
    live = await conn.fetchval("SELECT count(*) FROM plankton_occurrences")
    await p.build_staging(conn)                       # empty staging -> every group missing
    with pytest.raises(p.SwapBlocked) as e:
        await p.swap_validated(conn)
    assert e.value.reasons
    assert await conn.fetchval("SELECT to_regclass('plankton_occurrences_new')") is None
    assert await conn.fetchval("SELECT to_regclass('plankton_datasets_new')") is None
    assert await conn.fetchval("SELECT count(*) FROM plankton_occurrences") == live == stats["kept"]


async def test_swap_while_live_tables_exist_is_atomic_and_repeatable(tmp_path):
    """Committed work in a private schema, a second connection watching. Proves: building `_new`
    next to live data collides on nothing (constraints, indexes, identity sequence), the swap
    replaces the data, a reader never sees an empty table, and a SECOND cycle works too."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("needs TEST_DATABASE_URL")
    schema = "plankton_t9_" + uuid.uuid4().hex[:8]
    opts = {"search_path": f"{schema},public"}
    a = await asyncpg.connect(url)
    b = await asyncpg.connect(url, server_settings=opts)
    try:
        await a.execute(f"CREATE SCHEMA {schema}")
        await a.execute(f"GRANT USAGE, CREATE ON SCHEMA {schema} TO PUBLIC")  # tables are owned by abyssal_user
        await a.execute(f"SET search_path = {schema}, public")
        await ensure_plankton(a)
        ids = _fixture_ids()
        path = _extract(tmp_path)
        kept = []
        for cycle in range(2):
            await p.build_staging(a)                  # live tables exist (empty, then populated)
            await p.load_datasets(a, _ds(ids))
            stats = await p.load_extract(a, path, {i: "cc-by" for i in ids})
            kept.append(stats["kept"])
            before = await b.fetchval("SELECT count(*) FROM plankton_occurrences")
            assert before == (0 if cycle == 0 else kept[0])
            assert await p.validate_staging(a) == [] or cycle == 0
            await p.swap(a)
            assert await b.fetchval("SELECT count(*) FROM plankton_occurrences") == stats["kept"]
            assert await b.fetchval("SELECT to_regclass('plankton_occurrences_new')") is None
            assert await b.fetchval("SELECT to_regclass('plankton_datasets_new')") is None
            leftovers = await b.fetch(
                "SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = $1 AND relname LIKE '%\\_new%'", schema)
            assert leftovers == []
            names = {r["relname"] for r in await b.fetch(
                "SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = $1", schema)}
            if cycle == 1:
                async def cons(c, sch):
                    return {r["conname"] for r in await c.fetch(
                        "SELECT conname FROM pg_constraint co JOIN pg_namespace n ON n.oid = co.connamespace "
                        "WHERE n.nspname = $1 AND co.conrelid IN (SELECT oid FROM pg_class WHERE relname LIKE 'plankton\\_%')", sch)}
                ref = "plankton_t9ref_" + uuid.uuid4().hex[:8]
                await a.execute(f"CREATE SCHEMA {ref}")
                await a.execute(f"GRANT USAGE, CREATE ON SCHEMA {ref} TO PUBLIC")
                await a.execute(f"SET search_path = {ref}, public")
                await ensure_plankton(a)
                fresh = await cons(a, ref)
                await a.execute(f"SET search_path = {schema}, public")
                await a.execute(f"DROP SCHEMA {ref} CASCADE")
                assert fresh and await cons(b, schema) == fresh
            assert {"plankton_occurrences_pkey", "plankton_occurrences_id_seq", "plankton_occurrences_geom_gix",
                    "plankton_datasets_pkey"} <= names
        assert set(GROUPS) >= {r[0] for r in await b.fetch("SELECT DISTINCT taxon_group FROM plankton_occurrences")}
    finally:
        await a.execute(f"DROP SCHEMA {schema} CASCADE")
        await a.close()
        await b.close()


async def test_swap_waits_a_bounded_time_for_a_long_reader_and_never_blocks_other_readers(tmp_path):
    """A reader holding the live table makes the swap's ACCESS EXCLUSIVE request queue. It must
    give up after lock_timeout (not wait forever), leave live AND `_new` intact, and must not
    hold other plain SELECTs hostage while it waits."""
    import asyncio
    import time
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("needs TEST_DATABASE_URL")
    schema = "plankton_t9_" + uuid.uuid4().hex[:8]
    opts = {"search_path": f"{schema},public"}
    a = await asyncpg.connect(url)
    reader = await asyncpg.connect(url, server_settings=opts)
    third = await asyncpg.connect(url, server_settings=opts)
    try:
        await a.execute(f"CREATE SCHEMA {schema}")
        await a.execute(f"GRANT USAGE, CREATE ON SCHEMA {schema} TO PUBLIC")
        await a.execute(f"SET search_path = {schema}, public")
        await ensure_plankton(a)
        ids = _fixture_ids()
        await p.build_staging(a)
        await p.load_datasets(a, _ds(ids))
        stats = await p.load_extract(a, _extract(tmp_path), {i: "cc-by" for i in ids})
        await p.swap(a)                                   # live now holds data
        live = await a.fetchval("SELECT count(*) FROM plankton_occurrences")
        await p.build_staging(a)
        await p.load_datasets(a, _ds(ids))
        await p.load_extract(a, _extract(tmp_path), {i: "cc-by" for i in ids})
        new_rows = await a.fetchval("SELECT count(*) FROM plankton_occurrences_new")

        tx = reader.transaction()
        await tx.start()
        await reader.fetchval("SELECT count(*) FROM plankton_occurrences")   # holds ACCESS SHARE
        t0 = time.monotonic()
        task = asyncio.create_task(p.swap(a, lock_timeout="400ms", backoff=(1.5,)))
        await asyncio.sleep(0.9)                          # attempt 1 timed out, now in backoff
        t1 = time.monotonic()
        assert await asyncio.wait_for(third.fetchval("SELECT count(*) FROM plankton_occurrences"), 1.0) == live
        # while attempt 2 holds the queue (t ~ 1.9-2.3 s) a plain SELECT may wait at most the timeout
        await asyncio.sleep(1.2)
        t2 = time.monotonic()
        assert await asyncio.wait_for(third.fetchval("SELECT count(*) FROM plankton_occurrences"), 1.0) == live
        with pytest.raises(p.SwapLockTimeout):
            await task
        assert time.monotonic() - t0 < 5
        await tx.rollback()
        assert await third.fetchval("SELECT count(*) FROM plankton_occurrences") == live
        assert await third.fetchval("SELECT count(*) FROM plankton_occurrences_new") == new_rows
        # the staging pair is still swappable once the reader is gone
        await p.swap(a)
        assert await third.fetchval("SELECT count(*) FROM plankton_occurrences") == new_rows
        assert t2 > t1
    finally:
        await a.execute(f"DROP SCHEMA {schema} CASCADE")
        for c in (a, reader, third):
            await c.close()
