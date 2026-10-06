# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
import asyncio
import configparser
import importlib
import os
import pathlib
from datetime import timedelta

import asyncpg
import pytest

import db
import glodap_bottles_worker as w
import scheduling
import sync_queue
from plankton_helpers import conn, needs_db  # noqa: F401
from sync_log import log_sync_skipped
from schema.core import ensure_sync_queue
from schema.glodap_bottles import ensure_glodap_bottles

REPO = pathlib.Path(__file__).resolve().parents[2]


async def _support(conn):
    """sync_log and the force-sync queue: the test database starts without them."""
    await conn.execute("""CREATE TABLE IF NOT EXISTS sync_log (source text PRIMARY KEY,
        last_synced_at timestamptz, records_added int NOT NULL DEFAULT 0, total_records int NOT NULL DEFAULT 0,
        skipped_reason text, skipped_at timestamptz)""")
    await ensure_sync_queue(conn)
    await ensure_glodap_bottles(conn)


async def _fresh_source(conn):
    await conn.execute("DROP TABLE IF EXISTS glodap_bottle_source CASCADE")
    await _support(conn)


@needs_db
async def test_never_loaded_decides_to_run(conn):
    await _fresh_source(conn)
    assert await w._decide(conn, head=lambda: {"etag": '"x"'}) == "never"


@needs_db
async def test_fresh_check_does_not_touch_the_network(conn):
    await _fresh_source(conn)
    await conn.execute("UPDATE glodap_bottle_source SET loaded_at=now(), last_checked_at=now(), etag='\"x\"'")

    def boom():
        raise AssertionError("HEAD must not run within 30 days")
    assert await w._decide(conn, head=boom) == "fresh"


@needs_db
async def test_monthly_check_detects_a_new_release(conn):
    await _fresh_source(conn)
    await conn.execute("UPDATE glodap_bottle_source SET loaded_at=now()-interval '40 days', "
                       "last_checked_at=now()-interval '40 days', etag='\"old\"'")
    assert await w._decide(conn, head=lambda: {"etag": '"new"'}) == "changed"
    await conn.execute("UPDATE glodap_bottle_source SET last_checked_at=now()-interval '40 days'")
    assert await w._decide(conn, head=lambda: {"etag": '"old"'}) == "unchanged"
    # an unchanged check is remembered: the next run is "fresh", with no HEAD
    assert await w._decide(conn, head=lambda: pytest.fail("HEAD ran twice in one month")) == "fresh"


@needs_db
async def test_without_an_etag_content_length_and_last_modified_decide(conn):
    await _fresh_source(conn)
    await conn.execute("UPDATE glodap_bottle_source SET loaded_at=now()-interval '40 days', "
                       "last_checked_at=now()-interval '40 days', etag=NULL, content_length=100, "
                       "last_modified='Mon, 01 Jan 2026 00:00:00 GMT'")
    same = {"content_length": 100, "last_modified": "Mon, 01 Jan 2026 00:00:00 GMT"}
    assert await w._decide(conn, head=lambda: dict(same, content_length=101)) == "changed"
    assert await w._decide(conn, head=lambda: same) == "unchanged"


@needs_db
async def test_a_failing_head_is_a_skipped_check_not_a_crash(conn):
    await _fresh_source(conn)
    await conn.execute("UPDATE glodap_bottle_source SET loaded_at=now()-interval '40 days', "
                       "last_checked_at=now()-interval '40 days'")

    def down():
        raise OSError("network is down")
    assert await w._decide(conn, head=down) == "head failed"
    # the check did not happen, so it must not be stamped as done
    assert await conn.fetchval("SELECT last_checked_at < now()-interval '30 days' FROM glodap_bottle_source")


@needs_db
async def test_a_live_started_marker_means_running_and_a_stale_one_does_not(conn):
    await _fresh_source(conn)
    await conn.execute("DELETE FROM sync_log WHERE source='glodap-bottles'")
    await conn.execute("INSERT INTO sync_log (source, skipped_reason, skipped_at) "
                       "VALUES ('glodap-bottles', 'started (never)', now()-interval '1 hour')")
    assert await w._decide(conn, head=lambda: {}) == "running"
    await conn.execute("UPDATE sync_log SET skipped_at=now()-interval '9 hours' WHERE source='glodap-bottles'")
    assert await w._decide(conn, head=lambda: {}) == "never"      # a killed run no longer blocks


