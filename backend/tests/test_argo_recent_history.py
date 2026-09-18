# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Our own database must hold the last six months densely.

The periodic sync refreshes only `_ARGO_RECENT_WINDOW_DAYS` (30). Anything that
falls out of that window is never revisited, so a period the sync missed — or
covered while the ingest was still narrow — stays sparse forever. Measured on
production 2026-09-09: March..July 2026 held ~400 profiles per month against
August's 10,717, roughly 4% coverage, left over from the pre-widening ingest.

The rolling top-up re-walks the last ARGO_HISTORY_FLOOR_DAYS in month chunks.

⛔ The guarantee that matters here is that it does NOT touch
argo_backfill_state. That row is the full-history walk's only bookmark; moving
it from 2007 to 2026 to repair a recent gap would silently declare 2008..2025
already done, and nothing would ever notice the missing eighteen years.
"""
import os
from datetime import date, datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)

_CURSOR_BEFORE = date(2007, 10, 1)


@pytest.fixture
async def pool():
    import asyncpg
    import db as _db
    import schema

    _db.pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    await schema.ensure_schema()
    async with _db.pool.acquire() as c:
        await c.execute("DELETE FROM argo_profiles WHERE platform_id = '9999002'")
        await c.execute(
            """INSERT INTO argo_backfill_state (id, done_through, updated_at)
               VALUES (1, $1, NOW())
               ON CONFLICT (id) DO UPDATE SET done_through = $1""", _CURSOR_BEFORE)
        await c.execute("DELETE FROM argo_topup_state")
    yield _db.pool
    async with _db.pool.acquire() as c:
        await c.execute("DELETE FROM argo_profiles WHERE platform_id = '9999002'")
    await _db.pool.close()


def _fake_window(seen: list):
    async def _f(_client, start_dt, end_dt, _params):
        seen.append((start_dt.date(), end_dt.date()))
        return [{
            "_id": f"9999002_{len(seen):03d}",
            "timestamp": start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "geolocation": {"type": "Point", "coordinates": [-30.0, 40.0]},
            "geolocation_argoqc": 1,
            "data": [[10.0, 1500.0], [5.0, 2.0], [34.5, 34.6]],
            "data_info": [["pressure", "temperature", "salinity"], [], []],
        }]
    return _f


@pytest.mark.asyncio
async def test_top_up_never_moves_the_full_history_cursor(pool, monkeypatch):
    from domains import sensors

    seen: list = []
    monkeypatch.setattr(sensors, "_fetch_argo_window", _fake_window(seen))
    async def _vocab(_c): return ["temperature", "salinity"]
    monkeypatch.setattr(sensors, "_fetch_argo_param_vocabulary", _vocab)
    monkeypatch.setattr(sensors, "_ARGO_BACKFILL_CHUNK_PACING_SECONDS", 0)

    result = await sensors.sync_argo_recent_history(budget_seconds=60)

    async with pool.acquire() as conn:
        cursor = await conn.fetchval("SELECT done_through FROM argo_backfill_state WHERE id = 1")

    assert cursor == _CURSOR_BEFORE, (
        f"the full-history cursor moved to {cursor}. It is the only bookmark "
        "for the 1999..today walk — jumping it forward to repair a recent gap "
        "declares every year in between already done, silently and forever.")
    assert result["bounded"] is True
    assert result["months_done"] >= 1, "the top-up walked no months at all"


@pytest.mark.asyncio
async def test_top_up_covers_the_whole_six_month_floor(pool, monkeypatch):
    from domains import sensors

    seen: list = []
    monkeypatch.setattr(sensors, "_fetch_argo_window", _fake_window(seen))
    async def _vocab(_c): return ["temperature", "salinity"]
    monkeypatch.setattr(sensors, "_fetch_argo_param_vocabulary", _vocab)
    monkeypatch.setattr(sensors, "_ARGO_BACKFILL_CHUNK_PACING_SECONDS", 0)

    await sensors.sync_argo_recent_history(budget_seconds=120)

    today = datetime.now(timezone.utc).date()
    floor = today - timedelta(days=sensors.ARGO_HISTORY_FLOOR_DAYS)
    assert seen, "no window was requested at all"
    assert seen[0][0] == floor, (
        f"the walk started at {seen[0][0]}, not at the {sensors.ARGO_HISTORY_FLOOR_DAYS}-day "
        f"floor {floor} — the oldest part of the guaranteed window is the part "
        "most likely to be sparse, so starting late defeats the whole pass")
    assert seen[-1][1] >= today, (
        f"the walk stopped at {seen[-1][1]}, short of today — a gap is left "
        "immediately before the live sync's 30-day window")
    # month chunks, contiguous, no hole between them
    for a, b in zip(seen, seen[1:]):
        assert a[1] == b[0], f"a gap between chunks: {a} then {b}"


@pytest.mark.asyncio
async def test_the_unbounded_backfill_still_advances_its_cursor(pool, monkeypatch):
    """The other half: the long walk must keep its bookmark working."""
    from domains import sensors

    seen: list = []
    monkeypatch.setattr(sensors, "_fetch_argo_window", _fake_window(seen))
    async def _vocab(_c): return ["temperature", "salinity"]
    monkeypatch.setattr(sensors, "_fetch_argo_param_vocabulary", _vocab)
    monkeypatch.setattr(sensors, "_ARGO_BACKFILL_CHUNK_PACING_SECONDS", 0)

    await sensors.sync_argo_profiles_backfill(budget_seconds=5)

    async with pool.acquire() as conn:
        cursor = await conn.fetchval("SELECT done_through FROM argo_backfill_state WHERE id = 1")

    assert cursor > _CURSOR_BEFORE, (
        f"the full-history cursor stayed at {cursor} — the bounded mode's "
        "cursor guard is suppressing the unbounded walk's progress too, so the "
        "backfill would restart from the same month forever")


def test_the_floor_is_six_months():
    """⛔ Pins the REQUIREMENT, not the code that implements it.

    The two tests above compute the expected window from
    ARGO_HISTORY_FLOOR_DAYS, so they follow the constant wherever it goes —
    shrinking it from 180 to 30 left all three green. That is a tautology, not
    a guard.

    Six months in our own database is Michal's decision (2026-09-09), taken
    because the periodic sync's 30-day window cannot self-heal a gap. Anyone
    lowering this is changing a product commitment, and should have to edit a
    test that says so out loud.
    """
    from domains import sensors

    assert sensors.ARGO_HISTORY_FLOOR_DAYS >= 180, (
        f"the guaranteed history floor is {sensors.ARGO_HISTORY_FLOOR_DAYS} days, "
        "below the six months agreed on 2026-09-09. Anything the periodic sync's "
        "30-day window drops is never revisited, so shortening this floor silently "
        "reintroduces the March..July 2026 hole (~4% coverage) it exists to prevent."
    )


@pytest.mark.asyncio
async def test_two_walks_cannot_run_at_once(pool, monkeypatch):
    """⛔ Two Argo history walks deadlock on argo_profiles.

    2026-09-09, production: the recent-history top-up was started while a full
    backfill request was still executing inside the API. Killing the shell
    driver that issued it does NOT cancel work already in flight, so both
    walked months and upserted into the same table:

        failed_chunk: "2026-03-13..2026-04-01: DeadlockDetectedError"

    The second walk must decline, and must say it declined — reporting it as a
    stall would make a healthy refusal look like the silent-stall bug this
    endpoint already shipped once.
    """
    import asyncio

    from domains import sensors

    started = asyncio.Event()
    release = asyncio.Event()

    async def _slow_window(_client, start_dt, end_dt, _params):
        started.set()
        await release.wait()
        return []

    async def _vocab(_c): return ["temperature"]
    monkeypatch.setattr(sensors, "_fetch_argo_window", _slow_window)
    monkeypatch.setattr(sensors, "_fetch_argo_param_vocabulary", _vocab)
    monkeypatch.setattr(sensors, "_ARGO_BACKFILL_CHUNK_PACING_SECONDS", 0)

    first = asyncio.create_task(sensors.sync_argo_recent_history(budget_seconds=60))
    await asyncio.wait_for(started.wait(), timeout=10)

    try:
        # ⛔ A timeout, not a bare await. Without the lock the second walk does
        # not fail — it STARTS, blocks on the same gate as the first, and the
        # test hangs instead of going red. A guard whose sabotage hangs is a
        # guard nobody will run twice.
        second = await asyncio.wait_for(
            sensors.sync_argo_profiles_backfill(budget_seconds=60), timeout=15)
    except asyncio.TimeoutError:
        release.set()
        await first
        pytest.fail(
            "the second walk started instead of declining — it blocked behind "
            "the first rather than returning. That is the configuration that "
            "deadlocked on argo_profiles in production.")

    release.set()
    await first

    assert second["months_done"] == 0, (
        "a second walk started while the first held the lock — that is the "
        "deadlock configuration")
    assert second.get("skipped_reason"), (
        f"the refusal carried no reason: {second}. An operator cannot tell it "
        "apart from a run that tried and got nowhere.")
    assert second["stalled"] is False, (
        "a healthy refusal was reported as a stall, which is the alarm shape "
        "reserved for a run that silently achieved nothing")


def test_the_map_window_stays_within_the_proxy_cap():
    """⛔ The window we SEND is not the window we KEEP, and only one of them
    can be raised safely.

    Measured 2026-09-09 against live responses: 14,870 points over 90 days
    weigh 13.98 MB from this backend, which does not compress; the BFF gzips
    them to 1.80 MB for the browser. Six months at full coverage is roughly
    75,000 points, about 67 MB uncompressed.

    ⛔ Whether Cloud Run's 32 MiB cap applies before or after that gzip was NOT
    verified. The uncompressed figure is the one to treat as at risk.

    Michal ruled on 2026-09-09 that the map stays at 90 days. Raising this to
    match ARGO_HISTORY_FLOOR_DAYS reads like a one-line config tweak, which is
    exactly why it needs a test that says otherwise out loud.
    """
    from domains import sensors

    assert sensors._ARGO_CACHE_WINDOW_DAYS <= 90, (
        f"the map window is {sensors._ARGO_CACHE_WINDOW_DAYS} days, above the 90 "
        "ruled on 2026-09-09. At ~940 uncompressed bytes per trail point, six "
        "months at full coverage is ~67 MB against a 32 MiB Cloud Run cap. "
        "Serving that needs the trail payload trimmed to position/date/id first "
        "(2.87 MB at 90 days) — an option considered and declined, not something "
        "to enable by raising this number."
    )
    assert sensors.ARGO_HISTORY_FLOOR_DAYS > sensors._ARGO_CACHE_WINDOW_DAYS, (
        "we are serving at least as much as we keep, which means the map is the "
        "only copy of that history and nothing is being retained beyond it"
    )


@pytest.mark.asyncio
async def test_cancelling_a_walk_releases_the_lock(pool, monkeypatch):
    """⛔ The failure that actually happened, 2026-09-09.

    The lock was taken on a POOLED connection and released with
    `await pg_advisory_unlock(...)` in a finally. When the driving curl was
    killed, uvicorn cancelled the request task; the finally ran, and its very
    first await was cancelled too, so the unlock never executed. The connection
    went back to the pool still holding the lock. pg_stat_activity showed it
    idle for 20 minutes with `SELECT pg_try_advisory_lock($1)` as its last
    query, and every later walk was refused by a lock nobody was using.

    Cleanup that awaits inside a cancelled task does not run. The fix is a
    dedicated connection and terminate(), which is synchronous.
    """
    import asyncio

    from domains import sensors

    started = asyncio.Event()

    async def _hangs(_client, _s, _e, _p):
        started.set()
        await asyncio.sleep(3600)

    async def _vocab(_c): return ["temperature"]
    monkeypatch.setattr(sensors, "_fetch_argo_window", _hangs)
    monkeypatch.setattr(sensors, "_fetch_argo_param_vocabulary", _vocab)
    monkeypatch.setattr(sensors, "_ARGO_BACKFILL_CHUNK_PACING_SECONDS", 0)

    task = asyncio.create_task(sensors.sync_argo_recent_history(budget_seconds=600))
    await asyncio.wait_for(started.wait(), timeout=10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # A fresh walk must be able to take the lock straight away.
    monkeypatch.setattr(sensors, "_fetch_argo_window", _fake_window([]))
    result = await asyncio.wait_for(
        sensors.sync_argo_recent_history(budget_seconds=30), timeout=60)

    assert not result.get("skipped_reason"), (
        f"the lock survived the cancellation: {result.get('skipped_reason')!r}. "
        "Nothing holds it and nothing will ever release it — every future walk "
        "is refused until the process restarts.")
    assert result["months_done"] >= 1


def test_the_lock_release_path_does_not_await():
    """⛔ A shape test, deliberately, and here is why.

    Production 2026-09-09: the lock was taken on a pooled connection and
    released with `await pg_advisory_unlock(...)` in a finally. Killing the
    driving curl made uvicorn cancel the request task; the unlock never ran.
    pg_stat_activity showed the connection idle for 20:55 with
    `SELECT pg_try_advisory_lock($1)` as its last query, and six consecutive
    top-up runs were refused by a lock nobody was using. It cleared only on
    the next service restart.

    ⚠️ The behavioural test above (test_cancelling_a_walk_releases_the_lock)
    does NOT catch this: a plain task.cancel() still lets one await complete
    inside the finally, so restoring the old pattern leaves it green. That was
    verified by sabotage, not assumed. Rather than ship a guard that cannot
    fail, this asserts the property that actually holds the invariant —
    cleanup that cannot be interrupted contains no await.
    """
    import inspect

    from domains import sensors

    src = inspect.getsource(sensors.sync_argo_profiles_backfill)
    finally_block = src[src.rindex("finally:"):]
    assert "await" not in finally_block, (
        "the lock release awaits. Cleanup that awaits does not run when the "
        f"task is cancelled, which is how the lock went stale:\n{finally_block}")
    assert "terminate()" in finally_block, (
        "the connection is not terminated. Dropping the socket is what makes "
        "Postgres release the advisory lock without needing a query to run.")
    assert "db.pool.acquire" not in src, (
        "the lock is held on a POOLED connection. A connection that keeps the "
        "lock is then handed to unrelated work, and the pool keeps it alive "
        "long past the walk that took it.")


@pytest.mark.asyncio
async def test_the_top_up_resumes_instead_of_restarting_at_the_floor(pool, monkeypatch):
    """⛔ Measured 2026-09-09: six consecutive runs, May stuck at 466 profiles.

    Each invocation started at the 180-day floor and spent its whole budget
    re-fetching March and April, which were already dense. The newest months in
    the guaranteed window were never reached — the pass could not converge, and
    nothing reported a problem because every run looked busy and successful.
    """
    from domains import sensors

    import asyncio

    seen: list = []
    inner = _fake_window(seen)

    async def _slow(client, start_dt, end_dt, params):
        # Slow enough that a 1-second budget stops the walk part-way through
        # the six-month window — the real case this test is about.
        await asyncio.sleep(0.4)
        return await inner(client, start_dt, end_dt, params)

    monkeypatch.setattr(sensors, "_fetch_argo_window", _slow)
    async def _vocab(_c): return ["temperature", "salinity"]
    monkeypatch.setattr(sensors, "_fetch_argo_param_vocabulary", _vocab)
    monkeypatch.setattr(sensors, "_ARGO_BACKFILL_CHUNK_PACING_SECONDS", 0)

    first = await sensors.sync_argo_recent_history(budget_seconds=1)
    reached = first["done_through"]
    today = datetime.now(timezone.utc).date().isoformat()
    assert reached < today, (
        f"the first run finished the whole window ({reached}); this test needs "
        "a partial pass to have anything to resume from")

    async with pool.acquire() as conn:
        stored = await conn.fetchval("SELECT done_through FROM argo_topup_state WHERE id = 1")
    assert stored is not None, "the top-up recorded no cursor of its own"
    assert stored.isoformat() == reached, (
        f"stored cursor {stored} does not match where the run reached ({reached})")

    seen.clear()
    second = await sensors.sync_argo_recent_history(budget_seconds=1)

    assert second["since"] == reached, (
        f"the second run restarted at {second['since']} instead of resuming at "
        f"{reached} — it will re-fetch the same settled months forever and never "
        "reach the newest part of the window")
    assert seen and seen[0][0].isoformat() == reached, (
        f"the first window requested was {seen[0][0]}, not the resume point")


@pytest.mark.asyncio
async def test_the_top_up_cursor_is_not_the_backfill_cursor(pool, monkeypatch):
    """Two bookmarks, two tables — the top-up must not be able to touch the
    full-history one even now that it writes a cursor of its own."""
    from domains import sensors

    monkeypatch.setattr(sensors, "_fetch_argo_window", _fake_window([]))
    async def _vocab(_c): return ["temperature"]
    monkeypatch.setattr(sensors, "_fetch_argo_param_vocabulary", _vocab)
    monkeypatch.setattr(sensors, "_ARGO_BACKFILL_CHUNK_PACING_SECONDS", 0)

    await sensors.sync_argo_recent_history(budget_seconds=30)

    async with pool.acquire() as conn:
        long_walk = await conn.fetchval("SELECT done_through FROM argo_backfill_state WHERE id = 1")
        top_up    = await conn.fetchval("SELECT done_through FROM argo_topup_state WHERE id = 1")

    assert long_walk == _CURSOR_BEFORE, (
        f"the full-history cursor moved to {long_walk} — the top-up is writing "
        "the wrong bookmark and has just declared 2008..2025 done")
    assert top_up is not None and top_up > _CURSOR_BEFORE


@pytest.mark.asyncio
async def test_a_dropped_connection_is_retried_not_fatal(pool, monkeypatch):
    """⛔ One transient network event must not end a six-month fill.

    Production 2026-09-09: the top-up filled May (15,053 rows) and then died on

        failed_chunk: "2026-06-01..2026-07-01: RemoteProtocolError"

    Argovis closed the connection mid-response on a single month. Only HTTP 429
    was retried, so June and July stayed at ~400 profiles each — about 4% of a
    month — and the pass stopped with the guaranteed window still unfilled.
    """
    import httpx

    from domains import sensors

    calls = {"n": 0}
    seen: list = []
    inner = _fake_window(seen)

    async def _flaky(client, start_dt, end_dt, params):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.RemoteProtocolError("server disconnected without sending a response")
        return await inner(client, start_dt, end_dt, params)

    async def _vocab(_c): return ["temperature", "salinity"]
    monkeypatch.setattr(sensors, "_fetch_argo_window", _flaky)
    monkeypatch.setattr(sensors, "_fetch_argo_param_vocabulary", _vocab)
    monkeypatch.setattr(sensors, "_ARGO_BACKFILL_CHUNK_PACING_SECONDS", 0)
    monkeypatch.setattr(sensors, "_ARGO_429_BASE_WAIT_SECONDS", 0.01)

    result = await sensors.sync_argo_recent_history(budget_seconds=30)

    assert result["failed_chunk"] is None, (
        f"a dropped connection ended the walk: {result['failed_chunk']}. It has "
        "to be retried like a 429 — the request never got an answer, so there "
        "is nothing to respect and everything to retry.")
    assert result["months_done"] >= 1, "the walk gave up after the retry"
    assert calls["n"] >= 2, "the failing request was never retried at all"


@pytest.mark.skip(
    reason="Source-shape guard, disabled 2026-09-18 by Michal's call. Every "
           "assertion below reads SOURCE TEXT, not behaviour: hasattr on a "
           "module, a substring search in inspect.getsource(lifespan), a "
           "substring search for 'while True'. The middle one became "
           "unsatisfiable by construction when the web/worker split replaced "
           "43 hand-written create_task calls with one loop over TASK_REGISTRY "
           "— lifespan no longer NAMES any task, so no task name can appear in "
           "its source. A guard that a behaviour-preserving refactor turns red "
           "is measuring where the code lives. What it was protecting is now "
           "checked directly against production instead (see "
           "docs/ops/2026-09-18-web-worker-split.md): that argo_profiles "
           "coverage actually spans ARGO_HISTORY_FLOOR_DAYS, which is the "
           "outcome, not the wiring. ⚠️ The cadence itself is therefore "
           "UNGUARDED in the suite — if the floor task is ever dropped from "
           "TASK_REGISTRY, nothing here will say so."
)
def test_the_floor_has_a_cadence():
    """⛔ A constant is not a guarantee until something runs on a schedule.

    ARGO_HISTORY_FLOOR_DAYS and sync_argo_recent_history were both added on
    2026-09-09, and the window was filled that day — by hand, from a shell
    driver. Nothing would have kept it filled: sync_argo_profiles only ever
    refreshes the last 30 days, which is precisely how March..July 2026 reached
    ~4% coverage in the first place.

    This asserts the task exists and is started, because "we filled it once" and
    "we keep six months" look identical in the database on the day you fill it.
    """
    import inspect

    import main

    assert hasattr(main, "_argo_history_floor_task"), (
        "there is no periodic task for the history floor — the six-month "
        "guarantee depends on someone remembering to trigger it")

    lifespan = inspect.getsource(main.lifespan)
    assert "_argo_history_floor_task" in lifespan, (
        "the history-floor task is defined but never started, so the floor is "
        "maintained by nothing at all")

    body = inspect.getsource(main._argo_history_floor_task)
    assert "sync_argo_recent_history" in body
    assert "while True" in body, "the task runs once and exits — that is not a cadence"
