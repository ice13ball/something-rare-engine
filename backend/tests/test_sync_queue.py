# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""A force-sync must reach the worker, and a force-sync nobody picks up must be LOUD.

## The incident these guards are shaped around

2026-09-17, the Mac staleness monitor: `POST /admin/sync/sio-bic` answered
`{"status":"started"}`, the job never appeared in `/admin/sync/running` across
ten minutes of polling, and the data never moved. The operator could not tell
"queued behind something" from "lost". The 2026-09-18 web/worker split adds
three fresh ways to produce exactly that:

  * no worker process is running at all;
  * the worker is alive but wedged on a long sync holding `_sync_lock`;
  * ⚠️ the NOTIFY was issued while no listener happened to be connected —
    `NOTIFY` is fire-and-forget, so a listener that attaches a moment later
    never learns it happened.

Every test below binds one clause of the answer to that. Each was verified by
sabotage: the counts are in the commit message.
"""
from __future__ import annotations

import asyncio
import os

import asyncpg
import pytest

import db
import scheduling
import sync_queue

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)

_SOURCE = "TEST-SYNC-QUEUE"
_OTHER = "TEST-SYNC-QUEUE-other"


@pytest.fixture
async def pool():
    """A REAL pool on a REAL connection, not a transaction-scoped fake.

    The listener opens its own connection with `asyncpg.connect(db.dsn)` — it
    has to, because `add_listener` needs a connection held for the process
    lifetime and the pool only has four. A connection outside our transaction
    cannot see uncommitted rows, so a rollback-scoped fixture would make every
    listener test pass vacuously (nothing to claim, so nothing to get wrong).
    We therefore commit, and clean up by name afterwards.
    """
    url = os.environ["TEST_DATABASE_URL"]
    p = await asyncpg.create_pool(url, min_size=1, max_size=4)
    previous_pool, previous_dsn = db.pool, db.dsn
    db.pool, db.dsn = p, url
    await _cleanup(p)
    try:
        yield p
    finally:
        await _cleanup(p)
        db.pool, db.dsn = previous_pool, previous_dsn
        await p.close()


async def _cleanup(p) -> None:
    async with p.acquire() as conn:
        await conn.execute("DELETE FROM sync_requests WHERE source LIKE 'TEST-SYNC-QUEUE%'")
        await conn.execute("DELETE FROM running_syncs WHERE source LIKE 'TEST-SYNC-QUEUE%'")


async def _requests(p, source=_SOURCE):
    async with p.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM sync_requests WHERE source = $1 ORDER BY id", source)


# ── 1. The POST does not run anything ────────────────────────────────────────

async def test_the_post_queues_the_sync_and_does_not_run_it(pool):
    """Binds `await sync_queue.enqueue(source)` in `admin_sync_source`.

    ⛔ Restoring `asyncio.create_task(_run_tracked(source, fn()))` runs a
    multi-gigabyte bake inside the process that serves tiles — the single
    thing the web/worker split exists to prevent. The assertion that catches
    it is `not ran`: the old line executes the lambda synchronously to build
    its coroutine, so `ran` flips before the response is even returned.
    """
    from httpx import ASGITransport, AsyncClient

    import main

    ran: list[str] = []

    async def _fake_sync():
        ran.append(_SOURCE)

    main._SYNC_SOURCES[_SOURCE] = _fake_sync
    main.app.dependency_overrides[main._require_admin_token] = lambda: None
    try:
        async with AsyncClient(transport=ASGITransport(app=main.app),
                               base_url="http://t") as client:
            resp = await client.post(f"/admin/sync/{_SOURCE}")
    finally:
        main.app.dependency_overrides.clear()
        main._SYNC_SOURCES.pop(_SOURCE, None)

    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert not ran, (
        "the web process RAN the sync. After the split this is the starvation "
        "the split exists to remove: the force-sync must be handed to the "
        "worker, not executed here.")
    assert body["status"] == "queued", (
        f"answered {body['status']!r}. On 2026-09-17 this endpoint said "
        "'started' for a job that never ran, and the operator had no way to "
        "tell queued from lost. A process that started nothing must not say "
        "it started something.")

    rows = await _requests(pool)
    assert len(rows) == 1, "no durable row — a lost NOTIFY would erase the request"
    assert rows[0]["claimed_at"] is None


async def test_the_org_admin_force_sync_also_queues(pool):
    """The SECOND force-sync entry point (`/ops/sync/{source}` in
    routers/admin_layers_api.py) had the identical in-process `create_task`.
    Fixing only the one in main.py would leave the starvation reachable from
    the panel most operators actually use. Called directly rather than over
    HTTP so the super-admin session machinery isn't in the way — the
    behaviour under test is the body, not the auth chain."""
    import main
    from routers import admin_layers_api

    ran: list[str] = []

    async def _fake_sync():
        ran.append(_SOURCE)

    main._SYNC_SOURCES[_SOURCE] = _fake_sync
    try:
        body = await admin_layers_api.ops_sync(_SOURCE, admin={"username": "tester"})
    finally:
        main._SYNC_SOURCES.pop(_SOURCE, None)

    assert not ran, "the org-admin route ran the sync in the web process"
    assert body["status"] == "queued"
    rows = await _requests(pool)
    assert len(rows) == 1 and rows[0]["requested_by"] == "tester"


# ── 2. The listener picks it up, including when the NOTIFY was lost ──────────

def _collector():
    ran: list[str] = []

    async def runner(source, fn):
        ran.append(source)
        await fn()

    return ran, runner


async def test_the_listener_claims_and_runs_a_queued_request(pool):
    called: list[str] = []

    async def _fake_sync():
        called.append(_SOURCE)

    await sync_queue.enqueue(_SOURCE, requested_by="test")
    ran, runner = _collector()
    await asyncio.wait_for(
        sync_queue.sync_request_listener(
            {_SOURCE: _fake_sync}.get, runner, sweep_interval=0.2, cycles=1),
        timeout=20)

    assert ran == [_SOURCE] and called == [_SOURCE]
    rows = await _requests(pool)
    assert rows[0]["claimed_at"] is not None
    assert rows[0]["finished_at"] is not None
    assert rows[0]["error"] is None


async def test_a_request_whose_notification_nobody_heard_is_still_run(pool):
    """⛔ THE hole this whole design is built around.

    `NOTIFY` is fire-and-forget: Postgres hands it to whoever is listening at
    that instant and to nobody else. A force-sync issued while the worker is
    restarting produces a row and a notification into the void. Without the
    sweep the listener attaches, waits for a notification that already
    happened, and the request sits unclaimed forever — the 2026-09-17
    silence, reproduced by design.

    The row is inserted DIRECTLY, with no `pg_notify` at all — indistinguishable
    from a notification nobody was listening for. `cycles=0` means the listener
    attaches, runs its STARTUP sweep and returns without ever entering the
    notify/timeout loop, so the startup sweep is the only thing that can find
    the row. Delete it and this goes red on its own.
    """
    called: list[str] = []

    async def _fake_sync():
        called.append(_SOURCE)

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO sync_requests (source, requested_by) VALUES ($1, 'nobody-heard')",
            _SOURCE)

    ran, runner = _collector()
    await asyncio.wait_for(
        sync_queue.sync_request_listener(
            {_SOURCE: _fake_sync}.get, runner, sweep_interval=0.2, cycles=0),
        timeout=20)

    assert called == [_SOURCE], (
        "a request with no live listener at NOTIFY time was never picked up. "
        "That is exactly how a force-sync vanishes without a trace.")


async def test_a_request_arriving_after_the_listener_is_already_idle_is_swept(pool):
    """The periodic sweep specifically, not the startup one: the row is
    created AFTER the listener has attached and drained, so only the idle-tick
    sweep can find it. Together with the test above — which runs with
    `cycles=0` and so exercises the STARTUP sweep alone — neither half can be
    deleted without something going red. Verified by sabotaging each
    separately; the counts are in the commit message."""
    called: list[str] = []

    async def _fake_sync():
        called.append(_SOURCE)

    ran, runner = _collector()
    task = asyncio.create_task(sync_queue.sync_request_listener(
        {_SOURCE: _fake_sync}.get, runner, sweep_interval=0.2))
    try:
        await asyncio.sleep(0.6)  # let it attach and complete its startup sweep
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO sync_requests (source, requested_by) VALUES ($1, 'late')",
                _SOURCE)
        for _ in range(100):
            if called:
                break
            await asyncio.sleep(0.1)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert called == [_SOURCE], "the idle-tick sweep never looked for unclaimed rows"


async def test_an_unknown_source_is_closed_out_rather_than_left_queued(pool):
    """A request naming a source no worker understands must not sit in
    `_queued` forever pretending help is on the way."""
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO sync_requests (source) VALUES ($1)", _SOURCE)

    ran, runner = _collector()
    await asyncio.wait_for(
        sync_queue.sync_request_listener(
            {}.get, runner, sweep_interval=0.2, cycles=0), timeout=20)

    rows = await _requests(pool)
    assert rows[0]["claimed_at"] is not None
    assert "unknown source" in (rows[0]["error"] or "")


async def test_a_failing_sync_records_its_error(pool):
    async def _boom():
        raise RuntimeError("upstream 500")

    await sync_queue.enqueue(_SOURCE)
    ran, runner = _collector()
    await asyncio.wait_for(
        sync_queue.sync_request_listener(
            {_SOURCE: _boom}.get, runner, sweep_interval=0.2, cycles=0), timeout=20)

    rows = await _requests(pool)
    assert "upstream 500" in (rows[0]["error"] or ""), (
        "a claimed-then-failed request reads exactly like a successful one")


# ── 3. The claim is atomic ───────────────────────────────────────────────────

async def test_two_claimers_cannot_both_win_the_same_request(pool):
    """Binds the single-statement `UPDATE ... FOR UPDATE SKIP LOCKED` in
    `claim_next`.

    ⛔ A `SELECT ... WHERE claimed_at IS NULL` followed by a separate `UPDATE`
    has an await between the two, so twenty coroutines all see the row
    unclaimed before any of them writes, and the sync runs twenty times. For a
    sync that reloads with DELETE-then-INSERT that is a layer briefly emptying
    in production.

    Twenty real connections, not two: a two-way race can be won by luck, a
    twenty-way one against a non-atomic claim cannot be lost.
    """
    await sync_queue.enqueue(_SOURCE)

    url = os.environ["TEST_DATABASE_URL"]
    conns = await asyncio.gather(*[asyncpg.connect(url) for _ in range(20)])
    try:
        rows = await asyncio.gather(
            *[sync_queue.claim_next(c, f"claimer-{i}") for i, c in enumerate(conns)])
    finally:
        await asyncio.gather(*[c.close() for c in conns], return_exceptions=True)

    winners = [r for r in rows if r is not None]
    assert len(winners) == 1, (
        f"{len(winners)} claimers won the same request — the sync would run "
        f"{len(winners)} times concurrently")


# ── 4. Running state is in Postgres, written by the lock ─────────────────────

async def test_holding_the_sync_lock_publishes_a_running_row(pool):
    """Binds `sync_queue.register_running(name)` in `_held_sync_lock`.

    The row is read by a connection from the pool while the lock is still
    held, so this is the cross-process view the admin endpoint gets — not a
    dict the same process happens to own.

    ⚠️ Note what this also proves: a SCHEDULED sync is visible now, not only a
    forced one. `_held_sync_lock` is the gate both go through.
    """
    async with scheduling._held_sync_lock(_SOURCE):
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM running_syncs WHERE source = $1", _SOURCE)
        assert row is not None, (
            "nothing published the running sync. /admin/sync/running is served "
            "by web while the sync runs in worker — without this row the "
            "endpoint answers {} for a sync that is very much running.")
        assert row["pid"] == os.getpid()
        assert row["role"]
        assert row["host"]

    async with pool.acquire() as conn:
        after = await conn.fetchval(
            "SELECT count(*) FROM running_syncs WHERE source = $1", _SOURCE)
    assert after == 0, "the row outlived the lock — /admin/sync/running would lie"


async def test_the_running_row_is_cleared_even_when_the_sync_raises(pool):
    with pytest.raises(RuntimeError):
        async with scheduling._held_sync_lock(_SOURCE):
            raise RuntimeError("sync blew up")

    async with pool.acquire() as conn:
        assert await conn.fetchval(
            "SELECT count(*) FROM running_syncs WHERE source = $1", _SOURCE) == 0


# ── 5. What /admin/sync/running actually reports ─────────────────────────────

async def _seed_running(p, source, *, started_ago=10, beat_ago=1, role="worker",
                        pid=4242, host="testbox"):
    async with p.acquire() as conn:
        await conn.execute(
            "INSERT INTO running_syncs (source, started_at, heartbeat_at, role, pid, host) "
            "VALUES ($1, now() - ($2 || ' seconds')::interval, "
            "        now() - ($3 || ' seconds')::interval, $4, $5, $6)",
            source, str(started_ago), str(beat_ago), role, pid, host)


async def test_the_endpoint_keeps_the_old_shape_for_running_syncs(pool):
    """⚠️ Backward compatibility, asserted. The Mac monitor parses the top
    level as `{source: seconds}` and has since before this queue existed."""
    await _seed_running(pool, _SOURCE, started_ago=42)

    snap = await sync_queue.running_snapshot()

    assert snap[_SOURCE] == 42, (
        "the top level no longer maps source -> seconds; the monitor that "
        "polls this endpoint every 30s parses exactly that")


async def test_the_endpoint_reports_queued_requests_with_their_age(pool):
    """Binds the `_queued` key in `running_snapshot`.

    ⛔ Without it, an operator who POSTs a force-sync and sees an empty
    /admin/sync/running is back in the 2026-09-17 position: nothing running,
    nothing to look at, no way to tell whether anything will ever happen.
    """
    await sync_queue.enqueue(_SOURCE, requested_by="operator")

    snap = await sync_queue.running_snapshot()

    queued = [q for q in snap["_queued"] if q["source"] == _SOURCE]
    assert queued, (
        "a queued-but-unclaimed request is invisible. That is the exact "
        "failure this endpoint exists to end: 'queued' and 'lost' look the same.")
    assert queued[0]["requested_by"] == "operator"
    assert queued[0]["age_seconds"] >= 0


async def test_a_claimed_request_stops_being_reported_as_queued(pool):
    """Otherwise `_queued` fills up with history and stops meaning anything."""
    await sync_queue.enqueue(_SOURCE)
    async with pool.acquire() as conn:
        await sync_queue.claim_next(conn, "worker:1@box")

    snap = await sync_queue.running_snapshot()
    assert not [q for q in snap["_queued"] if q["source"] == _SOURCE]


async def test_a_dead_process_row_is_reported_stale_not_running(pool):
    """⛔ A false "it is running" is worse than no answer.

    A process killed mid-sync never runs its `finally`, so its row sits there
    forever. Reporting it in the top-level map sends the operator away to wait
    for something that will never finish; deleting it silently destroys the
    only evidence the process died. So: separate key, with the age and the
    role/pid that claimed it, so there is something to go and look at.

    Liveness is proved by the heartbeat, not by elapsed time — a genuinely
    slow bake (GEBCO: tens of minutes) must not be called dead, which is why
    `started_ago` here is large and `beat_ago` is what decides.
    """
    await _seed_running(pool, _SOURCE, started_ago=4000, beat_ago=4000,
                        role="worker", pid=9999, host="deadbox")
    await _seed_running(pool, _OTHER, started_ago=4000, beat_ago=1)

    snap = await sync_queue.running_snapshot()

    assert _SOURCE not in snap, "a row whose process died is reported as running"
    assert snap[_OTHER] == 4000, (
        "a long-running sync that is still heartbeating was called stale")
    stale = [s for s in snap["_stale"] if s["source"] == _SOURCE]
    assert stale, "the dead row vanished instead of being reported"
    assert stale[0]["claimed_by"] == "worker:9999@deadbox", (
        "the stale report does not say which process to go and look at")
    assert stale[0]["age_seconds"] >= 4000


# ── 6. The listener is wired to a role that today's production starts ────────

def test_the_listener_is_in_the_registry_for_every_role_that_should_run_it():
    names = lambda role: {t.name for t in scheduling.tasks_for_role(role)}
    assert "sync-request-listener" in names("all"), (
        "ABYSSAL_ROLE=all is the DEFAULT and is what production runs right "
        "now — a single process that must both notify and listen. Without the "
        "listener there, every force-sync in production queues forever.")
    assert "sync-request-listener" in names("worker")
    assert "sync-request-listener" not in names("web"), (
        "the web process would run the bakes the split exists to keep out of it")


async def test_role_all_actually_drains_the_queue_end_to_end(pool, monkeypatch):
    """Not just "the spec is in the list" — the factory that `all` hands to
    `asyncio.create_task` is started here, and a real queued request has to
    come out the other side. ABYSSAL_ROLE is left unset on purpose: that is
    production's configuration today.

    ⛔ The sync is run through the registry's own factory, so this also covers
    `_forced_sync_runner` taking `_held_sync_lock` — a forced sync that
    skipped the lock could overlap the weekly chain against the same tables.
    """
    monkeypatch.delenv("ABYSSAL_ROLE", raising=False)
    called: list[str] = []
    holders: list[str | None] = []

    async def _fake_sync():
        holders.append(scheduling._lock_holder)
        called.append(_SOURCE)

    import sync_sources
    monkeypatch.setitem(sync_sources.SYNC_SOURCES, _SOURCE, _fake_sync)
    # No sweep-interval override: the request is enqueued BEFORE the task
    # starts, so it is the STARTUP sweep that has to find it — the production
    # path for "requested while the worker was down".

    spec = next(t for t in scheduling.tasks_for_role("all")
                if t.name == "sync-request-listener")

    await sync_queue.enqueue(_SOURCE, requested_by="role-all")
    task = asyncio.create_task(spec.factory(scheduling.TaskContext()))
    try:
        for _ in range(150):
            if called:
                break
            await asyncio.sleep(0.1)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert called == [_SOURCE], (
        "ABYSSAL_ROLE=all — today's production — never ran the queued sync")
    assert holders == [_SOURCE], (
        "the forced sync did not hold _sync_lock while running; it can now "
        "overlap a scheduled sync against the same tables")
