# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""plankton_obis_worker.run_once: freshness, failure back-off, low memory, blocking lock wait.

Real pool, not the rolled-back connection: advisory locks are per-session. Each test
cleans its own sync_log row, and `worker_pool` restores db.pool (run_once rebinds it).
"""
import asyncio
import os

import asyncpg
import pytest

import db
import plankton_obis_worker as w
from plankton_helpers import needs_db

SRC = "plankton-obis"
ENOUGH = 10 * 1024 * 1024


@pytest.fixture
async def worker_pool(monkeypatch):
    previous = db.pool
    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"], min_size=1, max_size=3)
    ran = []

    async def fake_sync(**_):
        ran.append(1)
        return {"outcome": "swapped"}

    monkeypatch.setattr(w, "sync_plankton_obis", fake_sync)
    monkeypatch.setattr(w, "_mem_available_kib", lambda: ENOUGH)
    async with pool.acquire() as c:
        await c.execute("DELETE FROM sync_log WHERE source = $1", SRC)
    try:
        yield pool, ran
    finally:
        async with pool.acquire() as c:
            await c.execute("DELETE FROM sync_log WHERE source = $1", SRC)
        await pool.close()
        db.pool = previous


async def _row(pool, success_days=None, fail_days=None, reason="error: boom"):
    async with pool.acquire() as c:
        await c.execute(
            """INSERT INTO sync_log (source, last_synced_at, records_added, total_records,
                                     skipped_reason, skipped_at)
               VALUES ($1,
                       CASE WHEN $2::int IS NULL THEN NULL ELSE now() - make_interval(days => $2::int) END,
                       1, 1,
                       CASE WHEN $3::int IS NULL THEN NULL ELSE $4 END,
                       CASE WHEN $3::int IS NULL THEN NULL ELSE now() - make_interval(days => $3::int) END)""",
            SRC, success_days, fail_days, reason)


async def _skip(pool):
    async with pool.acquire() as c:
        return await c.fetchrow("SELECT skipped_reason, skipped_at FROM sync_log WHERE source = $1", SRC)


@needs_db
async def test_fresh_success_does_nothing_and_logs_nothing(worker_pool):
    pool, ran = worker_pool
    await _row(pool, success_days=2)
    assert await w.run_once(pool) == "fresh"
    assert not ran and (await _skip(pool))["skipped_reason"] is None


@needs_db
async def test_failure_two_days_ago_backs_off_and_keeps_the_failure_reason(worker_pool):
    pool, ran = worker_pool
    await _row(pool, success_days=40, fail_days=2, reason="swap blocked — rows dropped")
    assert await w.run_once(pool) == "backoff"
    assert not ran
    assert (await _skip(pool))["skipped_reason"] == "swap blocked — rows dropped"


@needs_db
async def test_first_ever_failure_backs_off(worker_pool):
    pool, ran = worker_pool
    await _row(pool, fail_days=1)
    assert await w.run_once(pool) == "backoff" and not ran


@needs_db
async def test_failure_eight_days_ago_runs_again(worker_pool):
    pool, ran = worker_pool
    await _row(pool, success_days=40, fail_days=8)
    assert await w.run_once(pool) == "ran" and ran


@needs_db
async def test_never_ran_runs(worker_pool):
    pool, ran = worker_pool
    assert await w.run_once(pool) == "ran" and ran


@needs_db
async def test_stale_success_runs(worker_pool):
    pool, ran = worker_pool
    await _row(pool, success_days=31)
    assert await w.run_once(pool) == "ran" and ran


@needs_db
async def test_low_memory_logs_a_skip_with_the_reason_and_does_not_start_a_backoff(worker_pool, monkeypatch):
    pool, ran = worker_pool
    monkeypatch.setattr(w, "_mem_available_kib", lambda: 1024)
    assert await w.run_once(pool) == "low-memory"
    assert not ran
    row = await _skip(pool)
    assert row["skipped_reason"] and "MemAvailable" in row["skipped_reason"]
    assert str(w.MIN_AVAIL_KIB) in row["skipped_reason"]
    # memory recovers: the very next tick must run, not wait 7 days
    monkeypatch.setattr(w, "_mem_available_kib", lambda: ENOUGH)
    assert await w.run_once(pool) == "ran"


@needs_db
async def test_worker_waits_for_lock_4242001_then_runs_after_release(worker_pool):
    pool, ran = worker_pool
    holder = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
    try:
        await holder.execute("SELECT pg_advisory_lock(4242001)")
        task = asyncio.create_task(w.run_once(pool))
        await asyncio.sleep(1.0)
        assert not task.done() and not ran, "worker must block while the lock is held"
        await holder.execute("SELECT pg_advisory_unlock(4242001)")
        assert await asyncio.wait_for(task, 10) == "ran"
        assert ran
        # and the lock was released again by the worker
        assert await holder.fetchval("SELECT pg_try_advisory_lock(4242001)")
        await holder.execute("SELECT pg_advisory_unlock(4242001)")
    finally:
        await holder.close()


@needs_db
async def test_worker_that_waited_for_the_lock_re_decides_and_skips_a_fresh_success(worker_pool):
    """M5: decided "due", blocked behind another import, and that import succeeded meanwhile:
    this run must see "fresh" after the lock and NOT import a second time."""
    pool, ran = worker_pool
    await _row(pool, success_days=40)                     # due when run_once first looks
    holder = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
    try:
        await holder.execute("SELECT pg_advisory_lock(4242001)")
        task = asyncio.create_task(w.run_once(pool))
        await asyncio.sleep(1.0)
        assert not task.done() and not ran
        await holder.execute("UPDATE sync_log SET last_synced_at = now() WHERE source = $1", SRC)   # the other import finished
        await holder.execute("SELECT pg_advisory_unlock(4242001)")
        assert await asyncio.wait_for(task, 10) == "fresh"
        assert not ran, "a second full import ran right after the first"
    finally:
        await holder.close()


async def test_low_memory_without_pool_only_when_decision_precedes(monkeypatch):
    """_mem_available_kib returning None (no /proc) must not block the run."""
    monkeypatch.setattr(w, "_mem_available_kib", lambda: None)
    assert w._memory_ok() is True
    monkeypatch.setattr(w, "_mem_available_kib", lambda: w.MIN_AVAIL_KIB - 1)
    assert w._memory_ok() is False


async def _marker(pool, hours, success_days=None):
    async with pool.acquire() as c:
        await c.execute(
            """INSERT INTO sync_log (source, last_synced_at, records_added, total_records, skipped_reason, skipped_at)
               VALUES ($1, CASE WHEN $2::int IS NULL THEN NULL ELSE now() - make_interval(days => $2::int) END,
                       1, 1, $3, now() - make_interval(hours => $4::int))""",
            SRC, success_days, w.STARTED_PREFIX + ": import in progress", hours)


@needs_db
async def test_partial_swap_marker_is_a_success_not_a_failure_to_back_off_from(worker_pool):
    pool, ran = worker_pool
    await _row(pool, success_days=40, fail_days=2, reason="swapped with failed datasets: failed_datasets=1")
    assert await w.run_once(pool) == "ran" and ran      # stale success, and the marker is no back-off


@needs_db
async def test_stale_started_marker_means_a_killed_run_and_backs_off(worker_pool):
    pool, ran = worker_pool
    await _marker(pool, hours=9, success_days=40)         # older than TimeoutStartSec (8 h)
    assert await w.run_once(pool) == "backoff" and not ran


@needs_db
async def test_fresh_started_marker_means_a_run_is_in_progress_so_no_second_import(worker_pool):
    pool, ran = worker_pool
    await _marker(pool, hours=2, success_days=40)
    assert await w.run_once(pool) == "running" and not ran
    assert (await _skip(pool))["skipped_reason"].startswith(w.STARTED_PREFIX)    # a decision writes nothing


@needs_db
async def test_started_marker_older_than_the_backoff_window_runs_again(worker_pool):
    pool, ran = worker_pool
    await _marker(pool, hours=24 * 8, success_days=40)
    assert await w.run_once(pool) == "ran" and ran
