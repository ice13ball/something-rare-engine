# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Cross-process force-sync queue and running-sync state.

## Why this module exists

Before the 2026-09-18 web/worker split, `POST /admin/sync/{source}` called
`asyncio.create_task(_run_tracked(...))` and the sync ran in the only process
there was. After the split the POST is served by the WEB process — so that
`create_task` would run a multi-gigabyte bake inside the process that serves
tiles, which is precisely the starvation the split exists to remove.

So the POST no longer runs anything. It writes a row to `sync_requests` and
issues `pg_notify`; a listener task in the worker claims the row and runs the
sync through the same `_held_sync_lock` path the scheduled syncs use.

## The failure mode this module is shaped around

⚠️ `NOTIFY` is fire-and-forget. Postgres delivers it to whoever is listening at
that instant and to nobody else — a listener that connects a second later never
learns the notification happened. A force-sync issued during a worker restart
would therefore be silently swallowed, which is the exact 2026-09-17 incident
this work exists to prevent: `POST /admin/sync/sio-bic` answered
`{"status":"started"}`, nothing ever appeared in `/admin/sync/running`, and the
operator could not tell "queued" from "lost".

Hence: the durable row is the source of truth and the notification is only a
latency optimisation. `sweep_unclaimed()` runs once as soon as the listener
attaches AND on every idle tick, so a request that missed its notification is
picked up within `SWEEP_INTERVAL_SECONDS` instead of never.

⛔ Do not "simplify" the listener to react to notifications only. That removes
the only thing that makes a lost notification recoverable.

## Import constraints

This module is imported by `scheduling.py` (hence by `worker.py`) and by
`main.py`. It must therefore never import `main` or `fastapi` — see
`worker.py`'s docstring for why that matters.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from typing import Any, Awaitable, Callable

import asyncpg

import db

log = logging.getLogger(__name__)

# The Postgres NOTIFY channel. Lower-case and unquoted everywhere: Postgres
# folds unquoted identifiers, and `pg_notify(text, text)` does NOT fold, so a
# mixed-case name here and an unquoted LISTEN would never meet.
NOTIFY_CHANNEL = "abyssal_sync_request"

# How long the listener waits for a notification before sweeping anyway. This is
# the worst-case latency for a request whose notification was lost (issued while
# no listener was attached), NOT the normal path — a notification that arrives
# wakes the loop immediately.
SWEEP_INTERVAL_SECONDS = 30.0

# How often a running sync refreshes `running_syncs.heartbeat_at`, and how long
# a row may go unrefreshed before `/admin/sync/running` calls it stale. The
# ratio matters more than the values: 4x leaves room for an event loop that is
# busy inside a CPU-bound `to_thread` bake without declaring a live sync dead.
HEARTBEAT_INTERVAL_SECONDS = 15.0
STALE_AFTER_SECONDS = 60.0

# How long the listener waits before rebuilding a dropped listener connection.
RECONNECT_DELAY_SECONDS = 5.0


def process_identity(role: str | None = None) -> str:
    """`role:pid@host` — what gets recorded as `claimed_by` / reported for a
    stale row. An operator staring at a row that claims to be running needs to
    know WHICH process to go and look at; "something, somewhere" is not an
    answer they can act on."""
    role = role or os.environ.get("ABYSSAL_ROLE", "all")
    return f"{role}:{os.getpid()}@{socket.gethostname()}"


# ── Enqueue side (runs in the web process) ───────────────────────────────────

async def enqueue(source: str, requested_by: str = "admin") -> int:
    """Record a force-sync request and wake any listener. Returns the row id.

    ⛔ The INSERT comes first and the NOTIFY second, in the same statement
    batch on the same connection. If the notification were sent first, a
    listener could sweep before the row existed, find nothing, and go back to
    sleep — and the row would then wait a full sweep interval for no reason.
    """
    async with db.pool.acquire() as conn:
        request_id = await conn.fetchval(
            "INSERT INTO sync_requests (source, requested_by) VALUES ($1, $2) RETURNING id",
            source, requested_by,
        )
        await conn.execute("SELECT pg_notify($1, $2)", NOTIFY_CHANNEL, str(request_id))
    log.info("sync_queue: queued %s (request %s) by %s", source, request_id, requested_by)
    return int(request_id)


# ── Claim side (runs in the worker process) ──────────────────────────────────

async def claim_next(conn, claimed_by: str) -> asyncpg.Record | None:
    """Atomically claim the oldest unclaimed request, or return None.

    ⛔ ONE statement. A `SELECT ... WHERE claimed_at IS NULL` followed by a
    separate `UPDATE` is two round trips with an await between them, so two
    listeners (or two coroutines in one listener) both see the row unclaimed
    and both run the sync — double-running a sync that writes with
    DELETE-then-INSERT is how a layer briefly empties in production.
    `FOR UPDATE SKIP LOCKED` inside the sub-select is what makes the row
    handover exclusive without blocking a second claimer behind a lock.
    """
    return await conn.fetchrow(
        """
        UPDATE sync_requests
           SET claimed_at = now(), claimed_by = $1
         WHERE id = (
                SELECT id FROM sync_requests
                 WHERE claimed_at IS NULL
                 ORDER BY requested_at, id
                 LIMIT 1
                 FOR UPDATE SKIP LOCKED
               )
        RETURNING id, source, requested_at, requested_by
        """,
        claimed_by,
    )


