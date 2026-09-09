# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Executes ingestion/onc_ingest.py and domains/onc.sync_onc_sensors against
real code paths (mocked HTTP transport, real PostGIS for the sensors test),
not just grepping the source.

Covers:
  - the device category list is fetched dynamically from ONC, not hardcoded
  - a 404 on one category is skipped without aborting the sync
  - locations seen under two categories dedupe to one row, with two rows in
    onc_location_categories
  - SABOTAGE CHECK: sync_onc_sensors must never delete a location that
    returns no scalar data — that is the exact regression that silently
    undid the category-widening once already.
"""
import json
import os

import httpx
import pytest

from ingestion import onc_ingest


_RealAsyncClient = httpx.AsyncClient


def _client_factory(handler):
    """Returns a drop-in replacement for httpx.AsyncClient bound to a MockTransport.

    Monkeypatching `onc_ingest.httpx.AsyncClient` patches the *module-level*
    attribute on the shared `httpx` module (onc_ingest does `import httpx`),
    so this factory must call the real class it captured before patching —
    calling `httpx.AsyncClient` again would recurse into itself.
    """
    def factory(*args, **kwargs):
        kwargs.pop("timeout", None)
        return _RealAsyncClient(transport=httpx.MockTransport(handler), timeout=5)
    return factory


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setattr(onc_ingest, "ONC_TOKEN", "test-token")


def test_device_categories_fetched_dynamically(monkeypatch):
    """The category list comes from GET /deviceCategories?method=get, not a hardcoded constant."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "deviceCategories" in str(request.url):
            return httpx.Response(200, json=[
                {"deviceCategoryCode": "CTD"},
                {"deviceCategoryCode": "MAGNETOMETER"},
            ])
        return httpx.Response(404)

    import asyncio
    categories = asyncio.run(
        onc_ingest.fetch_device_categories(_RealAsyncClient(transport=httpx.MockTransport(handler)))
    )
    assert categories == ["CTD", "MAGNETOMETER"]


def test_device_categories_fetch_failure_signals_none(monkeypatch):
    """A failed fetch must be distinguishable from a successful small one —
    fetch_device_categories returns None, never silently substitutes the
    fallback list itself. (Defect 2, 2026-09-08 audit: silently substituting
    here let one timed-out call collapse ~1,993 locations to ~183.)"""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await onc_ingest.fetch_device_categories(client)

    import asyncio
    categories = asyncio.run(run())
    assert categories is None


def test_404_category_is_skipped_not_aborted(monkeypatch):
    """A category-level 404 (e.g. MAGNETOMETER) must not abort the whole sync."""
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "deviceCategories" in url:
            return httpx.Response(200, json=[
                {"deviceCategoryCode": "CTD"},
                {"deviceCategoryCode": "MAGNETOMETER"},
            ])
        if "deviceCategoryCode=MAGNETOMETER" in url:
            return httpx.Response(404)
        if "deviceCategoryCode=CTD" in url:
            return httpx.Response(200, json=[
                {"locationCode": "BACAX", "locationName": "Barkley Canyon Axis",
                 "lat": 48.3, "lon": -126.1, "depth": 985, "description": ""},
            ])
        return httpx.Response(404)

    monkeypatch.setattr(onc_ingest.httpx, "AsyncClient", _client_factory(handler))

    import asyncio
    locations, pairs, categories_ok = asyncio.run(onc_ingest.fetch_onc_locations())

    assert len(locations) == 1
    assert locations[0]["location_code"] == "BACAX"
    assert pairs == [("BACAX", "CTD")]
    assert categories_ok is True


