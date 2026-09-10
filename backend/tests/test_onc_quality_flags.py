# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""ONC publishes a quality flag with every sample. We must store it.

`scalardata` returns `qaqcFlags` in the same `data` object as `values` and
`sampleTimes`. Until 2026-09-10 we read two of those three and threw the
third away — `qaqc` did not appear anywhere in this repository.

Measured over 75 readings from 25 stations, before this was fixed:

    flag 1 (good) ................ 79%
    flag 0 (no QC performed) ..... 13%
    flag 3 (bad, correctable) ..... 7%
    flag 4 (bad) .................. 1%

ONC states plainly that "poor quality data is qualified as quality control
flags 3 and 4", so roughly one displayed reading in twelve had already been
marked doubtful by the people who collected it, and we showed it without a
word. The project's own policy (docs/methods/data-passthrough.md) says
quality flags "are requested, stored, and honoured" — for ONC we did none of
the three, while doing all three for Argo, GEOTRACES and WOD.

⛔ Honoured means honoured at PRESENTATION. The measurement is stored either
way, with its flag beside it. Dropping flagged values would put "we have no
reading" and "we have a doubtful reading" back on one code path, which is the
confusion this layer just spent a day untangling.

Covers:
  - a flag ONC sent is carried into the stored reading
  - no flag stored as None, never 0 (0 is a claim, absence is not)
  - a reading flagged 4 is STORED, not dropped
  - all three latest-reading paths carry the flag, not just one
"""
import ast
import os
from pathlib import Path

import httpx
import pytest

import db
from domains import onc

_RealAsyncClient = httpx.AsyncClient
_ONC_PY = Path(__file__).resolve().parents[1] / "domains" / "onc.py"

pytestmark_db = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)


def _sensor(value=4.2, flags=None, prop="oxygen", code="oxygen_corrected"):
    data = {"values": [value], "sampleTimes": ["2026-09-09T00:00:00.000Z"]}
    if flags is not None:
        data["qaqcFlags"] = flags
    return {
        "sensorCode": code,
        "propertyCode": prop,
        "sensorName": "Oxygen",
        "unitOfMeasure": "mL/L",
        "data": data,
    }


def _client(payload):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return lambda *a, **kw: _RealAsyncClient(transport=httpx.MockTransport(handler))


# ── the flag reader itself ──────────────────────────────────────────────────

def test_the_flag_onc_sent_is_the_flag_we_keep():
    assert onc.onc_qc_flag({"values": [1.0], "qaqcFlags": [4]}) == 4
    assert onc.onc_qc_flag({"values": [1.0], "qaqcFlags": [3]}) == 3
    assert onc.onc_qc_flag({"values": [1.0], "qaqcFlags": [1]}) == 1


def test_we_read_the_flag_of_the_sample_we_kept():
    """We keep values[-1], so we must keep qaqcFlags[-1] — not the first."""
    assert onc.onc_qc_flag({"values": [1.0, 2.0, 3.0], "qaqcFlags": [1, 1, 4]}) == 4


def test_no_flag_is_none_never_zero():
    """⛔ 0 means "we ran no QC". Absence means "we do not know"."""
    assert onc.onc_qc_flag({"values": [1.0]}) is None
    assert onc.onc_qc_flag({"values": [1.0], "qaqcFlags": []}) is None
    assert onc.onc_qc_flag({}) is None


def test_a_zero_flag_from_onc_is_preserved_as_zero():
    """0 is a real answer from ONC and must not be flattened into None."""
    assert onc.onc_qc_flag({"values": [1.0], "qaqcFlags": [0]}) == 0


# ── the paths that store readings ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_live_onc_carries_the_flag(monkeypatch):
    monkeypatch.setenv("ONC_TOKEN", "test-token")
    monkeypatch.setattr(onc.httpx, "AsyncClient",
                        _client({"sensorData": [_sensor(4.2, flags=[3])]}))

    result = await onc.live_onc("BACAX")

    assert result["available"] is True
    assert result["sensors"]["oxygen"]["qc"] == 3


@pytest.mark.asyncio
async def test_a_reading_flagged_bad_is_stored_not_dropped(monkeypatch):
    """⛔ The value survives. Only its presentation changes."""
    monkeypatch.setenv("ONC_TOKEN", "test-token")
    monkeypatch.setattr(onc.httpx, "AsyncClient",
                        _client({"sensorData": [_sensor(99.9, flags=[4])]}))

    result = await onc.live_onc("BACAX")

    assert result["available"] is True, "a flagged reading must not make the station look empty"
    assert result["sensors"]["oxygen"]["value"] == 99.9
    assert result["sensors"]["oxygen"]["qc"] == 4


@pytestmark_db
@pytest.mark.asyncio
async def test_the_sweep_stores_the_flag(monkeypatch):
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
            "VALUES ('CRIP', 'Test', 48.0, -126.0)")
        await conn.execute(
            "INSERT INTO onc_location_categories (location_code, device_category_code) "
            "VALUES ('CRIP', 'OXYSENSOR')")

    monkeypatch.setenv("ONC_TOKEN", "test-token")
    monkeypatch.setattr(onc.httpx, "AsyncClient",
                        _client({"sensorData": [_sensor(7.7, flags=[3])]}))

    await onc.sync_onc_sensors()

    async with pool.acquire() as conn:
        stored = await conn.fetchval(
            "SELECT latest_sensors FROM onc_locations WHERE location_code = 'CRIP'")
    import json as _json
    payload = _json.loads(stored) if isinstance(stored, str) else stored
    assert payload["oxygen"]["value"] == 7.7
    assert payload["oxygen"]["qc"] == 3, (
        "the sweep dropped the flag on the way to the database"
    )
    await pool.close()
    db.pool = None


# ── all three paths, not just the one with a test ───────────────────────────

def test_every_latest_reading_path_records_the_flag():
    """⛔ Three call sites build a "latest reading". A flag added to one and
    forgotten in another is exactly how this layer got a 365-day window in
    three places and a fix in one."""
    tree = ast.parse(_ONC_PY.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        # A "latest reading" dict is one that carries a measured value, its
        # unit and the moment it was taken.
        if {"value", "unit", "time"} <= keys and "qc" not in keys:
            offenders.append(node.lineno)
    assert not offenders, (
        f"domains/onc.py lines {offenders} build a reading with value+unit+time "
        "but no qc — ONC sent a flag for it and it is being thrown away"
    )
