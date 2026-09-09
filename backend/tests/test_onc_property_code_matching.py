# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""sync_onc_sensors must match ONC sensors on propertyCode, not sensorCode.

Verified against the live ONC API 2026-09-09: sensorCode `oxygen_corrected`
and `oxygen_uncorrected` both carry propertyCode `oxygen`, and the old
sensorCode-exact-match dict dropped both silently — 584 OXYSENSOR locations,
one surviving oxygen reading out of 54. See
.claude/rules/layers/onc-observatory.md and the task brief for history.

Covers:
  - a sensor with sensorCode `oxygen_corrected` / propertyCode `oxygen` IS stored
  - SABOTAGE CHECK: restoring the old sensorCode-exact-match logic must fail
    the above test
  - two sensors sharing propertyCode `oxygen` collapse to ONE deterministic
    reading (the corrected one), never last-write-wins
  - `turbidityftu` and `turbidityntu` both survive as separate readings
  - methane and pH readings are stored with ONC's own unit
  - a reading with no `unitOfMeasure` stores NULL, not an invented unit
  - an unrecognised propertyCode increments the drop counter and is named in
    the warning line
"""
import json
import os

import json

import httpx
import pytest

import db
from domains import onc

_RealAsyncClient = httpx.AsyncClient

pytestmark_db = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)


def _sensor(sensor_code, property_code, value, unit=None):
    return {
        "sensorCode": sensor_code,
        "propertyCode": property_code,
        "unitOfMeasure": unit,
        "data": {"values": [value], "sampleTimes": ["2026-09-09T00:00:00.000Z"]},
    }


async def _setup_pool():
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
        await conn.execute("DELETE FROM sync_log WHERE source LIKE 'onc%'")
        await conn.execute(
            "INSERT INTO onc_locations (location_code, name, lat, lon) "
            "VALUES ('CRIP', 'Test Location', 48.0, -126.0)"
        )
        await conn.execute(
            "INSERT INTO onc_location_categories (location_code, device_category_code) "
            "VALUES ('CRIP', 'OXYSENSOR')"
        )
    return pool


@pytestmark_db
@pytest.mark.asyncio
async def test_oxygen_corrected_sensor_is_stored(monkeypatch):
    """sensorCode `oxygen_corrected` / propertyCode `oxygen` must survive the sync."""
    pool = await _setup_pool()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"sensorData": [
            _sensor("oxygen_corrected", "oxygen", 4.2, "mL/L"),
        ]})

    monkeypatch.setenv("ONC_TOKEN", "test-token")
    monkeypatch.setattr(
        onc.httpx, "AsyncClient",
        lambda *a, **kw: _RealAsyncClient(transport=httpx.MockTransport(handler)),
    )

    await onc.sync_onc_sensors()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT latest_sensors FROM onc_locations WHERE location_code = 'CRIP'"
        )
    await pool.close()

    latest = row["latest_sensors"]
    assert latest is not None, "oxygen_corrected was dropped"
    latest = json.loads(latest)
    assert "oxygen" in latest, latest
    assert latest["oxygen"]["value"] == 4.2


@pytestmark_db
@pytest.mark.asyncio
async def test_shared_property_code_collision_is_deterministic_not_last_write_wins(monkeypatch):
    """oxygen_corrected and oxygen_uncorrected both report propertyCode
    `oxygen`. The corrected reading must win regardless of arrival order."""
    pool = await _setup_pool()

    def handler_corrected_last(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"sensorData": [
            _sensor("oxygen_uncorrected", "oxygen", 1.0, "mL/L"),
            _sensor("oxygen_corrected", "oxygen", 4.2, "mL/L"),
        ]})

    def handler_corrected_first(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"sensorData": [
            _sensor("oxygen_corrected", "oxygen", 4.2, "mL/L"),
            _sensor("oxygen_uncorrected", "oxygen", 1.0, "mL/L"),
        ]})

    monkeypatch.setenv("ONC_TOKEN", "test-token")

    for handler in (handler_corrected_last, handler_corrected_first):
        monkeypatch.setattr(
            onc.httpx, "AsyncClient",
            lambda *a, **kw: _RealAsyncClient(transport=httpx.MockTransport(handler)),
        )
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE onc_locations SET latest_sensors = NULL, sensors_fetched_at = NULL"
            )
        await onc.sync_onc_sensors()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT latest_sensors FROM onc_locations WHERE location_code = 'CRIP'"
            )
        latest = json.loads(row["latest_sensors"])
        assert latest["oxygen"]["value"] == 4.2, (
            "the corrected reading must win regardless of arrival order "
            f"(got {latest})"
        )
        assert len(latest) == 1, "only one 'oxygen' key must exist, no overwrite artifacts"

    await pool.close()


@pytestmark_db
@pytest.mark.asyncio
async def test_turbidity_ftu_and_ntu_survive_as_separate_readings(monkeypatch):
    pool = await _setup_pool()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"sensorData": [
            _sensor("turb_ftu", "turbidityftu", 2.1, "FTU"),
            _sensor("turb_ntu", "turbidityntu", 3.4, "NTU"),
        ]})

    monkeypatch.setenv("ONC_TOKEN", "test-token")
    monkeypatch.setattr(
        onc.httpx, "AsyncClient",
        lambda *a, **kw: _RealAsyncClient(transport=httpx.MockTransport(handler)),
    )

    await onc.sync_onc_sensors()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT latest_sensors FROM onc_locations WHERE location_code = 'CRIP'"
        )
    await pool.close()

    sensors = json.loads(row["latest_sensors"])
    assert sensors["turbidityftu"]["value"] == 2.1
    assert sensors["turbidityntu"]["value"] == 3.4
    assert sensors["turbidityftu"]["unit"] == "FTU"
    assert sensors["turbidityntu"]["unit"] == "NTU"


@pytestmark_db
@pytest.mark.asyncio
async def test_methane_and_ph_stored_with_oncs_own_unit(monkeypatch):
    pool = await _setup_pool()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"sensorData": [
            _sensor("ph_sensor", "ph", 7.9, "pH"),
            _sensor("ch4_conc", "methaneconcentration", 1.8, "ppm"),
        ]})

    monkeypatch.setenv("ONC_TOKEN", "test-token")
    monkeypatch.setattr(
        onc.httpx, "AsyncClient",
        lambda *a, **kw: _RealAsyncClient(transport=httpx.MockTransport(handler)),
    )

    await onc.sync_onc_sensors()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT latest_sensors FROM onc_locations WHERE location_code = 'CRIP'"
        )
    await pool.close()

    sensors = json.loads(row["latest_sensors"])
    assert sensors["ph"]["value"] == 7.9
    assert sensors["ph"]["unit"] == "pH"
    assert sensors["methaneconcentration"]["value"] == 1.8
    assert sensors["methaneconcentration"]["unit"] == "ppm"


@pytestmark_db
@pytest.mark.asyncio
async def test_missing_unit_stores_null_never_invented(monkeypatch):
    """rules/subsystems/units-and-passthrough.md: if ONC sends no unit,
    store NULL — never fall back to a hardcoded guess."""
    pool = await _setup_pool()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"sensorData": [
            _sensor("oxygen_corrected", "oxygen", 4.2, unit=None),
        ]})

    monkeypatch.setenv("ONC_TOKEN", "test-token")
    monkeypatch.setattr(
        onc.httpx, "AsyncClient",
        lambda *a, **kw: _RealAsyncClient(transport=httpx.MockTransport(handler)),
    )

    await onc.sync_onc_sensors()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT latest_sensors FROM onc_locations WHERE location_code = 'CRIP'"
        )
    await pool.close()

    assert json.loads(row["latest_sensors"])["oxygen"]["unit"] is None


@pytestmark_db
@pytest.mark.asyncio
async def test_unrecognised_property_code_increments_drop_counter_and_logs(monkeypatch, caplog):
    """An unrecognised propertyCode must be counted and named in a WARNING —
    the single line that would have surfaced the original bug in a day."""
    pool = await _setup_pool()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"sensorData": [
            _sensor("weird_sensor", "somebrandnewproperty", 1.0, "unit"),
        ]})

    monkeypatch.setenv("ONC_TOKEN", "test-token")
    monkeypatch.setattr(
        onc.httpx, "AsyncClient",
        lambda *a, **kw: _RealAsyncClient(transport=httpx.MockTransport(handler)),
    )

    import logging
    caplog.set_level(logging.WARNING, logger=onc.log.name)

    await onc.sync_onc_sensors()
    await pool.close()

    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("somebrandnewproperty" in w for w in warnings), warnings
    assert any("dropped" in w for w in warnings), warnings


@pytestmark_db
@pytest.mark.asyncio
async def test_ctd_profile_temperature_alias_collision_is_not_last_write_wins(monkeypatch):
    """`seawatertemperature` and `temperature` are two DISTINCT ONC
    propertyCodes that sync_onc_ctd_profiles deliberately collapses into one
    `temperature` key, because the profile builder needs exactly that key.

    ⛔ The collision guard originally keyed on the PRE-collapse propertyCode, so
    the two never looked like a collision — whichever ONC listed second silently
    overwrote the first. Order-dependent, nothing logged, and the profile would
    render a plausible curve built from the wrong sensor.

    Found 2026-09-09 while widening ONC readings to all 28 bio/chem properties.

    ⚠️ This test drives the REAL sync_onc_ctd_profiles and reads what it stored.
    An earlier version of it asserted on the tie-break helper directly and still
    passed with the bug reinstated — a guard that cannot go red is not a guard.
    """
    import db
    pool = await _setup_pool()
    monkeypatch.setenv("ONC_TOKEN", "test-token")

    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS onc_instruments (
                id SERIAL PRIMARY KEY, device_code TEXT, device_category TEXT,
                location_code TEXT)
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS onc_ctd_profiles (
                location_code TEXT, device_code TEXT, cast_time TIMESTAMPTZ,
                profile JSONB, updated_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (location_code, device_code, cast_time))
        """)
        await conn.execute("DELETE FROM onc_instruments")
        await conn.execute("DELETE FROM onc_ctd_profiles")
        await conn.execute(
            "INSERT INTO onc_instruments (device_code, device_category, location_code) "
            "VALUES ('DEV1', 'Conductivity Temperature Depth', 'CTDLOC')")

    # 3.0 comes from `seawatertemperature`, 9.9 from `temperature`. Both collapse
    # to the same key. Only the tie-break may decide, never the array order.
    UNCORR = _sensor("temperature_uncorrected", "seawatertemperature", 3.0, "C")
    CORR   = _sensor("temperature_corrected", "temperature", 9.9, "C")
    PRES   = _sensor("pressure", "pressure", 100.0, "decibar")

    results = []
    for order in ([UNCORR, CORR, PRES], [CORR, UNCORR, PRES]):
        def handler(request: httpx.Request, _o=order) -> httpx.Response:
            return httpx.Response(200, json={"sensorData": _o})
        monkeypatch.setattr(
            onc.httpx, "AsyncClient",
            lambda *a, **kw: _RealAsyncClient(transport=httpx.MockTransport(handler)),
        )
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM onc_ctd_profiles")
        await onc.sync_onc_ctd_profiles()
        async with pool.acquire() as conn:
            prof = await conn.fetchval(
                "SELECT profile FROM onc_ctd_profiles WHERE location_code = 'CTDLOC'")
        results.append(json.loads(prof) if isinstance(prof, str) else prof)

    await pool.close()

    temps = []
    for r in results:
        assert r, "sync_onc_ctd_profiles stored no profile at all"
        t = r.get("temperature") if isinstance(r, dict) else None
        temps.append(json.dumps(t, sort_keys=True))

    assert temps[0] == temps[1], (
        "the stored temperature changed with ONC's array order — the two "
        "propertyCodes still race into one key"
    )
    assert "9.9" in temps[0], (
        "the uncorrected seawatertemperature reading won; the corrected one "
        "must, per the documented tie-break"
    )