def test_two_categories_dedupe_to_one_location_two_category_rows(monkeypatch):
    """A location returned by both CTD and OXYSENSOR must produce ONE location
    row but TWO (location, category) pairs — the mapping is the new information
    and must not be collapsed away."""
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "deviceCategories" in url:
            return httpx.Response(200, json=[
                {"deviceCategoryCode": "CTD"},
                {"deviceCategoryCode": "OXYSENSOR"},
            ])
        payload = [{
            "locationCode": "BACAX", "locationName": "Barkley Canyon Axis",
            "lat": 48.3, "lon": -126.1, "depth": 985, "description": "",
        }]
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(onc_ingest.httpx, "AsyncClient", _client_factory(handler))

    import asyncio
    locations, pairs, categories_ok = asyncio.run(onc_ingest.fetch_onc_locations())

    assert len(locations) == 1
    assert sorted(pairs) == [("BACAX", "CTD"), ("BACAX", "OXYSENSOR")]
    assert categories_ok is True


def test_category_fetch_failure_is_marked_not_ok(monkeypatch):
    """When deviceCategories fails, fetch_onc_locations must still return the
    fallback-based results (so ONC_TOKEN not being set doesn't fully break
    the ingest) but flag categories_ok=False so sync_onc() knows not to trust
    it as a full replacement."""
    def handler(request: httpx.Request) -> httpx.Response:
        if "deviceCategories" in str(request.url):
            raise httpx.ConnectError("boom", request=request)
        if "deviceCategoryCode=CTD" in str(request.url):
            return httpx.Response(200, json=[
                {"locationCode": "BACAX", "locationName": "Barkley Canyon Axis",
                 "lat": 48.3, "lon": -126.1, "depth": 985, "description": ""},
            ])
        return httpx.Response(404)

    monkeypatch.setattr(onc_ingest.httpx, "AsyncClient", _client_factory(handler))

    import asyncio
    locations, pairs, categories_ok = asyncio.run(onc_ingest.fetch_onc_locations())

    assert categories_ok is False
    # Fallback list still ran (CTD, OXYSENSOR), so this is non-empty —
    # exactly the case that must NOT be allowed to truncate the real table.
    assert len(locations) == 1


# ── SABOTAGE CHECK: sync_onc_sensors must not delete no-data locations ─────

pytestmark_db = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)


@pytestmark_db
@pytest.mark.asyncio
async def test_sync_onc_sensors_never_deletes_no_data_locations(monkeypatch):
    """A location that legitimately has no scalar sensors (e.g. a junction box)
    must SURVIVE sync_onc_sensors with latest_sensors left NULL — it must not
    be deleted. This is the exact regression a hardcoded 2-category loop with
    a DELETE reintroduces; see .claude/rules and the task brief for history.
    """
    import asyncpg
    import db
    from domains import onc

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    db.pool = pool
    async with pool.acquire() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        await conn.execute("DROP TABLE IF EXISTS onc_locations")
        await conn.execute("DROP TABLE IF EXISTS onc_location_categories")
        await conn.execute("""
            CREATE TABLE onc_locations (
                location_code TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                lat DOUBLE PRECISION NOT NULL,
                lon DOUBLE PRECISION NOT NULL,
                depth_m DOUBLE PRECISION,
                description TEXT DEFAULT '',
                geom GEOMETRY(Point, 4326),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                latest_sensors JSONB,
                sensors_fetched_at TIMESTAMPTZ
            )
        """)
        await conn.execute("""
            CREATE TABLE onc_location_categories (
                location_code TEXT NOT NULL,
                device_category_code TEXT NOT NULL,
                PRIMARY KEY (location_code, device_category_code)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_log (
                source TEXT PRIMARY KEY,
                last_synced_at TIMESTAMPTZ,
                records_added INTEGER,
                total_records INTEGER
            )
        """)
        await conn.execute(
            "INSERT INTO onc_locations (location_code, name, lat, lon) "
            "VALUES ('JBOX1', 'Junction Box 1', 48.0, -126.0)"
        )
        await conn.execute(
            "INSERT INTO onc_location_categories (location_code, device_category_code) "
            "VALUES ('JBOX1', 'JB')"
        )

    monkeypatch.setattr(onc, "os", __import__("os"))
    monkeypatch.setenv("ONC_TOKEN", "test-token")

    def handler(request: httpx.Request) -> httpx.Response:
        # ONC returns no sensorData for a junction box — the realistic case.
        return httpx.Response(200, json={"sensorData": []})

    monkeypatch.setattr(
        onc.httpx, "AsyncClient",
        lambda *a, **kw: _RealAsyncClient(transport=httpx.MockTransport(handler)),
    )

    await onc.sync_onc_sensors()

    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM onc_locations WHERE location_code = 'JBOX1'")

    assert row is not None, (
        "sync_onc_sensors deleted a location with no scalar data — this is the "
        "exact regression that silently undoes the category-widening"
    )
    assert row["latest_sensors"] is None

    await pool.close()


