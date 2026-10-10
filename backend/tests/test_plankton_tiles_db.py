# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""Tile SQL: exact server-side filtering per combination, zoom bands, version + bytes in one statement."""
import asyncpg
import mapbox_vector_tile
import pytest

from plankton_helpers import conn, needs_db, row, seed_live, tile_of  # noqa: F401
from services import plankton_tiles as tiles

S1, S2, S3, S4 = (10.2, 50.2), (10.7, 50.2), (10.45, 50.6), (12.2, 50.2)


def _rows():
    return ([row("copepoda", *S1, year=1995, depth=50.0)] * 3 + [row("diatoms", *S1, year=2015, depth=50.0)] * 2
            + [row("copepoda", *S2, year=2012, depth=50.0)]
            + [row("dinoflagellates", *S3, year=2015, edna=True)] * 2
            + [row("diatoms", *S4, year=2001), row("copepoda", *S4, year=2001)])


async def _feats(conn, lon, lat, z, **flt):
    x, y = tile_of(lon, lat, z)
    return await tiles.tile_features(conn, z, x, y, tiles.parse_filter(**flt))


def _at(feats, lon, lat):
    return [f for f in feats if abs(f["lon"] - lon) < 1e-6 and abs(f["lat"] - lat) < 1e-6]


def _raw_layer(data):
    """The top-level Layer message of an MVT tile, decoded by hand: {name, keys}. (Tile field 3 = Layer;
    Layer field 1 = name, field 3 = keys.)"""
    def varint(buf, i):
        n = shift = 0
        while True:
            b = buf[i]
            i += 1
            n |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                return n, i

    def fields(buf):
        i = 0
        while i < len(buf):
            tag, i = varint(buf, i)
            fn, wt = tag >> 3, tag & 7
            if wt == 0:
                val, i = varint(buf, i)
            elif wt == 2:
                ln, i = varint(buf, i)
                val, i = buf[i:i + ln], i + ln
            elif wt == 5:
                val, i = buf[i:i + 4], i + 4
            elif wt == 1:
                val, i = buf[i:i + 8], i + 8
            else:
                raise AssertionError(wt)
            yield fn, val
    (layer,) = [v for fn, v in fields(data) if fn == 3]
    return {"keys": [v.decode() for fn, v in fields(layer) if fn == 3]}


def _decode(data):
    return mapbox_vector_tile.decode(data)["plankton"]["features"]


@needs_db
async def test_a_grid_cell_sums_every_group_and_names_the_dominant_one(conn):
    await seed_live(conn, _rows())
    (cell,) = _at(await _feats(conn, 10.5, 50.5, 3), 10.5, 50.5)
    assert (cell["n"], cell["top_group"], cell["groups"], cell["edna_only"], cell["site_key"]) == \
        (8, "copepoda", 1 | 4 | 16, False, None)


@needs_db
async def test_copepods_in_the_2010s_never_show_a_place_whose_copepods_are_from_the_1990s(conn):
    await seed_live(conn, _rows())
    flt = {"g": "copepoda", "d": "2010"}
    (cell,) = _at(await _feats(conn, 10.5, 50.5, 3, **flt), 10.5, 50.5)
    assert (cell["n"], cell["top_group"], cell["groups"]) == (1, "copepoda", 1)
    assert _at(await _feats(conn, *S1, 7, **flt), *S1) == []
    (s2,) = _at(await _feats(conn, *S2, 7, **flt), *S2)
    assert (s2["n"], s2["site_key"]) == (1, "10.700000,50.200000")


