# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""What sync_oceansites_obs leaves in the table, run against real PostGIS.

⛔ "Missing" and "broken" must not share a code path. On 2026-10-01 the
OceanSITES GDAC server answered 503 to everything, including its front page,
and the sync — which only ever saw an empty result — wiped the five readings
GDAC had fed, exactly as if those moorings had stopped transmitting. A source
that is down says nothing about its moorings, so they keep their last reading;
it carries its own obs_time and the panel marks it stale.

The same run must still clear what genuinely has nothing: a mooring NDBC
answered for with no file (NDBC is per-station, a 404 is an answer), and any
mooring no longer OPERATIONAL (0N10W and 15N90E kept July/August readings).
"""
import json
import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)

_OLD = {"obs_time": "2026-09-29T12:00:00Z", "wtmp": 20.0}


@pytest.fixture
async def pool():
    import asyncpg
    import db as _db
    import schema

    _db.pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    await schema.ensure_schema()
    async with _db.pool.acquire() as c:
        await c.execute("DELETE FROM oceansites_stations")
        rows = [
            # ref,       name,     status,        lat,   lon,     previous source
            ("1500009", "00N03",  "OPERATIONAL", 0.0,  -3.0,    None),    # NDBC by WMO
            ("GDACSTN", "STRATUS", "OPERATIONAL", -20.0, -85.0,  "GDAC"),  # GDAC fed it
            ("PMELSTN", "0N110W", "OPERATIONAL", 0.0,  -110.0,  "PMEL"),  # PMEL fed it
            ("1500077", "NDBCGONE", "OPERATIONAL", 5.0, -5.0,    "NDBC"),  # NDBC: no file now
            ("1500002", "0N10W",  "INACTIVE",    0.0,  -10.0,   "PMEL"),  # retired
        ]
        for ref, name, status, lat, lon, src in rows:
            await c.execute(
                """INSERT INTO oceansites_stations
                       (ref, name, status, lat, lon, geom, latest_obs, obs_source)
                   VALUES ($1, $2, $3, $4, $5, ST_SetSRID(ST_MakePoint($5, $4), 4326),
                           $6::jsonb, $7)""",
                ref, name, status, lat, lon,
                json.dumps(_OLD) if src else None, src,
            )
    yield _db.pool
    async with _db.pool.acquire() as c:
        await c.execute("DELETE FROM oceansites_stations")
    await _db.pool.close()


def _fakes(monkeypatch, *, pmel, gdac_up, gdac=None):
    from domains import sensors
    from ingestion import ndbc_realtime, oceansites_gdac, pmel_erddap

    async def ndbc(client, ref, lat, lon):
        if ref == "1500009":
            return {"obs_time": "2026-10-01 09:00Z", "wtmp": 26.0, "ndbc_station": "15009"}
        return None

    async def pmel_fetch(lookback_days: int = 365):
        if isinstance(pmel, Exception):
            raise pmel
        return pmel

    async def reachable(timeout: float = 20.0):
        return gdac_up

    async def gdac_fetch(names):
        return gdac or {}

    async def no_log(*a, **k):
        return None

    monkeypatch.setattr(ndbc_realtime, "fetch_ndbc_observation", ndbc)
    monkeypatch.setattr(pmel_erddap, "fetch_pmel_observations", pmel_fetch)
    monkeypatch.setattr(oceansites_gdac, "gdac_reachable", reachable)
    monkeypatch.setattr(oceansites_gdac, "fetch_gdac_observations", gdac_fetch)
    monkeypatch.setattr(sensors, "_log_sync", no_log)
    return sensors


async def _state(pool):
    async with pool.acquire() as c:
        rows = await c.fetch("SELECT ref, obs_source, latest_obs FROM oceansites_stations")
    return {r["ref"]: (r["obs_source"], json.loads(r["latest_obs"]) if r["latest_obs"] else None)
            for r in rows}


async def test_a_source_that_is_down_keeps_the_readings_it_fed(pool, monkeypatch):
    sensors = _fakes(monkeypatch, pmel=RuntimeError("PMEL 503"), gdac_up=False)
    await sensors.sync_oceansites_obs()
    s = await _state(pool)

    assert s["GDACSTN"] == ("GDAC", _OLD)
    assert s["PMELSTN"] == ("PMEL", _OLD)
    # what had a real answer is still written or cleared
    assert s["1500009"][0] == "NDBC" and s["1500009"][1]["ndbc_station"] == "15009"
    assert s["1500077"] == (None, None)
    assert s["1500002"] == (None, None)


async def test_a_source_that_answers_with_nothing_clears_its_moorings(pool, monkeypatch):
    sensors = _fakes(monkeypatch, pmel={"5n95w": {"obs_time": "2026-09-30", "wtmp": 27.0}},
                     gdac_up=True, gdac={})
    await sensors.sync_oceansites_obs()
    s = await _state(pool)

    assert s["GDACSTN"] == (None, None)
    assert s["PMELSTN"] == (None, None)
    assert s["1500002"] == (None, None)