@pytestmark_db
@pytest.mark.asyncio
async def test_readings_accumulate_across_every_category_not_just_the_first(monkeypatch):
    """A location carrying several instrument categories must yield readings
    from ALL of them, not from whichever answered first.

    ⛔ sync_onc_sensors used to `return` on the first category that produced
    data. That was invisible while only CTD and OXYSENSOR were ingested, but
    after the 2026-09-08 widening to ~120 categories it became the dominant
    truncation: a location with a CTD *and* a pH sensor *and* a CO2 sensor
    reported one of them and never requested the rest. Nothing raised — the
    location just looked like it carried a single instrument.

    Found 2026-09-09 while checking whether measurement dates were being kept.
    """
    import db
    pool = await _setup_pool()
    monkeypatch.setenv("ONC_TOKEN", "test-token")

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM onc_location_categories")
        await conn.executemany(
            "INSERT INTO onc_location_categories (location_code, device_category_code) "
            "VALUES ($1, $2) ON CONFLICT DO NOTHING",
            [("CRIP", "CTD"), ("CRIP", "PHSENSOR"), ("CRIP", "CO2SENSOR")],
        )
        await conn.execute(
            "UPDATE onc_locations SET latest_sensors = NULL, sensors_fetched_at = NULL")

    def handler(request: httpx.Request) -> httpx.Response:
        cat = request.url.params.get("deviceCategoryCode")
        by_cat = {
            "CTD":       [_sensor("temperature", "temperature", 8.4, "C")],
            "PHSENSOR":  [_sensor("ph", "ph", 7.91, "pH")],
            "CO2SENSOR": [_sensor("co2", "co2partialpressure", 412.0, "pCO2 uatm")],
        }
        return httpx.Response(200, json={"sensorData": by_cat.get(cat, [])})

    monkeypatch.setattr(
        onc.httpx, "AsyncClient",
        lambda *a, **kw: _RealAsyncClient(transport=httpx.MockTransport(handler)),
    )
    await onc.sync_onc_sensors()

    async with pool.acquire() as conn:
        raw = await conn.fetchval(
            "SELECT latest_sensors FROM onc_locations WHERE location_code = 'CRIP'")
    await pool.close()

    sensors = json.loads(raw) if isinstance(raw, str) else raw
    assert sensors, "no readings stored at all"
    keys = set(sensors)
    assert keys == {"temperature", "ph", "co2partialpressure"}, (
        f"expected readings from all three categories, got {sorted(keys)} — "
        "the sweep stopped at the first category that answered"
    )
    # Each reading must keep its OWN category and time, not the location's first.
    assert sensors["ph"]["category"] == "PHSENSOR"
    assert sensors["co2partialpressure"]["category"] == "CO2SENSOR"
    assert sensors["ph"]["time"], "a reading must carry its own measurement time"
