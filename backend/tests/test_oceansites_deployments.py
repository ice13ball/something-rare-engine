# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""OceanSITES must keep every deployment OceanOPS returns, not the last one.

Measured against the live OceanOPS API 2026-09-09: 5,795 platform records,
5,795 DISTINCT refs — there is nothing to deduplicate. The ingest collapsed
them to 1,072 by stripping the `_NNN` redeployment suffix and keeping the
highest per base ref, discarding 4,723 real records. One mooring (5100007)
holds 61 deployments from 1988-05-27 to 2026-03-27; 31 base refs hold
deployments more than a degree apart, the widest 7.9 degrees (~880 km); and
each deployment carries its OWN WIGOS identifier (0-22000-<n>-<base>), the
key WMO systems join on.

The station table still collapses — that is what a map point should be — but
oceansites_deployments keeps the whole record set.
"""
import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)

_SAMPLE = [
    # base ref with three deployments, moving position, own WIGOS id each
    {"ref": "5100007",     "id": 1, "name": "PAPA", "status": {"name": "CLOSED"},
     "model": {"name": "ATLAS"}, "age": "NaN",
     "deployment": {"latitude": 50.0, "longitude": -145.0, "date": "1988-05-27T00:00:00",
                    "ship": {"name": "RV ALPHA"}},
     "identifiers": {"wigos_id": "0-22000-0-5100007"},
     "program": {"country": {"name": "United States"}},
     "sensor_lists": {"models": "SEABIRD_SBE37"}},
    {"ref": "5100007_001", "id": 2, "name": "PAPA", "status": {"name": "CLOSED"},
     "model": {"name": "ATLAS"}, "age": 400,
     "deployment": {"latitude": 50.1, "longitude": -145.2, "date": "2007-06-01T00:00:00",
                    "ship": {"name": "RV BETA"}},
     "identifiers": {"wigos_id": "0-22000-1-5100007"},
     "program": {"country": {"name": "United States"}},
     "sensor_lists": {"models": "SEABIRD_SBE37, RDI Sentinel"}},
    {"ref": "5100007_002", "id": 3, "name": "PAPA", "status": {"name": "OPERATIONAL"},
     "model": {"name": "ATLAS_NEXT"}, "age": 12,
     "deployment": {"latitude": 50.2, "longitude": -145.4, "date": "2026-03-27T00:00:00",
                    "ship": {"name": "RV GAMMA"}},
     "identifiers": {"wigos_id": "0-22000-2-5100007"},
     "program": {"country": {"name": "United States"}},
     "sensor_lists": {"models": "SEABIRD_SBE37, RDI Sentinel, PAINE"}},
    # the null-island sentinel: a real platform whose position is a placeholder
    {"ref": "2300495_001", "id": 4, "name": "", "status": {"name": "CLOSED"},
     "model": {"name": "MOORING"}, "age": "NaN",
     "deployment": {"latitude": 0, "longitude": 0, "date": "1900-01-01T00:00:00"},
     "identifiers": {}, "program": {}, "sensor_lists": {}},
]


@pytest.fixture
async def pool(monkeypatch):
    import asyncpg
    import db as _db
    import schema

    _db.pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    await schema.ensure_schema()
    async with _db.pool.acquire() as c:
        await c.execute("DELETE FROM oceansites_deployments")
        await c.execute("DELETE FROM oceansites_stations")
    yield _db.pool
    async with _db.pool.acquire() as c:
        await c.execute("DELETE FROM oceansites_deployments")
        await c.execute("DELETE FROM oceansites_stations")
    await _db.pool.close()


class _Resp:
    def __init__(self, payload): self._p = payload
    def raise_for_status(self): pass
    def json(self): return self._p


class _Client:
    def __init__(self, payload): self._p = payload
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def get(self, _url): return _Resp(self._p)


async def _run_sync(monkeypatch, records):
    import httpx

    from domains import sensors
    from ingestion import oceansites_ingest

    monkeypatch.setattr(oceansites_ingest.httpx, "AsyncClient",
                        lambda *a, **k: _Client({"data": records}))
    # the observation fetch is a separate source; keep this test on the ingest
    async def _no_obs(): return 0
    monkeypatch.setattr(sensors, "sync_oceansites_obs", _no_obs)
    async def _no_notify(_u): return None
    monkeypatch.setattr(sensors, "_notify_indexnow", _no_notify)
    assert httpx  # keep the import meaningful
    return await sensors.sync_oceansites()


@pytest.mark.asyncio
async def test_every_source_record_becomes_a_deployment_row(pool, monkeypatch):
    await _run_sync(monkeypatch, _SAMPLE)

    async with pool.acquire() as conn:
        depl = await conn.fetchval("SELECT count(*) FROM oceansites_deployments")
        stations = await conn.fetchval("SELECT count(*) FROM oceansites_stations")

    assert depl == len(_SAMPLE), (
        f"{len(_SAMPLE)} source records produced {depl} deployment rows — "
        "records are still being discarded by the _NNN collapse"
    )
    # the station table still collapses, and still drops the position-less one
    assert stations == 1, f"expected 1 collapsed station, got {stations}"


@pytest.mark.asyncio
async def test_each_deployment_keeps_its_own_wigos_id_position_and_ship(pool, monkeypatch):
    """⛔ The fields that made the collapse lossy, one row at a time."""
    await _run_sync(monkeypatch, _SAMPLE)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT ref, deploy_num, lat, lon, wigos_id, deploy_ship, deploy_date, "
            "       sensor_models, country, status "
            "FROM oceansites_deployments WHERE base_ref = '5100007' ORDER BY deploy_num")

    assert [r["wigos_id"] for r in rows] == [
        "0-22000-0-5100007", "0-22000-1-5100007", "0-22000-2-5100007"], (
        "deployments share a WIGOS id — the identifier WMO systems join on was "
        "collapsed away")
    assert [r["deploy_ship"] for r in rows] == ["RV ALPHA", "RV BETA", "RV GAMMA"]
    assert [r["lat"] for r in rows] == [50.0, 50.1, 50.2], "positions were collapsed"
    assert [r["deploy_date"].isoformat() for r in rows] == [
        "1988-05-27", "2007-06-01", "2026-03-27"], "the deployment history lost its dates"
    assert rows[0]["sensor_models"] == "SEABIRD_SBE37"
    assert rows[2]["sensor_models"] == "SEABIRD_SBE37, RDI Sentinel, PAINE"
    assert rows[0]["country"] == "United States"
    # status is per deployment, not per station
    assert [r["status"] for r in rows] == ["CLOSED", "CLOSED", "OPERATIONAL"]


@pytest.mark.asyncio
async def test_null_island_is_recorded_as_unknown_not_as_a_position(pool, monkeypatch):
    """⛔ (0,0) is a placeholder. Storing it renders a mooring off West Africa."""
    await _run_sync(monkeypatch, _SAMPLE)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT lat, lon, geom, position_flag, deploy_date, model "
            "FROM oceansites_deployments WHERE ref = '2300495_001'")

    assert row is not None, "the position-less platform was dropped entirely"
    assert row["lat"] is None and row["lon"] is None, (
        "(0,0) was stored as a real coordinate")
    assert row["geom"] is None, "a geometry was built from the (0,0) placeholder"
    assert row["position_flag"] == "null-island", (
        "the reason the position is missing was not recorded, so 'unknown' is "
        "indistinguishable from 'never had one'")
    assert row["deploy_date"] is None, "the 1900-01-01 sentinel became a real date"
    assert row["model"] == "MOORING", "the rest of the record was thrown away with the position"


@pytest.mark.asyncio
async def test_station_row_carries_the_new_fields_and_a_deployment_count(pool, monkeypatch):
    await _run_sync(monkeypatch, _SAMPLE)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT wigos_id, country, sensor_models, deploy_ship, deployment_count "
            "FROM oceansites_stations WHERE ref = '5100007'")

    assert row["wigos_id"] == "0-22000-2-5100007", "the station kept no WIGOS id"
    assert row["country"] == "United States"
    assert row["deploy_ship"] == "RV GAMMA"
    assert row["deployment_count"] == 3, (
        f"deployment_count is {row['deployment_count']}, expected 3 — the station "
        "row does not say how much history sits behind it")


@pytest.mark.asyncio
async def test_a_shrunken_fetch_is_refused_not_applied(pool, monkeypatch):
    """⛔ A bad filter upstream must not delete deployment history."""
    await _run_sync(monkeypatch, _SAMPLE)
    async with pool.acquire() as conn:
        before = await conn.fetchval("SELECT count(*) FROM oceansites_deployments")

    await _run_sync(monkeypatch, _SAMPLE[:1])  # 1 of 4 — a 75% drop

    async with pool.acquire() as conn:
        after = await conn.fetchval("SELECT count(*) FROM oceansites_deployments")

    assert after == before, (
        f"a fetch returning 1 of {before} rows was applied, taking the table to "
        f"{after}. Deployment history is not recoverable from OceanOPS once a "
        "shrunken sync deletes it.")


@pytest.mark.asyncio
async def test_a_ref_oceanops_stops_returning_is_removed(pool, monkeypatch):
    """The other half of the guard: real removals must still happen."""
    await _run_sync(monkeypatch, _SAMPLE)
    # drop one of four — 25%, inside the 20%... no: 3 of 4 is a 25% drop, which
    # exceeds the guard, so extend the set instead and remove from the larger one
    bigger = _SAMPLE + [
        {"ref": f"9900{i:03d}", "id": 100 + i, "name": f"T{i}",
         "status": {"name": "CLOSED"}, "model": {"name": "M"}, "age": "NaN",
         "deployment": {"latitude": 1.0 + i, "longitude": 2.0, "date": "2010-01-01T00:00:00"},
         "identifiers": {}, "program": {}, "sensor_lists": {}}
        for i in range(20)
    ]
    await _run_sync(monkeypatch, bigger)
    async with pool.acquire() as conn:
        before = await conn.fetchval("SELECT count(*) FROM oceansites_deployments")
    assert before == 24

    await _run_sync(monkeypatch, bigger[:-2])  # remove 2 of 24 — an 8% drop

    async with pool.acquire() as conn:
        after = await conn.fetchval("SELECT count(*) FROM oceansites_deployments")
        gone = await conn.fetchval(
            "SELECT count(*) FROM oceansites_deployments WHERE ref = '9900019'")

    assert after == 22, f"expected 22 rows after a real removal, got {after}"
    assert gone == 0, "a ref OceanOPS stopped returning was left behind"


@pytest.mark.asyncio
async def test_map_endpoint_serialises_after_a_cold_cache(pool, monkeypatch):
    """⛔ /v1/map/oceansites built its payload with json.dumps over a raw
    datetime.date and raised TypeError on every rebuild.

    `deploy_date` was TEXT until the 2026-09-08 OceanOPS widening migrated it
    to DATE. The endpoint kept
    passing the value straight through. It went unnoticed because the
    module-level `_oceansites_cache` keeps serving the last string built while
    the column was still TEXT — the 500 appears only after a restart clears the
    cache, i.e. right after a deploy, when the layer silently stops loading:

        TypeError: Object of type date is not JSON serializable

    This test clears the cache first, so it exercises the build, not the cache.
    """
    import json

    from domains import sensors

    await _run_sync(monkeypatch, _SAMPLE)
    sensors._oceansites_cache = None  # a cold start, as after every deploy

    resp = await sensors.get_oceansites()
    payload = json.loads(resp.body)

    feats = payload["features"]
    assert len(feats) == 1, f"expected the one positioned station, got {len(feats)}"
    props = feats[0]["properties"]
    assert props["deploy_date"] == "2026-03-27", (
        f"deploy_date came back as {props['deploy_date']!r} — it must be an ISO "
        "string, not a date object the JSON encoder cannot take")
    assert props["deployment_count"] == 3
    assert props["country"] == "United States"
    assert props["wigos_id"] == "0-22000-2-5100007"
    assert props["sensor_models"] == "SEABIRD_SBE37, RDI Sentinel, PAINE"
