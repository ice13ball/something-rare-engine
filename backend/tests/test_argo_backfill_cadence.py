# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The full Argo history must walk itself, and must say which kind of nothing
it did.

Measured on production 2026-09-15: `argo_profiles` held 1999..2007 and 2026 and
NOTHING in between — eighteen years missing — while
`argo_backfill_state.done_through` sat at 2007-08-01, where a hand-run had left
it five days earlier. Every part of the walk worked. It simply had no caller:
advancing it meant POSTing /v1/admin/argo-backfill by hand about forty times.

Two separate guarantees live here, and each has its own failure:

1. **A cadence.** A resumable walk with nobody to resume it is a walk that does
   not happen, and this one writes no `sync_log` row, so the gap was invisible
   until somebody counted profiles per year.
2. **A finished walk must not look like a broken one.** Both return
   `months_done == 0`. Once the cadence runs every four hours, a completed
   history reporting `stalled: true` would be the permanent state of a healthy
   system — and an alarm that is always on is an alarm nobody reads.
"""
import logging
import os
from datetime import date, datetime, timedelta, timezone

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Cadence and wiring. No database: these are about whether anything calls the
# walk at all, which is a question about the module, not about its data.
# ─────────────────────────────────────────────────────────────────────────────

def test_the_long_walk_has_a_cadence():
    """⛔ The machinery existed for six days and moved twice.

    `sync_argo_profiles_backfill` is resumable, chunked, rate-limit-aware and
    lock-protected — and none of that mattered, because the only caller was a
    human with curl. This asserts something starts it on a schedule.

    2026-09-18: the task moved from `main.py` (43 literal
    `asyncio.create_task` call sites in `lifespan()`) into
    `scheduling.TASK_REGISTRY` (one generic loop, driven by data) as part of
    the web/worker process split. The guarantee this test cares about —
    something with a `while True` cadence, wired so it actually starts —
    now lives one level up: in the registry, not in `lifespan()`'s source.
    """
    import scheduling

    names = {t.name for t in scheduling.TASK_REGISTRY}
    assert "argo-history-backfill" in names, (
        "there is no periodic task for the full-history walk — closing the "
        "1997..today range depends on someone remembering to POST forty times")

    # Reachable under role "worker" (and therefore "all", the default) — not
    # just present in the registry with no role that ever starts it.
    worker_names = {t.name for t in scheduling.tasks_for_role("worker")}
    assert "argo-history-backfill" in worker_names, (
        "the task is registered but not wired to any role that actually "
        "starts it — present in TASK_REGISTRY is not the same as scheduled")

    # 2026-09-18: two further assertions lived here and read SOURCE TEXT —
    # "while True" in inspect.getsource(_argo_history_backfill_task) and
    # "sync_argo_profiles_backfill" in inspect.getsource(
    # _run_argo_history_backfill). Both were removed under Michal's rule that a
    # guard polices data, not code shape. The two assertions above survive
    # because they read the registry as DATA — objects, not text.
    # ⚠️ What went unguarded with them: that the task body loops rather than
    # running once, and that it drives the FULL-history walk rather than the
    # six-month top-up. Nothing in the suite says so now.


def test_a_pass_does_not_run_back_to_back_with_the_next_one():
    """The budget must fit inside the interval, with room to spare.

    ⚠️ `_run_unless_paused` holds `_sync_lock` for the whole call, so while the
    walk runs, every other sync in the service waits. The budget is also only
    checked at MONTH boundaries, so a pass overruns by up to one dense month.
    An interval shorter than the budget would mean the walk is essentially
    always holding the lock.
    """
    import scheduling

    assert scheduling.ARGO_HISTORY_BACKFILL_INTERVAL_SECONDS > scheduling.ARGO_HISTORY_BACKFILL_BUDGET_SECONDS * 2, (
        f"a {scheduling.ARGO_HISTORY_BACKFILL_BUDGET_SECONDS}s budget every "
        f"{scheduling.ARGO_HISTORY_BACKFILL_INTERVAL_SECONDS}s leaves no room for the "
        "month-boundary overrun, and this pass holds _sync_lock against every "
        "other sync while it runs")


def test_a_paused_backfill_can_be_started_again():
    """⛔ Pausing is always possible; un-pausing needs a registry entry.

    `_run_unless_paused("argo-backfill", …)` means an operator can stop this
    walk. Without a `_SYNC_SOURCES` entry there is no force-sync button to
    start it again, so a temporary pause becomes a permanent one.
    """
    import main

    assert "argo-backfill" in main._SYNC_SOURCES, (
        "the action the cadence pauses on has no entry in _SYNC_SOURCES — "
        "stopping the walk would be a one-way door")


# ─────────────────────────────────────────────────────────────────────────────
# The four kinds of "zero months". Executed, not grepped: the runner is called
# with each result shape and the log records are read back.
# ─────────────────────────────────────────────────────────────────────────────

def _runner_with(monkeypatch, result: dict):
    import main
    from domains import sensors

    async def _fake(**_kw):
        return result

    monkeypatch.setattr(sensors, "sync_argo_profiles_backfill", _fake)
    return main._run_argo_history_backfill


@pytest.mark.asyncio
async def test_a_finished_history_is_not_logged_as_a_problem(monkeypatch, caplog):
    run = _runner_with(monkeypatch, {
        "months_done": 0, "inserted": 0, "bounded": False,
        "done_through": "2026-09-15", "stalled": False, "complete": True,
        "failed_chunk": None,
    })
    with caplog.at_level(logging.INFO):
        await run()

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not warnings, (
        f"a completed history produced {len(warnings)} warning(s): "
        f"{[r.getMessage() for r in warnings]}. Running every four hours, that "
        "is a permanent alarm on a healthy system.")
    assert any("complete" in r.getMessage() for r in caplog.records), (
        "nothing in the log says the history finished — silence and success "
        "look identical to whoever reads it next")


@pytest.mark.asyncio
async def test_a_real_stall_is_logged_as_a_warning(monkeypatch, caplog):
    run = _runner_with(monkeypatch, {
        "months_done": 0, "inserted": 0, "bounded": False,
        "done_through": "2007-08-01", "stalled": True, "complete": False,
        "failed_chunk": "2007-08-01..2007-09-01: ReadTimeout",
    })
    with caplog.at_level(logging.INFO):
        await run()

    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, (
        "a walk stuck at 2007 with eighteen years still missing logged no "
        "warning at all — this is the exact silence that hid the gap")
    assert any("2007-08-01" in m for m in warnings), (
        f"the warning does not say where the walk is stuck: {warnings}")
    assert any("ReadTimeout" in m for m in warnings), (
        f"the warning does not say why — a stall with no reason is not "
        f"actionable: {warnings}")


@pytest.mark.asyncio
async def test_a_lock_refusal_is_not_an_alarm(monkeypatch, caplog):
    """A second walk declining to start is correct behaviour, not a failure."""
    run = _runner_with(monkeypatch, {
        "months_done": 0, "inserted": 0, "bounded": False,
        "done_through": "1997-01-01", "stalled": False, "complete": False,
        "skipped_reason": "another argo walk holds the lock", "failed_chunk": None,
    })
    with caplog.at_level(logging.INFO):
        await run()

    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert not warnings, (
        f"a healthy refusal was logged as a problem: {warnings}. The overlap "
        "guard fires every time the floor top-up runs long.")
    assert any("holds the lock" in r.getMessage() for r in caplog.records), (
        "the refusal left no trace at all, so a walk that never starts because "
        "something else always holds the lock would be invisible")


@pytest.mark.asyncio
async def test_a_vocabulary_outage_is_not_mistaken_for_progress(monkeypatch, caplog):
    """⛔ This branch shipped with no `stalled` key at all.

    `result.get("stalled")` returned None — falsy — so an upstream outage that
    attempted zero chunks read exactly like a healthy completed walk.
    """
    run = _runner_with(monkeypatch, {
        "months_done": 0, "inserted": 0, "bounded": False,
        "done_through": "2007-08-01", "error": "vocabulary_fetch_failed",
        "stalled": True, "complete": False,
    })
    with caplog.at_level(logging.INFO):
        await run()

    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "a vocabulary outage passed without a single warning"
    assert any("vocabulary_fetch_failed" in m for m in warnings), (
        f"the warning does not name the reason: {warnings}")


# ─────────────────────────────────────────────────────────────────────────────
# The walk's own verdict. Needs a database: the cursor lives in a table.
# ─────────────────────────────────────────────────────────────────────────────

_db_only = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)


@pytest.fixture
async def pool():
    import asyncpg
    import db as _db
    import schema

    _db.pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    # ⚠️ `ensure_ownership_grants` runs a bare `ALTER TABLE … OWNER TO
    # abyssal_user` with no try/except — unlike the argo sweep twenty lines
    # above it, which swallows exactly this error. On a database without the
    # production role, schema setup therefore dies partway through and every
    # test in the file errors with `role "abyssal_user" does not exist`, which
    # looks nothing like the missing role it is. The role owns nothing here; it
    # only has to exist.
    async with _db.pool.acquire() as c:
        await c.execute("""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'abyssal_user')
                THEN CREATE ROLE abyssal_user;
                END IF;
            END $$;
        """)
    await schema.ensure_schema()
    yield _db.pool
    await _db.pool.close()


async def _set_cursor(pool, value: date):
    async with pool.acquire() as c:
        await c.execute(
            """INSERT INTO argo_backfill_state (id, done_through, updated_at)
               VALUES (1, $1, NOW())
               ON CONFLICT (id) DO UPDATE SET done_through = $1, updated_at = NOW()""",
            value,
        )


def _no_vocab_fetch(monkeypatch):
    from domains import sensors

    async def _vocab(_c):
        return ["temperature", "salinity"]

    monkeypatch.setattr(sensors, "_fetch_argo_param_vocabulary", _vocab)
    monkeypatch.setattr(sensors, "_ARGO_BACKFILL_CHUNK_PACING_SECONDS", 0)


@_db_only
@pytest.mark.asyncio
async def test_a_history_that_reached_today_reports_complete_not_stalled(pool, monkeypatch):
    from domains import sensors

    _no_vocab_fetch(monkeypatch)
    tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
    await _set_cursor(pool, tomorrow)

    result = await sensors.sync_argo_profiles_backfill(budget_seconds=10)

    assert result["months_done"] == 0, "a cursor past today should walk nothing"
    assert result["complete"] is True, (
        "a walk whose cursor has passed today does not say it is finished, so "
        "nothing can tell it apart from one that failed to start")
    assert result["stalled"] is False, (
        "a finished history reports stalled=True — run four-hourly, that is a "
        "warning on every single healthy pass, forever")


@_db_only
@pytest.mark.asyncio
async def test_a_walk_stuck_in_2007_still_reports_stalled(pool, monkeypatch):
    """The other half. Making `complete` true must not switch the alarm off."""
    from domains import sensors

    _no_vocab_fetch(monkeypatch)
    await _set_cursor(pool, date(2007, 8, 1))

    async def _boom(*_a, **_kw):
        raise RuntimeError("upstream said no")

    monkeypatch.setattr(sensors, "_fetch_argo_day", _boom)

    result = await sensors.sync_argo_profiles_backfill(budget_seconds=10)

    assert result["months_done"] == 0
    assert result["complete"] is False, (
        "a cursor in 2007 claims the history is complete — eighteen missing "
        "years would be declared done")
    assert result["stalled"] is True, (
        "a walk that tried and got nowhere reports itself healthy")
    assert result["failed_chunk"], "a stall with no named chunk is not actionable"

    async with pool.acquire() as conn:
        cursor = await conn.fetchval("SELECT done_through FROM argo_backfill_state WHERE id = 1")
    assert cursor == date(2007, 8, 1), (
        f"the cursor moved to {cursor} after a FAILED chunk — the failed month "
        "would be skipped and never revisited")


@_db_only
@pytest.mark.asyncio
async def test_a_vocabulary_outage_carries_the_stalled_flag(pool, monkeypatch):
    """The early return that shipped without one."""
    import httpx
    from domains import sensors

    await _set_cursor(pool, date(2007, 8, 1))

    async def _vocab_down(_c):
        raise httpx.ConnectError("argovis unreachable")

    monkeypatch.setattr(sensors, "_fetch_argo_param_vocabulary", _vocab_down)

    result = await sensors.sync_argo_profiles_backfill(budget_seconds=10)

    assert result.get("stalled") is True, (
        "the vocabulary-failure branch returns no `stalled` key, so "
        "result.get('stalled') is None — falsy — and an upstream outage that "
        "attempted zero chunks reads as a healthy completed walk")
    assert result.get("complete") is False, (
        "an outage that fetched nothing claims the history is complete")
