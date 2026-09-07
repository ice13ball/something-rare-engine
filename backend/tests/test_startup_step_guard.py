# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""`_ensure_step` must let the API start even when a schema step never returns.

The guard exists because of a live outage on 2026-08-21: a startup CREATE INDEX
sat on a relation lock for 8 minutes, `lifespan()` never returned, uvicorn never
bound its port, and systemd still reported the service `active`. The lock
tolerance that was supposed to cover this only fires when the step RAISES, which
needs a `lock_timeout` on the step's own connection — 4 of 15 steps set one.
"""
from __future__ import annotations

import asyncio

import asyncpg
import pytest

from main import _ensure_step


@pytest.mark.asyncio
async def test_a_step_that_never_returns_is_abandoned_not_awaited_forever():
    started = asyncio.Event()

    async def hangs_forever():
        started.set()
        await asyncio.sleep(3600)

    # Would hang the whole boot before the guard existed.
    await asyncio.wait_for(
        _ensure_step(hangs_forever, "hangs_forever", timeout_s=0.1),
        timeout=5,
    )
    assert started.is_set(), "the step should have been entered, not skipped"


@pytest.mark.asyncio
async def test_the_hanging_step_is_actually_cancelled():
    """Abandoning must not leave the query running behind our back."""
    cancelled = False

    async def hangs_forever():
        nonlocal cancelled
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled = True
            raise

    await _ensure_step(hangs_forever, "hangs_forever", timeout_s=0.1)
    await asyncio.sleep(0)
    assert cancelled, "wait_for must cancel the step, not orphan it"


@pytest.mark.asyncio
async def test_lock_unavailable_is_still_tolerated():
    async def blocked():
        raise asyncpg.exceptions.LockNotAvailableError("lock timeout")

    await _ensure_step(blocked, "blocked")  # must not raise


@pytest.mark.asyncio
async def test_any_other_error_still_fails_startup():
    """Tolerance is narrow on purpose — bad SQL must not be swallowed."""
    async def broken():
        raise asyncpg.exceptions.UndefinedTableError("relation does not exist")

    with pytest.raises(asyncpg.exceptions.UndefinedTableError):
        await _ensure_step(broken, "broken")


@pytest.mark.asyncio
async def test_a_normal_step_runs_to_completion():
    ran = False

    async def fine():
        nonlocal ran
        ran = True

    await _ensure_step(fine, "fine")
    assert ran
