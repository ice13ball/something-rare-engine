# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""GET /v1/plankton/tiles/{z}/{x}/{y}.pbf — validation, read-through disk cache, cache headers."""
import asyncio

import asyncpg
import pytest

import db
from domains import plankton as route
from plankton_helpers import api_get as _get, conn, needs_db, row, seed_live, tile_of  # noqa: F401
from services import plankton_tiles as tiles

IMMUTABLE_CC = "public, max-age=31536000, immutable"
ROWS = [row("copepoda", 10.2, 50.2, year=1995, depth=50.0), row("diatoms", 10.2, 50.2, year=2015, depth=50.0)]


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(route, "_refreshing", None, raising=False)   # a pending refresh of another test must not block ours
    monkeypatch.setenv("PLANKTON_TILE_CACHE_DIR", str(tmp_path / "tiles"))
    monkeypatch.setattr(route, "_live", (None, 0.0), raising=False)
    return tmp_path / "tiles"


@pytest.fixture
async def leaked_refresh():
    """What an earlier test can leave behind: a background refresh that never finished."""
    route._refreshing = asyncio.get_running_loop().create_future()
    yield
    route._refreshing = None


async def test_the_fixture_clears_a_background_refresh_left_by_an_earlier_test(leaked_refresh, cache):
    assert route._refreshing is None


def _url(z, lon=10.2, lat=50.2, q=""):
    x, y = tile_of(lon, lat, z)
    return f"/v1/plankton/tiles/{z}/{x}/{y}.pbf" + (f"?{q}" if q else "")


async def _no_render(*a, **k):
    raise AssertionError("rendered again instead of reading the disk cache")


@needs_db
@pytest.mark.parametrize("q", ["g=jellyfish", "d=1930", "b=4", "e=2", "d=19x0"])
async def test_an_unknown_filter_value_is_a_400(conn, cache, q):
    await seed_live(conn, ROWS)
    r = await _get(_url(7, q=q))
    assert r.status_code == 400 and not cache.exists()


@needs_db
@pytest.mark.parametrize("path", ["/v1/plankton/tiles/2/4/0.pbf", "/v1/plankton/tiles/2/0/4.pbf",
                                  "/v1/plankton/tiles/23/0/0.pbf", "/v1/plankton/tiles/2/-1/0.pbf",
                                  "/v1/plankton/tiles/13/0/0.pbf"])  # the map never asks above z12
async def test_coordinates_outside_the_zoom_are_a_400(conn, cache, path):
    await seed_live(conn, ROWS)
    assert (await _get(path)).status_code == 400 and not cache.exists()


@needs_db
async def test_before_the_first_build_the_answer_is_503_not_an_empty_map(conn, cache):
    await seed_live(conn, ROWS)
    await conn.execute("DELETE FROM plankton_tile_version")
    r = await _get(_url(3))
    assert r.status_code == 503 and r.headers["retry-after"] == "300"


@needs_db
async def test_a_missing_aggregate_table_during_render_is_503_not_an_empty_200(conn, cache, monkeypatch):
    await seed_live(conn, ROWS)

    async def missing(*a, **k):
        raise asyncpg.UndefinedTableError('relation "plankton_cell_facets" does not exist')
    monkeypatch.setattr(tiles, "render", missing)
    r = await _get(_url(7))
    assert r.status_code == 503 and r.headers["retry-after"] == "300" and not cache.exists()


@needs_db
async def test_the_second_read_comes_from_disk(conn, cache, monkeypatch):
    version = await seed_live(conn, ROWS)
    first = await _get(_url(7))
    assert first.status_code == 200 and first.headers["content-type"] == "application/vnd.mapbox-vector-tile"
    x, y = tile_of(10.2, 50.2, 7)
    assert (cache / version / "all" / "7" / str(x) / f"{y}.pbf").read_bytes() == first.content
    monkeypatch.setattr(tiles, "render", _no_render)
    second = await _get(_url(7))
    assert second.status_code == 200 and second.content == first.content


@needs_db
async def test_reordered_filters_share_one_cache_entry(conn, cache):
    version = await seed_live(conn, ROWS)
    a = await _get(_url(7, q="g=diatoms,copepoda&d=2010,1990"))
    b = await _get(_url(7, q="d=1990,2010,2010&g=copepoda,diatoms"))
    assert a.status_code == b.status_code == 200 and a.content == b.content
    assert sorted(p.name for p in (cache / version).iterdir()) == ["g05-d140-bf-e1"]


@needs_db
async def test_cache_control_is_immutable_only_for_the_current_version(conn, cache):
    version = await seed_live(conn, ROWS)
    assert (await _get(_url(7, q=f"v={version}"))).headers["cache-control"] == \
        "public, max-age=31536000, immutable"
    assert (await _get(_url(7, q="v=20200101000000-000000"))).headers["cache-control"] == "public, max-age=60"
    assert (await _get(_url(7))).headers["cache-control"] == "public, max-age=60"