@pytestmark_db
@pytest.mark.asyncio
async def test_sync_onc_refuses_to_truncate_on_categories_fetch_failure(monkeypatch):
    """Defect 2, 2026-09-08 audit: a transient blip on the category-list
    fetch must not wipe the widened onc_locations table. sync_onc() must
    refuse to truncate when fetch_onc_locations reports categories_ok=False,
    and must not stamp last_synced_at."""
    import asyncpg
    import db
    from domains import onc

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
        # ⚠️ sync_log survives the DROP/CREATE above, so a sibling test that
        # completed a successful sync leaves a row here. Any assertion of the
        # form "a failed sync must not stamp last_synced_at" then passes or
        # fails purely on test ORDER. Clear our own source.
        await conn.execute("DELETE FROM sync_log WHERE source LIKE 'onc%'")
        # Simulate the widened table: 1000 pre-existing locations.
        await conn.executemany(
            "INSERT INTO onc_locations (location_code, name, lat, lon) "
            "VALUES ($1, 'X', 48.0, -126.0)",
            [(f"LOC{i}",) for i in range(1000)],
        )

    async def fake_fetch_onc_locations():
        # Looks like a real, non-empty result — but categories_ok=False.
        return (
            [{"location_code": "LOC0", "name": "X", "lat": 48.0, "lon": -126.0,
              "depth_m": None, "description": ""}],
            [("LOC0", "CTD")],
            False,
        )

    import ingestion.onc_ingest as onc_ingest_mod
    monkeypatch.setattr(onc_ingest_mod, "fetch_onc_locations", fake_fetch_onc_locations)

    result = await onc.sync_onc()

    assert result == 0
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM onc_locations")
        synced = await conn.fetchval(
            "SELECT last_synced_at FROM sync_log WHERE source = 'onc'"
        )
    assert count == 1000, "sync_onc truncated the table despite categories_ok=False"
    assert synced is None, "a failed sync must not stamp last_synced_at"

    await pool.close()


@pytestmark_db
@pytest.mark.asyncio
async def test_sync_onc_shrink_guard_refuses_dramatic_drop(monkeypatch):
    """Belt-and-braces guard: even with categories_ok=True, refuse to replace
    the table if the new set is far smaller than what's stored."""
    import asyncpg
    import db
    from domains import onc

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
        # ⚠️ sync_log survives the DROP/CREATE above, so a sibling test that
        # completed a successful sync leaves a row here. Any assertion of the
        # form "a failed sync must not stamp last_synced_at" then passes or
        # fails purely on test ORDER. Clear our own source.
        await conn.execute("DELETE FROM sync_log WHERE source LIKE 'onc%'")
        await conn.executemany(
            "INSERT INTO onc_locations (location_code, name, lat, lon) "
            "VALUES ($1, 'X', 48.0, -126.0)",
            [(f"LOC{i}",) for i in range(1000)],
        )

    async def fake_fetch_onc_locations():
        # categories_ok=True but the live set genuinely shrank a lot — still
        # refuse, per the >=50%-of-existing threshold.
        return (
            [{"location_code": f"LOC{i}", "name": "X", "lat": 48.0, "lon": -126.0,
              "depth_m": None, "description": ""} for i in range(100)],
            [],
            True,
        )

    import ingestion.onc_ingest as onc_ingest_mod
    monkeypatch.setattr(onc_ingest_mod, "fetch_onc_locations", fake_fetch_onc_locations)

    result = await onc.sync_onc()

    assert result == 0
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM onc_locations")
    assert count == 1000, "sync_onc truncated the table despite a >50% shrink"

    await pool.close()


