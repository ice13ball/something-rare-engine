# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The seamount SEO query must not scan every contract polygon.

`mining_contracts.geom` is `geometry`; the SEO path asks
`ST_DWithin(mc.geom::geography, s.geom::geography, 10000)` because 10 000 means
metres only on a geography. That cast produces a value the plain
`USING GIST(geom)` index cannot serve, so Postgres fell back to a sequential
scan of all 1,318 contract polygons — computing a geodesic distance for each —
on every request, twice per page.

Measured on production 2026-09-18, `/v1/seo/seamount/4272884`:

    without idx_mining_contracts_geog   Seq Scan   41.9 ms   → endpoint 65 ms
    with it                             Index Scan  0.17 ms  → endpoint 3.9 ms

Googlebot crawling ~20 seamount pages a minute saturated the single backend
process; nginx logged 48 × 499 from the BFF and Google received 503s against
~37,900 seamount URLs.

⚠️ This test asserts the PLAN, not the timing. A duration test would be flaky
on a shared runner and would not say why it got slow; the plan says exactly
which index was used, and a missing index changes it.

⛔ `enable_seqscan` is left alone on purpose. Turning it off would force an
index scan and the test would pass with the index dropped — it would measure
the setting, not the schema.
"""
import os

import asyncpg
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)

# Enough rows that a sequential scan is genuinely the cheaper plan without an
# index — production has 1,318. With a handful of rows Postgres would pick a
# seq scan even WITH the index, and the test could not fail.
_CONTRACTS = 2000

_SEO_PREDICATE = """
    SELECT s.peak_id,
           EXISTS(
               SELECT 1 FROM mining_contracts mc
               WHERE ST_DWithin(mc.geom::geography, s.geom::geography, 10000)
           ) AS in_concession
      FROM seamounts s
     WHERE s.peak_id = $1
"""


@pytest.fixture
async def conn():
    c = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
    tx = c.transaction()
    await tx.start()
    try:
        yield c
    finally:
        await tx.rollback()          # nothing seeded here survives
        await c.close()


async def _seed(c):
    # `seamounts` is created by its ingest, not by the schema steps, so a CI
    # database may not have it — and a database where other tests ran may hold
    # a one-column stub (test_onc_seo_gate.py creates `seamounts(peak_id)`).
    # Both are made workable here, inside the transaction, so the rollback
    # leaves whichever of the two was there untouched.
    await c.execute("CREATE TABLE IF NOT EXISTS seamounts (peak_id INTEGER PRIMARY KEY)")
    await c.execute("ALTER TABLE seamounts ADD COLUMN IF NOT EXISTS height_m INTEGER")
    await c.execute("ALTER TABLE seamounts ADD COLUMN IF NOT EXISTS geom geography(Point, 4326)")

    # Contracts spread across the Pacific, one seamount 200 km from all of them.
    await c.execute(
        """
        INSERT INTO mining_contracts (isa_id, contractor_name, geom)
        SELECT 'TEST-' || g,
               'Test contractor',
               ST_SetSRID(ST_MakeEnvelope(
                   -170 + (g % 300) * 0.1, -20 + (g / 300.0) * 0.1,
                   -169.9 + (g % 300) * 0.1, -19.9 + (g / 300.0) * 0.1), 4326)::geometry
          FROM generate_series(1, $1) AS g
        """,
        _CONTRACTS,
    )
    await c.execute(
        """INSERT INTO seamounts (peak_id, height_m, geom)
           VALUES (999000001, 1200, ST_SetSRID(ST_MakePoint(-140.0, 10.0), 4326)::geography)"""
    )
    await c.execute("ANALYZE mining_contracts")
    await c.execute("ANALYZE seamounts")


async def _plan(c) -> str:
    rows = await c.fetch("EXPLAIN " + _SEO_PREDICATE.replace("$1", "999000001"))
    return "\n".join(r[0] for r in rows)


async def test_the_concession_check_uses_an_index_not_a_full_scan(conn):
    await _seed(conn)
    plan = await _plan(conn)
    assert "Seq Scan on mining_contracts" not in plan, (
        "the concession check scans every contract polygon:\n" + plan)
    assert "idx_mining_contracts_geog" in plan, (
        "no geography index in the plan — something else is carrying it:\n" + plan)


async def test_without_the_index_the_plan_is_the_slow_one(conn):
    """⛔ The control. Without it, a plan that never mentions a seq scan for
    some unrelated reason would let the assertion above pass on an unindexed
    database, and the guard would be measuring nothing.

    Dropped inside the transaction, so the index is back on rollback.
    """
    await _seed(conn)
    await conn.execute("DROP INDEX idx_mining_contracts_geog")
    plan = await _plan(conn)
    assert "Seq Scan on mining_contracts" in plan, (
        "dropping the geography index did NOT produce a sequential scan — the "
        "test above cannot fail, so it is not a guard:\n" + plan)


async def test_the_index_is_on_the_cast_not_the_plain_column(conn):
    """The plain GIST(geom) index already existed and did not help: the query
    asks about `geom::geography`, which is a different value."""
    defs = await conn.fetch(
        "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'mining_contracts'")
    by_name = {r["indexname"]: r["indexdef"] for r in defs}
    assert "idx_mining_contracts_geom" in by_name, "the geometry index disappeared"
    geog = by_name.get("idx_mining_contracts_geog", "")
    assert "geography" in geog, f"idx_mining_contracts_geog is not on the cast: {geog!r}"