@needs_db
async def test_force_sync_from_the_api_reaches_the_worker(conn):
    """Failure mode: a sync nothing calls. The admin POST only enqueues; the worker's listener resolves
    the source through SYNC_SOURCES and runs it under the shared sync lock — drive exactly that path."""
    import sync_sources
    await _fresh_source(conn)
    await conn.execute("UPDATE glodap_bottle_source SET loaded_at=now(), last_checked_at=now()")
    await conn.execute("DELETE FROM sync_requests WHERE source='glodap-bottles'")
    assert await w._decide(conn, head=lambda: {}) == "fresh"

    request_id = await sync_queue.enqueue("glodap-bottles")                 # what POST /admin/sync/{source} does
    ran = await sync_queue._drain(conn, sync_sources.SYNC_SOURCES.get, scheduling._forced_sync_runner, "test")

    assert ran == 1
    done = await conn.fetchrow("SELECT claimed_at, finished_at, error FROM sync_requests WHERE id=$1", request_id)
    assert done["claimed_at"] and done["finished_at"] and done["error"] is None
    assert await w._decide(conn, head=lambda: {}) == "requested"
    assert "refresh requested" in await conn.fetchval(
        "SELECT skipped_reason FROM sync_log WHERE source='glodap-bottles'")


@needs_db
async def test_a_request_during_a_live_import_keeps_the_started_marker(conn):
    from domains import glodap_points
    await _fresh_source(conn)
    await conn.execute("DELETE FROM sync_log WHERE source='glodap-bottles'")
    await conn.execute("INSERT INTO sync_log (source, skipped_reason, skipped_at) "
                       "VALUES ('glodap-bottles', 'started (requested)', now())")
    assert await glodap_points.request_refresh() == {"requested": True}
    assert await conn.fetchval("SELECT skipped_reason FROM sync_log WHERE source='glodap-bottles'") \
        == "started (requested)"
    assert await conn.fetchval("SELECT refresh_requested_at FROM glodap_bottle_source") is not None


def test_the_systemd_unit_runs_a_module_whose_main_runs_the_sync():
    unit = configparser.ConfigParser(strict=False, interpolation=None)
    unit.read(REPO / "deploy" / "glodap-bottles.service")
    exec_start = unit["Service"]["ExecStart"]
    module = exec_start.split("-m", 1)[1].split()[0]
    mod = importlib.import_module(module)
    assert mod is w and callable(mod.main) and callable(mod.run_once)
    assert unit["Service"]["Type"] == "oneshot"
    # the measured streaming RSS (~1006 MB on the synthetic file) must fit with headroom
    assert unit["Service"]["MemoryMax"] == "1.5G" and unit["Service"]["MemoryHigh"] == "1.3G"
    # the scratch directory the unit hands the loader is the one the loader reads
    env_lines = [ln.split("=", 1)[1] for ln in (REPO / "deploy" / "glodap-bottles.service").read_text().splitlines()
                 if ln.startswith("Environment=")]
    assert any(v.startswith("GLODAP_SCRATCH_DIR=") for v in env_lines)
    # TimeoutStartSec must cover the lock poll budget plus a full import, and a start marker is stale exactly
    # when the unit could no longer be running. 6h: 2 h poll + 4 h import cap.
    assert unit["Service"]["TimeoutStartSec"] == "6h"
    assert w.STARTED_STALE == timedelta(hours=6)
    assert w.LOCK_WAIT_S == 2 * 3600 and w.LOCK_WAIT_S + 4 * 3600 <= 6 * 3600
    timer = configparser.ConfigParser(strict=False, interpolation=None)
    timer.read(REPO / "deploy" / "glodap-bottles.timer")
    assert timer["Timer"]["Unit"] == "glodap-bottles.service" and timer["Timer"]["OnCalendar"]


