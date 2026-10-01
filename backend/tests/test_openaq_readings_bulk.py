# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Executes domains/land/hazards._sync_air_quality_readings (bulk
/v3/parameters/{id}/latest) against real PostGIS (TEST_DATABASE_URL) with a
fake OpenAQ transport. Replaces the per-station tests: one request per station
made a full refresh of 26,078 stations take ~160 days at the shared-key rate.
"""
import os
from datetime import datetime, timezone

import asyncpg
import httpx
import pytest

import db
import openaq_guard

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")

_REAL = httpx.AsyncClient
A, B, C = 950001, 950002, 950003  # private location-id range

# name -> ids, as GET /v3/parameters would list them (o3 has two units).
CATALOGUE = {"results": [
    {"id": 2, "name": "pm25", "units": "µg/m³"},
    {"id": 3, "name": "o3", "units": "µg/m³"},
    {"id": 10, "name": "o3", "units": "ppm"},
    {"id": 999, "name": "wind_speed", "units": "m/s"},   # not ours: never fetched
]}


def _row(loc, sensor, value, utc="2026-09-30T10:00:00Z"):
    return {"locationsId": loc, "sensorsId": sensor, "value": value,
            "datetime": {"utc": utc, "local": utc}}


class Fake:
    """Routes by path; records every request path+page."""
    def __init__(self, latest=None, catalogue=CATALOGUE, status=None):
        self.latest = latest or {}      # id -> list of page dicts
        self.catalogue = catalogue
        self.status = status or {}      # path -> forced status
        self.calls = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        page = int(request.url.params.get("page", 1))
        self.calls.append((path, page))
        if path in self.status:
            return httpx.Response(self.status[path], json={})
        if path == "/v3/parameters":
            return httpx.Response(200, json=self.catalogue)
        pid = int(path.split("/")[3])
        pages = self.latest.get(pid, [])
        body = pages[page - 1] if page <= len(pages) else {"results": []}
        return httpx.Response(200, json=body)


@pytest.fixture
async def ctx(monkeypatch):
    import schema
    from domains.land import schema_orchestrator
    real = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"], min_size=1, max_size=2)
    previous = db.pool
    db.pool = real
    await schema.ensure_schema()
    await schema_orchestrator.ensure_land_schema()
    conn = await real.acquire()
    tx = conn.transaction()
    await tx.start()

    class _Acq:
        async def __aenter__(self): return conn
        async def __aexit__(self, *a): return False

    class _Pool:
        def acquire(self): return _Acq()
    db.pool = _Pool()

    await conn.execute("DELETE FROM sync_log WHERE source = 'air_quality_readings'")
    for loc in (A, B, C):
        await conn.execute(
            "INSERT INTO air_quality_stations (location_id, name, geom) "
            "VALUES ($1, $2, ST_SetSRID(ST_MakePoint(0, 0), 4326)) "
            "ON CONFLICT (location_id) DO UPDATE SET pm25 = NULL, o3 = NULL, "
            "readings_attempted_at = NULL", loc, f"s{loc}")
        await conn.execute("DELETE FROM air_quality_params WHERE location_id = $1", loc)

    import domains.land.hazards as hazards
    monkeypatch.setattr(hazards, "OPENAQ_API_KEY", "test-key")
    monkeypatch.setenv("OPENAQ_DAILY_BUDGET", "1000")
    monkeypatch.setattr(openaq_guard, "_process_pacer",
                        openaq_guard.RateLimitPacer(min_interval_s=0.0))

    def install(fake):
        monkeypatch.setattr(hazards.httpx, "AsyncClient", lambda *a, **k: _REAL(
            transport=httpx.MockTransport(fake), timeout=5))
    try:
        yield hazards, conn, install
    finally:
        db.pool = previous
        await tx.rollback()
        await real.release(conn)
        await real.close()


async def _params(conn, loc):
    return {(r["sensor_id"], r["parameter"]): r for r in await conn.fetch(
        "SELECT * FROM air_quality_params WHERE location_id = $1", loc)}


async def _log(conn):
    return await conn.fetchrow(
        "SELECT skipped_reason, last_synced_at FROM sync_log WHERE source = 'air_quality_readings'")


@pytest.mark.asyncio
async def test_two_locations_sharing_a_parameter_each_get_their_own_value(ctx):
    """Key is location + sensor + parameter: a wrong key would write A's
    reading to B. Also proves the unit comes from the catalogue per id."""
    hazards, conn, install = ctx
    fake = Fake(latest={
        2: [{"results": [_row(A, 11, 5.0), _row(B, 22, 9.0), _row(C, 33, 7.5)]}],
        3: [{"results": [_row(A, 12, 80.0)]}],
        10: [{"results": [_row(B, 23, 0.04)]}],
    })
    install(fake)
    assert await hazards._sync_air_quality_readings() == 3

    assert (await _params(conn, A))[(11, "pm25")]["value"] == 5.0
    assert (await _params(conn, B))[(22, "pm25")]["value"] == 9.0
    assert (await _params(conn, C))[(33, "pm25")]["value"] == 7.5
    assert (await _params(conn, A))[(12, "o3")]["unit"] == "µg/m³"
    assert (await _params(conn, B))[(23, "o3")]["unit"] == "ppm"   # never assumed
    cols = {r["location_id"]: r for r in await conn.fetch(
        "SELECT location_id, pm25, o3 FROM air_quality_stations WHERE location_id = ANY($1)", [A, B, C])}
    assert (cols[A]["pm25"], cols[B]["pm25"], cols[C]["pm25"]) == (5.0, 9.0, 7.5)
    assert cols[A]["o3"] == 80.0 and cols[B]["o3"] == 0.04 and cols[C]["o3"] is None
    assert all(p != "/v3/parameters/999/latest" for p, _ in fake.calls), "fetched a parameter we do not store"
    assert (await conn.fetchval(
        "SELECT count(*) FROM air_quality_stations WHERE location_id = ANY($1) "
        "AND readings_attempted_at IS NOT NULL", [A, B, C])) == 3
    row = await _log(conn)
    assert row["skipped_reason"] is None and row["last_synced_at"] is not None


@pytest.mark.asyncio
async def test_pagination_stops_on_short_page_and_on_exact_found(ctx, monkeypatch):
    hazards, conn, install = ctx
    monkeypatch.setattr(hazards, "_READINGS_PAGE_LIMIT", 2)
    cat = {"results": [{"id": 2, "name": "pm25", "units": "µg/m³"}]}
    fake = Fake(catalogue=cat, latest={2: [
        {"results": [_row(A, 1, 1.0), _row(B, 2, 2.0)], "meta": {"found": 3}},
        {"results": [_row(C, 3, 3.0)], "meta": {"found": 3}},
    ]})
    install(fake)
    await hazards._sync_air_quality_readings()
    assert fake.calls == [("/v3/parameters", 1), ("/v3/parameters/2/latest", 1),
                          ("/v3/parameters/2/latest", 2)]   # short page ends it

    # full page whose meta.found says that was everything: no page 2
    fake = Fake(catalogue=cat, latest={2: [
        {"results": [_row(A, 1, 1.0), _row(B, 2, 2.0)], "meta": {"found": 2}}]})
    install(fake)
    await hazards._sync_air_quality_readings()
    assert fake.calls[-1] == ("/v3/parameters/2/latest", 1) and len(fake.calls) == 2


@pytest.mark.asyncio
async def test_old_reading_keeps_its_own_datetime_and_newest_sensor_wins(ctx):
    hazards, conn, install = ctx
    fake = Fake(latest={2: [{"results": [
        _row(A, 11, 40.0, "2019-03-01T00:00:00Z"),           # dead sensor, years old
        _row(A, 12, 6.0, "2026-09-30T09:00:00Z"),            # live sensor
        _row(B, 21, -9999, "2026-09-30T09:00:00Z"),          # fill value, newest
        _row(B, 22, 4.0, "2026-09-29T09:00:00Z"),            # valid, older
        _row(123456789, 1, 1.0),                             # not our station
    ]}]})
    install(fake)
    await hazards._sync_air_quality_readings()

    old = (await _params(conn, A))[(11, "pm25")]
    assert old["datetime_last"] == datetime(2019, 3, 1, tzinfo=timezone.utc), "stamped as fresh"
    assert await conn.fetchval("SELECT pm25 FROM air_quality_stations WHERE location_id=$1", A) == 6.0
    assert await conn.fetchval("SELECT pm25 FROM air_quality_stations WHERE location_id=$1", B) == 4.0, \
        "a fill value blanked / beat a valid reading"
    assert await conn.fetchval("SELECT count(*) FROM air_quality_params WHERE location_id=123456789") == 0


@pytest.mark.asyncio
async def test_upsert_keeps_the_sensor_aggregates_it_cannot_see(ctx):
    hazards, conn, install = ctx
    await conn.execute(
        "INSERT INTO air_quality_params (location_id, sensor_id, parameter, value, unit, "
        "datetime_first, coverage_pct, value_max) VALUES ($1, 11, 'pm25', 1, 'x', "
        "'2020-01-01', 88, 99)", A)
    install(Fake(latest={2: [{"results": [_row(A, 11, 5.0)]}]}))
    await hazards._sync_air_quality_readings()
    r = (await _params(conn, A))[(11, "pm25")]
    assert (r["value"], r["unit"]) == (5.0, "µg/m³")
    assert r["coverage_pct"] == 88 and r["value_max"] == 99 and r["datetime_first"] is not None


@pytest.mark.asyncio
async def test_budget_stop_mid_pagination_keeps_written_pages(ctx, monkeypatch):
    hazards, conn, install = ctx
    monkeypatch.setattr(hazards, "_READINGS_PAGE_LIMIT", 1)
    monkeypatch.setenv("OPENAQ_DAILY_BUDGET", "2")   # catalogue + page 1 only
    # the budget counts per UTC day in a real table; start from a clean day
    await conn.execute("DELETE FROM openaq_request_budget WHERE utc_day = (now() at time zone 'utc')::date")
    cat = {"results": [{"id": 2, "name": "pm25", "units": "µg/m³"}]}
    fake = Fake(catalogue=cat, latest={2: [
        {"results": [_row(A, 1, 1.0)], "meta": {"found": 3}},
        {"results": [_row(B, 2, 2.0)], "meta": {"found": 3}}]})
    install(fake)
    assert await hazards._sync_air_quality_readings() == 1
    assert len(fake.calls) == 2, "a request was sent past the budget"
    assert (await _log(conn))["skipped_reason"] == "OpenAQ daily budget 2 reached"
    assert (await _log(conn))["last_synced_at"] is None
    assert (1, "pm25") in await _params(conn, A)
    assert await _params(conn, B) == {}
    # B was never seen: not stamped, so it never reads as "asked, nothing there"
    assert await conn.fetchval(
        "SELECT readings_attempted_at FROM air_quality_stations WHERE location_id=$1", B) is None


@pytest.mark.asyncio
async def test_401_stops_at_once_with_the_key_reason(ctx):
    hazards, conn, install = ctx
    fake = Fake(status={"/v3/parameters": 401})
    install(fake)
    await hazards._sync_air_quality_readings()
    assert len(fake.calls) == 1
    assert (await _log(conn))["skipped_reason"] == \
        "OpenAQ rejected the API key (401) — key invalid or banned"


@pytest.mark.asyncio
async def test_consecutive_5xx_abort_and_a_success_resets_the_streak(ctx):
    hazards, conn, install = ctx
    assert hazards._CONSECUTIVE_5XX_ABORT == 3
    # every /latest 500s: catalogue ok, then 3 failures in a row -> abort
    fake = Fake(status={"/v3/parameters/2/latest": 500, "/v3/parameters/3/latest": 500,
                        "/v3/parameters/10/latest": 500})
    install(fake)
    await hazards._sync_air_quality_readings()
    assert len(fake.calls) == 4
    row = await _log(conn)
    assert "3 consecutive" in row["skipped_reason"] and row["last_synced_at"] is None

    # two failures, then a good parameter: no abort; the run is reported incomplete
    fake = Fake(status={"/v3/parameters/3/latest": 500, "/v3/parameters/10/latest": 500},
                latest={2: [{"results": [_row(A, 1, 1.0)]}]})
    install(fake)
    await hazards._sync_air_quality_readings()
    assert (1, "pm25") in await _params(conn, A)
    assert (await _log(conn))["skipped_reason"].startswith("incomplete: could not read")


@pytest.mark.asyncio
async def test_pollutant_fill_values_reach_no_station_column(ctx):
    hazards, conn, install = ctx
    install(Fake(latest={2: [{"results": [_row(A, 1, -9999)]}]}))
    await hazards._sync_air_quality_readings()
    assert await conn.fetchval("SELECT pm25 FROM air_quality_stations WHERE location_id=$1", A) is None
