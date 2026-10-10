# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Parallel extraction, the per-dataset ledger and --resume of the plankton import.

ExtractStream tests need no database; the rest use the rolled-back connection of plankton_helpers
(real PostGIS, real extract children, the 4-dataset fixture)."""
import asyncio
import contextlib
import pathlib

import pytest

import plankton_obis_worker as w
from ingestion import plankton_obis as p
from plankton_helpers import conn, needs_db  # noqa: F401  (conn is a fixture)
from test_plankton_sync_db import (  # noqa: F401  (fixtures + helpers of the sync tests)
    IDS, LIC, META, _log, _run, _setup, _split_fixture, alerts)

GB = 1024**3


# ---- ExtractStream, no database -----------------------------------------------------------------

async def _drain(stream, consume_s=0.0, on_item=None):
    got = []
    async with contextlib.aclosing(stream.results()) as it:
        async for i, res, err in it:
            got.append((i, res, err))
            if on_item:
                on_item(i)
            if consume_s:
                await asyncio.sleep(consume_s)
    return got


def _stream(ids, sizes, parallel, *, mem_ok=lambda: True, work=0.03, log=None, fail=()):
    """ExtractStream over fake extracts that record who runs at once and with which weight."""
    state = {"running": {}, "max_w": 0, "max_n": 0, "giant_with_other": False}
    log = [] if log is None else log

    async def run_one(i):
        state["running"][i] = p.weight_for_size(sizes[i])
        state["max_w"] = max(state["max_w"], sum(state["running"].values()))
        state["max_n"] = max(state["max_n"], len(state["running"]))
        if p.weight_for_size(sizes[i]) == 3 and len(state["running"]) > 1:
            state["giant_with_other"] = True
        if any(w_ == 3 for k, w_ in state["running"].items() if k != i):
            state["giant_with_other"] = True
        log.append(i)
        try:
            await asyncio.sleep(work)
            if i in fail:
                raise p.ChildFailed("boom")
            return i
        finally:
            del state["running"][i]

    async def weigh(i):
        return p.weight_for_size(sizes[i])
    return p.ExtractStream(ids, run_one, weigh, parallel, mem_ok=mem_ok), state


async def test_weight_admission_never_exceeds_the_budget_and_giants_run_alone():
    sizes = {f"g{n}": 5 * GB for n in range(3)} | {f"m{n}": GB for n in range(6)} | {f"s{n}": 10**6 for n in range(9)}
    order = ["s0", "g0", "m0", "m1", "s1", "m2", "g1", "s2", "s3", "m3", "s4", "g2", "m4", "m5", "s5", "s6", "s7", "s8"]
    stream, st = _stream(order, sizes, parallel=3)
    got = await _drain(stream)
    assert sorted(i for i, _, _ in got) == sorted(order)          # nothing skipped, nothing twice
    assert st["max_w"] <= p.WEIGHT_BUDGET
    assert not st["giant_with_other"], "a >= 2 GB dataset must run alone"
    assert st["max_n"] >= 2                                       # ... and it did overlap the small ones


async def test_unknown_size_counts_as_big():
    assert p.weight_for_size(None) == p.WEIGHT_BUDGET
    assert p._source_size("/nonexistent/x.parquet") is None
    assert p.weight_for_size(2 * GB) == 3 and p.weight_for_size(GB) == 2
    assert p.weight_for_size(512 * 1024**2) == 2 and p.weight_for_size(10**6) == 1


async def test_parallel_one_is_strictly_sequential():
    ids = [f"s{n}" for n in range(6)]
    stream, st = _stream(ids, {i: 10**6 for i in ids}, parallel=1)
    got = await _drain(stream)
    assert [i for i, _, _ in got] == ids and st["max_n"] == 1


async def test_finished_extracts_waiting_for_their_load_never_exceed_the_concurrency():
    """The consumer (the load) is slow: extracts must not pile up finished files without bound."""
    ids = [f"s{n}" for n in range(12)]
    waiting, peak = set(), [0]
    stream, _ = _stream(ids, {i: 10**6 for i in ids}, parallel=3, work=0.001)
    orig = stream.run_one

    async def run_one(i):
        r = await orig(i)
        waiting.add(i)                                           # "file written", not yet loaded
        peak[0] = max(peak[0], len(waiting))
        return r
    stream.run_one = run_one
    await _drain(stream, consume_s=0.02, on_item=waiting.discard)
    assert 1 <= peak[0] <= 3


async def test_memory_guard_delays_admission_but_never_deadlocks(monkeypatch):
    monkeypatch.setattr(p, "MEM_POLL_S", 0.01)
    ids = [f"s{n}" for n in range(6)]
    sizes = {i: 10**6 for i in ids}
    high, st_high = _stream(ids, sizes, parallel=3, mem_ok=lambda: False)
    got = await asyncio.wait_for(_drain(high), 10)                # a lone child is always admitted: no deadlock
    assert len(got) == 6 and st_high["max_n"] == 1
    reads = []
    gate = {"open": False}

    def mem_ok():
        reads.append(1)
        return gate["open"]
    ok, st = _stream(ids, sizes, parallel=3, mem_ok=mem_ok, work=0.2)

    async def open_later():
        await asyncio.sleep(0.1)
        gate["open"] = True
    asyncio.ensure_future(open_later())
    await _drain(ok)
    assert reads and st["max_n"] >= 2                            # admitted once the reader said so, not before


async def test_a_failed_extract_is_reported_once_and_the_others_continue():
    ids = [f"s{n}" for n in range(6)]
    stream, _ = _stream(ids, {i: 10**6 for i in ids}, parallel=3, fail={"s2"})
    got = await _drain(stream)
    assert len(got) == 6
    errs = [(i, e) for i, _, e in got if e is not None]
    assert [i for i, _ in errs] == ["s2"] and isinstance(errs[0][1], p.ChildFailed)


async def test_closing_the_stream_cancels_running_children():
    ids = [f"s{n}" for n in range(6)]
    stream, st = _stream(ids, {i: 10**6 for i in ids}, parallel=3, work=30)
    async with contextlib.aclosing(stream.results()) as it:
        nxt = asyncio.ensure_future(it.__anext__())
        await asyncio.sleep(0.2)
        assert st["running"]
        nxt.cancel()
        with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
            await nxt
    assert not st["running"]


# ---- the import itself --------------------------------------------------------------------------

async def _rows(conn, table="plankton_occurrences"):
    return [tuple(r) for r in await conn.fetch(
        f"SELECT taxon_group, scientific_name, aphia_id, taxon_order, dataset_id::text, licence, is_edna, depth_m,"
        f" event_date, year, month, lon, lat FROM {table} "
        f"ORDER BY dataset_id, taxon_group, scientific_name, lon, lat, event_date, depth_m")]


def _launches(monkeypatch):
    """Records the source of every extract child launched (and how many run at once)."""
    seen = {"sources": [], "now": 0, "max": 0}
    real = p.extract_in_child

    async def spy(source, dest, scratch, title=None, **kw):
        seen["sources"].append(source)
        seen["now"] += 1
        seen["max"] = max(seen["max"], seen["now"])
        try:
            return await real(source, dest, scratch, title, **kw)
        finally:
            seen["now"] -= 1
    monkeypatch.setattr(p, "extract_in_child", spy)
    return seen


@needs_db
async def test_parallel_and_sequential_imports_give_identical_tables(conn, tmp_path, alerts, monkeypatch):
    src = _split_fixture(tmp_path)
    out = {}
    # the guard reads the memory of THIS process: a pytest run that has grown past it would hold it shut
    monkeypatch.setattr(p, "_mem_in_use_mb", lambda: 0)
    for par in ("1", "3"):
        monkeypatch.setenv("PLANKTON_PARALLEL", par)
        await _setup(conn)
        seen = _launches(monkeypatch)
        res = await _run(tmp_path, src)
        assert res["outcome"] == "swapped", res
        out[par] = (res, await _rows(conn),
                    await conn.fetch("SELECT dataset_id::text, licence, record_count FROM plankton_datasets ORDER BY 1"),
                    seen["max"])
        monkeypatch.delenv("PLANKTON_PARALLEL")
    (r1, rows1, ds1, max1), (r3, rows3, ds3, max3) = out["1"], out["3"]
    assert max1 == 1 and max3 > 1, "PLANKTON_PARALLEL=3 must actually overlap extracts on the fixture"
    assert rows1 and rows1 == rows3 and [tuple(r) for r in ds1] == [tuple(r) for r in ds3]
    for k in ("kept", "total", "datasets", "groups", "licences", "drops", "failed_datasets", "attempted"):
        assert r1[k] == r3[k], k


@needs_db
async def test_import_never_runs_two_giants_at_once_through_the_orchestrator(conn, tmp_path, alerts, monkeypatch):
    await _setup(conn)
    src = _split_fixture(tmp_path)
    monkeypatch.setenv("PLANKTON_PARALLEL", "3")
    sizes = {src[IDS[0]]: 5 * GB, src[IDS[1]]: 5 * GB, src[IDS[2]]: GB, src[IDS[3]]: 10**6}
    monkeypatch.setattr(p, "_source_size", lambda s: sizes[s])
    running, worst = {}, [0]
    real = p.extract_in_child

    async def spy(source, dest, scratch, title=None, **kw):
        running[source] = p.weight_for_size(sizes[source])
        worst[0] = max(worst[0], sum(running.values()))
        try:
            return await real(source, dest, scratch, title, **kw)
        finally:
            del running[source]
    monkeypatch.setattr(p, "extract_in_child", spy)
    res = await _run(tmp_path, src)
    assert res["outcome"] == "swapped" and worst[0] <= p.WEIGHT_BUDGET


@needs_db
async def test_loads_are_sequential_on_the_one_connection(conn, tmp_path, alerts, monkeypatch):
    await _setup(conn)
    monkeypatch.setenv("PLANKTON_PARALLEL", "3")
    now, peak, copies = [0], [0], [0]
    real = type(conn).copy_records_to_table

    async def copy(self, *a, **kw):
        now[0] += 1
        peak[0] = max(peak[0], now[0])
        copies[0] += 1
        try:
            await asyncio.sleep(0.05)                    # a window for an overlapping COPY to show itself
            return await real(self, *a, **kw)
        finally:
            now[0] -= 1
    monkeypatch.setattr(type(conn), "copy_records_to_table", copy)
    res = await _run(tmp_path, _split_fixture(tmp_path))
    assert res["outcome"] == "swapped" and copies[0] >= len(IDS) and peak[0] == 1


@needs_db
async def test_a_crashing_child_under_parallelism_counts_once_and_the_rest_load(conn, tmp_path, alerts, monkeypatch):
    from test_plankton_sync_db import _crash_one_child
    await _setup(conn)
    monkeypatch.setenv("PLANKTON_PARALLEL", "3")
    calls = _crash_one_child(monkeypatch, 2, "import sys; sys.exit(7)")
    res = await _run(tmp_path, _split_fixture(tmp_path))
    assert len(calls) == len(IDS)
    assert res["outcome"] == "swapped" and res["failed_datasets"] == 1 and len(set(res["failed_ids"])) == 1
    assert res["attempted"] == len(IDS)
    assert await conn.fetchval("SELECT count(DISTINCT dataset_id) FROM plankton_occurrences") == len(IDS) - 1
    assert len(alerts) == 1 and "1 of" in alerts[0][1]


@needs_db
async def test_progress_lines_carry_the_number_in_flight(conn, tmp_path, alerts, monkeypatch, caplog):
    await _setup(conn)
    monkeypatch.setattr(p, "PROGRESS_SLOW_S", -1)
    with caplog.at_level("INFO"):
        await _run(tmp_path, _split_fixture(tmp_path))
    lines = [r.getMessage() for r in caplog.records if " datasets, rows so far " in r.getMessage()]
    assert lines and all("in flight " in m for m in lines)


# ---- the ledger and kill safety -----------------------------------------------------------------

@needs_db
async def test_staging_has_a_ledger_and_swap_and_discard_drop_it(conn, tmp_path, alerts):
    await _setup(conn)
    await p.build_staging(conn)
    assert await conn.fetchval("SELECT to_regclass('plankton_progress_new')")
    cols = {r["column_name"]: r for r in await conn.fetch(
        "SELECT column_name, is_nullable, data_type FROM information_schema.columns "
        "WHERE table_name = 'plankton_progress_new'")}
    assert set(cols) == {"dataset_id", "rows", "finished_at"} and cols["dataset_id"]["data_type"] == "uuid"
    await p.discard_staging(conn)
    assert not await conn.fetchval("SELECT to_regclass('plankton_progress_new')")
    await _setup(conn)
    res = await _run(tmp_path, _split_fixture(tmp_path))
    assert res["outcome"] == "swapped" and not await conn.fetchval("SELECT to_regclass('plankton_progress_new')")


async def _stage(conn, tmp_path, src, done_ids, *, ledger=True):
    """A staging pair as an interrupted run leaves it: every listed dataset in plankton_datasets_new,
    `done_ids` fully loaded."""
    await _setup(conn)
    rows = {i: p.resolve_dataset(META[i], p.parse_licences(LIC).get(i)) for i in IDS}
    await p.build_staging(conn)
    await p.load_datasets(conn, list(rows.values()))
    lic = {i: d["licence"] for i, d in rows.items()}
    scratch = tmp_path / "stage"
    scratch.mkdir(exist_ok=True)
    for i in done_ids:
        dest = scratch / f"{i}.parquet"
        n, _ = await p.extract_in_child(src[i], dest, scratch)
        assert n
        await p._load_one(conn, dest, lic, i)
        dest.unlink()
    if not ledger:
        await conn.execute("DROP TABLE plankton_progress_new")


async def _full_reference(conn, tmp_path, src):
    await _setup(conn)
    res = await _run(tmp_path, src)
    assert res["outcome"] == "swapped"
    return res, await _rows(conn)


@needs_db
async def test_a_failing_load_leaves_nothing_of_that_dataset_and_no_ledger_row(conn, tmp_path, alerts, monkeypatch):
    """Kill safety: the rows are COPYed, then the ledger insert (the end of the same transaction) dies."""
    await _setup(conn)
    src = _split_fixture(tmp_path)
    target = IDS[1]
    real = p.record_progress

    async def dying(c, ds, n):
        if ds == target:
            raise ValueError("killed before commit")
        return await real(c, ds, n)
    monkeypatch.setattr(p, "record_progress", dying)
    monkeypatch.setattr(p, "FAILED_FLOOR", 0)           # any failure ends the run, staging stays visible (resume)
    monkeypatch.setattr(p, "FAILED_FRACTION", 0)
    monkeypatch.setenv("PLANKTON_PARALLEL", "1")
    # a resumed run keeps its staging: that is where the leftovers would be visible
    await _stage(conn, tmp_path, src, [])
    res = await _run(tmp_path, src, resume=True)
    assert res["outcome"] == "error" and target in res["reasons"][0]
    assert await conn.fetchval("SELECT count(*) FROM plankton_occurrences_new WHERE dataset_id = $1::uuid", target) == 0
    assert await conn.fetchval("SELECT count(*) FROM plankton_progress_new WHERE dataset_id = $1::uuid", target) == 0
    ledger = {str(r[0]): r[1] for r in await conn.fetch("SELECT dataset_id, rows FROM plankton_progress_new")}
    for i, n in ledger.items():                          # every ledger row is exact
        assert await conn.fetchval(
            "SELECT count(*) FROM plankton_occurrences_new WHERE dataset_id = $1::uuid", i) == n


@needs_db
async def test_a_dataset_with_no_plankton_rows_is_still_recorded_as_done(conn, tmp_path, alerts, monkeypatch):
    """0 rows is a finished dataset: a resume must not download it again."""
    src = _split_fixture(tmp_path)
    await _stage(conn, tmp_path, src, [])
    empty = IDS[0]
    real = p.extract_in_child

    async def spy(source, dest, scratch, title=None, **kw):
        if source == src[empty]:
            return 0, 1
        return await real(source, dest, scratch, title, **kw)
    monkeypatch.setattr(p, "extract_in_child", spy)
    monkeypatch.setattr(p, "swap_validated", lambda c: _noop())     # keep staging visible
    res = await _run(tmp_path, src, resume=True)                    # a resumed run keeps its staging on error
    assert res["outcome"] == "error"
    assert await conn.fetchval("SELECT rows FROM plankton_progress_new WHERE dataset_id = $1::uuid", empty) == 0
    assert await conn.fetchval("SELECT count(*) FROM plankton_progress_new") == len(IDS)


async def _noop():
    raise RuntimeError("stop before the swap")


@needs_db
async def test_resume_with_a_ledger_skips_exactly_the_done_datasets(conn, tmp_path, alerts, monkeypatch):
    src = _split_fixture(tmp_path)
    ref, ref_rows = await _full_reference(conn, tmp_path, src)
    done = IDS[:2]
    await _stage(conn, tmp_path, src, done)
    built = []
    real_build = p.build_staging

    async def spy_build(c):
        built.append(1)
        return await real_build(c)
    monkeypatch.setattr(p, "build_staging", spy_build)
    seen = _launches(monkeypatch)
    res = await _run(tmp_path, src, resume=True)
    assert res["outcome"] == "swapped" and res["resumed"] is True and res["already_loaded"] == 2
    assert not built, "--resume must never call build_staging (it drops the loaded rows)"
    assert sorted(seen["sources"]) == sorted(src[i] for i in IDS if i not in done)   # no skip, no double load
    assert await _rows(conn) == ref_rows
    for k in ("kept", "datasets", "groups", "licences"):
        assert res[k] == ref[k], k
    assert not await conn.fetchval("SELECT to_regclass('plankton_progress_new')")


@needs_db
async def test_resume_without_a_ledger_seeds_it_from_the_rows_in_staging(conn, tmp_path, alerts, monkeypatch):
    src = _split_fixture(tmp_path)
    ref, ref_rows = await _full_reference(conn, tmp_path, src)
    done = IDS[:3]
    await _stage(conn, tmp_path, src, done, ledger=False)
    expected = {str(r[0]): r[1] for r in await conn.fetch(
        "SELECT dataset_id, count(*)::int FROM plankton_occurrences_new GROUP BY 1")}
    assert set(expected) == set(done)
    seen = _launches(monkeypatch)
    seeded = {}
    real_prepare = p._prepare_resume

    async def prepare(c):
        r = await real_prepare(c)
        seeded.update({str(x[0]): x[1] for x in await c.fetch("SELECT dataset_id, rows FROM plankton_progress_new")})
        return r
    monkeypatch.setattr(p, "_prepare_resume", prepare)
    res = await _run(tmp_path, src, resume=True)
    assert seeded == expected
    assert sorted(seen["sources"]) == sorted(src[i] for i in IDS if i not in done)
    assert res["outcome"] == "swapped" and await _rows(conn) == ref_rows and res["kept"] == ref["kept"]


@needs_db
async def test_resume_without_staging_tables_falls_back_to_a_full_run(conn, tmp_path, alerts, monkeypatch, caplog):
    src = _split_fixture(tmp_path)
    await _setup(conn)
    seen = _launches(monkeypatch)
    with caplog.at_level("WARNING"):
        res = await _run(tmp_path, src, resume=True)
    assert res["outcome"] == "swapped" and res["resumed"] is False
    assert sorted(seen["sources"]) == sorted(src.values())
    assert "do not both exist" in caplog.text
    # one of the two missing is just as little to resume from
    await _setup(conn)
    await p.build_staging(conn)
    await conn.execute("DROP TABLE plankton_occurrences_new")
    seen["sources"].clear()
    res = await _run(tmp_path, src, resume=True)
    assert res["outcome"] == "swapped" and len(seen["sources"]) == len(IDS)


@needs_db
async def test_resume_retries_a_failed_dataset_and_keeps_its_staging(conn, tmp_path, alerts, monkeypatch):
    """A failed dataset has no ledger row: the next resume loads it, and only it."""
    src = _split_fixture(tmp_path)
    ref, ref_rows = await _full_reference(conn, tmp_path, src)
    bad = IDS[2]
    await _stage(conn, tmp_path, src, IDS[:1])
    monkeypatch.setattr(p, "FAILED_FLOOR", 0)
    monkeypatch.setattr(p, "FAILED_FRACTION", 0)
    broken = {**src, bad: str(tmp_path / "missing.parquet")}
    res = await _run(tmp_path, broken, resume=True)
    assert res["outcome"] == "error"
    ledger = {str(r[0]) for r in await conn.fetch("SELECT dataset_id FROM plankton_progress_new")}
    assert bad not in ledger and IDS[0] in ledger and len(ledger) == len(IDS) - 1
    assert await conn.fetchval("SELECT to_regclass('plankton_occurrences_new')"), "a failed resume keeps its staging"
    monkeypatch.undo()
    seen = _launches(monkeypatch)
    res = await _run(tmp_path, src, resume=True)
    assert seen["sources"] == [src[bad]]
    assert res["outcome"] == "swapped" and await _rows(conn) == ref_rows


@needs_db
async def test_resume_drops_loaded_datasets_a_full_run_would_no_longer_keep(conn, tmp_path, alerts, monkeypatch):
    src = _split_fixture(tmp_path)
    await _stage(conn, tmp_path, src, IDS[:2])
    gone = IDS[0]
    res = await _run(tmp_path, src, ids=[i for i in IDS if i != gone], resume=True)    # no longer listed by OBIS
    assert res["outcome"] == "swapped"
    assert await conn.fetchval("SELECT count(*) FROM plankton_occurrences WHERE dataset_id = $1::uuid", gone) == 0
    assert await conn.fetchval("SELECT count(*) FROM plankton_datasets WHERE dataset_id = $1::uuid", gone) == 0


# ---- worker -------------------------------------------------------------------------------------

def test_cli_resume_implies_force():
    ns = w.parse_args(["--resume"])
    assert ns.resume is True and ns.force is True
    assert w.parse_args([]).resume is False and w.parse_args(["--force"]).resume is False


def test_parallel_env_defaults_to_three_and_one_means_sequential(monkeypatch):
    monkeypatch.delenv("PLANKTON_PARALLEL", raising=False)
    assert p._parallel() == 3
    monkeypatch.setenv("PLANKTON_PARALLEL", "1")
    assert p._parallel() == 1
    monkeypatch.setenv("PLANKTON_PARALLEL", "junk")
    assert p._parallel() == 3
    monkeypatch.setenv("PLANKTON_PARALLEL", "0")
    assert p._parallel() == 1


def test_cgroup_reader_and_fallback_never_raise(monkeypatch):
    assert isinstance(p._mem_in_use_mb(), int)
    monkeypatch.setattr(p, "_cgroup_anon_mb", lambda: None)
    assert p._mem_in_use_mb() >= 1
    monkeypatch.setattr(p, "_cgroup_anon_mb", lambda: 100)
    assert p._mem_in_use_mb() == 100
    monkeypatch.setattr(p, "_mem_in_use_mb", lambda: p.MEM_GUARD_MB + 1)
    assert p._memory_allows_child() is False
