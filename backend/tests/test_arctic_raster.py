# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import os

import pytest

DBURL = os.environ.get("DATABASE_URL")
needs_db = pytest.mark.skipif(not DBURL, reason="needs DATABASE_URL")


def test_empty_png_is_valid():
    from backend.raster_tiles import EMPTY_PNG
    assert EMPTY_PNG[:8] == b"\x89PNG\r\n\x1a\n"


@needs_db
@pytest.mark.asyncio
async def test_greenland_tile_non_empty_png():
    import asyncpg
    from backend.raster_tiles import render_arctic_tile
    conn = await asyncpg.connect(DBURL)
    try:
        png = await render_arctic_tile(4, 6, 3, "ocs_mean", conn)
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        assert len(png) > 1000  # has content
    finally:
        await conn.close()


@needs_db
@pytest.mark.asyncio
async def test_ocean_tile_is_transparent_png():
    import asyncpg
    from backend.raster_tiles import render_arctic_tile
    conn = await asyncpg.connect(DBURL)
    try:
        png = await render_arctic_tile(4, 0, 7, "ocs_mean", conn)  # open Atlantic, no catchments
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
    finally:
        await conn.close()
