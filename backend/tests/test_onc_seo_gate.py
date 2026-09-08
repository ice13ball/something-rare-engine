# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Executes seo_sitemap_core(), seo_sitemap_entries() and seo_onc() against
real PostGIS to verify the sitemap gate.

`onc_ingest.py` now pulls every ONC device category (~1,993 locations, most
with no measurements — junction boxes, power supplies, cameras). Per Michal's
decision (2026-09-08): ALL locations go on the map, but ONLY locations with
real sensor data (`latest_sensors IS NOT NULL`) are crawlable/indexable —
sitemap, /hub/onc, nearby_onc_stations.

`/v1/seo/onc/{code}` must still resolve every location that exists in the DB,
gated or not — "not in the sitemap" is not the same as "does not exist"
(repo rule: missing vs broken must never share a code path).

⚠️ PRODUCTION READS THE SITEMAP FROM `seo_sitemap_core()`, NOT
`seo_sitemap_entries()`. `frontend/server.js:881` and `:1126` both fetch
`/v1/seo/sitemap/core`, which FastAPI routes to `seo_sitemap_core()`
(backend/domains/seo.py). `seo_sitemap_entries()` (`/v1/seo/sitemap-entries`)
is a second, older sitemap-builder function that nothing in production calls
— it existed already on 2026-09-08 when the ONC sensor-data gate was first
added, and that gate went onto `seo_sitemap_entries()` instead of
`seo_sitemap_core()`, so the real sitemap kept advertising all ~1,993 URLs
while a green test watched the wrong function. Both are exercised
below, plus an equality assertion, so the two ONC sets can never drift apart
silently again.
"""
import os

import pytest
from fastapi import HTTPException

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)

_WITH_DATA = "test-onc-has-sensors-1"
_NO_DATA = "test-onc-no-sensors-1"


@pytest.fixture
async def pool_and_endpoints():
    import asyncpg
    import db
    from domains import seo, seo_hubs
    from schema.onc import ensure_onc_core

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    async with pool.acquire() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        await ensure_onc_core(conn)
        # None of these tables are created by ensure_onc_core, and
        # seo_sitemap_core()/seo_sitemap_entries() query them unconditionally
        # (report_cache, sync_log) or per-table inside a try/except that
        # swallows a missing table as count 0 (the _LAYER_PAGE_TABLES loop).
        # Minimal stubs so both sitemap functions run end to end on a fresh
        # CI database — unrelated to the ONC gate itself.
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS seamounts (peak_id INTEGER PRIMARY KEY)"
        )
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS mining_contracts ("
            "isa_id TEXT PRIMARY KEY, act_date DATE, created_at TIMESTAMPTZ, "
            "contractor_name TEXT, geom GEOMETRY)"
        )
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS hydrothermal_vents ("
            "id TEXT PRIMARY KEY, created_at TIMESTAMPTZ)"
        )
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS oceansites_stations ("
            "ref TEXT PRIMARY KEY, updated_at TIMESTAMPTZ)"
        )
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS report_cache ("
            "platform_id TEXT PRIMARY KEY, generated_at TIMESTAMPTZ, "
            "report_json JSONB)"
        )
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS sync_log ("
            "source TEXT PRIMARY KEY, last_synced_at TIMESTAMPTZ, "
            "records_added INTEGER, total_records INTEGER)"
        )
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS arctic_river_stations ("
            "station_id TEXT PRIMARY KEY, source TEXT)"
        )

    original_pool = db.pool
    db.pool = pool

    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO onc_locations
                 (location_code, name, lat, lon, depth_m, description, geom,
                  latest_sensors, sensors_fetched_at)
               VALUES
                 ($1, 'Has Sensors Node', 49.0, -126.0, 100.0, '',
                  ST_SetSRID(ST_MakePoint(-126.0, 49.0), 4326),
                  '{"CTD": {"temperature": 8.1}}'::jsonb, NOW())
               ON CONFLICT (location_code) DO UPDATE SET
                 latest_sensors = EXCLUDED.latest_sensors,
                 sensors_fetched_at = EXCLUDED.sensors_fetched_at""",
            _WITH_DATA,
        )
        await conn.execute(
            """INSERT INTO onc_locations
                 (location_code, name, lat, lon, depth_m, description, geom,
                  latest_sensors, sensors_fetched_at)
               VALUES
                 ($1, 'No Sensors Node', 49.1, -126.1, 50.0, '',
                  ST_SetSRID(ST_MakePoint(-126.1, 49.1), 4326),
                  NULL, NULL)
               ON CONFLICT (location_code) DO UPDATE SET
                 latest_sensors = NULL, sensors_fetched_at = NULL""",
            _NO_DATA,
        )

    try:
        yield seo, seo_hubs
    finally:
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM onc_locations WHERE location_code = ANY($1)",
                [_WITH_DATA, _NO_DATA],
            )
        db.pool = original_pool
        await pool.close()


