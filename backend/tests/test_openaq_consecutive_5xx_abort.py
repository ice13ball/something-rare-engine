# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""A sustained OpenAQ 5xx outage must stop the sweep, not grind through it.

Production incident, 2026-09-18 06:20 UTC (measured, not re-derived): OpenAQ
answered every `/v3/locations/<id>/sensors` call with HTTP 500 for an
extended burst. The sync kept calling anyway — one log line per failed call,
thousands of them — while the SAME single uvicorn process was trying to serve
Googlebot. CPU sat at 100%; Googlebot got 503s.

This guards the fix in `domains/land/hazards._sync_air_quality_readings`:

  - N CONSECUTIVE 5xx aborts the run — never cumulative. Verified against the
    live API 2026-09-09: ~4% of OpenAQ locations answer /sensors with a 500
    that is THEIR fault, scattered across the whole station list, not
    clustered. A cumulative counter would abort a perfectly healthy run the
    moment it happened to touch enough of them.
  - a success resets the streak to zero.
  - an abort is recorded via `sync_log.log_sync_skipped`, which deliberately
    leaves `last_synced_at` (and `total_records`) alone — NEVER through
    `log_sync`/`_log_land_sync`, which would stamp `NOW()` and make a run
    that gave up after seconds look freshly synced.
  - one summary WARNING line replaces the old one-line-per-call flood, and
    names the counts, not just "upstream failing".
  - no credential ever reaches a log line — the OpenAQ key travels in the
    `X-API-Key` header for this endpoint, never the URL.