@needs_db
async def test_run_once_calls_the_sync_when_requested(monkeypatch):
    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"], min_size=1, max_size=2)
    try:
        async with pool.acquire() as c:
            await _support(c)
            await c.execute("UPDATE glodap_bottle_source SET refresh_requested_at=now()")
        called = {}

        async def fake_sync(**kw):
            called["yes"] = True
            return {"outcome": "swapped", "casts": 1, "reasons": []}
        monkeypatch.setattr(w, "sync_glodap_bottles", fake_sync)
        monkeypatch.setattr(w, "_mem_available_kib", lambda: 8 * 1024 * 1024)
        monkeypatch.setattr(w, "_disk_used_fraction", lambda: 0.6)
        assert await w.run_once(pool, head=lambda: {}) == "swapped" and called
        async with pool.acquire() as c:                      # the advisory lock was released
            assert await c.fetchval("SELECT pg_try_advisory_lock($1)", w.LOCK_KEY)
            await c.execute("SELECT pg_advisory_unlock($1)", w.LOCK_KEY)
    finally:
        async with pool.acquire() as c:
            await c.execute("UPDATE glodap_bottle_source SET refresh_requested_at=NULL")
            await c.execute("DELETE FROM sync_log WHERE source='glodap-bottles'")
        await pool.close()


@needs_db
async def test_full_disk_refuses_and_logs(monkeypatch):
    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"], min_size=1, max_size=2)
    try:
        async with pool.acquire() as c:
            await _support(c)
            await c.execute("UPDATE glodap_bottle_source SET refresh_requested_at=now()")

        async def must_not_run(**kw):
            raise AssertionError("the sync must not start on a full disk")
        monkeypatch.setattr(w, "sync_glodap_bottles", must_not_run)
        monkeypatch.setattr(w, "_mem_available_kib", lambda: 8 * 1024 * 1024)
        monkeypatch.setattr(w, "_disk_used_fraction", lambda: 0.81)
        assert await w.run_once(pool, head=lambda: {}) == "disk"
        async with pool.acquire() as c:                      # "ran, refused" is visible to the monitor
            assert "disk" in await c.fetchval("SELECT skipped_reason FROM sync_log WHERE source='glodap-bottles'")
    finally:
        async with pool.acquire() as c:
            await c.execute("UPDATE glodap_bottle_source SET refresh_requested_at=NULL")
            await c.execute("DELETE FROM sync_log WHERE source='glodap-bottles'")
        await pool.close()


@needs_db
async def test_running_decision_leaves_the_started_marker_alone(monkeypatch):
    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"], min_size=1, max_size=2)
    try:
        async with pool.acquire() as c:
            await _support(c)
            await c.execute("DELETE FROM sync_log WHERE source='glodap-bottles'")
            await c.execute("INSERT INTO sync_log (source, skipped_reason, skipped_at) "
                            "VALUES ('glodap-bottles', 'started (never)', now())")
        assert await w.run_once(pool, head=lambda: {}) == "running"
        async with pool.acquire() as c:
            assert await c.fetchval("SELECT skipped_reason FROM sync_log WHERE source='glodap-bottles'") \
                == "started (never)"
    finally:
        async with pool.acquire() as c:
            await c.execute("DELETE FROM sync_log WHERE source='glodap-bottles'")
        await pool.close()


# ── failure back-off ─────────────────────────────────────────────────────────

@needs_db
@pytest.mark.parametrize("age,decision", [("6 days 23 hours", "backoff"), ("7 days 1 hour", "never")])
async def test_backoff_holds_for_six_days_and_lifts_on_day_seven(conn, age, decision):
    await _fresh_source(conn)
    await conn.execute(f"UPDATE glodap_bottle_source SET last_failed_at = now() - interval '{age}', "
                       "last_failure = 'blocked'")
    assert await w._decide(conn, head=lambda: {}) == decision


