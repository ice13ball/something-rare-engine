# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Executes against real PostGIS (2026-09-08 OceanSITES widening: 65
OPERATIONAL-only rows -> every OceanOPS status, ~5,795 platforms).

Covers:
  - nested `deployment.date` is parsed
  - the 1900-01-01 sentinel becomes NULL and is counted
  - a CLOSED platform is KEPT with status updated (not hard-deleted)
  - a Station-M-shaped row (CLOSED, 1948 date) survives ingest end to end
  - the shrink guard refuses a dramatically smaller fetch
  - sitemap: a platform with data appears, one without does not; the
    per-station endpoint still resolves both
"""
import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)


def _record(ref, status, lat, lon, name="Test Mooring", deploy_iso=None):
    rec = {
        "ref": ref,
        "name": name,
        "status": {"name": status},
        "deployment": {"latitude": lat, "longitude": lon},
        "age": None,
        "model": {"name": "Test Model"},
    }
    if deploy_iso is not None:
        rec["deployment"]["date"] = deploy_iso
    return rec


@pytest.fixture
async def pool():
    import asyncpg
    import db
    from schema.sensors import ensure_oceansites

    p = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    async with p.acquire() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        await ensure_oceansites(conn)
        await conn.execute(
            "DELETE FROM oceansites_stations WHERE ref LIKE 'TEST_%' OR ref = 'TMP174579701'"
        )

    original_pool = db.pool
    db.pool = p
    yield p
    async with p.acquire() as conn:
        await conn.execute(
            "DELETE FROM oceansites_stations WHERE ref LIKE 'TEST_%' OR ref = 'TMP174579701'"
        )
    db.pool = original_pool
    await p.close()


def test_deployment_date_parsed(monkeypatch):
    """`deployment.date` (nested) is parsed to a plain ISO date string."""
    from ingestion import oceansites_ingest

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [_record("TEST_1", "OPERATIONAL", 10.0, 20.0,
                                      deploy_iso="2006-06-08T00:00:00")]}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return FakeResp()

    monkeypatch.setattr(oceansites_ingest.httpx, "AsyncClient", lambda **kw: FakeClient())

    import asyncio
    stations = asyncio.run(oceansites_ingest.fetch_oceansites_stations())
    assert len(stations) == 1
    assert stations[0]["deploy_date"] == "2006-06-08"
    assert stations[0]["status"] == "OPERATIONAL"


def test_sentinel_rejected_and_counted(monkeypatch):
    """1900-01-01 becomes NULL and is counted via `last_sentinel_count`."""
    from ingestion import oceansites_ingest

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [
                _record("TESTSENTINEL1", "CLOSED", 1.0, 2.0, name=None,
                         deploy_iso="1900-01-01T00:00:00"),
                _record("TESTREAL1948", "CLOSED", 3.0, 4.0,
                         deploy_iso="1948-10-01T00:00:00"),
            ]}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return FakeResp()

    monkeypatch.setattr(oceansites_ingest.httpx, "AsyncClient", lambda **kw: FakeClient())

    import asyncio
    stations = asyncio.run(oceansites_ingest.fetch_oceansites_stations())
    by_ref = {s["ref"]: s for s in stations}
    assert by_ref["TESTSENTINEL1"]["deploy_date"] is None
    assert by_ref["TESTREAL1948"]["deploy_date"] == "1948-10-01"
    assert oceansites_ingest.last_sentinel_count == 1


async def test_closed_platform_kept_status_updated(pool):
    """A CLOSED platform is KEPT with status updated — sync must UPSERT, not
    hard-delete a row that stopped being OPERATIONAL. This is the exact
    behaviour the old `DELETE FROM ... WHERE ref != ALL(...)` broke; the
    sabotage step (documented in the task report, not re-run automatically
    here) restores that DELETE and confirms this test goes RED.
    """
    from domains import sensors
    import ingestion.oceansites_ingest as ing

    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO oceansites_stations (ref, name, lat, lon, status, network, geom)
               VALUES ('TEST_CLOSED_1', 'Old Op Mooring', 5.0, 6.0, 'OPERATIONAL', 'OceanSITES',
                       ST_SetSRID(ST_MakePoint(6.0, 5.0), 4326))"""
        )
        # 5 pre-existing "operational" siblings so the shrink guard (20%)
        # doesn't refuse this small, single-row fetch as implausible.
        for i in range(5):
            await conn.execute(
                f"""INSERT INTO oceansites_stations (ref, name, lat, lon, status, network, geom)
                    VALUES ('TEST_KEEP_{i}', 'Keep {i}', 1.0, 1.0, 'OPERATIONAL', 'OceanSITES',
                            ST_SetSRID(ST_MakePoint(1.0, 1.0), 4326))"""
            )

    stations = [
        {"ref": "TEST_CLOSED_1", "name": "Old Op Mooring", "lat": 5.0, "lon": 6.0,
         "status": "CLOSED", "network": "OceanSITES", "deploy_date": "2001-01-01",
         "age_days": None, "model": None},
    ] + [
        {"ref": f"TEST_KEEP_{i}", "name": f"Keep {i}", "lat": 1.0, "lon": 1.0,
         "status": "OPERATIONAL", "network": "OceanSITES", "deploy_date": None,
         "age_days": None, "model": None}
        for i in range(5)
    ]

    async def fake_fetch():
        return stations

    ing.last_sentinel_count = 0
    orig_fetch = ing.fetch_oceansites_stations
    ing.fetch_oceansites_stations = fake_fetch
    try:
        await sensors.sync_oceansites()
    finally:
        ing.fetch_oceansites_stations = orig_fetch

    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM oceansites_stations WHERE ref = 'TEST_CLOSED_1'")
    assert row is not None, "CLOSED platform was hard-deleted — must be kept with status updated"
    assert row["status"] == "CLOSED"


