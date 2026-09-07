# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import os
import pytest

TEST_DB = os.getenv("TEST_DATABASE_URL")


@pytest.mark.asyncio
@pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")
async def test_schema_and_upsert_roundtrip():
    import asyncpg
    pool = await asyncpg.create_pool(TEST_DB, min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS worms_taxa (aphia_id INTEGER PRIMARY KEY, scientificname TEXT, is_marine SMALLINT);
                CREATE TABLE IF NOT EXISTS taxon_name_map (
                    raw_name TEXT PRIMARY KEY,
                    matched_aphia_id INTEGER REFERENCES worms_taxa(aphia_id) ON DELETE SET NULL,
                    match_type TEXT, verified BOOLEAN);
            """)
            await conn.execute("DELETE FROM taxon_name_map WHERE raw_name LIKE 'test-%'")
            await conn.execute("INSERT INTO worms_taxa (aphia_id, scientificname, is_marine) VALUES (106807,'Munidopsis',1) ON CONFLICT DO NOTHING")
            await conn.execute(
                "INSERT INTO taxon_name_map (raw_name, matched_aphia_id, match_type, verified) "
                "VALUES ('test-Munidopsis', 106807, 'exact', TRUE) ON CONFLICT (raw_name) DO NOTHING")
            # JOIN shape the consumers will use
            row = await conn.fetchrow(
                "SELECT w.scientificname AS valid_name, m.verified "
                "FROM taxon_name_map m JOIN worms_taxa w ON w.aphia_id = m.matched_aphia_id "
                "WHERE m.raw_name = 'test-Munidopsis'")
            assert row["valid_name"] == "Munidopsis" and row["verified"] is True
            await conn.execute("DELETE FROM taxon_name_map WHERE raw_name = 'test-Munidopsis'")
    finally:
        await pool.close()