@needs_db
async def test_a_request_made_after_the_failure_bypasses_the_backoff(conn):
    await _fresh_source(conn)
    await conn.execute("UPDATE glodap_bottle_source SET last_failed_at = now() - interval '1 day', "
                       "last_failure = 'error', refresh_requested_at = now() - interval '2 days'")
    assert await w._decide(conn, head=lambda: {}) == "backoff"       # the request that preceded the failure
    await conn.execute("UPDATE glodap_bottle_source SET refresh_requested_at = now() - interval '1 hour'")
    assert await w._decide(conn, head=lambda: {}) == "requested"     # an operator asked again afterwards


@needs_db
async def test_backoff_also_holds_back_the_monthly_head(conn):
    await _fresh_source(conn)
    await conn.execute("UPDATE glodap_bottle_source SET loaded_at = now() - interval '40 days', "
                       "last_checked_at = now() - interval '40 days', last_failed_at = now() - interval '1 day'")
    assert await w._decide(conn, head=lambda: pytest.fail("no HEAD during a back-off")) == "backoff"


async def _pool_with_request(monkeypatch, *, mem=8 * 1024 * 1024, disk=0.6):
    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"], min_size=1, max_size=2)
    async with pool.acquire() as c:
        await _support(c)
        await c.execute("UPDATE glodap_bottle_source SET refresh_requested_at=now(), last_failed_at=NULL, "
                        "last_failure=NULL, last_run_at=NULL, last_decision=NULL")
        await c.execute("DELETE FROM sync_log WHERE source='glodap-bottles'")
    monkeypatch.setattr(w, "_mem_available_kib", lambda: mem)
    monkeypatch.setattr(w, "_disk_used_fraction", lambda: disk)
    return pool


async def _cleanup(pool):
    async with pool.acquire() as c:
        await c.execute("UPDATE glodap_bottle_source SET refresh_requested_at=NULL, last_failed_at=NULL, "
                        "last_failure=NULL")
        await c.execute("DELETE FROM sync_log WHERE source='glodap-bottles'")
    await pool.close()


@needs_db
@pytest.mark.parametrize("outcome", ["blocked", "error", "schema"])
async def test_a_persistent_failure_starts_the_backoff(monkeypatch, outcome):
    pool = await _pool_with_request(monkeypatch)
    try:
        async def failing(**kw):
            await log_sync_skipped("glodap-bottles", f"{outcome}: stand-in")    # the loader's _outcome replaces the marker
            return {"outcome": outcome, "casts": 0, "reasons": ["x"], "rejected": {}}
        monkeypatch.setattr(w, "sync_glodap_bottles", failing)
        assert await w.run_once(pool, head=lambda: {}) == outcome
        async with pool.acquire() as c:
            s = await c.fetchrow("SELECT last_failure, last_failed_at, refresh_requested_at, last_decision "
                                 "FROM glodap_bottle_source")
            assert s["last_failure"] == outcome and s["last_failed_at"] > s["refresh_requested_at"]
            assert s["last_decision"] == outcome
            assert await w._decide(c, head=lambda: {}) == "backoff"
        # the next timer tick downloads nothing
        async def must_not_run(**kw):
            raise AssertionError("a backed-off import must not start")
        monkeypatch.setattr(w, "sync_glodap_bottles", must_not_run)
        assert await w.run_once(pool, head=lambda: {}) == "backoff"
    finally:
        await _cleanup(pool)


@needs_db
async def test_a_killed_run_starts_the_backoff_and_a_swap_or_lock_timeout_does_not(monkeypatch):
    pool = await _pool_with_request(monkeypatch)
    try:
        async def killed(**kw):
            raise RuntimeError("SIGKILL stand-in: the process dies before any outcome is recorded")
        monkeypatch.setattr(w, "sync_glodap_bottles", killed)
        with pytest.raises(RuntimeError):
            await w.run_once(pool, head=lambda: {})
        async with pool.acquire() as c:
            assert await c.fetchval("SELECT last_failure FROM glodap_bottle_source") == "interrupted"
            assert await w._decide(c, head=lambda: {}) == "running"       # the dead run's marker, for 6 h
            await c.execute("UPDATE sync_log SET skipped_at = now() - interval '9 hours' "
                            "WHERE source='glodap-bottles'")
            assert await w._decide(c, head=lambda: {}) == "backoff"       # then the daily tick backs off
            await c.execute("UPDATE glodap_bottle_source SET refresh_requested_at = now()")   # operator asks again

        async def timed_out(**kw):
            return {"outcome": "lock_timeout", "casts": 0, "reasons": [], "rejected": {}}
        monkeypatch.setattr(w, "sync_glodap_bottles", timed_out)
        assert await w.run_once(pool, head=lambda: {}) == "lock_timeout"
        async with pool.acquire() as c:
            assert await c.fetchval("SELECT last_failed_at FROM glodap_bottle_source") is None
    finally:
        await _cleanup(pool)


