# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""GET /v1/game/block/{isa_id} — public game endpoint.

Auth: anon_client pattern from test_auth_hardening.py (no DB). DB cases use
the pangaea_water_helpers `conn` fixture (rolled-back transaction installed as
db.pool) plus an httpx AsyncClient against main.app with
dependency_overrides[get_api_key] so the auth Depends still executes on every
call (including cache hits) without needing a real API key.
"""
from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

import auth as backend_auth
import db
import main
from domains import game
from pangaea_water_helpers import conn, needs_db  # noqa: F401  (conn is a fixture)


class _FakePool:
    def acquire(self):
        raise AssertionError("DB should not be touched for the anon (no API key) case")


@pytest.fixture
def anon_client(monkeypatch):
    monkeypatch.setattr(db, "pool", _FakePool())
    return AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test")


@pytest.fixture(autouse=True)
def _clear_game_cache():
    game.clear_caches()
    yield
    game.clear_caches()


@pytest.mark.asyncio
async def test_no_api_key_is_rejected(anon_client):
    async with anon_client as client:
        r = await client.get("/v1/game/block/ISA-TEST-1")
        assert r.status_code in (401, 403)


@pytest.fixture
async def authed_client(conn):
    main.app.dependency_overrides[backend_auth.get_api_key] = lambda: "test-key"
    try:
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
            yield client
    finally:
        main.app.dependency_overrides.pop(backend_auth.get_api_key, None)


NODULE_MULTIPOLYGON = (
    "SRID=4326;MULTIPOLYGON(((150 10, 151 10, 151 11, 150 11, 150 10)))"
)
SULPHIDE_MULTIPOLYGON = (
    "SRID=4326;MULTIPOLYGON(((10 10, 11 10, 11 11, 10 11, 10 10)))"
)
APEI_POLYGON_1 = "SRID=4326;POLYGON((150 5, 151 5, 151 6, 150 6, 150 5))"
APEI_POLYGON_2 = "SRID=4326;POLYGON((160 5, 161 5, 161 6, 160 6, 160 5))"


@pytest.fixture
async def seeded(conn):
    await conn.execute(
        """INSERT INTO mining_contracts (isa_id, contractor_name, resource_type, area_km2, geom)
           VALUES ($1, $2, $3, $4, ST_GeomFromEWKT($5))""",
        "ISA-NODULE-1", "Secret Contractor Ltd", "Polymetallic Manganese Nodules", 75000.0,
        NODULE_MULTIPOLYGON,
    )
    await conn.execute(
        """INSERT INTO mining_contracts (isa_id, contractor_name, resource_type, area_km2, geom)
           VALUES ($1, $2, $3, $4, ST_GeomFromEWKT($5))""",
        "ISA-SULPHIDE-1", "Other Contractor Inc", "Polymetallic Sulphides", 1000.0,
        SULPHIDE_MULTIPOLYGON,
    )
    await conn.execute(
        """INSERT INTO isa_apeis (arcgis_id, area_km2, status, remarks, geom)
           VALUES ($1, $2, $3, $4, ST_GeomFromEWKT($5))""",
        1, 400000.0, "Established", "First APEI", APEI_POLYGON_1,
    )
    await conn.execute(
        """INSERT INTO isa_apeis (arcgis_id, area_km2, status, remarks, geom)
           VALUES ($1, $2, $3, $4, ST_GeomFromEWKT($5))""",
        2, 410000.0, "Established", "Second APEI", APEI_POLYGON_2,
    )
    await conn.execute(
        """INSERT INTO sync_log (source, last_synced_at, records_added, total_records)
           VALUES ('mining_contracts', '2026-01-01T00:00:00Z', 2, 2)"""
    )
    await conn.execute(
        """INSERT INTO sync_log (source, last_synced_at, records_added, total_records)
           VALUES ('apeis', '2026-06-15T12:00:00Z', 2, 2)"""
    )
    return conn


@needs_db
@pytest.mark.asyncio
async def test_shape_and_no_leaked_fields(seeded, authed_client):
    r = await authed_client.get("/v1/game/block/ISA-NODULE-1")
    assert r.status_code == 200
    body = r.json()

    blocks = [f for f in body["features"] if f["properties"]["kind"] == "block"]
    apeis = [f for f in body["features"] if f["properties"]["kind"] == "apei"]
    assert len(blocks) == 1
    assert len(apeis) == 2

    assert set(blocks[0]["properties"].keys()) == {
        "kind", "isa_id", "resource_type", "area_km2", "centroid_lon", "centroid_lat",
    }

    raw = r.content
    for forbidden in (b"Secret Contractor Ltd", b"contractor_name", b"jurisdiction", b"nearest_"):
        assert forbidden not in raw, f"{forbidden!r} leaked into the response"

    assert body["meta"]["synced_at"] == "2026-06-15T12:00:00+00:00"


@needs_db
@pytest.mark.asyncio
async def test_unknown_id_is_404(seeded, authed_client):
    r = await authed_client.get("/v1/game/block/NO-SUCH-ID")
    assert r.status_code == 404


@needs_db
@pytest.mark.asyncio
async def test_sulphide_block_is_400(seeded, authed_client):
    r = await authed_client.get("/v1/game/block/ISA-SULPHIDE-1")
    assert r.status_code == 400


@needs_db
@pytest.mark.asyncio
async def test_second_call_is_a_cache_hit_and_stale_data_survives(seeded, authed_client):
    # A cache hit must still pass through the key check: that is what makes it
    # count toward the game key's quota.
    auth_calls = []
    main.app.dependency_overrides[backend_auth.get_api_key] = lambda: auth_calls.append(1) or "test-key"

    r1 = await authed_client.get("/v1/game/block/ISA-NODULE-1")
    assert r1.status_code == 200
    assert r1.headers["X-Cache"] == "MISS"

    await seeded.execute(
        "UPDATE mining_contracts SET area_km2 = 999999 WHERE isa_id = $1", "ISA-NODULE-1"
    )

    r2 = await authed_client.get("/v1/game/block/ISA-NODULE-1")
    assert r2.status_code == 200
    assert r2.headers["X-Cache"] == "HIT"
    assert r2.content == r1.content
    assert len(auth_calls) == 2


@needs_db
@pytest.mark.asyncio
async def test_404_is_never_cached(seeded, authed_client):
    r1 = await authed_client.get("/v1/game/block/WILL-EXIST-SOON")
    assert r1.status_code == 404

    await seeded.execute(
        """INSERT INTO mining_contracts (isa_id, contractor_name, resource_type, area_km2, geom)
           VALUES ($1, $2, $3, $4, ST_GeomFromEWKT($5))""",
        "WILL-EXIST-SOON", "New Contractor", "Polymetallic Manganese Nodules", 500.0,
        NODULE_MULTIPOLYGON,
    )

    r2 = await authed_client.get("/v1/game/block/WILL-EXIST-SOON")
    assert r2.status_code == 200
    assert r2.headers["X-Cache"] == "MISS"
    blocks = [f for f in r2.json()["features"] if f["properties"]["kind"] == "block"]
    assert [b["properties"]["isa_id"] for b in blocks] == ["WILL-EXIST-SOON"]


@needs_db
@pytest.mark.asyncio
async def test_clear_caches_forces_a_miss(seeded, authed_client):
    r1 = await authed_client.get("/v1/game/block/ISA-NODULE-1")
    assert r1.headers["X-Cache"] == "MISS"

    r2 = await authed_client.get("/v1/game/block/ISA-NODULE-1")
    assert r2.headers["X-Cache"] == "HIT"

    game.clear_caches()

    r3 = await authed_client.get("/v1/game/block/ISA-NODULE-1")
    assert r3.headers["X-Cache"] == "MISS"