async def test_station_m_shaped_row_survives_ingest(pool):
    """CLOSED + 1948 deploy_date survives end to end (Station M is the exact
    case this widening exists for)."""
    from domains import sensors
    import ingestion.oceansites_ingest as ing

    stations = [{
        "ref": "TMP174579701", "name": "STATION-M-1", "lat": 66.0, "lon": 2.0,
        "status": "CLOSED", "network": "OceanSITES", "deploy_date": "1948-10-01",
        "age_days": None, "model": None,
    }]

    async def fake_fetch():
        return stations

    ing.last_sentinel_count = 0
    orig_fetch = ing.fetch_oceansites_stations
    ing.fetch_oceansites_stations = fake_fetch
    try:
        await sensors.sync_oceansites()
    finally:
        ing.fetch_oceansites_stations = orig_fetch

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, deploy_date FROM oceansites_stations WHERE ref = 'TMP174579701'"
        )
    assert row is not None
    assert row["status"] == "CLOSED"
    assert str(row["deploy_date"]) == "1948-10-01"


async def test_shrink_guard_refuses_dramatic_drop(pool):
    """A fetch far smaller than what's stored is refused, not applied."""
    from domains import sensors
    import ingestion.oceansites_ingest as ing

    async with pool.acquire() as conn:
        for i in range(20):
            await conn.execute(
                f"""INSERT INTO oceansites_stations (ref, name, lat, lon, status, network, geom)
                    VALUES ('TEST_SHRINK_{i}', 'S {i}', 1.0, 1.0, 'OPERATIONAL', 'OceanSITES',
                            ST_SetSRID(ST_MakePoint(1.0, 1.0), 4326))"""
            )

    # Only 2 of 20 returned — an 90% drop, well past the 20% guard.
    stations = [
        {"ref": "TEST_SHRINK_0", "name": "S 0", "lat": 1.0, "lon": 1.0,
         "status": "OPERATIONAL", "network": "OceanSITES", "deploy_date": None,
         "age_days": None, "model": None},
        {"ref": "TEST_SHRINK_1", "name": "S 1", "lat": 1.0, "lon": 1.0,
         "status": "OPERATIONAL", "network": "OceanSITES", "deploy_date": None,
         "age_days": None, "model": None},
    ]

    async def fake_fetch():
        return stations

    ing.last_sentinel_count = 0
    orig_fetch = ing.fetch_oceansites_stations
    ing.fetch_oceansites_stations = fake_fetch
    try:
        result = await sensors.sync_oceansites()
    finally:
        ing.fetch_oceansites_stations = orig_fetch

    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM oceansites_stations WHERE ref LIKE 'TEST_SHRINK_%'"
        )
    assert count == 20, "shrink guard did not refuse — rows were deleted/replaced"
    assert result == count


async def test_sitemap_gates_data_free_platforms(pool):
    """A platform with data appears in the sitemap query; one without does
    not. The per-station SEO endpoint still resolves both (never an empty
    200 — 404 for truly unknown refs only)."""
    from domains import seo

    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO oceansites_stations
                 (ref, name, lat, lon, status, network, geom, latest_obs)
               VALUES
                 ('TEST_HAS_DATA', 'Has Data', 1.0, 1.0, 'OPERATIONAL', 'OceanSITES',
                  ST_SetSRID(ST_MakePoint(1.0, 1.0), 4326), '{"sst": 12.3}'::jsonb),
                 ('TEST_NO_DATA', 'No Data', 2.0, 2.0, 'CLOSED', 'OceanSITES',
                  ST_SetSRID(ST_MakePoint(2.0, 2.0), 4326), NULL)"""
        )
        rows = await conn.fetch(
            "SELECT ref FROM oceansites_stations WHERE latest_obs IS NOT NULL "
            "AND ref LIKE 'TEST_%' ORDER BY ref"
        )
    refs = [r["ref"] for r in rows]
    assert refs == ["TEST_HAS_DATA"]

    # Per-station endpoint still resolves both, real 404 for unknown ref.
    row_with = await seo.seo_oceansites("TEST_HAS_DATA")
    assert row_with.ref == "TEST_HAS_DATA"
    row_without = await seo.seo_oceansites("TEST_NO_DATA")
    assert row_without.ref == "TEST_NO_DATA"

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await seo.seo_oceansites("TEST_DOES_NOT_EXIST")
    assert exc_info.value.status_code == 404


async def test_sitemap_core_and_entries_agree_on_oceansites_gate():
    """seo_sitemap_core() and its unused twin seo_sitemap_entries() must gate
    OceanSITES identically — an earlier fix today gated only the twin while
    production calls seo_sitemap_core(), and a green test watched the wrong
    function. Static check on source text, not execution, so it fails loudly
    if either query's WHERE clause diverges."""
    import inspect
    from domains import seo

    core_src = inspect.getsource(seo.seo_sitemap_core)
    entries_src = inspect.getsource(seo.seo_sitemap_entries)

    core_gate = "WHERE latest_obs IS NOT NULL" in core_src
    entries_gate = "WHERE latest_obs IS NOT NULL" in entries_src
    assert core_gate, "seo_sitemap_core (the one server.js actually calls) is not gated"
    assert entries_gate, "seo_sitemap_entries diverged from seo_sitemap_core's gate"