@needs_db
@pytest.mark.parametrize("mem,disk,decision", [(1024 * 1024, 0.6, "low memory"), (8 * 1024 * 1024, 0.9, "disk")])
async def test_a_memory_or_disk_deferral_does_not_start_the_backoff(monkeypatch, mem, disk, decision):
    pool = await _pool_with_request(monkeypatch, mem=mem, disk=disk)
    try:
        assert await w.run_once(pool, head=lambda: {}) == decision
        async with pool.acquire() as c:
            assert await c.fetchval("SELECT last_failed_at FROM glodap_bottle_source") is None
            assert await w._decide(c, head=lambda: {}) == "requested"      # still due tomorrow
            assert await c.fetchval("SELECT last_decision FROM glodap_bottle_source") == decision
    finally:
        await _cleanup(pool)


@needs_db
async def test_a_failing_head_does_not_start_the_backoff(monkeypatch):
    pool = await _pool_with_request(monkeypatch)
    try:
        async with pool.acquire() as c:
            await c.execute("UPDATE glodap_bottle_source SET refresh_requested_at=NULL, loaded_at = now() - "
                            "interval '40 days', last_checked_at = now() - interval '40 days'")

        def down():
            raise OSError("network is down")
        assert await w.run_once(pool, head=down) == "head failed"
        async with pool.acquire() as c:
            assert await c.fetchval("SELECT last_failed_at FROM glodap_bottle_source") is None
    finally:
        await _cleanup(pool)


# ── healthy decisions leave sync_log alone ───────────────────────────────────

@needs_db
@pytest.mark.parametrize("state", ["fresh", "backoff", "running"])
async def test_a_healthy_decision_keeps_the_swapped_note_and_stamps_the_source(monkeypatch, state):
    pool = await _pool_with_request(monkeypatch)
    note = "swapped, but rejected_rows=6 (date=3, position=3)"
    try:
        async with pool.acquire() as c:
            await c.execute("INSERT INTO sync_log (source, last_synced_at, skipped_reason, skipped_at) "
                            "VALUES ('glodap-bottles', now(), $1, now() - interval '1 day')", note)
            await c.execute("UPDATE glodap_bottle_source SET refresh_requested_at=NULL, loaded_at=now(), "
                            "last_checked_at=now()")
            if state == "backoff":
                await c.execute("UPDATE glodap_bottle_source SET last_failed_at=now() - interval '1 day'")
            if state == "running":
                await c.execute("UPDATE sync_log SET skipped_reason='started (never)', skipped_at=now()")
                note = "started (never)"
        assert await w.run_once(pool, head=lambda: pytest.fail("no HEAD")) == state
        async with pool.acquire() as c:
            row = await c.fetchrow("SELECT skipped_reason, skipped_at FROM sync_log WHERE source='glodap-bottles'")
            assert row["skipped_reason"] == note
            assert await c.fetchval("SELECT skipped_at < now() - interval '12 hours' FROM sync_log "
                                    "WHERE source='glodap-bottles'") == (state != "running")
            s = await c.fetchrow("SELECT last_run_at, last_decision FROM glodap_bottle_source")
            assert s["last_run_at"] is not None and s["last_decision"] == state
    finally:
        await _cleanup(pool)


