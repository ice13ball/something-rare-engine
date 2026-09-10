# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""ONC "latest reading" must be the latest reading.

`rowLimit=1` returns the FIRST row at or after `dateFrom`, never the last.
Paired with a `dateFrom` floor — as all three ONC scalardata call sites used
to be — it yields the reading from the moment the floor opens, which the
panel then labels "latest". Measured on production 2026-09-09: BACAX stored
at 2025-09-09T18:53 (floor was now - 365 days) while the station published
2026-09-09T20:55 live; 1319 of 1615 stored readings older than 300 days,
8 fresher than a week.

The same floor also emptied most of the layer, because most ONC locations
are not cabled observatories — 723 of them are drifter buoys from finished
expeditions whose data is public and simply from 2015. 1745 of 1976
locations held nothing; a 40-location sample of those returned data for 30
once the floor came off.

Covers:
  - the shared param helper asks for getLatest and sets NO lower date bound
  - `live_onc` really sends those params to ONC (executed, params captured)
  - `sync_onc_sensors` really sends those params to ONC (needs TEST_DATABASE_URL)
  - no dict literal in domains/onc.py may pair an explicit `rowLimit` with a
    `dateFrom`, which is the shape of the original defect
"""
import ast
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

import db
from domains import onc

_RealAsyncClient = httpx.AsyncClient

pytestmark_db = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)

_ONC_PY = Path(__file__).resolve().parents[1] / "domains" / "onc.py"


def _capturing_client(seen: list[dict], payload: dict):
    """An httpx.AsyncClient stand-in that records query params and replies once."""
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json=payload)

    return lambda *a, **kw: _RealAsyncClient(transport=httpx.MockTransport(handler))


def _sensor(value=4.2):
    return {
        "sensorCode": "oxygen_corrected",
        "propertyCode": "oxygen",
        "unitOfMeasure": "mL/L",
        "data": {"values": [value], "sampleTimes": ["2015-03-17T19:04:47.000Z"]},
    }


# ── the shared contract ─────────────────────────────────────────────────────

def test_latest_params_ask_for_the_latest_and_set_no_lower_bound():
    p = onc.onc_latest_sample_params(datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc))
    assert p["getLatest"] == "true", "without getLatest, rowLimit=1 returns the OLDEST row"
    assert p["rowLimit"] == 1
    assert "dateFrom" not in p, (
        "a dateFrom floor turns 'latest reading' into 'reading from the floor', "
        "and hides every location whose last deployment predates it"
    )
    assert p["dateTo"] == "2026-09-09T12:00:00.000Z"


# ── the call sites, executed ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_live_onc_endpoint_requests_the_latest_sample(monkeypatch):
    """The live fallback endpoint must ask ONC for the latest sample."""
    seen: list[dict] = []
    monkeypatch.setenv("ONC_TOKEN", "test-token")
    monkeypatch.setattr(onc.httpx, "AsyncClient", _capturing_client(seen, {"sensorData": [_sensor()]}))

    result = await onc.live_onc("NC15.DR73")

    assert result["available"] is True
    assert seen, "the endpoint never called ONC"
    params = seen[0]
    assert params["getLatest"] == "true"
    assert params["rowLimit"] == "1"
    assert "dateFrom" not in params


@pytest.mark.asyncio
async def test_live_onc_surfaces_a_decade_old_reading_with_its_own_timestamp(monkeypatch):
    """A 2015 drifter reading is worth showing — but never as if it were current."""
    monkeypatch.setenv("ONC_TOKEN", "test-token")
    monkeypatch.setattr(
        onc.httpx, "AsyncClient",
        _capturing_client([], {"sensorData": [_sensor()]}),
    )

    result = await onc.live_onc("NC15.DR73")

    assert result["available"] is True
    assert result["sensors"]["oxygen"]["time"] == "2015-03-17T19:04:47.000Z"


@pytestmark_db
@pytest.mark.asyncio
async def test_sync_onc_sensors_requests_the_latest_sample(monkeypatch):
    """The sweep that fills onc_locations.latest_sensors must ask for the latest."""
    import asyncpg

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    db.pool = pool
    async with pool.acquire() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        await conn.execute("DROP TABLE IF EXISTS onc_locations")
        await conn.execute("DROP TABLE IF EXISTS onc_location_categories")
        await conn.execute("""
            CREATE TABLE onc_locations (
                location_code TEXT PRIMARY KEY, name TEXT NOT NULL,
                lat DOUBLE PRECISION NOT NULL, lon DOUBLE PRECISION NOT NULL,
                depth_m DOUBLE PRECISION, description TEXT DEFAULT '',
                geom GEOMETRY(Point, 4326), updated_at TIMESTAMPTZ DEFAULT NOW(),
                latest_sensors JSONB, sensors_fetched_at TIMESTAMPTZ
            )
        """)
        await conn.execute("""
            CREATE TABLE onc_location_categories (
                location_code TEXT NOT NULL, device_category_code TEXT NOT NULL,
                PRIMARY KEY (location_code, device_category_code)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_log (
                source TEXT PRIMARY KEY, last_synced_at TIMESTAMPTZ,
                records_added INTEGER, total_records INTEGER
            )
        """)
        await conn.execute(
            "INSERT INTO onc_locations (location_code, name, lat, lon) "
            "VALUES ('NC15.DR73', 'Drifter', 50.0, -128.0)"
        )
        await conn.execute(
            "INSERT INTO onc_location_categories (location_code, device_category_code) "
            "VALUES ('NC15.DR73', 'OXYSENSOR')"
        )

    seen: list[dict] = []
    monkeypatch.setenv("ONC_TOKEN", "test-token")
    monkeypatch.setattr(onc.httpx, "AsyncClient", _capturing_client(seen, {"sensorData": [_sensor()]}))

    await onc.sync_onc_sensors()

    assert seen, "the sweep never called ONC"
    params = seen[0]
    assert params["getLatest"] == "true"
    assert params["rowLimit"] == "1"
    assert "dateFrom" not in params, (
        "a floor here re-hides the 1745 locations whose last deployment is older than it"
    )

    async with pool.acquire() as conn:
        stored = await conn.fetchval(
            "SELECT latest_sensors FROM onc_locations WHERE location_code = 'NC15.DR73'"
        )
    assert stored is not None, "a 2015 reading must still be stored"
    await pool.close()
    db.pool = None


# ── the shape of the original defect, across every call site ────────────────

def test_no_call_site_pairs_rowlimit_with_a_datefrom_floor():
    """`rowLimit` + `dateFrom` is the defect. Any new call site must not reintroduce it."""
    tree = ast.parse(_ONC_PY.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        if "rowLimit" in keys and "dateFrom" in keys:
            offenders.append(node.lineno)
    assert not offenders, (
        f"domains/onc.py lines {offenders} pair rowLimit with dateFrom — that returns "
        "the row at the floor, not the latest one. Use onc_latest_sample_params()."
    )
