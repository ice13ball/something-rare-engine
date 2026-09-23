# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""A re-sync must move `chess_occurrences.lat`/`lon`, not only `geom`.

⛔ WHY THIS EXISTS. The `ON CONFLICT DO UPDATE` in `sync_chess` used to refresh
`geom` while leaving `lat` and `lon` alone. A row whose source coordinate had
changed therefore ended up holding two contradictory positions at once.

Measured on production 2026-09-22, after the ChEssBase coordinate override was
removed and the layer re-synced — gbifID `5789994787`:

    geom     33.3500 / -117.3000   (the coordinate ChEssBase publishes)
    lat/lon  32.5833 / -117.4833   (the override, written months earlier)

`/v1/map/chess` selects `AVG(lat)`/`AVG(lon)`, so the map went on serving a
position the ingestion had already stopped producing. The code change was live,
the data was not, and nothing anywhere reported a problem.

⚠️ This test drives the real `sync_chess` against a real PostGIS. It stubs only
the network fetch. Asserting on the SQL text instead would pass against any
statement that merely mentions the columns.
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)

# A synthetic id far outside the GBIF range, so a stray production row can
# never satisfy this test and nothing real is ever touched.
TEST_ID = "test-chess-upsert-900001"

FIRST = {
    "occurrence_id": TEST_ID, "species": "Bathymodiolus azoricus",
    "phylum": "Mollusca", "class_name": "Bivalvia", "family": "Mytilidae",
    "depth_m": 850.0, "lat": 37.8417, "lon": -31.5250,
    "locality": "Menez Gwen", "institution_code": "FIRST",
}
# Same record, every source-supplied field changed.
SECOND = {
    **FIRST,
    "species": "Alvinocaris williamsi", "phylum": "Arthropoda",
    "class_name": "Malacostraca", "family": "Alvinocarididae",
    "depth_m": 1700.0, "lat": 30.1250, "lon": -42.1183,
    "locality": "Lost City", "institution_code": "SECOND",
}


@pytest.fixture
async def pool():
    import asyncpg
    import db as _db

    _db.pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    from schema.biodiversity import ensure_vents_and_chess
    async with _db.pool.acquire() as c:
        await ensure_vents_and_chess(c)
        await c.execute("DELETE FROM chess_occurrences WHERE occurrence_id = $1", TEST_ID)
    yield _db.pool
    async with _db.pool.acquire() as c:
        await c.execute("DELETE FROM chess_occurrences WHERE occurrence_id = $1", TEST_ID)
    await _db.pool.close()


async def _sync_with(monkeypatch, records):
    """Run the real sync_chess; only the network fetch is replaced."""
    from ingestion import chess_ingest
    from domains import biodiversity

    async def _fake_fetch():
        return [dict(r) for r in records]

    monkeypatch.setattr(chess_ingest, "fetch_chess_occurrences", _fake_fetch)
    await biodiversity.sync_chess()


async def _read(pool):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """SELECT species, phylum, class_name, family, depth_m,
                      lat, lon, locality, institution_code,
                      ST_Y(geom) AS geom_lat, ST_X(geom) AS geom_lon
               FROM chess_occurrences WHERE occurrence_id = $1""",
            TEST_ID,
        )


async def test_resync_moves_the_coordinate_columns(pool, monkeypatch):
    await _sync_with(monkeypatch, [FIRST])
    before = await _read(pool)
    assert before["lat"] == pytest.approx(37.8417)

    await _sync_with(monkeypatch, [SECOND])
    after = await _read(pool)

    assert after["lat"] == pytest.approx(SECOND["lat"]), (
        "lat kept its old value across a re-sync — the ON CONFLICT DO UPDATE "
        "has stopped refreshing the coordinate columns"
    )
    assert after["lon"] == pytest.approx(SECOND["lon"])


async def test_geometry_and_columns_never_disagree(pool, monkeypatch):
    """The defect's signature: one row, two positions."""
    await _sync_with(monkeypatch, [FIRST])
    await _sync_with(monkeypatch, [SECOND])
    row = await _read(pool)

    assert row["lat"] == pytest.approx(row["geom_lat"], abs=1e-9), (
        f"row holds two latitudes at once: column {row['lat']}, "
        f"geometry {row['geom_lat']}"
    )
    assert row["lon"] == pytest.approx(row["geom_lon"], abs=1e-9)


async def test_every_source_field_is_refreshed(pool, monkeypatch):
    """Coordinates were not the only stale columns."""
    await _sync_with(monkeypatch, [FIRST])
    await _sync_with(monkeypatch, [SECOND])
    row = await _read(pool)

    stale = {
        field: (row[field], SECOND[key])
        for field, key in (
            ("species", "species"), ("phylum", "phylum"),
            ("class_name", "class_name"), ("family", "family"),
            ("depth_m", "depth_m"), ("locality", "locality"),
            ("institution_code", "institution_code"),
        )
        if row[field] != SECOND[key]
    }
    assert not stale, f"columns kept their first-sync value: {stale}"
