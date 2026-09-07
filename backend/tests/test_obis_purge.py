# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Guards on the OBIS stale-row purge.

The purge deletes rows the current OBIS snapshot no longer carries. That is the
right semantics — a record the source withdrew should not survive here — but it
is also the one operation in this sync that can destroy data, so the conditions
under which it declines to run are locked here rather than left to review.

Context: OBIS regenerates a record's `_id` whenever a contributor republishes a
dataset. A republication therefore orphans a whole generation of rows. Only a
pass that saw every parquet file can tell an orphan from a live record, so a
partial pass must never be allowed to reach the DELETE.
"""
import pytest

from backend.ingestion.obis_sync import (
    _PURGE_MIN_STAMPED_RATIO,
    _coverage_complete,
    _purge_stale,
)


class _FakeLockConn:
    """Stands in for the connection holding the advisory lock."""

    def __init__(self, still_locked: int = 1):
        self._still_locked = still_locked

    async def fetchval(self, *_args):
        return self._still_locked


class _FakeConn:
    def __init__(self, seen: int, deleted: int):
        self._seen = seen
        self._deleted = deleted
        self.executed: list[str] = []

    async def fetchval(self, *_args):
        return self._seen

    async def execute(self, sql, *_args):
        self.executed.append(sql)
        return f"DELETE {self._deleted}"


class _FakePool:
    def __init__(self, conn: _FakeConn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *_exc):
                return False

        return _Ctx()


async def _run(*, seen, deleted, total_before, complete, still_locked=1):
    conn = _FakeConn(seen, deleted)
    n = await _purge_stale(_FakePool(conn), total_before, _FakeLockConn(still_locked),
                           complete=complete)
    return n, conn


def _deletes(conn) -> list[str]:
    return [s for s in conn.executed if s.strip().startswith("DELETE")]


@pytest.mark.asyncio
async def test_incomplete_pass_never_deletes():
    """An aborted pass records a partial view; purging on it would empty the table."""
    n, conn = await _run(seen=40_000_000, deleted=999, total_before=40_774_532,
                         complete=False)
    assert n == 0
    assert conn.executed == []


@pytest.mark.asyncio
async def test_implausibly_low_seen_count_refuses_to_delete():
    """Second guard: pass "completed" but saw almost nothing (e.g. S3 returned empties)."""
    total_before = 40_774_532
    n, conn = await _run(seen=int(total_before * 0.1), deleted=999,
                         total_before=total_before, complete=True)
    assert n == 0
    assert _deletes(conn) == []


@pytest.mark.asyncio
async def test_healthy_pass_purges_and_reports_count():
    """The real case: ~80% of pre-existing rows re-observed, the rest are orphans."""
    total_before = 40_774_532
    n, conn = await _run(seen=32_724_724, deleted=8_049_808,
                         total_before=total_before, complete=True)
    assert n == 8_049_808
    assert len(_deletes(conn)) == 1
    assert "biodiversity_hotspots" in _deletes(conn)[0]


@pytest.mark.asyncio
async def test_ratio_guard_is_skipped_on_an_empty_table():
    """A first-ever sync has nothing to compare against and must not deadlock itself."""
    n, conn = await _run(seen=1_000, deleted=0, total_before=0, complete=True)
    assert n == 0                    # nothing was stale
    assert len(_deletes(conn)) == 1  # but the purge did run


@pytest.mark.asyncio
async def test_losing_the_advisory_lock_refuses_to_delete():
    """A dropped session releases the lock; another pass may then own `obis_seen`."""
    n, conn = await _run(seen=32_724_724, deleted=8_049_808, total_before=40_774_532,
                         complete=True, still_locked=0)
    assert n == 0
    assert _deletes(conn) == []


@pytest.mark.parametrize("stats, expected", [
    ({}, False),                                        # generator never reported
    ({"files_total": 7118, "files_ok": 7118}, True),    # the healthy case
    ({"files_total": 7118, "files_ok": 7117}, False),   # ONE missing file is enough
    ({"files_total": 7118, "files_ok": 0}, False),
    ({"files_total": 0, "files_ok": 0}, False),         # empty catalogue proves nothing
])
def test_coverage_requires_every_file(stats, expected):
    """Skipped batches only warn and the generator still ends normally — so
    finishing is not evidence of coverage, and an empty stats dict least of all."""
    assert _coverage_complete(stats) is expected


@pytest.mark.asyncio
async def test_boundary_exactly_at_the_ratio_purges():
    """Right at the threshold the pass is trusted — the guard is `<`, not `<=`."""
    total_before = 1_000_000
    n, conn = await _run(seen=int(total_before * _PURGE_MIN_STAMPED_RATIO), deleted=7,
                         total_before=total_before, complete=True)
    assert n == 7
    assert len(_deletes(conn)) == 1


# ── catalogue-truncation guard (a short S3 listing looks "complete") ──────────

import asyncio

from backend.ingestion.obis_sync import (
    _CATALOGUE_MIN_RATIO,
    _catalogue_short,
    _catalogue_hwm,
    _record_catalogue_hwm,
)


@pytest.mark.parametrize("files_total, hwm, expected", [
    (7118, None, False),   # first pass ever — no history, cannot compare
    (7118, 0, False),      # HWM row absent/zero — treated as no history
    (7118, 7118, False),   # steady state — same size
    (7500, 7118, False),   # OBIS legitimately grew
    (6407, 7118, False),   # just above the 0.9 boundary (7118*0.9=6406.2) — allowed
    (6406, 7118, True),    # just below the 0.9 boundary — caught
    (5196, 7118, True),    # reviewer's 27% loss — clears the 0.5 row-ratio, caught here
    (2135, 7118, True),    # reviewer's 70% loss
    (0, 7118, True),       # empty listing against real history
])
def test_catalogue_short_flags_a_truncated_listing(files_total, hwm, expected):
    assert _catalogue_short(files_total, hwm) is expected


def test_catalogue_short_boundary_is_exactly_the_ratio():
    hwm = 10_000
    assert _catalogue_short(int(hwm * _CATALOGUE_MIN_RATIO), hwm) is False   # == ratio: ok
    assert _catalogue_short(int(hwm * _CATALOGUE_MIN_RATIO) - 1, hwm) is True  # just under


class _HwmConn:
    """Fake conn backing the sync_log HWM row."""
    def __init__(self, stored=None):
        self.stored = stored
        self.executed = []

    async def fetchval(self, sql, *args):
        return self.stored

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        # emulate GREATEST(old, new)
        new = args[1]
        self.stored = new if self.stored is None else max(self.stored, new)


class _HwmPool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *_exc):
                return False

        return _Ctx()


def test_hwm_read_returns_none_when_absent():
    conn = _HwmConn(stored=None)
    assert asyncio.run(_catalogue_hwm(_HwmPool(conn))) is None


def test_hwm_record_never_lowers_the_mark():
    conn = _HwmConn(stored=7118)
    asyncio.run(_record_catalogue_hwm(_HwmPool(conn), 5000))  # a smaller pass
    assert conn.stored == 7118                                 # HWM held
    asyncio.run(_record_catalogue_hwm(_HwmPool(conn), 7500))   # genuine growth
    assert conn.stored == 7500                                 # HWM raised