@needs_db
async def test_a_healthy_decision_clears_a_transient_deferral_but_not_a_failure(monkeypatch):
    pool = await _pool_with_request(monkeypatch)
    try:
        for reason, cleared in (("low memory: deferred to the next timer run", True),
                                ("disk above 80 %: refused", True),
                                ("head failed: monthly check skipped", True),
                                ("blocked: rows dropped 12 %", False)):
            async with pool.acquire() as c:
                await c.execute("UPDATE glodap_bottle_source SET refresh_requested_at=NULL, loaded_at=now(), "
                                "last_checked_at=now()")
                await c.execute("DELETE FROM sync_log WHERE source='glodap-bottles'")
                await c.execute("INSERT INTO sync_log (source, skipped_reason, skipped_at) "
                                "VALUES ('glodap-bottles', $1, now())", reason)
            assert await w.run_once(pool, head=lambda: pytest.fail("no HEAD")) == "fresh"
            async with pool.acquire() as c:
                left = await c.fetchval("SELECT skipped_reason FROM sync_log WHERE source='glodap-bottles'")
            assert (left is None) == cleared, reason
    finally:
        await _cleanup(pool)


# ── shared advisory lock: polled, never waited on blockingly ─────────────────

async def _holder(monkeypatch_pool_dsn):
    """A second connection that holds the shared lock, like plankton mid-import."""
    c = await asyncpg.connect(monkeypatch_pool_dsn)
    assert await c.fetchval("SELECT pg_try_advisory_lock($1)", w.LOCK_KEY)
    return c


@needs_db
async def test_a_lock_held_past_the_budget_exits_busy_and_leaves_nothing_behind(monkeypatch):
    pool = await _pool_with_request(monkeypatch)
    holder = await _holder(os.environ["TEST_DATABASE_URL"])
    try:
        async def must_not_run(**kw):
            raise AssertionError("the import must not start while another job holds the lock")
        monkeypatch.setattr(w, "sync_glodap_bottles", must_not_run)
        t0 = asyncio.get_running_loop().time()
        assert await w.run_once(pool, head=lambda: {}, lock_wait_s=0.6, lock_poll_s=0.1) == "busy"
        waited = asyncio.get_running_loop().time() - t0
        assert 0.5 <= waited < 5            # it polled for the budget, not forever and not zero
        async with pool.acquire() as c:
            s = await c.fetchrow("SELECT last_failed_at, last_failure, last_decision, last_run_at, "
                                 "refresh_requested_at FROM glodap_bottle_source")
            assert s["last_decision"] == "busy" and s["last_run_at"] is not None     # "ran, found it busy"
            assert s["last_failed_at"] is None and s["last_failure"] is None         # no back-off
            assert s["refresh_requested_at"] is not None                             # still due
            assert await c.fetchval("SELECT count(*) FROM sync_log WHERE source='glodap-bottles'") == 0
            assert await c.fetchval("SELECT to_regclass('glodap_casts_new')") is None
            assert await w._decide(c, head=lambda: {}) == "requested"                # tomorrow's tick imports
    finally:
        await holder.close()
        await _cleanup(pool)


@needs_db
async def test_a_lock_freed_within_the_budget_lets_the_import_proceed(monkeypatch):
    pool = await _pool_with_request(monkeypatch)
    holder = await _holder(os.environ["TEST_DATABASE_URL"])
    try:
        called = {}

        async def fake_sync(**kw):
            called["yes"] = True
            return {"outcome": "swapped", "casts": 1, "reasons": []}
        monkeypatch.setattr(w, "sync_glodap_bottles", fake_sync)

        async def free_soon():
            await asyncio.sleep(0.4)
            await holder.execute("SELECT pg_advisory_unlock($1)", w.LOCK_KEY)
        freeing = asyncio.create_task(free_soon())
        assert await w.run_once(pool, head=lambda: {}, lock_wait_s=10, lock_poll_s=0.1) == "swapped"
        await freeing
        assert called
        async with pool.acquire() as c:                      # the lock was released again at the end
            assert await c.fetchval("SELECT pg_try_advisory_lock($1)", w.LOCK_KEY)
            await c.execute("SELECT pg_advisory_unlock($1)", w.LOCK_KEY)
            assert await c.fetchval("SELECT last_decision FROM glodap_bottle_source") == "swapped"
    finally:
        await holder.close()
        await _cleanup(pool)