async def mark_finished(conn, request_id: int, error: str | None = None) -> None:
    """Close out a claimed request. `error` is kept, not swallowed — a request
    that was picked up and then failed must not read like one that succeeded."""
    await conn.execute(
        "UPDATE sync_requests SET finished_at = now(), error = $2 WHERE id = $1",
        request_id, error,
    )


async def sweep_unclaimed(conn) -> int:
    """How many requests are sitting unclaimed. Used only for logging — the
    claim loop below drains by claiming, not by counting."""
    return int(await conn.fetchval(
        "SELECT count(*) FROM sync_requests WHERE claimed_at IS NULL"
    ))


# ── Running-sync state (written by scheduling._held_sync_lock) ───────────────

async def register_running(source: str, role: str | None = None) -> int | None:
    """Record that `source` is running in THIS process. Returns the row id, or
    None if the row could not be written (the sync still runs — the admin view
    degrading is not a reason to refuse to sync)."""
    try:
        async with db.pool.acquire() as conn:
            return int(await conn.fetchval(
                "INSERT INTO running_syncs (source, role, pid, host) "
                "VALUES ($1, $2, $3, $4) RETURNING id",
                source,
                role or os.environ.get("ABYSSAL_ROLE", "all"),
                os.getpid(),
                socket.gethostname(),
            ))
    except Exception:
        log.warning("sync_queue: could not register running sync %s", source, exc_info=True)
        return None


async def touch_running(row_id: int) -> None:
    async with db.pool.acquire() as conn:
        await conn.execute(
            "UPDATE running_syncs SET heartbeat_at = now() WHERE id = $1", row_id)


async def unregister_running(row_id: int | None) -> None:
    if row_id is None:
        return
    try:
        async with db.pool.acquire() as conn:
            await conn.execute("DELETE FROM running_syncs WHERE id = $1", row_id)
    except Exception:
        log.warning("sync_queue: could not clear running sync %s", row_id, exc_info=True)