@needs_db
async def test_an_empty_tile_is_204_and_is_cached_as_empty(conn, cache, monkeypatch):
    version = await seed_live(conn, ROWS)
    assert (await _get(_url(7, lon=-150.0, lat=-60.0))).status_code == 204
    x, y = tile_of(-150.0, -60.0, 7)
    assert (cache / version / "all" / "7" / str(x) / f"{y}.pbf").read_bytes() == b""
    monkeypatch.setattr(tiles, "render", _no_render)
    assert (await _get(_url(7, lon=-150.0, lat=-60.0))).status_code == 204


@needs_db
async def test_a_timed_out_tile_is_a_503_and_is_never_cached(conn, cache, monkeypatch):
    version = await seed_live(conn, ROWS)

    async def slow(*a, **k):
        raise asyncpg.QueryCanceledError("canceling statement due to statement timeout")
    monkeypatch.setattr(tiles, "render", slow)
    r = await _get(_url(7))
    assert r.status_code == 503 and r.headers["cache-control"] == "no-store" and r.headers["retry-after"] == "5"
    assert not (cache / version).exists()


@needs_db
async def test_an_unwritable_cache_still_serves_the_tile(conn, tmp_path, monkeypatch):
    await seed_live(conn, ROWS)
    blocker = tmp_path / "not-a-dir"
    blocker.write_bytes(b"")
    monkeypatch.setenv("PLANKTON_TILE_CACHE_DIR", str(blocker))
    r = await _get(_url(7))
    assert r.status_code == 200 and b"plankton" in r.content


@needs_db
async def test_a_queued_render_holds_no_pool_connection(conn, cache, monkeypatch):
    """P4: the semaphore comes BEFORE the pool connection, so cold tiles waiting for a render slot cannot
    drain the API pool. Only the one-row version lookup may have been acquired while the slot is taken."""
    await seed_live(conn, ROWS)
    acquired = []
    real = db.pool

    class Counting:
        def acquire(self):
            acquired.append(1)
            return real.acquire()
    monkeypatch.setattr(db, "pool", Counting())
    monkeypatch.setattr(route, "_RENDER_SEM", asyncio.Semaphore(0))
    task = asyncio.create_task(_get(_url(7)))
    await asyncio.sleep(0.5)
    assert not task.done() and len(acquired) == 1
    route._RENDER_SEM.release()
    r = await asyncio.wait_for(task, 10)
    assert r.status_code == 200 and len(acquired) == 2


class _CountingPool:
    def __init__(self, real):
        self.real, self.acquired = real, 0

    def acquire(self):
        self.acquired += 1
        return self.real.acquire()


@needs_db
async def test_a_disk_hit_with_a_valid_v_takes_no_pool_connection(conn, cache, monkeypatch):
    version = await seed_live(conn, ROWS)
    first = await _get(_url(7, q=f"v={version}"))          # cold: fills the disk and the in-process version
    pool = _CountingPool(db.pool)
    monkeypatch.setattr(db, "pool", pool)
    monkeypatch.setattr(tiles, "render", _no_render)
    second = await _get(_url(7, q=f"v={version}"))
    assert second.content == first.content and pool.acquired == 0
    assert second.headers["cache-control"] == IMMUTABLE_CC


@needs_db
async def test_a_hit_whose_v_is_not_the_known_live_version_gets_the_short_max_age(conn, cache, monkeypatch):
    version = await seed_live(conn, ROWS)
    await _get(_url(7, q=f"v={version}"))
    monkeypatch.setattr(route, "_live", ("20200101000000-000000", route.time.monotonic()))
    r = await _get(_url(7, q=f"v={version}"))
    assert r.status_code == 200 and r.headers["cache-control"] == "public, max-age=60"
    # an expired in-process version can only downgrade, never claim immutable
    monkeypatch.setattr(route, "_live", (version, route.time.monotonic() - 3600))
    r = await _get(_url(7, q=f"v={version}"))
    assert r.headers["cache-control"] == "public, max-age=60"
    await route._refreshing   # the lazy refresh the stale value kicked off (it shares the test's one connection)
    assert route._live_version() == version


@needs_db
async def test_an_unready_pool_on_a_miss_is_a_503_not_a_500(conn, cache, monkeypatch):
    await seed_live(conn, ROWS)
    monkeypatch.setattr(db, "pool", None)
    r = await _get(_url(7))
    assert r.status_code == 503 and r.headers["retry-after"] == "5"


@needs_db
async def test_the_highest_zoom_the_map_requests_is_served(conn, cache):
    await seed_live(conn, ROWS)
    assert (await _get(_url(12))).status_code in (200, 204)
