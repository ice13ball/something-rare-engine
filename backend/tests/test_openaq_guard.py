# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""Executes openaq_guard and both OpenAQ call sites against a fake HTTP transport.

Context: OpenAQ banned this project's key on 2026-09-27 without ever sending a
429 (~4,000 requests/day). The key is now SHARED with downWindGlobal, so these
limits are ours, enforced before the request goes out:

  - pacing interval respected (injected clock + sleep, nothing really sleeps)
  - the header brake STOPS the run (never sleeps) at <= 30 requests left
  - 429 -> stop, not retried; 401/403 -> stop with the key reason
  - the daily budget stops at N, records the reason, and survives a "restart"
  - the readings drip is due 6 h after the last run, measured from sync_log

DB-backed tests need TEST_DATABASE_URL and roll back; nothing is deleted.
"""
import asyncio
import os
from datetime import date, datetime, timedelta, timezone

import asyncpg
import httpx
import pytest

import db
import openaq_guard
from openaq_guard import (
    DailyBudget, OpenAQBudgetExhausted, OpenAQHeadroomLow, OpenAQKeyRejected,
    OpenAQRateLimited, OpenAQStop, RateLimitPacer, guarded_get,
)

needs_db = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")

_REAL_CLIENT = httpx.AsyncClient


class _NoBudget:
    """Stand-in budget for the DB-free tests."""
    def __init__(self):
        self.taken = 0

    async def take(self):
        self.taken += 1


def _client(handler):
    return _REAL_CLIENT(transport=httpx.MockTransport(handler), timeout=5)


class _FakeTime:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def clock(self):
        return self.now

    async def sleep(self, s):
        self.sleeps.append(s)
        self.now += s


# ── pacing ───────────────────────────────────────────────────────────────────

def test_shipped_pacing_is_well_below_downwinds():
    # downWindGlobal runs 3.0 s (20/min); we share its key, so we are slower.
    assert openaq_guard.DEFAULT_MIN_INTERVAL_S >= 12.0
    assert openaq_guard.MIN_ALLOWED_INTERVAL_S >= 10.0
    assert openaq_guard.HEADROOM_STOP_REMAINING > 20   # stops before downwind brakes
    assert openaq_guard.DEFAULT_DAILY_BUDGET == 1000


def test_interval_env_override_is_clamped(monkeypatch):
    monkeypatch.setenv("OPENAQ_MIN_INTERVAL_S", "0.1")
    assert RateLimitPacer().min_interval_s == openaq_guard.MIN_ALLOWED_INTERVAL_S
    monkeypatch.setenv("OPENAQ_MIN_INTERVAL_S", "garbage")
    assert RateLimitPacer().min_interval_s == openaq_guard.DEFAULT_MIN_INTERVAL_S


@pytest.mark.asyncio
async def test_requests_start_at_least_min_interval_apart():
    t = _FakeTime()
    pacer = RateLimitPacer(min_interval_s=12.0, clock=t.clock, sleep=t.sleep)
    starts = []

    def handler(request):
        starts.append(t.now)
        return httpx.Response(200, json={})

    async with _client(handler) as c:
        for _ in range(4):
            await guarded_get(c, "https://x/y", pacer=pacer, budget=_NoBudget())
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    assert len(starts) == 4 and all(g >= 12.0 for g in gaps), gaps
    assert t.sleeps == [12.0, 12.0, 12.0]   # first request never waits


@pytest.mark.asyncio
async def test_one_pacer_spans_both_call_sites():
    t = _FakeTime()
    pacer = RateLimitPacer(min_interval_s=12.0, clock=t.clock, sleep=t.sleep)
    async with _client(lambda r: httpx.Response(200, json={})) as c:
        await guarded_get(c, "https://x/locations", pacer=pacer, budget=_NoBudget())
        await guarded_get(c, "https://x/locations/1/sensors", pacer=pacer, budget=_NoBudget())
    assert t.sleeps == [12.0]
    assert openaq_guard.process_pacer() is openaq_guard.process_pacer()


# ── header brake: stop, never sleep ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_low_remaining_header_stops_the_next_request_without_sleeping():
    t = _FakeTime()
    pacer = RateLimitPacer(min_interval_s=12.0, clock=t.clock, sleep=t.sleep)
    calls = []

    def handler(request):
        calls.append(1)
        left = "30" if len(calls) == 1 else "55"
        return httpx.Response(200, json={}, headers={
            "x-ratelimit-remaining": left, "x-ratelimit-reset": "40"})

    async with _client(handler) as c:
        await guarded_get(c, "https://x/a", pacer=pacer, budget=_NoBudget())   # 30 left
        with pytest.raises(OpenAQHeadroomLow) as e:
            await guarded_get(c, "https://x/b", pacer=pacer, budget=_NoBudget())
        assert "30" in e.value.reason and "downWindGlobal" in e.value.reason
        assert len(calls) == 1, "a request was sent while yielding"
        assert t.sleeps == [], "the brake must yield, not sleep-and-hog"
        # window passed (reset 40 s + 1) -> allowed again
        t.now += 42
        await guarded_get(c, "https://x/c", pacer=pacer, budget=_NoBudget())
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_headroom_above_threshold_and_missing_headers_do_not_stop():
    pacer = RateLimitPacer(min_interval_s=0.0)
    seen = iter([{"x-ratelimit-remaining": "31", "x-ratelimit-reset": "5"},
                 {}, {"x-ratelimit-remaining": "abc"}])
    async with _client(lambda r: httpx.Response(200, json={}, headers=next(seen))) as c:
        for _ in range(3):
            await guarded_get(c, "https://x/a", pacer=pacer, budget=_NoBudget())
    assert pacer.min_remaining_seen == 31


@pytest.mark.asyncio
async def test_yield_is_capped_when_reset_header_is_absurd():
    t = _FakeTime()
    pacer = RateLimitPacer(min_interval_s=0.0, clock=t.clock, sleep=t.sleep)
    hdr = {"x-ratelimit-remaining": "1", "x-ratelimit-reset": "99999"}
    async with _client(lambda r: httpx.Response(200, json={}, headers=hdr)) as c:
        await guarded_get(c, "https://x/a", pacer=pacer, budget=_NoBudget())
        t.now += openaq_guard.MAX_YIELD_S + 1
        await guarded_get(c, "https://x/b", pacer=pacer, budget=_NoBudget())


# ── 429 / 401 / 403: stop, never retry ───────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("code,exc,text", [
    (429, OpenAQRateLimited, "429"),
    (401, OpenAQKeyRejected, "OpenAQ rejected the API key (401) — key invalid or banned"),
    (403, OpenAQKeyRejected, "OpenAQ rejected the API key (403) — key invalid or banned"),
])
async def test_ban_and_rate_limit_codes_stop_without_retry(code, exc, text):
    t = _FakeTime()
    pacer = RateLimitPacer(min_interval_s=12.0, clock=t.clock, sleep=t.sleep)
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(code, headers={"Retry-After": "1"})

    async with _client(handler) as c:
        with pytest.raises(exc) as e:
            await guarded_get(c, "https://x/a", pacer=pacer, budget=_NoBudget())
    assert text in e.value.reason
    assert len(calls) == 1 and t.sleeps == []


@pytest.mark.asyncio
async def test_5xx_is_returned_to_the_caller_not_raised():
    pacer = RateLimitPacer(min_interval_s=0.0)
    async with _client(lambda r: httpx.Response(500)) as c:
        r = await guarded_get(c, "https://x/a", pacer=pacer, budget=_NoBudget())
    assert r.status_code == 500


# ── daily budget (Postgres) ──────────────────────────────────────────────────

class _Acquire:
    def __init__(self, c): self._c = c
    async def __aenter__(self): return self._c
    async def __aexit__(self, *a): return False


class _Pool:
    def __init__(self, c): self._c = c
    def acquire(self): return _Acquire(self._c)


@pytest.fixture
async def rolled_back_pool(monkeypatch):
    import schema
    real = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"], min_size=1, max_size=2)
    previous = db.pool
    db.pool = real
    await schema.ensure_schema()
    conn = await real.acquire()
    tx = conn.transaction()
    await tx.start()
    db.pool = _Pool(conn)
    try:
        yield conn
    finally:
        db.pool = previous
        await tx.rollback()
        await real.release(conn)
        await real.close()


@needs_db
@pytest.mark.asyncio
async def test_daily_budget_stops_at_n_and_names_the_reason(rolled_back_pool, monkeypatch):
    monkeypatch.setenv("OPENAQ_DAILY_BUDGET", "3")
    budget = DailyBudget(today=lambda: date(2099, 1, 1))
    assert [await budget.take() for _ in range(3)] == [1, 2, 3]
    with pytest.raises(OpenAQBudgetExhausted) as e:
        await budget.take()
    assert e.value.reason == "OpenAQ daily budget 3 reached"
    stored = await rolled_back_pool.fetchval(
        "SELECT requests FROM openaq_request_budget WHERE utc_day = '2099-01-01'")
    assert stored == 3, "the refused request must not be counted"


@needs_db
@pytest.mark.asyncio
async def test_daily_budget_survives_a_restart_and_resets_on_a_new_utc_day(rolled_back_pool, monkeypatch):
    monkeypatch.setenv("OPENAQ_DAILY_BUDGET", "2")
    day = {"d": date(2099, 2, 1)}
    await DailyBudget(today=lambda: day["d"]).take()
    await DailyBudget(today=lambda: day["d"]).take()
    # "restart": brand-new objects, nothing carried in memory
    monkeypatch.setattr(openaq_guard, "_process_pacer", None)
    with pytest.raises(OpenAQBudgetExhausted):
        await DailyBudget(today=lambda: day["d"]).take()
    day["d"] = date(2099, 2, 2)
    assert await DailyBudget(today=lambda: day["d"]).take() == 1


@needs_db
@pytest.mark.asyncio
async def test_budget_default_and_env_override(rolled_back_pool, monkeypatch):
    monkeypatch.delenv("OPENAQ_DAILY_BUDGET", raising=False)
    assert openaq_guard.daily_budget_limit() == 1000
    monkeypatch.setenv("OPENAQ_DAILY_BUDGET", "0")
    with pytest.raises(OpenAQBudgetExhausted):
        await DailyBudget(today=lambda: date(2099, 3, 1)).take()
    monkeypatch.setenv("OPENAQ_DAILY_BUDGET", "nonsense")
    assert openaq_guard.daily_budget_limit() == 1000


# ── the station sync (land-air-quality) stops and says why ───────────────────

@pytest.fixture
async def land_ctx(rolled_back_pool, monkeypatch):
    import domains.land.hazards as hazards
    monkeypatch.setattr(hazards, "OPENAQ_API_KEY", "test-key")
    await rolled_back_pool.execute(
        "DELETE FROM sync_log WHERE source = 'air_quality'")   # rolled back
    yield hazards, rolled_back_pool


def _loc(i):
    return {"id": i, "name": f"n{i}", "coordinates": {"latitude": 1.0, "longitude": 2.0}}


@needs_db
@pytest.mark.asyncio
async def test_station_sync_budget_stop_is_recorded_not_silent(land_ctx, monkeypatch):
    hazards, conn = land_ctx
    monkeypatch.setenv("OPENAQ_DAILY_BUDGET", "1")
    monkeypatch.setattr(openaq_guard, "_process_pacer", RateLimitPacer(min_interval_s=0.0))
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"results": [_loc(990001)]})

    real = httpx.AsyncClient
    monkeypatch.setattr(hazards.httpx, "AsyncClient",
                        lambda *a, **k: real(transport=httpx.MockTransport(handler), timeout=5))
    # pin "today" so an existing real row for today cannot mask the test
    monkeypatch.setattr(openaq_guard.DailyBudget, "__init__",
                        lambda self, today=None: setattr(self, "_today", lambda: date(2099, 4, 1)))

    assert await hazards._sync_air_quality(force=True) == 0
    assert len(calls) == 1
    row = await conn.fetchrow(
        "SELECT skipped_reason, last_synced_at FROM sync_log WHERE source = 'air_quality'")
    assert row["skipped_reason"] == "OpenAQ daily budget 1 reached"
    assert row["last_synced_at"] is None
    assert await conn.fetchval(
        "SELECT count(*) FROM air_quality_stations WHERE location_id = 990001") == 0


@needs_db
@pytest.mark.asyncio
@pytest.mark.parametrize("code,needle", [(401, "key invalid or banned"), (429, "429")])
async def test_station_sync_ban_codes_stop_at_once(land_ctx, monkeypatch, code, needle):
    hazards, conn = land_ctx
    monkeypatch.setattr(openaq_guard, "_process_pacer", RateLimitPacer(min_interval_s=0.0))
    monkeypatch.setattr(openaq_guard.DailyBudget, "__init__",
                        lambda self, today=None: setattr(self, "_today", lambda: date(2099, 4, 2)))
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(code)

    real = httpx.AsyncClient
    monkeypatch.setattr(hazards.httpx, "AsyncClient",
                        lambda *a, **k: real(transport=httpx.MockTransport(handler), timeout=5))
    assert await hazards._sync_air_quality(force=True) == 0
    assert len(calls) == 1
    reason = await conn.fetchval(
        "SELECT skipped_reason FROM sync_log WHERE source = 'air_quality'")
    assert needle in reason


@needs_db
@pytest.mark.asyncio
async def test_missing_key_behaviour_is_unchanged(land_ctx, monkeypatch):
    hazards, conn = land_ctx
    monkeypatch.setattr(hazards, "OPENAQ_API_KEY", "")
    called = []
    monkeypatch.setattr(openaq_guard, "guarded_get", lambda *a, **k: called.append(1))
    assert await hazards._sync_air_quality(force=True) == 0
    assert await hazards._sync_air_quality_readings() == 0
    assert called == []


# ── cadence ──────────────────────────────────────────────────────────────────

def test_readings_cadence_is_six_hours():
    import scheduling
    assert scheduling.AIR_QUALITY_READINGS_INTERVAL_SECONDS == 6 * 3600


class _CadencePool:
    def __init__(self, last): self.last = last
    def acquire(self): return self
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def fetchval(self, *a): return self.last


async def _run_task_once(monkeypatch, last):
    import scheduling
    ran, waits = [], []

    async def fake_run(action, fn, label=None):
        ran.append(label)
        return True

    class _Stop(Exception):
        pass

    async def fake_sleep(s):
        if s == 900:          # the startup delay
            return
        waits.append(s)
        raise _Stop           # first loop-end sleep: one iteration is enough

    monkeypatch.setattr(db, "pool", _CadencePool(last))
    monkeypatch.setattr(scheduling, "_run_unless_paused", fake_run)
    monkeypatch.setattr(scheduling.asyncio, "sleep", fake_sleep)

    async def go():
        try:
            await scheduling._air_quality_readings_task()
        except _Stop:
            pass

    await go()
    return ran, waits


@pytest.mark.asyncio
async def test_restart_shortly_after_a_run_does_not_retrigger_the_drip(monkeypatch):
    last = datetime.now(timezone.utc) - timedelta(minutes=10)
    ran, waits = await _run_task_once(monkeypatch, last)
    assert ran == []
    assert 5.5 * 3600 < waits[0] <= 6 * 3600 - 9 * 60


@pytest.mark.asyncio
async def test_drip_runs_when_six_hours_have_passed_or_never_ran(monkeypatch):
    ran, waits = await _run_task_once(monkeypatch, datetime.now(timezone.utc) - timedelta(hours=6, minutes=1))
    assert ran == ["air_quality_readings_6h"] and waits[0] == 6 * 3600
    ran, _ = await _run_task_once(monkeypatch, None)
    assert ran == ["air_quality_readings_6h"]
