# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""The coral-exposure startup bake must neither freeze the API nor repeat itself
after every restart.

2026-09-26: the bake ran inline in the event loop, 41 minutes after each restart,
and every endpoint answered 499/503 for ~3 minutes (11:22 and 21:24 that day).
"""
import asyncio
import os
import time

import asyncpg
import pytest

import db
from domains.fields import carbon
from services import coral_acid_exposure as cae

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")


# ── The bake leaves the event loop free ──────────────────────────────────────

class _FakeConn:
    async def fetchval(self, *_a):
        return 1                                   # vme_cells is not empty

    async def fetch(self, *_a):
        return []

    async def execute(self, *_a):
        return None

    async def executemany(self, *_a):
        return None

    def transaction(self):
        return _Ctx(None)


class _Ctx:
    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def acquire(self):
        return _Ctx(_FakeConn())


async def test_bake_keeps_the_event_loop_serving_requests(monkeypatch):
    def slow_inputs():
        time.sleep(0.4)                            # stands in for the ~4 GB grid load
        return None, ("today", "pi", "axes")

    def slow_classify(rows, grids):
        time.sleep(0.4)                            # stands in for the per-cell loop
        return [], []

    monkeypatch.setattr(cae, "_load_inputs", slow_inputs)
    monkeypatch.setattr(cae, "_classify_rows", slow_classify)

    ticks = 0

    async def other_requests():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.02)
            ticks += 1

    ticker = asyncio.create_task(other_requests())
    await cae.bake_exposure(_FakePool())
    ticker.cancel()
    # 0.8 s of blocking work: a free loop ticks ~40 times, a frozen one ~0.
    assert ticks >= 20, f"event loop was blocked during the bake ({ticks} ticks)"


# ── The bake is skipped when its stored result is newer than its inputs ──────

class _PoolFromConn:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _Ctx(self._conn)


@pytest.fixture
async def conn():
    c = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
    tx = c.transaction()
    await tx.start()
    previous = db.pool
    db.pool = _PoolFromConn(c)
    try:
        await c.execute("DELETE FROM sync_log WHERE source IN "
                        "('coral-acid-exposure', 'vme-sdm', 'acidification')")
        await c.execute("DELETE FROM vme_exposure_cells")
        yield c
    finally:
        db.pool = previous
        await tx.rollback()
        await c.close()


@pytest.fixture
def bakes(monkeypatch):
    calls = []

    async def fake_bake(_pool):
        calls.append(1)
        return {"cells": 1, "skipped": None, "summary": {}}

    monkeypatch.setattr(cae, "bake_exposure", fake_bake)
    return calls


async def _stamp(c, source, age_hours):
    await c.execute(
        "INSERT INTO sync_log (source, last_synced_at) VALUES ($1, now() - make_interval(hours => $2)) "
        "ON CONFLICT (source) DO UPDATE SET last_synced_at = EXCLUDED.last_synced_at",
        source, age_hours)


async def _one_exposure_row(c):
    await c.execute("INSERT INTO vme_exposure_cells (cell_id, state) VALUES ('test-cell', 'no_data')")


@needs_db
class TestFreshnessGuard:
    async def test_skips_when_stored_bake_is_newer_than_both_inputs(self, conn, bakes):
        await _one_exposure_row(conn)
        await _stamp(conn, "vme-sdm", 300)
        await _stamp(conn, "acidification", 100)
        await _stamp(conn, "coral-acid-exposure", 1)
        await carbon.sync_coral_exposure()
        assert bakes == []
        reason = await conn.fetchval(
            "SELECT skipped_reason FROM sync_log WHERE source = 'coral-acid-exposure'")
        assert reason == "stored bake is newer than its inputs"

    async def test_bakes_when_an_input_is_newer(self, conn, bakes):
        await _one_exposure_row(conn)
        await _stamp(conn, "vme-sdm", 300)
        await _stamp(conn, "coral-acid-exposure", 10)
        await _stamp(conn, "acidification", 1)        # re-run after the last exposure bake
        await carbon.sync_coral_exposure()
        assert bakes == [1]

    async def test_bakes_when_the_table_is_empty(self, conn, bakes):
        await _stamp(conn, "vme-sdm", 300)
        await _stamp(conn, "acidification", 100)
        await _stamp(conn, "coral-acid-exposure", 1)
        await carbon.sync_coral_exposure()
        assert bakes == [1]

    async def test_bakes_when_it_never_ran(self, conn, bakes):
        await _one_exposure_row(conn)
        await carbon.sync_coral_exposure()
        assert bakes == [1]

    async def test_force_always_bakes(self, conn, bakes):
        await _one_exposure_row(conn)
        await _stamp(conn, "coral-acid-exposure", 1)
        await carbon.sync_coral_exposure(force=True)
        assert bakes == [1]

    async def test_a_failed_bake_does_not_read_as_fresh(self, conn, monkeypatch):
        async def broken(_pool):
            raise RuntimeError("grid unreadable")

        monkeypatch.setattr(cae, "bake_exposure", broken)
        await _one_exposure_row(conn)
        await _stamp(conn, "coral-acid-exposure", 50)
        before = await conn.fetchval(
            "SELECT last_synced_at FROM sync_log WHERE source = 'coral-acid-exposure'")
        await carbon.sync_coral_exposure(force=True)
        row = await conn.fetchrow(
            "SELECT last_synced_at, skipped_reason FROM sync_log WHERE source = 'coral-acid-exposure'")
        assert row["last_synced_at"] == before
        assert row["skipped_reason"] == "bake failed: RuntimeError"
