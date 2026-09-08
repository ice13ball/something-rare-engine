# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""migrate.py must fail the deploy rather than defer itself.

On 2026-09-06 at 15:28 ensure_schema hit a lock timeout at startup, logged
"API starting without it, step will reapply on next restart", and the API
served the rest of the day on a schema the code did not expect. The whole
point of moving this work into a script is that the script says no.
"""
import os
import pathlib
import subprocess
import sys
import time

import pytest

from schema_steps import SCHEMA_STEPS

# ⛔ Derived, never a literal. This assertion is about "migrate.py recorded what it
# actually ran", not about how many steps there are — that number is pinned
# deliberately in test_schema_steps_single_source.py, which is the gate for adding
# one. Spelling it twice meant adding a step turned this file red for a reason that
# has nothing to do with what it tests (it did, on 2026-09-08, and only in CI:
# these two cases need a real TEST_DATABASE_URL and are skipped without one).
EXPECTED_STEPS = len(SCHEMA_STEPS)

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
MIGRATE = REPO / "backend" / "scripts" / "migrate.py"

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)


def _run(env_extra=None):
    env = dict(os.environ)
    env["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(MIGRATE)],
                          capture_output=True, text=True, env=env, timeout=900)


def test_migrate_applies_the_schema_and_records_the_commit():
    r = _run({"ABYSSAL_GIT_SHA": "deadbeefcafe"})
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "ensure_schema" in r.stdout
    # every step reports a duration, so a slow step is visible without a journal
    assert "OK" in r.stdout


def test_migrate_is_idempotent():
    """It runs on every deploy. A second run must be a no-op, not a failure."""
    first = _run({"ABYSSAL_GIT_SHA": "deadbeefcafe"})
    assert first.returncode == 0, first.stderr
    second = _run({"ABYSSAL_GIT_SHA": "deadbeefcafe"})
    assert second.returncode == 0, f"second run failed:\n{second.stderr}"


@pytest.mark.asyncio
async def test_the_recorded_row_is_readable_and_single():
    import asyncpg
    _run({"ABYSSAL_GIT_SHA": "0123456789ab"})
    conn = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
    try:
        rows = await conn.fetch("SELECT id, git_sha, steps FROM schema_migrations")
        assert len(rows) == 1, "schema_migrations must hold exactly one row"
        assert rows[0]["id"] == 1
        assert rows[0]["git_sha"] == "0123456789ab"
        assert rows[0]["steps"] == EXPECTED_STEPS
    finally:
        await conn.close()


def test_missing_database_url_is_a_configuration_error_not_a_crash():
    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL",)}
    env["TEST_DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    r = subprocess.run([sys.executable, str(MIGRATE)],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 2, f"expected exit 2, got {r.returncode}: {r.stderr}"
    assert "DATABASE_URL" in r.stderr


def test_a_failing_step_stops_the_run_and_exits_one():
    """The deploy gate. A step that raises must not be skipped, and no later
    step may run — a half-applied schema is the thing this prevents.

    ABYSSAL_MIGRATE_FAIL_AT raises THROUGH run_step (not around it), so this
    exercises the real except-block / is_lock_error check / exit path, not
    just the seam's own branch."""
    r = _run({"ABYSSAL_GIT_SHA": "deadbeefcafe", "ABYSSAL_MIGRATE_FAIL_AT": "ensure_log_schema"})
    assert r.returncode == 1, f"expected exit 1, got {r.returncode}\n{r.stdout}"
    assert "ensure_log_schema" in (r.stdout + r.stderr)
    assert "FAILED" in (r.stdout + r.stderr)
    # ensure_admin_schema comes after it and must not have run
    assert "ensure_admin_schema" not in r.stdout


def test_a_locked_step_retries_and_then_succeeds():
    """The retry path — the one the 2026-09-06 incident needed and the
    ABYSSAL_MIGRATE_FAIL_AT test alone never proves: a lock is a reason to
    wait, not to skip the step. ABYSSAL_MIGRATE_LOCK_AT makes the named step
    raise a lock-shaped error on its first attempt only, so the run must
    retry once and then succeed — exit 0, not 1.

    ABYSSAL_MIGRATE_LOCK_RETRY_EVERY_S is set small here so the test doesn't
    have to wait the real 15s default."""
    started = time.monotonic()
    r = _run({
        "ABYSSAL_GIT_SHA": "deadbeefcafe",
        "ABYSSAL_MIGRATE_LOCK_AT": "ensure_log_schema",
        "ABYSSAL_MIGRATE_LOCK_RETRY_EVERY_S": "2",
    })
    elapsed = time.monotonic() - started
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "ensure_log_schema" in r.stdout
    assert "retrying" in r.stdout
    # proves the run actually waited for the retry interval rather than
    # racing past a lock error it should have honoured
    assert elapsed >= 2.0, f"run finished in {elapsed:.1f}s, expected >= 2s of retry wait"


@pytest.mark.asyncio
async def test_aoi_seed_failure_is_non_fatal():
    """seed_aois_from_existing_layers is deliberately NOT in SCHEMA_STEPS: a
    stale/failed AOI seed means AIS filtering runs on outdated bboxes, not
    that the schema is wrong, so it must never block the deploy. A failure
    here must still exit 0 and still record schema_migrations — the same
    non-fatal contract lifespan() already applies around the same call."""
    import asyncpg

    r = _run({
        "ABYSSAL_GIT_SHA": "aoifa11ed0000",
        "ABYSSAL_MIGRATE_AOI_SEED_FAIL": "1",
    })
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "seed_aois_from_existing_layers" in r.stdout
    assert "WARN" in r.stdout

    conn = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
    try:
        row = await conn.fetchrow(
            "SELECT git_sha, steps FROM schema_migrations WHERE id = 1"
        )
        assert row is not None, "schema_migrations must still be written on AOI-seed failure"
        assert row["git_sha"] == "aoifa11ed0000"
        assert row["steps"] == EXPECTED_STEPS
    finally:
        await conn.close()