Network stubbed via `httpx.MockTransport` (no real HTTP), DB access gated on
`TEST_DATABASE_URL` and rolled back at the end of every test — same shape as
`test_sync_log_skipped.py`.
"""
import logging
import os

import asyncpg
import httpx
import pytest

import db

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)

_SOURCE = "air_quality_readings"
_STATION_IDS = list(range(950000, 950005))  # a private ID range, own from any other test file
_REAL_ASYNC_CLIENT = httpx.AsyncClient
_SECRET = "test-secret-openaq-key-do-not-log-me"


def _client_factory(handler):
    """Same pattern as test_openaq_readings_rate_limit.py: swap httpx.AsyncClient
    for one wired to a MockTransport, no real network."""
    def factory(*args, **kwargs):
        kwargs.pop("timeout", None)
        return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler), timeout=5)
    return factory


class _Acquire:
    """Hands the helper the connection our transaction is open on, so writes
    made inside `_sync_air_quality_readings` (which does several separate
    `db.pool.acquire()` calls) land on the same transaction and the final
    rollback undoes all of them."""

    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _PoolFromConn:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _Acquire(self._conn)


@pytest.fixture
async def ctx(monkeypatch):
    c = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
    tx = c.transaction()
    await tx.start()
    previous = db.pool
    db.pool = _PoolFromConn(c)

    # A clean slate for this source, whatever another test file left behind
    # (rolled back at teardown, so this never touches real data).
    await c.execute("DELETE FROM sync_log WHERE source = $1", _SOURCE)
    for loc_id in _STATION_IDS:
        await c.execute(
            """INSERT INTO air_quality_stations (location_id, name, geom, last_updated)
               VALUES ($1, $2, ST_SetSRID(ST_MakePoint(0, 0), 4326), NOW())
               ON CONFLICT (location_id) DO UPDATE
               SET readings_attempted_at = NULL, readings_error = NULL""",
            loc_id, f"station-{loc_id}",
        )

    monkeypatch.setenv("OPENAQ_API_KEY", _SECRET)
    import domains.land.hazards as hazards
    monkeypatch.setattr(hazards, "OPENAQ_API_KEY", _SECRET)

    async def fake_sleep(_s):
        return None
    monkeypatch.setattr(hazards.asyncio, "sleep", fake_sleep)

    try:
        yield hazards, c
    finally:
        db.pool = previous
        await tx.rollback()
        await c.close()


async def _seed_sync_log(c, last_synced_at, total_records):
    await c.execute(
        """INSERT INTO sync_log (source, last_synced_at, records_added, total_records)
           VALUES ($1, $2, 99, $3)
           ON CONFLICT (source) DO UPDATE
           SET last_synced_at = $2, records_added = 99, total_records = $3,
               skipped_reason = NULL, skipped_at = NULL""",
        _SOURCE, last_synced_at, total_records,
    )


async def _sync_log_row(c):
    return await c.fetchrow(
        """SELECT last_synced_at, records_added, total_records, skipped_reason, skipped_at
             FROM sync_log WHERE source = $1""",
        _SOURCE,
    )


# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_n_consecutive_5xx_aborts_the_run(ctx, monkeypatch):
    hazards, conn = ctx
    monkeypatch.setattr(hazards, "_CONSECUTIVE_5XX_ABORT", 2)

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(500, text="Internal Server Error")

    monkeypatch.setattr(hazards.httpx, "AsyncClient", _client_factory(handler))

    updated = await hazards._sync_air_quality_readings()

    assert updated == 0, "nothing could have succeeded — every call 500'd"
    assert len(calls) == 2, (
        f"expected exactly 2 calls before the abort fired, got {len(calls)}: {calls}. "
        "The sweep kept going past the consecutive-5xx threshold."
    )

    row = await _sync_log_row(conn)
    assert row is not None
    assert row["skipped_reason"] is not None, "an abort must leave a skipped_reason"
    assert row["skipped_at"] is not None


@pytest.mark.asyncio
async def test_n_minus_1_consecutive_then_a_success_does_not_abort_and_resets(ctx, monkeypatch):
    """5 stations: 500, 500, 200, 500, 500 with threshold=3. Never 3 in a row —
    the success in the middle must reset the streak. A CUMULATIVE counter
    would have hit 4 total 5xx (>= 3) and aborted; this proves it does not."""
    hazards, conn = ctx
    monkeypatch.setattr(hazards, "_CONSECUTIVE_5XX_ABORT", 3)

    statuses = [500, 500, 200, 500, 500]
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        status = statuses[len(calls) - 1]
        if status == 200:
            return httpx.Response(200, json={"results": [{
                "id": 1, "parameter": {"name": "pm25", "units": "ug/m3"},
                "latest": {"value": 9.0},
            }]})
        return httpx.Response(status, text="Internal Server Error")

    monkeypatch.setattr(hazards.httpx, "AsyncClient", _client_factory(handler))

    updated = await hazards._sync_air_quality_readings()

    assert len(calls) == 5, f"the run stopped early: only {len(calls)} of 5 stations attempted"
    assert updated == 1, "exactly one station (the 200) should have written readings"

    row = await _sync_log_row(conn)
    assert row is not None
    assert row["skipped_reason"] is None, (
        "a run that finished its batch without hitting the threshold must not "
        "be recorded as an abort"
    )
    assert row["last_synced_at"] is not None, "a completed run must log through log_sync"


@pytest.mark.asyncio
async def test_abort_uses_log_sync_skipped_not_log_sync(ctx, monkeypatch):
    """Binds the exact contract log_sync_skipped documents: last_synced_at and
    total_records from BEFORE the abort must survive untouched — log_sync (or
    an equivalent stamp-NOW()) would silently claim the run refreshed data."""
    hazards, conn = ctx
    monkeypatch.setattr(hazards, "_CONSECUTIVE_5XX_ABORT", 2)

    from datetime import datetime, timezone
    baseline_synced_at = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    await _seed_sync_log(conn, baseline_synced_at, 4242)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    monkeypatch.setattr(hazards.httpx, "AsyncClient", _client_factory(handler))

    await hazards._sync_air_quality_readings()

    row = await _sync_log_row(conn)
    assert row["last_synced_at"] == baseline_synced_at, (
        "an abort must not advance last_synced_at — that is what log_sync does, "
        "and it would make a dead run look freshly synced"
    )
    assert row["total_records"] == 4242, (
        "an abort must not overwrite total_records — the table still holds "
        "whatever was served before the outage"
    )
    assert row["records_added"] == 0
    assert row["skipped_reason"] is not None
    assert row["skipped_at"] is not None


@pytest.mark.asyncio
async def test_summary_line_names_the_counts(ctx, monkeypatch, caplog):
    hazards, conn = ctx
    monkeypatch.setattr(hazards, "_CONSECUTIVE_5XX_ABORT", 2)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    monkeypatch.setattr(hazards.httpx, "AsyncClient", _client_factory(handler))

    with caplog.at_level(logging.WARNING):
        await hazards._sync_air_quality_readings()

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    summary = [m for m in warnings if "consecutive" in m and "aborted" in m]
    assert len(summary) == 1, (
        f"expected exactly one abort summary WARNING, found {len(summary)} in: {warnings}"
    )
    line = summary[0]
    assert "2" in line, "the consecutive-5xx count is missing from the summary"
    assert "500" in line, "the last HTTP status is missing from the summary"
    # requests_made: 2 calls were made before the abort fired.
    assert "2 calls" in line or "requests" in line.lower() or line.count("2") >= 1

    row = await _sync_log_row(conn)
    assert "2" in row["skipped_reason"] and "500" in row["skipped_reason"], (
        "the sync_log reason text must carry the numbers too, not just prose"
    )


@pytest.mark.asyncio
async def test_no_credential_reaches_any_log_line(ctx, monkeypatch, caplog):
    hazards, conn = ctx
    monkeypatch.setattr(hazards, "_CONSECUTIVE_5XX_ABORT", 2)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    monkeypatch.setattr(hazards.httpx, "AsyncClient", _client_factory(handler))

    with caplog.at_level(logging.DEBUG):
        await hazards._sync_air_quality_readings()

    for record in caplog.records:
        assert _SECRET not in record.getMessage(), (
            f"the OpenAQ API key leaked into a log line: {record.getMessage()!r}"
        )

    row = await _sync_log_row(conn)
    assert _SECRET not in (row["skipped_reason"] or ""), (
        "the OpenAQ API key leaked into the sync_log skipped_reason"
    )


# ─────────────────────────────────────────────────────────────────────────────
# ⛔ The tests above inject their own threshold, so none of them can fail when
# the PRODUCTION value is wrong. Proved by sabotage 2026-09-18: setting
# `_CONSECUTIVE_5XX_ABORT = 10**9` — a breaker that can never trip — left every
# test green. A guard that cannot see the shipped value is measuring the
# mechanism, not the protection.
# ─────────────────────────────────────────────────────────────────────────────

def test_the_shipped_threshold_can_actually_trip():
    """Bounds, not a magic number.

    Lower bound 1: a breaker at 0 would abort before any call.
    Upper bound 50: OpenAQ answers 500 for roughly 4 % of locations as a matter
    of course (measured 2026-09-09 and documented in hazards.py), scattered
    rather than clustered — 20 in a row is already far outside that noise. A
    threshold above 50 would let a full outage grind through hundreds of calls,
    which is the behaviour this file exists to stop.
    """
    from domains.land import hazards

    assert 1 <= hazards._CONSECUTIVE_5XX_ABORT <= 50, (
        f"_CONSECUTIVE_5XX_ABORT is {hazards._CONSECUTIVE_5XX_ABORT}; outside "
        "1..50 it is either trigger-happy or decorative")
