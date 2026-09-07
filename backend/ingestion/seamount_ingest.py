# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""
Seamount ingestion from PANGAEA (Yesson et al. 2020 — V2 update).

Source: Yesson, C; Letessier, TB; Nimmo-Smith, A; Hosegood, P;
        Brierley, AS; Hardouin, M; Proud, R (2020)
  - doi.org/10.1594/PANGAEA.921688  (37,889 seamounts, Shapefile)
  - Based on SRTM v.11 global bathymetry (improved over 2011's 30-arc-sec)

License: CC BY 4.0

Shapefile fields:
  PeakID  Depth  Height  X  Y  Type  Area2d  In2011  NBSFilter  Filter

In2011: 1 = also present in 2011 catalogue, 0 = newly discovered in V2.
Filter: 1 = non-overlapping base, 0 = overlapping base.
We import ALL features regardless of filter value.
"""

import asyncio
import io
import logging
import os
import sys
import tempfile
import zipfile

import httpx

# Allow running standalone: add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

log = logging.getLogger(__name__)

SEAMOUNT_ZIP_URL = "https://download.pangaea.de/dataset/921688/files/YessonEtAl2019-Seamounts-V2.zip"
SHAPEFILE_NAME = "YessonEtAl2019-Seamounts-V2"


def _parse_shapefile(zip_bytes: bytes) -> list[dict]:
    """Extract seamount records from the zipped shapefile."""
    import shapefile

    with tempfile.TemporaryDirectory() as tmpdir:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            zf.extractall(tmpdir)

        sf = shapefile.Reader(os.path.join(tmpdir, SHAPEFILE_NAME))
        rows = []
        for rec in sf.iterRecords():
            try:
                rows.append({
                    "peak_id": int(rec["PeakID"]),
                    # ⛔ The PANGAEA record (doi.org/10.1594/PANGAEA.921688) and its
                    # parent methods paper (Yesson et al. 2011, doi.org/10.1016/j.dsr.2011.02.004)
                    # describe summit depths only in prose ("summit depth of <1.5 km");
                    # neither publishes a field dictionary stating the shapefile
                    # `Depth` column's sign convention. abs() is OUR assumption, not
                    # theirs: a genuine height above the seafloor would be silently
                    # turned into a depth. Recorded rather than resolved - see
                    # docs/methods/data-passthrough.md.
                    "summit_depth_m": abs(int(rec["Depth"])),
                    "height_m": int(rec["Height"]),
                    "longitude": float(rec["X"]),
                    "latitude": float(rec["Y"]),
                    "area_km2": round(float(rec["Area2d"]), 2),
                    "in_2011": bool(rec["In2011"]),
                    "overlapping_base": rec["Filter"] == 0,
                })
            except (ValueError, KeyError) as e:
                log.warning("Skipping malformed record: %s — %s", rec, e)
        return rows


async def sync_seamounts(conn) -> tuple[int, int]:
    """Download seamounts V2 from PANGAEA and upsert into DB.

    Returns (fetched_count, inserted_count).
    Expects an active asyncpg connection.
    """
    async with httpx.AsyncClient(timeout=120) as client:
        log.info("Fetching seamounts V2 shapefile from PANGAEA...")
        resp = await client.get(SEAMOUNT_ZIP_URL)
        resp.raise_for_status()
        seamounts = _parse_shapefile(resp.content)
        log.info("Parsed %d seamounts", len(seamounts))

    fetched = len(seamounts)

    # Recreate table
    await conn.execute("DROP TABLE IF EXISTS seamounts_new")
    await conn.execute("""
        CREATE TABLE seamounts_new (
            id               SERIAL PRIMARY KEY,
            peak_id          INTEGER UNIQUE NOT NULL,
            summit_depth_m   INTEGER,
            height_m         INTEGER,
            longitude        DOUBLE PRECISION NOT NULL,
            latitude         DOUBLE PRECISION NOT NULL,
            area_km2         DOUBLE PRECISION,
            in_2011          BOOLEAN DEFAULT FALSE,
            overlapping_base BOOLEAN DEFAULT FALSE,
            geom             geography(Point, 4326),
            in_concession    BOOLEAN DEFAULT FALSE
        )
    """)

    # Batch insert
    await conn.executemany(
        """INSERT INTO seamounts_new
           (peak_id, summit_depth_m, height_m, longitude, latitude, area_km2,
            in_2011, overlapping_base, geom)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8,
                   ST_SetSRID(ST_MakePoint($4, $5), 4326)::geography)""",
        [(r["peak_id"], r["summit_depth_m"], r["height_m"],
          r["longitude"], r["latitude"], r["area_km2"],
          r["in_2011"], r["overlapping_base"]) for r in seamounts],
    )

    # Create spatial index BEFORE concession update (massive speedup for ST_Intersects)
    await conn.execute("DROP INDEX IF EXISTS seamounts_new_geom_idx")
    await conn.execute(
        "CREATE INDEX seamounts_new_geom_idx ON seamounts_new USING GIST (geom)"
    )

    # Update in_concession flag (uses spatial index)
    await conn.execute("""
        UPDATE seamounts_new s
        SET in_concession = TRUE
        FROM mining_contracts mc
        WHERE ST_Intersects(s.geom, mc.geom::geography)
    """)

    # Atomic swap
    await conn.execute("DROP TABLE IF EXISTS seamounts_old")
    await conn.execute("ALTER TABLE IF EXISTS seamounts RENAME TO seamounts_old")
    await conn.execute("ALTER TABLE seamounts_new RENAME TO seamounts")
    await conn.execute("DROP TABLE IF EXISTS seamounts_old")

    inserted = await conn.fetchval("SELECT COUNT(*) FROM seamounts")
    log.info("Seamounts table rebuilt: %d features (V2 dataset)", inserted)
    return fetched, inserted


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    import asyncpg
    from dotenv import load_dotenv
    load_dotenv()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set in environment or .env")
        sys.exit(1)
    conn = await asyncpg.connect(database_url)
    try:
        fetched, inserted = await sync_seamounts(conn)
        print(f"Done: fetched={fetched}, inserted={inserted}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
