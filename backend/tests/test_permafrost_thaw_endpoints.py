# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Executes the permafrost-thaw bulk and /by-id endpoints against real PostGIS.

Split shipped 2026-09-08 to keep the bulk GeoJSON under Cloud Run's 32 MiB proxy
limit: imagery/authors/source_doi/data_source_type/obs_start/obs_end moved from
GET /v2/map/permafrost-thaw to GET /v2/map/permafrost-thaw/by-id/{unique_id}.
These tests run the actual endpoint functions against a real
`permafrost_thaw_features` table (`CREATE TABLE IF NOT EXISTS`, same column
names/types as `ensure_land_schema` in schema_orchestrator.py — that function
itself is not called here because it unconditionally runs
`ALTER TABLE ... OWNER TO abyssal_user`, a production-only ownership fixup
that assumes a role this test's DB user need not have), not just the SQL
strings.
"""
import json
import os

import pytest
from fastapi import HTTPException

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)

_UID = "test-permafrost-by-id-known-1"


@pytest.fixture
async def pool_and_endpoints():
    import asyncpg
    import db
    from domains.land import arctic

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    async with pool.acquire() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS permafrost_thaw_features (
                   id SERIAL PRIMARY KEY,
                   source TEXT NOT NULL,
                   unique_id TEXT NOT NULL,
                   feature_name TEXT,
                   feature_type TEXT,
                   feature_category TEXT,
                   thaw_type TEXT,
                   data_source_type TEXT,
                   authors TEXT,
                   source_doi TEXT,
                   imagery TEXT,
                   obs_start_year INTEGER,
                   obs_end_year INTEGER,
                   obs_start DATE,
                   obs_end DATE,
                   date_precision TEXT,
                   contribution_date DATE,
                   lat DOUBLE PRECISION NOT NULL,
                   lon DOUBLE PRECISION NOT NULL,
                   geom GEOMETRY(Point, 4326),
                   synced_at TIMESTAMPTZ DEFAULT NOW()
               )"""
        )
        await conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS permafrost_thaw_features_src_uid_uidx "
            "ON permafrost_thaw_features (source, unique_id)"
        )

    original_pool = db.pool
    db.pool = pool

    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO permafrost_thaw_features
                 (source, unique_id, feature_name, feature_type, feature_category,
                  thaw_type, data_source_type, authors, source_doi, imagery,
                  obs_start_year, obs_end_year, obs_start, obs_end, date_precision,
                  contribution_date, lat, lon, geom)
               VALUES
                 ('alaska_webb', $1, 'Known Site', 'thermokarst lake', 'Thermokarst Lake',
                  'abrupt', 'Field - unpublished', 'Webb et al. (2025)', '10.1/known-doi',
                  'aerial imagery 1985-2015',
                  1985, 2015, '1985-06-01', '2015-08-15', 'campaign',
                  '2024-01-10', 65.0, -150.0, ST_SetSRID(ST_MakePoint(-150.0, 65.0), 4326))
               ON CONFLICT (source, unique_id) DO NOTHING""",
            _UID,
        )

    arctic.clear_caches()
    try:
        yield arctic
    finally:
        arctic.clear_caches()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM permafrost_thaw_features WHERE unique_id = $1", _UID
            )
        db.pool = original_pool
        await pool.close()


@pytest.mark.asyncio
async def test_by_id_returns_detail_fields_for_known_unique_id(pool_and_endpoints):
    arctic = pool_and_endpoints
    detail = await arctic.permafrost_thaw_by_id(_UID)

    assert detail["imagery"] == "aerial imagery 1985-2015"
    assert detail["authors"] == "Webb et al. (2025)"
    assert detail["source_doi"] == "10.1/known-doi"
    assert detail["data_source_type"] == "Field - unpublished"
    assert detail["obs_start"] == "1985-06-01"
    assert detail["obs_end"] == "2015-08-15"


@pytest.mark.asyncio
async def test_by_id_404s_for_unknown_unique_id(pool_and_endpoints):
    arctic = pool_and_endpoints
    with pytest.raises(HTTPException) as exc_info:
        await arctic.permafrost_thaw_by_id("does-not-exist-" + _UID)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_bulk_response_no_longer_carries_the_moved_fields(pool_and_endpoints):
    arctic = pool_and_endpoints
    response = await arctic.get_permafrost_thaw()
    fc = json.loads(response.body)
    feat = next(f for f in fc["features"] if f["properties"]["unique_id"] == _UID)
    props = feat["properties"]

    for moved in ("imagery", "authors", "source_doi", "data_source_type", "obs_start", "obs_end"):
        assert moved not in props, f"{moved} should have moved to /by-id but is still in bulk properties"

    for kept in ("unique_id", "feature_name", "feature_category", "thaw_type", "source",
                 "feature_type", "date_precision", "obs_start_year", "obs_end_year"):
        assert kept in props, f"{kept} should still be in bulk properties"

    assert props["obs_start_year"] == 1985
    assert props["obs_end_year"] == 2015


@pytest.mark.asyncio
async def test_source_disambiguates_a_shared_unique_id(pool_and_endpoints):
    """The row's real key is (source, unique_id) — that is what the unique index
    is on. `unique_id` alone is globally unique in production TODAY, but nothing
    enforces it, so the endpoint must be correct the day that stops being true."""
    arctic = pool_and_endpoints
    import db

    async with db.pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO permafrost_thaw_features
                 (source, unique_id, feature_name, authors, lat, lon, geom)
               VALUES ('arts_panarctic', $1, 'Colliding Site', 'Someone Else (2026)',
                       66.0, -151.0, ST_SetSRID(ST_MakePoint(-151.0, 66.0), 4326))
               ON CONFLICT (source, unique_id) DO NOTHING""",
            _UID,
        )

    alaska = await arctic.permafrost_thaw_by_id(_UID, source="alaska_webb")
    arts = await arctic.permafrost_thaw_by_id(_UID, source="arts_panarctic")

    assert alaska["authors"] == "Webb et al. (2025)"
    assert arts["authors"] == "Someone Else (2026)"


@pytest.mark.asyncio
async def test_an_ambiguous_id_without_source_is_a_409_not_a_guess(pool_and_endpoints):
    """⛔ Returning row zero here would be a silent wrong answer — the popup would
    show another feature's provenance and nothing anywhere would report it. A 409
    is a bug that someone can see."""
    arctic = pool_and_endpoints
    import db

    async with db.pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO permafrost_thaw_features
                 (source, unique_id, feature_name, authors, lat, lon, geom)
               VALUES ('arts_panarctic', $1, 'Colliding Site', 'Someone Else (2026)',
                       66.0, -151.0, ST_SetSRID(ST_MakePoint(-151.0, 66.0), 4326))
               ON CONFLICT (source, unique_id) DO NOTHING""",
            _UID,
        )

    with pytest.raises(HTTPException) as exc_info:
        await arctic.permafrost_thaw_by_id(_UID)
    assert exc_info.value.status_code == 409
