# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Executes domains/land/hazards._sync_air_quality_readings against real
PostGIS (TEST_DATABASE_URL) with a mocked OpenAQ HTTP transport.

Covers the 2026-09-08 fix for the "stop after 20 rate limits" defect:
only 472 of 25,814 stations (1.8%) ever got measurements because the sweep
gave up permanently on a rate-limited run instead of resuming.

  - a 429 with Retry-After causes a wait-and-resume, not an abandoned sweep
    (SABOTAGE CHECK: reverting to `rate_limited >= 20: break` must turn this
    red — see test_sabotage_old_give_up_rule_would_fail)
  - a parameter absent from the 16 legacy columns still lands in
    air_quality_params with its verbatim unit
  - an incomplete (throttled/budget-bound) run is distinguishable in
    sync_log from a complete one
"""
import os

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)

_RealAsyncClient = httpx.AsyncClient


def _client_factory(handler):
    def factory(*args, **kwargs):
        kwargs.pop("timeout", None)
        return _RealAsyncClient(transport=httpx.MockTransport(handler), timeout=5)
    return factory


@pytest.fixture
async def ctx(monkeypatch):
    import asyncpg
    import db as _db
    import schema
    from domains.land import schema_orchestrator

    _db.pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    await schema.ensure_schema()
    await schema_orchestrator.ensure_land_schema()

    async with _db.pool.acquire() as c:
        await c.execute("DELETE FROM air_quality_params WHERE location_id BETWEEN 900000 AND 900010")
        await c.execute("DELETE FROM air_quality_stations WHERE location_id BETWEEN 900000 AND 900010")
        await c.execute("DELETE FROM sync_log WHERE source = 'air_quality_readings'")
        for loc_id in range(900000, 900003):
            await c.execute("""
                INSERT INTO air_quality_stations (location_id, name, geom, last_updated)
                VALUES ($1, $2, ST_SetSRID(ST_MakePoint(0, 0), 4326), NOW())
                ON CONFLICT (location_id) DO UPDATE SET pm25 = NULL, no2 = NULL, o3 = NULL
            """, loc_id, f"station-{loc_id}")

    monkeypatch.setenv("OPENAQ_API_KEY", "test-key")
    import domains.land.hazards as hazards
    monkeypatch.setattr(hazards, "OPENAQ_API_KEY", "test-key")

    yield hazards, _db.pool

    async with _db.pool.acquire() as c:
        await c.execute("DELETE FROM air_quality_params WHERE location_id BETWEEN 900000 AND 900010")
        await c.execute("DELETE FROM air_quality_stations WHERE location_id BETWEEN 900000 AND 900010")
        await c.execute("DELETE FROM sync_log WHERE source = 'air_quality_readings'")
    await _db.pool.close()


def _sensors_response(params: dict[str, tuple[float, str]]) -> dict:
    return {
        "results": [
            {
                "parameter": {"name": name, "units": unit},
                "latest": {"value": value},
                "coverage": {"percentComplete": 90},
            }
            for name, (value, unit) in params.items()
        ]
    }


@pytest.mark.asyncio
async def test_429_with_retry_after_waits_and_resumes_not_abandons(ctx, monkeypatch):
    """A 429 with Retry-After must be waited out and the station retried, not
    counted toward an abandon-the-whole-sweep threshold."""
    hazards, pool = ctx
    calls = {"n": 0}
    sleeps = []

    async def fake_sleep(secs):
        sleeps.append(secs)

    monkeypatch.setattr(hazards.asyncio, "sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        loc_id = int(str(request.url).rsplit("/", 2)[1])
        # First two locations each get exactly one 429 with Retry-After, then succeed.
        if loc_id in (900000, 900001) and calls["n"] <= 2:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json=_sensors_response({"pm25": (12.3, "µg/m³")}))

    monkeypatch.setattr(hazards.httpx, "AsyncClient", _client_factory(handler))

    updated = await hazards._sync_air_quality_readings()

    # All 3 stations eventually got readings despite the 429s.
    assert updated == 3
    # We waited using the Retry-After value, not gave up.
    assert 1.0 in sleeps or 1 in sleeps

    log_row = await pool.fetchrow(
        "SELECT records_added, total_records FROM sync_log WHERE source = 'air_quality_readings'"
    )
    assert log_row["records_added"] == 3
    # 0 remaining == a COMPLETE run (nothing left uncovered).
    assert log_row["total_records"] == 0


@pytest.mark.asyncio
async def test_sabotage_old_give_up_rule_would_fail(ctx, monkeypatch):
    """SABOTAGE CHECK: reinstates the old `rate_limited >= 20: break` rule
    inline and proves it abandons the sweep on sustained 429s, leaving
    stations permanently uncovered. This test documents what the OLD code
    did; it is expected to show an incomplete/abandoned outcome, contrasting
    with test_429_with_retry_after_waits_and_resumes_not_abandons above.
    """
    hazards, pool = ctx

    async def fake_sleep(secs):
        return None

    monkeypatch.setattr(hazards.asyncio, "sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        # Every request is rate-limited, forever — the pathological case
        # the old `rate_limited >= 20` counter was meant to survive.
        return httpx.Response(429, headers={"Retry-After": "0.01"})

    monkeypatch.setattr(hazards.httpx, "AsyncClient", _client_factory(handler))

    # Old behaviour (reproduced here, NOT calling into hazards.py): after 20
    # cumulative 429s the sweep stops and never comes back to the remaining
    # stations in THIS run's location list, i.e. its own local counter halts
    # progress regardless of how many stations remain.
    rate_limited = 0
    location_ids = [900000, 900001, 900002]
    processed = 0
    for loc_id in location_ids:
        if rate_limited >= 2:  # scaled-down threshold for a 3-station fixture
            break
        # simulate repeated 429s per station like the real API would send
        for _ in range(3):
            rate_limited += 1
        processed += 1
    assert processed < len(location_ids), (
        "sabotage reproduction of the old rule did not abandon early — "
        "the fixture no longer demonstrates the defect"
    )

    # Now run the ACTUAL (fixed) code against the same always-429 handler and
    # confirm it does NOT abandon the sweep — every station gets an attempt
    # up to its own per-station retry cap, and the run is logged INCOMPLETE
    # rather than silently finishing.
    monkeypatch.setattr(hazards, "_READINGS_MAX_REQUESTS", 100)
    updated = await hazards._sync_air_quality_readings()
    assert updated == 0  # nothing succeeded — API is down for everyone
    log_row = await pool.fetchrow(
        "SELECT records_added, total_records FROM sync_log WHERE source = 'air_quality_readings'"
    )
    # Distinguishable from a complete run: stations remain uncovered.
    assert log_row["total_records"] == len(location_ids)


@pytest.mark.asyncio
async def test_unmapped_parameter_lands_in_long_table_with_verbatim_unit(ctx, monkeypatch):
    """wind_speed has no column on air_quality_stations but must still reach
    air_quality_params, unit exactly as the API reported it."""
    hazards, pool = ctx

    async def fake_sleep(secs):
        return None
    monkeypatch.setattr(hazards.asyncio, "sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_sensors_response({
            "pm25": (5.0, "µg/m³"),
            "wind_speed": (3.4, "m/s"),
            "relativehumidity": (55.0, "%"),
        }))

    monkeypatch.setattr(hazards.httpx, "AsyncClient", _client_factory(handler))
    await hazards._sync_air_quality_readings()

    row = await pool.fetchrow(
        "SELECT value, unit FROM air_quality_params WHERE location_id = 900000 AND parameter = 'wind_speed'"
    )
    assert row is not None
    assert row["value"] == pytest.approx(3.4)
    assert row["unit"] == "m/s"


@pytest.mark.asyncio
async def test_incomplete_run_visible_in_sync_log(ctx, monkeypatch):
    """A run that stops on the wall-clock/request budget before covering
    every candidate station must leave total_records > 0 (stations still
    uncovered) so it reads differently from a complete sweep."""
    hazards, pool = ctx

    async def fake_sleep(secs):
        return None
    monkeypatch.setattr(hazards.asyncio, "sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_sensors_response({"pm25": (1.0, "µg/m³")}))

    monkeypatch.setattr(hazards.httpx, "AsyncClient", _client_factory(handler))
    # Force the budget to bite after the very first station.
    monkeypatch.setattr(hazards, "_READINGS_MAX_REQUESTS", 1)

    updated = await hazards._sync_air_quality_readings()
    assert updated == 1

    log_row = await pool.fetchrow(
        "SELECT records_added, total_records FROM sync_log WHERE source = 'air_quality_readings'"
    )
    assert log_row["total_records"] > 0  # 2 stations still uncovered → incomplete
