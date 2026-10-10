# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
import configparser
import importlib
import pathlib
from datetime import timedelta

import pytest

import argo_doxy_worker as w
import db
import scheduling
import sync_queue
from plankton_helpers import conn, needs_db  # noqa: F401
from schema.argo_doxy import ensure_argo_doxy
from schema.core import ensure_sync_queue

REPO = pathlib.Path(__file__).resolve().parents[2]


async def _fresh(conn):
    await conn.execute("""CREATE TABLE IF NOT EXISTS sync_log (source text PRIMARY KEY,
        last_synced_at timestamptz, records_added int NOT NULL DEFAULT 0, total_records int NOT NULL DEFAULT 0,
        skipped_reason text, skipped_at timestamptz)""")
    await conn.execute("DELETE FROM sync_log WHERE source = 'argo-doxy'")
    await ensure_sync_queue(conn)
    await conn.execute("DROP TABLE IF EXISTS argo_doxy_source CASCADE")
    await ensure_argo_doxy(conn)


@needs_db
async def test_never_loaded_decides_to_run(conn):
    await _fresh(conn)
    assert await w._decide(conn) == "never"


@needs_db
@pytest.mark.parametrize("age,decision", [
    ("1 day", "fresh"), ("6 days", "fresh"), ("6 days 11 hours", "fresh"),
    # the daily tick of day 7 sees the previous run's END stamp up to ~4.5 h short of 7 days (a full-budget run) and
    # the tick itself jitters: it must already be due, or the import slides to day 8
    ("6 days 13 hours", "due"), ("6 days 19 hours", "due"), ("6 days 23 hours", "due"), ("7 days", "due"),
    ("30 days", "due")])
async def test_weekly_cadence(conn, age, decision):
    await _fresh(conn)
    await conn.execute(f"UPDATE argo_doxy_source SET loaded_at=now(), last_complete_at=now()-interval '{age}'")
    assert await w._decide(conn) == decision


@needs_db
async def test_floats_left_pending_by_a_partial_run_are_resumed_next_tick(conn):
    await _fresh(conn)
    await conn.execute("UPDATE argo_doxy_source SET loaded_at=now(), last_complete_at=NULL, pending_floats=120")
    assert await w._decide(conn) == "pending"


@needs_db
async def test_a_live_started_marker_means_running_and_a_stale_one_does_not(conn):
    await _fresh(conn)
    await conn.execute("INSERT INTO sync_log (source, skipped_reason, skipped_at) VALUES ('argo-doxy', 'started (due)', now())")
    assert await w._decide(conn) == "running"
    # a run is allowed its whole TimeoutStartSec (6 h 30 min): at 6 h 20 min the marker is still a live run
    await conn.execute("UPDATE sync_log SET skipped_at = now() - interval '6 hours 20 minutes' WHERE source='argo-doxy'")
    assert await w._decide(conn) == "running"
    await conn.execute("UPDATE sync_log SET skipped_at = now() - interval '6 hours 40 minutes' WHERE source='argo-doxy'")
    assert await w._decide(conn) == "never"


@needs_db
@pytest.mark.parametrize("age,decision", [("6 days", "backoff"), ("8 days", "never")])
async def test_backoff_holds_for_a_week_after_a_failure(conn, age, decision):
    await _fresh(conn)
    await conn.execute(f"UPDATE argo_doxy_source SET last_failed_at = now() - interval '{age}', last_failure='error'")
    assert await w._decide(conn) == decision


@needs_db
async def test_a_request_made_after_the_failure_bypasses_the_backoff(conn):
    await _fresh(conn)
    await conn.execute("UPDATE argo_doxy_source SET last_failed_at = now() - interval '1 day', last_failure='error', "
                       "refresh_requested_at = now()")
    assert await w._decide(conn) == "requested"


