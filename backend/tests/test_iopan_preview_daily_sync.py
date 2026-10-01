# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""The IO PAN preview-layer sync is due 24 h after sync_log.last_synced_at, not 24 h
after process start: the API restarts on every deploy, and the old in-memory sleep
made a "monthly" sync run on every restart."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import scheduling

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
DAY = 24 * 3600


class _Stop(Exception):
    pass


class _FakeConn:
    def __init__(self, last):
        self.last = last
        self.queries = []

    async def fetchval(self, sql, *args):
        self.queries.append(args)
        return self.last


class _FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False
        return _Ctx()


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


def _run_one_cycle(monkeypatch, last):
    """Run the task until its second sleep; return (sync calls, sleeps)."""
    conn = _FakeConn(last)
    monkeypatch.setattr(scheduling.db, "pool", _FakePool(conn), raising=False)
    monkeypatch.setattr(scheduling, "datetime", _FrozenDatetime)
    calls, sleeps = [], []

    async def fake_run(action, fn, label=None):
        calls.append(action)

    async def fake_sleep(s):
        sleeps.append(s)
        if len(sleeps) >= 2:
            raise _Stop

    monkeypatch.setattr(scheduling, "_run_unless_paused", fake_run)
    monkeypatch.setattr(scheduling.asyncio, "sleep", fake_sleep)
    with pytest.raises(_Stop):
        asyncio.run(scheduling._iopan_preview_daily_task("aoc2025-poc", object()))
    assert conn.queries == [("aoc2025-poc",)]
    return calls, sleeps


def test_synced_an_hour_ago_does_not_sync_and_sleeps_the_remainder(monkeypatch):
    calls, sleeps = _run_one_cycle(monkeypatch, NOW - timedelta(hours=1))
    assert calls == []
    assert sleeps == [scheduling._IOPAN_PREVIEW_STARTUP_DELAY_S, 23 * 3600]


def test_synced_over_a_day_ago_syncs_then_sleeps_a_day(monkeypatch):
    calls, sleeps = _run_one_cycle(monkeypatch, NOW - timedelta(hours=25))
    assert calls == ["aoc2025-poc"]
    assert sleeps == [scheduling._IOPAN_PREVIEW_STARTUP_DELAY_S, DAY]


def test_never_synced_syncs(monkeypatch):
    calls, _ = _run_one_cycle(monkeypatch, None)
    assert calls == ["aoc2025-poc"]


def test_interval_is_one_day():
    assert scheduling._IOPAN_PREVIEW_INTERVAL_S == DAY
