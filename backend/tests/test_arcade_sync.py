# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

# backend/tests/test_arcade_sync.py
"""DB-gated reprojection test for the ARCADE arctic_catchments ingest.

Skipped automatically when DATABASE_URL is not set (CI without PostGIS).
"""
import os
import pytest

DBURL = os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DBURL, reason="needs DATABASE_URL")


@pytest.mark.asyncio
async def test_easegrid_reprojects_into_arctic_latlon():
    """A small EASE-Grid 2.0 North polygon reprojects to the Northern Hemisphere."""
    import asyncpg
    conn = await asyncpg.connect(DBURL)
    try:
        # A triangle near the EASE-Grid origin (metres around the North Pole).
        # The fixture gid=1 has center_lat ~66.503, center_lon ~179.934, so any
        # polar point should land in lat 40–90 after ST_Transform(…,4326).
        row = await conn.fetchrow("""
            SELECT ST_Y(ST_Centroid(ST_Transform(ST_SetSRID(
              ST_GeomFromText($1),6931),4326))) AS lat
        """, "MULTIPOLYGON(((-100000 100000, -99000 100000, -99000 101000, -100000 100000)))")
        assert 40 < row["lat"] < 90, f"Expected Northern Hemisphere lat, got {row['lat']}"
    finally:
        await conn.close()
