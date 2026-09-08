# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Startup verifies the schema; it does not create it, and it does not refuse.

Refusing to boot on a mismatch would crash-loop: the unit is Restart=always
with RestartSec=5. That converts a warning into a total outage, which is the
opposite of what this whole change is for. The deploy script is the gate; this
is the smoke alarm behind it.
"""
import pathlib
import re

import pytest

MAIN = pathlib.Path(__file__).resolve().parent.parent / "main.py"


def test_lifespan_no_longer_runs_the_schema_steps():
    """The property under test is the shape of the code: startup must not loop
    over SCHEMA_STEPS, or it is still doing the work migrate.py now owns."""
    src = MAIN.read_text()
    assert not re.search(r"for\s+\w+,\s*\w+\s+in\s+SCHEMA_STEPS", src), (
        "lifespan() still iterates SCHEMA_STEPS — the DDL has not moved"
    )
    assert "_ensure_step" not in src, (
        "_ensure_step survives but nothing calls it; delete it with its test"
    )


@pytest.mark.parametrize(
    "row, running_sha, expected",
    [
        ({"git_sha": "abc123"}, "abc123", "ok"),
        ({"git_sha": "abc123"}, "def456", "stale"),
        (None,                  "abc123", "stale"),
        ({"git_sha": "abc123"}, None,     "unknown"),
    ],
)
def test_schema_state_classification(row, running_sha, expected):
    from main import classify_schema_state
    assert classify_schema_state(row, running_sha) == expected


def test_a_stale_schema_does_not_raise():
    """Whatever the verdict, startup continues. Nothing here may raise."""
    from main import classify_schema_state
    for row in (None, {"git_sha": "x"}):
        for sha in (None, "y"):
            classify_schema_state(row, sha)  # must not raise


# ── Broad-catch + timeout guard around the fetch itself ─────────────────────
#
# classify_schema_state above only ever sees a row (or None) that was
# successfully read. It says nothing about what happens when the read never
# completes: a connection reset, an exhausted pool, a lock on the row, or a
# permission error. Any of those escaping lifespan() fails ASGI startup and,
# under Restart=always/RestartSec=5, becomes exactly the crash-loop this
# whole change exists to prevent — so they must be caught, and a hang must be
# bounded by a wall-clock timeout. Both map to "unknown" (we failed to look),
# never "stale" (we looked and saw a mismatch) — a missing table is the one
# case that IS a real "stale" verdict, and must stay one.
#
# These fake out the asyncpg pool rather than needing a real database.
import asyncio

import asyncpg


class _FakeConn:
    def __init__(self, behavior):
        self._behavior = behavior  # an exception instance, "hang", or a row

    async def fetchrow(self, *args, **kwargs):
        if self._behavior == "hang":
            await asyncio.sleep(3600)
        if isinstance(self._behavior, BaseException):
            raise self._behavior
        return self._behavior


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc_info):
        return False


class _FakePool:
    def __init__(self, behavior):
        self._conn = _FakeConn(behavior)

    def acquire(self):
        return _FakeAcquire(self._conn)


@pytest.mark.asyncio
async def test_arbitrary_fetch_exception_does_not_propagate_and_is_unknown():
    from main import _check_schema_state
    pool = _FakePool(RuntimeError("connection reset"))
    state, row = await _check_schema_state(pool, "abc123", timeout_s=1.0)
    assert state == "unknown"
    assert row is None


@pytest.mark.asyncio
async def test_fetch_that_never_returns_is_abandoned_at_timeout_and_is_unknown():
    from main import _check_schema_state
    pool = _FakePool("hang")
    state, row = await _check_schema_state(pool, "abc123", timeout_s=0.05)
    assert state == "unknown"
    assert row is None


@pytest.mark.asyncio
async def test_missing_table_is_still_stale_not_unknown():
    from main import _check_schema_state
    pool = _FakePool(asyncpg.exceptions.UndefinedTableError("relation \"schema_migrations\" does not exist"))
    state, row = await _check_schema_state(pool, "abc123", timeout_s=1.0)
    assert state == "stale"
    assert row is None