@needs_db
async def test_force_sync_from_the_api_reaches_the_worker(conn):
    """Failure mode: a sync nothing calls. POST /admin/sync/{source} only enqueues; drive the real drain path."""
    import sync_sources
    await _fresh(conn)
    await conn.execute("UPDATE argo_doxy_source SET loaded_at=now(), last_complete_at=now()")
    await conn.execute("DELETE FROM sync_requests WHERE source='argo-doxy'")
    assert await w._decide(conn) == "fresh"
    request_id = await sync_queue.enqueue("argo-doxy")
    ran = await sync_queue._drain(conn, sync_sources.SYNC_SOURCES.get, scheduling._forced_sync_runner, "test")
    assert ran == 1
    done = await conn.fetchrow("SELECT finished_at, error FROM sync_requests WHERE id=$1", request_id)
    assert done["finished_at"] and done["error"] is None
    assert await w._decide(conn) == "requested"


def test_the_layer_ops_and_action_maps_point_at_the_worker_source():
    import layer_ops
    import main
    assert layer_ops.LAYER_OPS["argo-oxygen-points"]["sync_source"] == "argo-doxy"
    assert main._SOURCE_TO_ACTION["argo-doxy"] == "argo-doxy"


def _seconds(spec: str) -> int:
    """systemd time span like '6h30m' -> seconds."""
    import re
    units = {"h": 3600, "m": 60, "s": 1}
    parts = re.findall(r"(\d+)([hms])", spec)
    assert parts and "".join(f"{n}{u}" for n, u in parts) == spec, spec
    return sum(int(n) * units[u] for n, u in parts)


def test_the_systemd_unit_runs_a_module_whose_main_runs_the_sync():
    unit = configparser.ConfigParser(strict=False, interpolation=None)
    unit.read(REPO / "deploy" / "argo-doxy.service")
    module = unit["Service"]["ExecStart"].split("-m", 1)[1].split()[0]
    mod = importlib.import_module(module)
    assert mod is w and callable(mod.main) and callable(mod.run_once)
    assert unit["Service"]["Type"] == "oneshot"
    assert unit["Service"]["MemoryMax"] == "1.5G" and unit["Service"]["MemoryHigh"] == "1.3G"
    env = [ln.split("=", 1)[1] for ln in (REPO / "deploy" / "argo-doxy.service").read_text().splitlines()
           if ln.startswith("Environment=")]
    assert any(v.startswith("ARGO_DOXY_SCRATCH_DIR=") for v in env)
    import ingestion.argo_doxy as L
    timeout = _seconds(unit["Service"]["TimeoutStartSec"])
    assert w.STARTED_STALE == timedelta(seconds=timeout)                  # a marker is "running" for exactly one unit run
    # The budget clock starts AFTER the index download/parse; the float in flight is finished, not cut. 1 h margin on
    # top of the lock poll and the budget covers a slow index, a 96 MB Sprof and the closing writes.
    assert timeout >= w.LOCK_WAIT_S + L.RUN_BUDGET_S + 3600
    # ... and the float in flight is bounded by the per-file download deadline, which must fit inside that margin
    assert 0 < L.FETCH_DEADLINE_S < 3600
    # Tick of day N+7 must find the run of day N due even though the run's end stamp is hours after its tick began:
    # a run that used its whole budget ends RUN_BUDGET_S + 1 h (index, float in flight, jitter) after its tick began.
    assert timedelta(days=6) <= w.CADENCE <= timedelta(days=7) - timedelta(seconds=L.RUN_BUDGET_S) - timedelta(hours=1)
    timer = configparser.ConfigParser(strict=False, interpolation=None)
    timer.read(REPO / "deploy" / "argo-doxy.timer")
    assert timer["Timer"]["Unit"] == "argo-doxy.service" and timer["Timer"]["OnCalendar"]