@pytestmark_db
@pytest.mark.asyncio
async def test_sync_onc_keeps_sensor_readings_it_did_not_fetch(monkeypatch):
    """A location sync must not destroy the readings the sensor sync collected.

    Found on production 2026-09-09: reading coverage had walked BACKWARDS from
    207 locations to 54 overnight. sync_onc() was doing TRUNCATE + INSERT, so
    every run cleared `latest_sensors`/`sensors_fetched_at` for the whole table,
    and sync_onc_sensors() — incremental at 400 locations per run — could only
    put back one batch before the next onc run wiped it again. With the old
    183-location layer this self-healed in a single pass and nobody noticed;
    at ~1,975 locations the two schedules can never converge.

    ⛔ Nothing raises when this regresses. The map still renders, the sync log
    still says success, and only the reading coverage rots. This test is the
    only thing that would notice.
    """
    import asyncpg
    import db
    from domains import onc

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
        # ⚠️ sync_log survives the DROP/CREATE above, so a sibling test that
        # completed a successful sync leaves a row here. Any assertion of the
        # form "a failed sync must not stamp last_synced_at" then passes or
        # fails purely on test ORDER. Clear our own source.
        await conn.execute("DELETE FROM sync_log WHERE source LIKE 'onc%'")
        # KEEPME already carries a reading. GONE is no longer served by ONC.
        await conn.execute(
            "INSERT INTO onc_locations (location_code, name, lat, lon, "
            "latest_sensors, sensors_fetched_at) VALUES "
            "('KEEPME', 'Has Reading', 48.0, -126.0, "
            "'{\"CTD\": {\"temperature\": 8.1}}'::jsonb, NOW())"
        )
        await conn.execute(
            "INSERT INTO onc_locations (location_code, name, lat, lon) "
            "VALUES ('GONE', 'Retired', 49.0, -127.0)"
        )

    async def fake_fetch_onc_locations():
        # ONC still serves KEEPME (and a new one); GONE has disappeared.
        return (
            [{"location_code": "KEEPME", "name": "Has Reading", "lat": 48.0,
              "lon": -126.0, "depth_m": None, "description": ""},
             {"location_code": "NEWLOC", "name": "New", "lat": 50.0,
              "lon": -128.0, "depth_m": None, "description": ""}],
            [("KEEPME", "CTD"), ("NEWLOC", "OXYSENSOR")],
            True,
        )

    import ingestion.onc_ingest as onc_ingest_mod
    monkeypatch.setattr(onc_ingest_mod, "fetch_onc_locations", fake_fetch_onc_locations)
    # The location sync calls the sensor sync at the end; stub it out so this
    # test measures the location sync alone.
    async def _noop(*a, **k):
        return 0
    monkeypatch.setattr(onc, "sync_onc_sensors", _noop)

    await onc.sync_onc()

    async with pool.acquire() as conn:
        kept = await conn.fetchrow(
            "SELECT latest_sensors, sensors_fetched_at FROM onc_locations "
            "WHERE location_code = 'KEEPME'"
        )
        gone = await conn.fetchval(
            "SELECT COUNT(*) FROM onc_locations WHERE location_code = 'GONE'"
        )
        new = await conn.fetchval(
            "SELECT COUNT(*) FROM onc_locations WHERE location_code = 'NEWLOC'"
        )
    await pool.close()

    assert kept is not None, "KEEPME was removed even though ONC still serves it"
    assert kept["latest_sensors"] is not None, (
        "sync_onc destroyed a reading it never fetched — the TRUNCATE regression"
    )
    assert kept["sensors_fetched_at"] is not None, (
        "sensors_fetched_at was reset, so this location goes to the front of the "
        "refresh queue forever and coverage never converges"
    )
    assert gone == 0, "a location ONC stopped serving should be removed"
    assert new == 1, "a newly served location should be inserted"
