# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""A float must never be drawn where the source does not know it was.

Reported from the live map 2026-09-09: some Argo trails ran as dead-straight
lines across the whole Pacific. Measured on production: 80 consecutive-profile
segments longer than 1,000 km inside the 90-day window, the longest 18,549 km
— covered in six days, by a float that drifts a few km a day.

Every one of them touched the literal coordinate (0, -90), the South Pole.
That is Argo's placeholder for a fix it does not have; under-ice Arctic floats
surface without GPS. Argovis carries the reason in `geolocation_argoqc`
(4 bad, 9 missing, 8 interpolated) — a field our ingest never read, because it
asked for `position_qc`, which Argovis does not have and returns as None.

Measured over 15,567 August 2026 profiles at the source: 147 carried (0, -90),
and all 147 had flag 9 (137) or 4 (10). Not one was a real position.

The profile keeps its row, its date and its measurements — those are real,
taken somewhere unknown. Only the position claim is withheld.
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)

_NOW = datetime.now(timezone.utc)


def _profile(pid: str, lon: float, lat: float, qc, days_ago: int) -> dict:
    """An Argovis profile as the API actually shapes one."""
    return {
        "_id": pid,
        "timestamp": (_NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "geolocation": {"type": "Point", "coordinates": [lon, lat]},
        "geolocation_argoqc": qc,
        # Argovis is COLUMN-major: data[i] is every depth level for variable i,
        # named by data_info[0][i]. Two levels here: 10 dbar and 1500 dbar.
        "data": [
            [10.0, 1500.0],   # pressure
            [5.0, 2.0],       # temperature
            [34.5, 34.6],     # salinity
        ],
        "data_info": [["pressure", "temperature", "salinity"], [], []],
    }


@pytest.fixture
async def pool():
    import asyncpg
    import db as _db
    import schema

    _db.pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    await schema.ensure_schema()
    async with _db.pool.acquire() as c:
        await c.execute("DELETE FROM argo_profiles WHERE platform_id = '9999001'")
    yield _db.pool
    async with _db.pool.acquire() as c:
        await c.execute("DELETE FROM argo_profiles WHERE platform_id = '9999001'")
    await _db.pool.close()


async def _insert(conn, pid, lon, lat, qc, days_ago):
    await conn.execute(
        """INSERT INTO argo_profiles
               (profile_id, platform_id, profile_date, max_depth_m,
                surface_temp_c, surface_salinity, deep_temp_c, deep_salinity,
                deep_pressure_m, temp_qc, sal_qc, position_qc, geom)
           VALUES ($1, $2, $3, 1000, 5.0, 34.5, 2.0, 34.6, 1000, 1, 1, $4,
                   ST_SetSRID(ST_MakePoint($5, $6), 4326))
           ON CONFLICT (profile_id) DO NOTHING""",
        pid, pid.split("_")[0], _NOW - timedelta(days=days_ago), qc, lon, lat)


@pytest.mark.asyncio
async def test_the_south_pole_placeholder_is_not_served_as_a_position(pool):
    from domains import sensors

    async with pool.acquire() as conn:
        await _insert(conn, "9999001_001", -140.0, 74.0, 1, 20)   # real Arctic fix
        await _insert(conn, "9999001_002",    0.0, -90.0, 9, 14)  # missing fix
        await _insert(conn, "9999001_003", -141.0, 74.2, 1, 8)    # real again
        await sensors.populate_argo_cache(conn)

    trail = sensors._argo_trail_cache.get("9999001") or []
    ids = [t["profile_id"] for t in trail]

    assert ids == ["9999001_001", "9999001_003"], (
        f"trail served {ids}. The (0, -90) placeholder is being drawn as a "
        "position, so the float's track runs from the Beaufort Sea to the South "
        "Pole and back.")


@pytest.mark.asyncio
async def test_the_row_and_its_measurements_are_kept(pool):
    """⛔ Withhold the position claim, not the profile."""
    async with pool.acquire() as conn:
        await _insert(conn, "9999001_002", 0.0, -90.0, 9, 14)
        row = await conn.fetchrow(
            "SELECT surface_temp_c, deep_salinity, profile_date, position_qc "
            "FROM argo_profiles WHERE profile_id = '9999001_002'")

    assert row is not None, "the profile was deleted instead of having its position withheld"
    assert row["surface_temp_c"] == 5.0, "a real measurement was thrown away with the bad fix"
    assert row["deep_salinity"] == 34.6
    assert row["position_qc"] == 9, "the reason the position is unusable was not recorded"


@pytest.mark.asyncio
async def test_an_interpolated_under_ice_position_is_still_served(pool):
    """Flag 8 is the best position that exists for that profile, not a bad one."""
    from domains import sensors

    async with pool.acquire() as conn:
        await _insert(conn, "9999001_004", -139.0, 73.5, 8, 10)
        await sensors.populate_argo_cache(conn)

    trail = sensors._argo_trail_cache.get("9999001") or []
    assert [t["profile_id"] for t in trail] == ["9999001_004"], (
        "an interpolated under-ice track was dropped — that hides the float "
        "entirely rather than showing its estimated position")
    assert trail[0]["position_qc"] == 8, "the flag does not travel with the row"


@pytest.mark.asyncio
async def test_rows_predating_the_column_are_still_served(pool):
    """NULL means 'never asked', and 281k stored rows are in that state."""
    from domains import sensors

    async with pool.acquire() as conn:
        await _insert(conn, "9999001_005", -20.0, 30.0, None, 10)
        await sensors.populate_argo_cache(conn)

    trail = sensors._argo_trail_cache.get("9999001") or []
    assert [t["profile_id"] for t in trail] == ["9999001_005"], (
        "profiles with no recorded position flag were hidden — that withholds "
        "the whole pre-existing archive to suppress a handful of bad fixes")


@pytest.mark.asyncio
async def test_ingest_stamps_the_flag_and_infers_it_from_the_placeholder(pool):
    """⛔ Even if a future feed drops geolocation_argoqc, (0,-90) is not a place."""
    from domains import sensors

    profiles = [
        _profile("9999001_010", -140.0, 74.0, 1, 20),
        _profile("9999001_011", 0.0, -90.0, 9, 14),
        _profile("9999001_012", 0.0, -90.0, None, 12),   # flag missing entirely
    ]
    await sensors._upsert_argo_profiles(profiles, ["temperature", "salinity"])

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT profile_id, position_qc FROM argo_profiles "
            "WHERE platform_id = '9999001' ORDER BY profile_id")

    got = {r["profile_id"]: r["position_qc"] for r in rows}
    assert got.get("9999001_010") == 1, f"a good fix was mis-flagged: {got}"
    assert got.get("9999001_011") == 9, f"the source flag was not stored: {got}"
    assert got.get("9999001_012") == 9, (
        f"a (0, -90) with no flag was stored as a usable position: {got}. The "
        "coordinate itself has to be enough — the flag is not guaranteed.")
