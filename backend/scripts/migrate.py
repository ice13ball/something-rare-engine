# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Apply every schema step, before the API restarts. Fails the deploy on error.

⛔ This is the deploy gate. It must NEVER skip a step. `lifespan()` used to
tolerate a lock timeout and defer the step "to next restart"; on 2026-09-06 that
let the API serve a whole day on a schema the code did not expect.

Usage (from the repository root):
    DATABASE_URL=postgresql://... backend/.venv/bin/python backend/scripts/migrate.py

Exit codes:  0 applied and recorded · 1 a step failed, do not restart · 2 misconfigured

⚠️ Does NOT create the `abyssal_user` role or enable PostGIS — that is
`backend/scripts/ci_bootstrap_db.py`'s job, run once against a fresh database.
Production already has both; this script only ever runs against a database
that already has them.
"""
from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import asyncpg  # noqa: E402

import db as _db  # noqa: E402
from ais_sync import seed_aois_from_existing_layers  # noqa: E402
from schema_steps import (  # noqa: E402
    SCHEMA_STEPS,
    is_lock_error,
    run_step,
    resolve_git_sha,
    ensure_schema_migrations_table,
    record_schema_migration,
)

log = logging.getLogger(__name__)

STEP_TIMEOUT_S = float(os.environ.get("ABYSSAL_MIGRATE_STEP_TIMEOUT_S", "300"))
LOCK_TIMEOUT = os.environ.get("ABYSSAL_MIGRATE_LOCK_TIMEOUT", "15s")
LOCK_RETRY_EVERY_S = float(os.environ.get("ABYSSAL_MIGRATE_LOCK_RETRY_EVERY_S", "15"))


def _missing_role_hint(exc: Exception) -> str:
    """abyssal_user missing surfaces as a raw asyncpg error otherwise — an
    operator sees 'role "abyssal_user" does not exist' with no pointer to the
    one-time tool that creates it, and this script deliberately does not
    create it itself (see module docstring)."""
    text = str(exc)
    if "abyssal_user" in text and "does not exist" in text:
        return (" — run backend/scripts/ci_bootstrap_db.py first; it creates "
                "the abyssal_user role (production already has it, a fresh "
                "database does not)")
    return ""


def _make_step(step, name, *, fail_at, lock_at, lock_at_fired):
    """Test seams for ABYSSAL_MIGRATE_FAIL_AT / ABYSSAL_MIGRATE_LOCK_AT.

    Both must raise THROUGH run_step, not return early around it — a seam
    that short-circuits before run_step proves only that the seam's own
    branch works, not that the retry / is_lock_error / exit path this task
    exists for (the 2026-09-06 incident) actually runs. So the seam swaps in
    a step callable that raises, and lets the real except-block handle it.
    """
    if name == fail_at:
        async def _wrapped():
            raise RuntimeError(f"{name} failed (ABYSSAL_MIGRATE_FAIL_AT test seam)")
        return _wrapped
    if name == lock_at and name not in lock_at_fired:
        async def _wrapped():
            lock_at_fired.add(name)
            # Message shape matters: is_lock_error() requires "lock" plus
            # either "timeout" or "canceling statement" in the text — this
            # mirrors what a real Postgres lock_timeout error looks like.
            raise RuntimeError(
                f"simulated lock timeout on {name} (ABYSSAL_MIGRATE_LOCK_AT test seam)"
            )
        return _wrapped
    return step


async def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("migrate: DATABASE_URL is not set", file=sys.stderr)
        return 2

    sha = resolve_git_sha()
    if sha is None:
        print("migrate: no ABYSSAL_GIT_SHA and no usable git checkout; "
              "recording 'unknown' — startup will log that it cannot verify",
              file=sys.stderr)
        sha = "unknown"

    # lock_timeout on the POOL, so all sixteen steps inherit it. Only 4 of them
    # set one on their own connection; the other eleven would otherwise wait
    # forever on a lock held by the still-running old process.
    pool = await asyncpg.create_pool(
        url, min_size=1, max_size=4,
        server_settings={"lock_timeout": LOCK_TIMEOUT},
    )
    _db.pool = pool

    fail_at = os.environ.get("ABYSSAL_MIGRATE_FAIL_AT")  # test seam — never set in production
    lock_at = os.environ.get("ABYSSAL_MIGRATE_LOCK_AT")  # test seam — never set in production
    aoi_seed_fail = os.environ.get("ABYSSAL_MIGRATE_AOI_SEED_FAIL")  # test seam — never set in production
    lock_at_fired: set[str] = set()
    try:
        async with pool.acquire() as conn:
            await ensure_schema_migrations_table(conn)

        for real_step, name in SCHEMA_STEPS:
            deadline = time.monotonic() + STEP_TIMEOUT_S
            while True:
                try:
                    # Re-decide on EVERY attempt, not once before the retry
                    # loop: ABYSSAL_MIGRATE_LOCK_AT's wrapper must stop
                    # raising once lock_at_fired records its first failure,
                    # or the retry loop calls the same always-raising closure
                    # forever and the run never terminates.
                    step = _make_step(real_step, name, fail_at=fail_at, lock_at=lock_at,
                                      lock_at_fired=lock_at_fired)
                    # Clamp each attempt to what's left of the step's own
                    # budget, not the full STEP_TIMEOUT_S again. Without this,
                    # a step that cycles through several lock-timeout retries
                    # and then blocks on something lock_timeout doesn't cover
                    # (e.g. pool-connection starvation) can run up to
                    # STEP_TIMEOUT_S *again* on that last attempt — up to 2x
                    # the stated ceiling, with deploy-if-new.sh blocked on it
                    # the whole time and nothing said about why.
                    attempt_timeout = max(0.0, min(STEP_TIMEOUT_S,
                                                    deadline - time.monotonic()))
                    elapsed = await run_step(step, name, timeout_s=attempt_timeout)
                    print(f"  {name:36s}  {elapsed * 1000:8.0f} ms  OK", flush=True)
                    break
                except Exception as exc:
                    remaining = deadline - time.monotonic()
                    if is_lock_error(exc) and remaining > LOCK_RETRY_EVERY_S:
                        # The old process is still serving and holding locks.
                        # Waiting is right; skipping is what we came here to stop.
                        print(f"  {name:36s}  locked, retrying in "
                              f"{LOCK_RETRY_EVERY_S:.0f}s ({remaining:.0f}s left)",
                              flush=True)
                        await asyncio.sleep(LOCK_RETRY_EVERY_S)
                        continue
                    hint = _missing_role_hint(exc)
                    print(f"  {name:36s}  FAILED  {type(exc).__name__}: {exc}{hint}",
                          flush=True)
                    print(f"migrate: {name} failed; not restarting{hint}", file=sys.stderr)
                    return 1

        # NOT a schema step, deliberately not in SCHEMA_STEPS and not run
        # through run_step (which always fails on a lock): seed_aois_from_existing_layers
        # populates which AIS bboxes we subscribe to, which is unrelated to
        # whether the database schema is correct. lifespan() has always run
        # it non-fatally (try/except around the same call in main.py) — a
        # stale/failed AOI seed means AIS filtering runs on outdated bboxes
        # for a while, not that the deploy should be blocked. Measured on
        # production 2026-09-07: this is ~14s of a 19s restart, three
        # quarters of the wall-clock time Goal 3 is about — it has to run
        # here, in the pre-restart gate, or moving the 16 DDL steps alone
        # barely moves the number lifespan() reports.
        aoi_started = time.monotonic()
        try:
            if aoi_seed_fail:
                raise RuntimeError(
                    f"seed_aois_from_existing_layers failed "
                    f"({aoi_seed_fail} — ABYSSAL_MIGRATE_AOI_SEED_FAIL test seam)"
                )
            aoi_count = await seed_aois_from_existing_layers()
        except Exception as exc:
            aoi_elapsed = time.monotonic() - aoi_started
            log.exception("AOI seeding failed (non-fatal)")
            print(f"  {'seed_aois_from_existing_layers':36s}  {aoi_elapsed * 1000:8.0f} ms  "
                  f"WARN  {type(exc).__name__}: {exc} — deploy continues, "
                  f"AIS bboxes may be stale until the next successful run", flush=True)
        else:
            aoi_elapsed = time.monotonic() - aoi_started
            print(f"  {'seed_aois_from_existing_layers':36s}  {aoi_elapsed * 1000:8.0f} ms  "
                  f"OK  ({aoi_count} aois seeded)", flush=True)

        async with pool.acquire() as conn:
            await record_schema_migration(conn, sha, len(SCHEMA_STEPS))
        print(f"migrate: {len(SCHEMA_STEPS)} steps applied, recorded {sha[:12]}")
        return 0
    finally:
        await pool.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