@needs_db
async def test_the_depth_band_filter_is_exact_per_facet_row_in_grid_and_places(conn):
    """Bands: 50 m -> 0 (0-200 m), 500 m -> 1. S1 holds shallow copepods and deep diatoms; S2 only deep
    copepods. Narrowed to band 0, S1 shows with its shallow rows only and S2 must not show at all."""
    await seed_live(conn, [row("copepoda", *S1, depth=50.0)] * 2 + [row("diatoms", *S1, depth=500.0)] * 5
                    + [row("copepoda", *S2, depth=500.0)] * 3)
    b_shallow = "0"
    (s1,) = _at(await _feats(conn, *S1, 7, b=b_shallow), *S1)
    assert (s1["n"], s1["top_group"], s1["groups"]) == (2, "copepoda", 1)
    assert _at(await _feats(conn, *S2, 7, b=b_shallow), *S2) == []
    (cell,) = _at(await _feats(conn, 10.5, 50.5, 3, b=b_shallow), 10.5, 50.5)
    assert (cell["n"], cell["top_group"], cell["groups"]) == (2, "copepoda", 1)


@needs_db
async def test_group_and_decade_match_the_combination_per_facet_row_in_the_grid_too(conn):
    """S1 has copepods only from the 1990s and diatoms from the 2010s. A cell holding only S1 must not
    appear for copepoda + 2010s (each dimension alone would match)."""
    await seed_live(conn, [row("copepoda", *S1, year=1995), row("diatoms", *S1, year=2015)])
    assert await _feats(conn, *S1, 3, g="copepoda", d="2010") == []
    assert await _feats(conn, *S1, 4, g="copepoda", d="2010") == []
    assert await _feats(conn, *S1, 7, g="copepoda", d="2010") == []
    assert len(await _feats(conn, *S1, 7, g="copepoda", d="1990")) == 1


@needs_db
async def test_an_edna_only_place_is_flagged_and_disappears_with_edna_off(conn):
    await seed_live(conn, _rows())
    (s3,) = _at(await _feats(conn, *S3, 7), *S3)
    assert (s3["n"], s3["edna_only"], s3["top_group"]) == (2, True, "dinoflagellates")
    assert _at(await _feats(conn, *S3, 7, e="0"), *S3) == []
    (cell,) = _at(await _feats(conn, 10.5, 50.5, 3, g="dinoflagellates"), 10.5, 50.5)
    assert cell["edna_only"] is True
    assert _at(await _feats(conn, 10.5, 50.5, 3, g="dinoflagellates", e="0"), 10.5, 50.5) == []


@needs_db
async def test_a_tie_names_the_group_first_in_alphabetical_order(conn):
    await seed_live(conn, _rows())
    (s4,) = _at(await _feats(conn, *S4, 7), *S4)
    assert (s4["n"], s4["top_group"], s4["groups"]) == (2, "copepoda", 1 | 4)


@needs_db
async def test_zoom_bands_one_degree_quarter_degree_then_places(conn):
    await seed_live(conn, _rows())
    assert _at(await _feats(conn, 10.5, 50.5, 3), 10.5, 50.5)            # 1° cell centre
    assert _at(await _feats(conn, 10.125, 50.125, 4), 10.125, 50.125)    # 0.25° cell centre of S1
    assert _at(await _feats(conn, 10.125, 50.125, 6), 10.125, 50.125)
    assert not _at(await _feats(conn, 10.5, 50.5, 4), 10.5, 50.5)        # no 1° centre at z4
    assert _at(await _feats(conn, *S1, 7), *S1)                          # the place itself


@needs_db
async def test_render_returns_the_version_and_an_mvt_named_plankton(conn):
    version = await seed_live(conn, _rows())
    x, y = tile_of(*S1, 7)
    got, data = await tiles.render(conn, 7, x, y, tiles.DEFAULT_FILTER)
    assert got == version == await tiles.current_version(conn)
    sites = _decode(data)
    assert {f["properties"]["site_key"] for f in sites} >= {"10.200000,50.200000"}
    assert all({"n", "top_group", "groups", "edna_only", "site_key"} <= set(f["properties"]) for f in sites)
    x, y = tile_of(-150.0, -60.0, 7)
    assert (await tiles.render(conn, 7, x, y, tiles.DEFAULT_FILTER))[1] == b""