@needs_db
async def test_run_once_calls_the_sync_when_due_and_stamps_the_outcome(conn, monkeypatch):
    await _fresh(conn)
    monkeypatch.setattr(w, "_mem_available_kib", lambda: 8 * 1024 * 1024)
    monkeypatch.setattr(w, "_disk_used_fraction", lambda: 0.5)
    calls = []

    async def fake_sync():
        calls.append(1)
        return {"outcome": "updated"}
    out = await w.run_once(db.pool, sync=fake_sync, lock_wait_s=1, lock_poll_s=0.1)
    assert out == "updated" and calls == [1]
    s = await conn.fetchrow("SELECT last_decision, last_failed_at FROM argo_doxy_source")
    assert s["last_decision"] == "updated" and s["last_failed_at"] is None
    reason = await conn.fetchval("SELECT skipped_reason FROM sync_log WHERE source='argo-doxy'")
    assert reason is None or not reason.startswith("started")          # /meta must not read "running" afterwards
    assert await conn.fetchval("SELECT last_run_at IS NOT NULL FROM argo_doxy_source")


@needs_db
@pytest.mark.parametrize("outcome", ["blocked", "error", "schema"])
async def test_a_persistent_failure_starts_the_backoff(conn, monkeypatch, outcome):
    await _fresh(conn)
    monkeypatch.setattr(w, "_mem_available_kib", lambda: 8 * 1024 * 1024)
    monkeypatch.setattr(w, "_disk_used_fraction", lambda: 0.5)

    async def fake_sync():
        return {"outcome": outcome}
    await w.run_once(db.pool, sync=fake_sync, lock_wait_s=1, lock_poll_s=0.1)
    assert await conn.fetchval("SELECT last_failure FROM argo_doxy_source") == outcome
    assert await w._decide(conn) == "backoff"


@needs_db
@pytest.mark.parametrize("outcome", ["partial", "disk", "index failed", "unreachable", "unchanged"])
async def test_transient_or_healthy_outcomes_do_not_start_the_backoff(conn, monkeypatch, outcome):
    await _fresh(conn)
    monkeypatch.setattr(w, "_mem_available_kib", lambda: 8 * 1024 * 1024)
    monkeypatch.setattr(w, "_disk_used_fraction", lambda: 0.5)

    async def fake_sync():
        return {"outcome": outcome}
    await w.run_once(db.pool, sync=fake_sync, lock_wait_s=1, lock_poll_s=0.1)
    assert await conn.fetchval("SELECT last_failed_at FROM argo_doxy_source") is None


@needs_db
async def test_a_short_result_from_an_early_exit_is_read_without_float_counts(conn, monkeypatch):
    """The loader's early exits ('index failed', 'schema') return a dict with no floats_done / written keys."""
    await _fresh(conn)
    monkeypatch.setattr(w, "_mem_available_kib", lambda: 8 * 1024 * 1024)
    monkeypatch.setattr(w, "_disk_used_fraction", lambda: 0.5)

    async def early():
        return {"outcome": "index failed"}
    assert await w.run_once(db.pool, sync=early, lock_wait_s=1, lock_poll_s=0.1) == "index failed"
    assert await conn.fetchval("SELECT last_decision FROM argo_doxy_source") == "index failed"

    async def no_outcome():
        return {}
    assert await w.run_once(db.pool, sync=no_outcome, lock_wait_s=1, lock_poll_s=0.1) == "error"
    assert await conn.fetchval("SELECT last_failure FROM argo_doxy_source") == "error"


@needs_db
async def test_a_killed_run_leaves_an_interrupted_stamp(conn, monkeypatch):
    await _fresh(conn)
    monkeypatch.setattr(w, "_mem_available_kib", lambda: 8 * 1024 * 1024)
    monkeypatch.setattr(w, "_disk_used_fraction", lambda: 0.5)

    async def killed():
        raise SystemExit("OOM")
    with pytest.raises(SystemExit):
        await w.run_once(db.pool, sync=killed, lock_wait_s=1, lock_poll_s=0.1)
    assert await conn.fetchval("SELECT last_failure FROM argo_doxy_source") == "interrupted"


