# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import os
import asyncpg
import pytest

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")

DS = "00000000-0000-0000-0000-000000000001"


async def _setup():
    from schema.plankton import ensure_plankton
    c = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
    tx = c.transaction()
    await tx.start()
    await ensure_plankton(c)
    await c.execute("INSERT INTO plankton_datasets (dataset_id, title, licence, licence_raw) "
                    f"VALUES ('{DS}','t','cc-by','CC-BY')")
    return c, tx


async def _rejected(c, exc, sql):
    """Run a statement that must fail, inside a savepoint so the outer tx survives."""
    with pytest.raises(exc):
        async with c.transaction():
            await c.execute(sql)


@needs_db
async def test_ensure_plankton_creates_both_tables_with_constraints():
    c, tx = await _setup()
    try:
        cols = {r["column_name"] for r in await c.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name='plankton_occurrences'")}
        assert {"taxon_group", "scientific_name", "aphia_id", "taxon_order", "dataset_id", "licence",
                "is_edna", "depth_m", "event_date", "year", "month", "lon", "lat", "geom"} <= cols
        with pytest.raises(asyncpg.CheckViolationError):
            await c.execute("INSERT INTO plankton_occurrences (taxon_group, dataset_id, licence, is_edna, lon, lat) "
                            f"VALUES ('jellyfish','{DS}','cc-by',false,1,1)")
    finally:
        await tx.rollback()
        await c.close()


@needs_db
async def test_geom_is_generated_from_lon_lat():
    c, tx = await _setup()
    try:
        await c.execute("INSERT INTO plankton_occurrences (taxon_group, dataset_id, licence, is_edna, lon, lat) "
                        f"VALUES ('copepoda','{DS}','cc-by',false,-20.5,55.25)")
        wkt = await c.fetchval("SELECT ST_AsText(geom) FROM plankton_occurrences")
        assert wkt == "POINT(-20.5 55.25)"
    finally:
        await tx.rollback()
        await c.close()


@needs_db
@pytest.mark.parametrize("lon,lat", [("NULL", "1"), ("1", "NULL")])
async def test_null_lon_or_lat_rejected(lon, lat):
    c, tx = await _setup()
    try:
        with pytest.raises(asyncpg.NotNullViolationError):
            await c.execute("INSERT INTO plankton_occurrences (taxon_group, dataset_id, licence, is_edna, lon, lat) "
                            f"VALUES ('copepoda','{DS}','cc-by',false,{lon},{lat})")
    finally:
        await tx.rollback()
        await c.close()


@needs_db
async def test_licence_not_null_and_restricted_rejected_in_both_tables():
    c, tx = await _setup()
    try:
        ins = ("INSERT INTO plankton_occurrences (taxon_group, dataset_id, licence, is_edna, lon, lat) "
               f"VALUES ('copepoda','{DS}',{{lic}},false,1,1)")
        await _rejected(c, asyncpg.NotNullViolationError, ins.format(lic="NULL"))
        await _rejected(c, asyncpg.CheckViolationError, ins.format(lic="'restricted'"))
        dsins = ("INSERT INTO plankton_datasets (dataset_id, licence) "
                 "VALUES ('00000000-0000-0000-0000-000000000002',{lic})")
        await _rejected(c, asyncpg.NotNullViolationError, dsins.format(lic="NULL"))
        await _rejected(c, asyncpg.CheckViolationError, dsins.format(lic="'restricted'"))
        for lic in ("cc0", "cc-by", "cc-by-sa", "cc-by-nc", "unknown"):
            await c.execute(ins.format(lic=f"'{lic}'"))
    finally:
        await tx.rollback()
        await c.close()


@needs_db
async def test_depth_may_be_null_and_ensure_is_idempotent():
    from schema.plankton import ensure_plankton
    c, tx = await _setup()
    try:
        await ensure_plankton(c)
        await c.execute("INSERT INTO plankton_occurrences (taxon_group, dataset_id, licence, is_edna, lon, lat) "
                        f"VALUES ('diatoms','{DS}','cc0',true,1,1)")
        assert await c.fetchval("SELECT depth_m FROM plankton_occurrences") is None
    finally:
        await tx.rollback()
        await c.close()
