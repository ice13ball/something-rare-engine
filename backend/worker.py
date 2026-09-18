# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Standalone worker process: runs every `worker`/`both` task in
scheduling.TASK_REGISTRY, serves NOTHING over HTTP.

⛔ This module must never import `main` or `fastapi`. That is the entire
point of splitting this out: `main.py` builds the FastAPI `app` object as a
module-level side effect of being imported (`app = FastAPI(...)`, then a
long run of `app.add_middleware(...)` / `app.include_router(...)` calls) —
so *any* import of `main`, even one that never calls `uvicorn.run`, already
constructs that object. A behavioural test can't observe this (constructing
`FastAPI()` doesn't bind a port or do anything visible at import time by
itself) — which is exactly why the test for this has to look at source/
import-graph, not run this module and check for an open socket. See
`backend/tests/` for that check.

This process:
  1. Builds the asyncpg pool with the SAME settings `lifespan()` uses in
     main.py, and assigns `db.pool` / `db.dsn` the same way — including the
     DSN-beside-the-pool assignment (see db.py's comment on `dsn`: some sync
     code, e.g. the Argo advisory-lock connection in domains/sensors.py,
     opens its own connection from `db.dsn` rather than the pool, and that
     only guards anything if it's the same database the pool talks to).
  2. Warms the paused-syncs cache once (so the first `is_sync_paused` check
     any worker task makes doesn't itself hit the DB — a cheap optimization,
     not a correctness requirement: `is_sync_paused` lazily reloads if the
     cache is still `None`).
  3. Starts every `worker`/`both`-labelled task from the registry — always
     role "worker", not read from ABYSSAL_ROLE: this process's whole reason
     to exist IS being the worker, there is no ambiguity to resolve from the
     environment the way there is in main.py's shared lifespan().
  4. Waits until asked to stop (SIGINT/SIGTERM), then cancels every task it
     started and closes the pool.

Deliberately NOT done here (all web-serving concerns, irrelevant to a
process with no HTTP listener): schema-state check, admin bootstrap,
API-key cache seeding, GeoIP loading. Skipping them is not a shortcut, it is
the correct shape for this process.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal

import asyncpg
import db
from dotenv import load_dotenv

from scheduling import TaskContext, tasks_for_role, _watch
from sync_log import _load_paused_syncs

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("worker")


async def _build_pool() -> asyncpg.Pool:
    # Same settings as main.py's lifespan() — see that function's comment on
    # why max_size is capped at 4 (shared CPU budget across web + worker; a
    # separate process still shares the same box and the same Postgres).
    pool = await asyncpg.create_pool(
        os.environ["DATABASE_URL"],
        min_size=2, max_size=4, max_inactive_connection_lifetime=300.0,
    )
    db.pool = pool
    # See db.py's comment on `dsn` — some sync code opens its own connection
    # from this, independent of the pool, and the guarantee it exists for
    # (e.g. the Argo advisory lock) only holds if this is the SAME database
    # the pool above was opened against.
    db.dsn = os.environ["DATABASE_URL"]
    return pool


async def main() -> None:
    pool = await _build_pool()
    log.info("worker: pool ready, db.dsn set")

    await _load_paused_syncs()

    ctx = TaskContext(log_pipe=None, geoip=None)  # no web-serving state here
    wanted = tasks_for_role("worker")
    tasks: list[asyncio.Task] = []
    for spec in wanted:
        t = asyncio.create_task(spec.factory(ctx), name=spec.name)
        t.add_done_callback(_watch)
        tasks.append(t)
    log.info("worker: started %d task(s): %s", len(tasks), ", ".join(s.name for s in wanted))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # add_signal_handler isn't available on every platform (e.g.
            # Windows) — the process still exits on an uncaught signal,
            # just without the graceful pool-close below.
            pass

    await stop.wait()
    log.info("worker: stop signal received — cancelling %d task(s)", len(tasks))
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await pool.close()
    log.info("worker: pool closed, exiting")


if __name__ == "__main__":
    asyncio.run(main())