@pytest.fixture
def _loader_fixture(tmp_path, monkeypatch):
    """The real loader on the real fixture, network replaced by local copies; the developer's disk must not decide."""
    import gzip
    import shutil
    from ingestion import argo_doxy as L
    fix = pathlib.Path(__file__).parent / "fixtures" / "argo_doxy"
    index = gzip.compress((fix / "argo_synthetic-profile_index.excerpt.txt").read_bytes())

    def fetch_sprof(dac, wmo, dest):
        shutil.copy(fix / f"{dac}_{wmo}_Sprof.nc", dest)
        return dest.stat().st_size
    monkeypatch.setattr(L, "SCRATCH_DIR", tmp_path / "scratch")
    monkeypatch.setattr(L, "_disk_used_fraction", lambda: 0.1)
    monkeypatch.setattr(w, "_mem_available_kib", lambda: 8 * 1024 * 1024)
    monkeypatch.setattr(w, "_disk_used_fraction", lambda: 0.5)
    return L, (lambda: index), fetch_sprof


@needs_db
async def test_a_partial_run_is_resumed_by_the_next_tick_until_complete_then_fresh(conn, _loader_fixture):
    """The whole chain through the worker with the REAL loader: never -> (budget ends) partial -> pending ->
    (resumed with room) complete -> fresh. The pending decision is read from what the loader left in
    argo_doxy_source, not from a hand-set pending_floats."""
    L, index, fetch_sprof = _loader_fixture
    await conn.execute("DROP TABLE IF EXISTS argo_doxy_profiles, argo_doxy_empty CASCADE")
    await _fresh(conn)
    assert await w._decide(conn) == "never"

    ticks = iter(range(0, 10**6, 1000))                     # a fake clock: 1000 s per float against a 2500 s budget

    async def short_budget():
        return await L.sync_argo_doxy(fetch_index=index, fetch_sprof=fetch_sprof, budget_s=2500, clock=lambda: next(ticks))
    assert await w.run_once(db.pool, sync=short_budget, lock_wait_s=1, lock_poll_s=0.1) == "partial"
    left = await conn.fetchval("SELECT pending_floats FROM argo_doxy_source")
    assert left > 0
    assert await w._decide(conn) == "pending"               # next tick: resumes, however recent the last run was
    assert await conn.fetchval("SELECT last_failed_at IS NULL FROM argo_doxy_source")   # a budget stop is not a failure

    marker = []

    async def with_room():
        # the worker wrote its start marker with the decision it acted on
        marker.append(await conn.fetchval("SELECT skipped_reason FROM sync_log WHERE source='argo-doxy'"))
        return await L.sync_argo_doxy(fetch_index=index, fetch_sprof=fetch_sprof)
    out = await w.run_once(db.pool, sync=with_room, lock_wait_s=1, lock_poll_s=0.1)
    assert marker == ["started (pending)"] and out == "updated"
    s = await conn.fetchrow("SELECT pending_floats, last_complete_at FROM argo_doxy_source")
    assert s["pending_floats"] == 0 and s["last_complete_at"] is not None
    assert await w._decide(conn) == "fresh"                 # and the daily tick goes back to doing nothing


@needs_db
async def test_a_short_gdac_outage_is_no_failure_and_the_next_tick_resumes(conn, _loader_fixture):
    """The real loader + worker: the GDAC refuses every download -> `unreachable` (transient: no last_failed_at, so no
    7-day back-off) -> the next tick resumes (`never` on a cold first import, `pending` once something is stored)."""
    import gzip
    L, index, fetch_sprof = _loader_fixture
    await conn.execute("DROP TABLE IF EXISTS argo_doxy_profiles, argo_doxy_empty CASCADE")
    await _fresh(conn)
    calls = []

    def down(dac, wmo, dest):
        calls.append(wmo)
        raise ConnectionError("GDAC down")

    def sync_with(fetch, idx=index):
        async def run():
            return await L.sync_argo_doxy(fetch_index=idx, fetch_sprof=fetch)
        return run

    async def tick(sync):
        return await w.run_once(db.pool, sync=sync, lock_wait_s=1, lock_poll_s=0.1)
    assert await tick(sync_with(down)) == "unreachable"            # cold first import, GDAC down
    assert len(calls) == 5 and await conn.fetchval("SELECT last_failed_at IS NULL FROM argo_doxy_source")
    assert await conn.fetchval("SELECT last_failure FROM argo_doxy_source") is None
    assert await w._decide(conn) == "never"                         # not `backoff`: the next daily tick runs again
    assert await tick(sync_with(fetch_sprof)) == "updated"
    # a weekly refresh with the whole index changed, GDAC down again
    newer = gzip.compress("".join(
        ln if ln.startswith(("#", "file,")) else ",".join(ln.split(",")[:9] + ["20991231000000"]) + "\n"
        for ln in gzip.decompress(index()).decode().splitlines(True)).encode())
    calls.clear()
    await conn.execute("UPDATE argo_doxy_source SET last_complete_at = now() - interval '7 days'")     # the week is up
    assert await tick(sync_with(down, lambda: newer)) == "unreachable"
    assert len(calls) == 5 and await conn.fetchval("SELECT last_failed_at IS NULL FROM argo_doxy_source")
    assert await w._decide(conn) == "pending"
    assert await tick(sync_with(fetch_sprof, lambda: newer)) == "updated"
    assert await conn.fetchval("SELECT pending_floats FROM argo_doxy_source") == 0
    assert await w._decide(conn) == "fresh"