@pytest.mark.asyncio
async def test_sitemap_core_includes_location_with_sensor_data(pool_and_endpoints):
    """seo_sitemap_core() is THE function production calls — see module
    docstring. This is the assertion that actually matters."""
    seo, _ = pool_and_endpoints
    result = await seo.seo_sitemap_core()
    locs = {e["loc"] for e in result["entries"]}
    assert f"https://something-rare.com/onc/{_WITH_DATA}" in locs


@pytest.mark.asyncio
async def test_sitemap_core_excludes_location_without_sensor_data(pool_and_endpoints):
    seo, _ = pool_and_endpoints
    result = await seo.seo_sitemap_core()
    locs = {e["loc"] for e in result["entries"]}
    assert f"https://something-rare.com/onc/{_NO_DATA}" not in locs


@pytest.mark.asyncio
async def test_sitemap_entries_includes_location_with_sensor_data(pool_and_endpoints):
    seo, _ = pool_and_endpoints
    result = await seo.seo_sitemap_entries()
    locs = {e["loc"] for e in result["entries"]}
    assert f"https://something-rare.com/onc/{_WITH_DATA}" in locs


@pytest.mark.asyncio
async def test_sitemap_entries_excludes_location_without_sensor_data(pool_and_endpoints):
    seo, _ = pool_and_endpoints
    result = await seo.seo_sitemap_entries()
    locs = {e["loc"] for e in result["entries"]}
    assert f"https://something-rare.com/onc/{_NO_DATA}" not in locs


@pytest.mark.asyncio
async def test_sitemap_core_and_entries_agree_on_onc_set(pool_and_endpoints):
    """The two sitemap builders must never drift apart again — on 2026-09-08 the
    ONC gate went onto the wrong one and the suite stayed green throughout."""
    seo, _ = pool_and_endpoints
    core = await seo.seo_sitemap_core()
    entries = await seo.seo_sitemap_entries()

    def onc_locs(result):
        return {e["loc"] for e in result["entries"] if "/onc/" in e["loc"]}

    assert onc_locs(core) == onc_locs(entries)


@pytest.mark.asyncio
async def test_onc_hub_count_excludes_location_without_sensor_data(pool_and_endpoints):
    _, seo_hubs = pool_and_endpoints
    hub = seo_hubs.HUBS["onc"]
    import db
    async with db.pool.acquire() as conn:
        count = await conn.fetchval(hub.count_sql)
        rows = await conn.fetch(hub.rows_sql, 250, 0)
    codes = {r["location_code"] for r in rows}
    assert _WITH_DATA in codes
    assert _NO_DATA not in codes
    assert count >= 1


@pytest.mark.asyncio
async def test_onc_detail_still_200s_for_ungated_location(pool_and_endpoints):
    seo, _ = pool_and_endpoints
    detail = await seo.seo_onc(_NO_DATA)
    assert detail.location_code == _NO_DATA
    assert detail.name == "No Sensors Node"


@pytest.mark.asyncio
async def test_onc_detail_404s_for_unknown_code(pool_and_endpoints):
    seo, _ = pool_and_endpoints
    with pytest.raises(HTTPException) as exc_info:
        await seo.seo_onc("does-not-exist-" + _NO_DATA)
    assert exc_info.value.status_code == 404