async def heartbeat_loop(row_id: int, interval: float = HEARTBEAT_INTERVAL_SECONDS) -> None:
    """Refresh one running_syncs row until cancelled. A swallowed error here
    would silently turn a live sync into a "stale" report, so it is logged."""
    while True:
        await asyncio.sleep(interval)
        try:
            await touch_running(row_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("sync_queue: heartbeat failed for running_syncs %s", row_id,
                        exc_info=True)


# ── The read model behind GET /admin/sync/running ────────────────────────────

async def running_snapshot(stale_after: float = STALE_AFTER_SECONDS) -> dict[str, Any]:
    """What `/admin/sync/running` answers.

    ⚠️ SHAPE CONTRACT. The top level still maps `source -> seconds` for syncs
    that are demonstrably running, because an external monitor on Michal's Mac
    parses exactly that and has done since before this queue existed. The two
    new facts go in sibling keys prefixed with `_` (no sync source has ever
    started with an underscore, so they cannot collide with a source name):

      `_queued` — requests written but not yet claimed by any worker, with age.
                  This is the whole point of the exercise: an operator who POSTs
                  a force-sync and sees nothing running must be able to tell
                  "waiting for the worker" from "nobody will ever pick this up".
      `_stale`  — rows in `running_syncs` whose heartbeat has stopped, i.e. the
                  process that claimed them probably died mid-sync. ⛔ These are
                  deliberately NOT in the top-level map and deliberately NOT
                  deleted: a false "it is running" sends the operator away to
                  wait for something that will never finish, and a silent delete
                  destroys the only evidence that a process died.

    Chosen over a second endpoint because the monitor polls this one every 30 s
    for 20 minutes and would never have learned about a lost request otherwise.
    """
    async with db.pool.acquire() as conn:
        running = await conn.fetch(
            """
            SELECT source, role, pid, host,
                   EXTRACT(EPOCH FROM (now() - started_at))   AS age,
                   EXTRACT(EPOCH FROM (now() - heartbeat_at)) AS since_beat
              FROM running_syncs
             ORDER BY started_at
            """
        )
        queued = await conn.fetch(
            """
            SELECT id, source, requested_by,
                   EXTRACT(EPOCH FROM (now() - requested_at)) AS age
              FROM sync_requests
             WHERE claimed_at IS NULL
             ORDER BY requested_at, id
            """
        )

    out: dict[str, Any] = {}
    stale: list[dict[str, Any]] = []
    for r in running:
        since_beat = float(r["since_beat"])
        entry = {
            "source": r["source"],
            "age_seconds": round(float(r["age"])),
            "claimed_by": f"{r['role']}:{r['pid']}@{r['host']}",
            "heartbeat_age_seconds": round(since_beat),
        }
        if since_beat > stale_after:
            stale.append(entry)
        else:
            out[r["source"]] = round(float(r["age"]))
    out["_queued"] = [
        {
            "request_id": int(q["id"]),
            "source": q["source"],
            "requested_by": q["requested_by"],
            "age_seconds": round(float(q["age"])),
        }
        for q in queued
    ]
    out["_stale"] = stale
    return out


# ── The listener task body (started from scheduling.TASK_REGISTRY) ───────────

Runner = Callable[[str, Callable[[], Awaitable[Any]]], Awaitable[Any]]
Resolver = Callable[[str], Callable[[], Awaitable[Any]] | None]


async def _drain(conn, resolve: Resolver, runner: Runner, claimed_by: str) -> int:
    """Claim and run every pending request, oldest first. Returns how many ran."""
    ran = 0
    while True:
        row = await claim_next(conn, claimed_by)
        if row is None:
            return ran
        source = row["source"]
        fn = resolve(source)
        if fn is None:
            # Unknown source: the request is claimed and closed with an error
            # rather than left unclaimed, so it cannot sit in `_queued` forever
            # pretending a worker will eventually understand it.
            log.error("sync_queue: request %s names unknown source %r", row["id"], source)
            await mark_finished(conn, row["id"], f"unknown source {source!r}")
            continue
        log.info("sync_queue: running forced sync %s (request %s)", source, row["id"])
        error: str | None = None
        try:
            await runner(source, fn)
        except asyncio.CancelledError:
            # Leave the row claimed-but-unfinished: it really was picked up, and
            # a shutdown mid-sync is exactly the thing that must stay visible.
            await mark_finished(conn, row["id"], "cancelled")
            raise
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            log.error("sync_queue: forced sync %s failed", source, exc_info=True)
        await mark_finished(conn, row["id"], error)
        ran += 1


async def sync_request_listener(
    resolve: Resolver,
    runner: Runner,
    *,
    role: str = "worker",
    sweep_interval: float = SWEEP_INTERVAL_SECONDS,
    reconnect_delay: float = RECONNECT_DELAY_SECONDS,
    cycles: int | None = None,
) -> None:
    """Hold a LISTEN connection, claim force-sync requests, run them.

    The connection is opened with `asyncpg.connect(db.dsn)` rather than taken
    from the pool on purpose — `add_listener` needs the connection for as long
    as the process lives, and the pool only has four.

    `cycles` exists so a test can isolate ONE of the two sweeps, and that
    separation is the whole reason it is a parameter rather than a `while
    True`:

      `cycles=0`    attach, run the STARTUP sweep, return. Nothing else can
                    pick a row up, so deleting the startup sweep is visible.
      `cycles=N`    also run N notify-or-timeout rounds, each ending in a sweep.
      `cycles=None` production: forever, reconnecting on failure.

    ⛔ With a single `iterations` knob that always did both, deleting either
    sweep left every test green — the other one covered for it. That was
    caught by sabotage, not reasoning.
    """
    claimed_by = process_identity(role)
    while True:
        conn = None
        try:
            conn = await asyncpg.connect(db.dsn)
            queue: asyncio.Queue[str] = asyncio.Queue()

            def _on_notify(_conn, _pid, _channel, payload):
                queue.put_nowait(payload)

            await conn.add_listener(NOTIFY_CHANNEL, _on_notify)
            log.info("sync_queue: listening on %s as %s", NOTIFY_CHANNEL, claimed_by)

            # ⛔ STARTUP SWEEP. NOTIFY is fire-and-forget: every request issued
            # while this process was down, restarting or reconnecting produced a
            # durable row and a notification nobody heard. Without this line
            # those rows are never looked at again and the operator's
            # force-sync is lost in silence — the 2026-09-17 incident, rebuilt.
            pending = await sweep_unclaimed(conn)
            if pending:
                log.warning("sync_queue: startup sweep found %d unclaimed request(s)", pending)
            await _drain(conn, resolve, runner, claimed_by)

            done = 0
            while cycles is None or done < cycles:
                try:
                    await asyncio.wait_for(queue.get(), timeout=sweep_interval)
                except asyncio.TimeoutError:
                    pass
                # ⛔ PERIODIC SWEEP. Same reason as the startup one, for the
                # window between this listener dropping and reconnecting: the
                # notification is gone, the row is not. Claiming unconditionally
                # (rather than only on a notification) is what makes a lost
                # notification cost a sweep interval instead of everything.
                await _drain(conn, resolve, runner, claimed_by)
                done += 1
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            if cycles is not None:
                raise  # a test asked for a bounded run; do not hide the failure
            log.error("sync_queue: listener connection failed, retrying in %ss",
                      reconnect_delay, exc_info=True)
            await asyncio.sleep(reconnect_delay)
        finally:
            if conn is not None:
                try:
                    await conn.close()
                except Exception:
                    pass