@needs_db
async def test_a_healthy_fresh_decision_writes_nothing_to_sync_log(conn):
    await _fresh(conn)
    await conn.execute("UPDATE argo_doxy_source SET loaded_at=now(), last_complete_at=now()")
    assert await w.run_once(db.pool, sync=None, lock_wait_s=1, lock_poll_s=0.1) == "fresh"
    assert await conn.fetchval("SELECT count(*) FROM sync_log WHERE source='argo-doxy'") == 0
    assert await conn.fetchval("SELECT last_decision FROM argo_doxy_source") == "fresh"


@needs_db
async def test_low_memory_or_full_disk_defers_and_logs(conn, monkeypatch):
    await _fresh(conn)
    monkeypatch.setattr(w, "_mem_available_kib", lambda: 1024)
    assert await w.run_once(db.pool, sync=None, lock_wait_s=1, lock_poll_s=0.1) == "low memory"
    monkeypatch.setattr(w, "_mem_available_kib", lambda: 8 * 1024 * 1024)
    monkeypatch.setattr(w, "_disk_used_fraction", lambda: 0.95)
    assert await w.run_once(db.pool, sync=None, lock_wait_s=1, lock_poll_s=0.1) == "disk"
    assert (await conn.fetchval("SELECT skipped_reason FROM sync_log WHERE source='argo-doxy'")).startswith("disk above")


@needs_db
async def test_a_lock_held_past_the_budget_exits_busy_and_writes_nothing(conn, monkeypatch):
    import asyncpg
    import os
    await _fresh(conn)
    monkeypatch.setattr(w, "_mem_available_kib", lambda: 8 * 1024 * 1024)
    monkeypatch.setattr(w, "_disk_used_fraction", lambda: 0.5)
    other = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
    try:
        assert await other.fetchval("SELECT pg_try_advisory_lock($1)", w.LOCK_KEY)

        async def must_not_run():
            raise AssertionError("imported without the lock")
        assert await w.run_once(db.pool, sync=must_not_run, lock_wait_s=0.3, lock_poll_s=0.1) == "busy"
        assert await conn.fetchval("SELECT count(*) FROM sync_log WHERE source='argo-doxy'") == 0
    finally:
        await other.execute("SELECT pg_advisory_unlock($1)", w.LOCK_KEY)
        await other.close()


def test_importing_the_worker_does_not_import_the_api_stack():
    """A fresh interpreter (-I: no cwd/PYTHONPATH): the worker's cgroup must not pay for fastapi/domains/schema."""
    import subprocess
    import sys
    backend = str(pathlib.Path(__file__).resolve().parent.parent)
    code = ("import sys; sys.path.insert(0, %r); import argo_doxy_worker; "
            "bad = sorted(m for m in sys.modules if m.split('.')[0] in ('fastapi', 'starlette', 'domains', 'schema', "
            "'routers', 'main')); print(bad); sys.exit(1 if bad else 0)" % backend)
    res = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stdout + res.stderr