@needs_db
@pytest.mark.parametrize("z, lon, lat", [(3, 10.5, 50.5), (4, 10.125, 50.125), (6, 10.125, 50.125)])
async def test_grid_tiles_carry_no_site_key_at_all(conn, z, lon, lat):
    await seed_live(conn, _rows())
    x, y = tile_of(lon, lat, z)
    _, data = await tiles.render(conn, z, x, y, tiles.DEFAULT_FILTER)
    feats = _decode(data)
    assert feats
    for f in feats:
        assert set(f["properties"]) == {"n", "top_group", "groups", "edna_only"}
    # The layer's key table is what a NULL site_key column would pollute (ST_AsMVT omits NULL values per
    # feature but still writes the KEY), so decode the raw layer, not the features.
    layer = _raw_layer(data)
    assert sorted(layer["keys"]) == ["edna_only", "groups", "n", "top_group"]
    assert b"site_key" not in data


@needs_db
async def test_a_slow_tile_is_cancelled_at_the_statement_timeout(conn, monkeypatch):
    await seed_live(conn, _rows())
    monkeypatch.setattr(tiles, "TILE_STATEMENT_TIMEOUT", "100ms")
    monkeypatch.setattr(tiles, "_SITE_FEATURES",
                        "SELECT 1::bigint AS n, 'copepoda'::text AS top_group, 1 AS groups, false AS edna_only, "
                        "'k'::text AS site_key, ST_SetSRID(ST_MakePoint(0, 0), 3857) AS geom FROM pg_sleep(1) "
                        "WHERE $4::text[] IS NOT NULL AND $5::smallint[] IS NOT NULL "
                        "AND $6::smallint[] IS NOT NULL AND $7::boolean IS NOT NULL")
    with pytest.raises(asyncpg.QueryCanceledError):
        await tiles.render(conn, 7, 0, 0, tiles.DEFAULT_FILTER)
    assert await conn.fetchval("SELECT 1") == 1           # the savepoint rolled back; the session is usable


@needs_db
async def test_no_version_row_means_no_version(conn):
    await seed_live(conn, _rows())
    await conn.execute("DELETE FROM plankton_tile_version")
    assert await tiles.current_version(conn) is None


@needs_db
async def test_the_tile_statement_and_the_swap_lock_in_one_order(conn):
    """The deadlock guard: the tile statement names the version first, then sites -> site_facets (or the
    grid facets), a subsequence of SWAP_LOCK_ORDER."""
    import re
    from ingestion import plankton_obis as p
    order = {t: i for i, t in enumerate(p.SWAP_LOCK_ORDER)}
    for z in (3, 7):
        sql = "SELECT version FROM plankton_tile_version " + tiles._features_sql(z)
        named = [t for t in re.findall(r"\b(plankton_[a-z_]+)\b", sql) if t in order]
        firsts = list(dict.fromkeys(named))
        assert firsts == sorted(firsts, key=order.get), (z, firsts)


@needs_db
async def test_a_place_just_outside_a_tile_edge_is_in_that_tile_and_in_its_own(conn):
    """Within the 64 px buffer ST_AsMVTGeom clips with, the row must be selected too, or circles are cut
    at the tile seam."""
    z = 7
    x, y = tile_of(10.2, 50.2, z)
    east = (x + 1) * 360.0 / 2 ** z - 180.0               # the edge between tile x and x+1
    near = (east + 0.02, 50.2)                              # 0.02° inside x+1; the buffer is ~0.044°
    far = (east + 0.2, 50.2)                                # well outside the buffer
    await seed_live(conn, [row("copepoda", *near), row("copepoda", *far)])
    assert tile_of(*near, z) == (x + 1, y)
    keys = lambda data: {f["properties"]["site_key"] for f in _decode(data)}   # noqa: E731
    _, tile_a = await tiles.render(conn, z, x, y, tiles.DEFAULT_FILTER)
    _, own = await tiles.render(conn, z, x + 1, y, tiles.DEFAULT_FILTER)
    assert keys(tile_a) == {"%.6f,%.6f" % near}
    assert keys(own) == {"%.6f,%.6f" % near, "%.6f,%.6f" % far}
