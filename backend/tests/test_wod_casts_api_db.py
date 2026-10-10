# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""WOD casts API on the REAL cut files (tests/fixtures/wod_casts/), loaded by the real loader. The expectations are
computed here from the oracle (expected.json) and this file's own Web-Mercator / Morton / cell arithmetic, never
read back from the tile SQL: a tile that groups, clamps, filters or versions wrongly turns a test red."""
import asyncio
import math
import pathlib
import subprocess
import sys

import mapbox_vector_tile
import numpy as np
import pytest

from domains import wod_casts as route
from ingestion import wod_casts as wc
from ingestion import wod_casts_rules as R
from services import woa_climatology
from wod_helpers import EXPECTED, api_get, conn, db, load_fixtures, needs_db  # noqa: F401  (fixtures)

GIB = 1024 ** 3
WORLD = 20037508.342789244
R_EARTH = 6378137.0
MERC_LAT = 85.0511
IMMUTABLE_CC = "public, max-age=31536000, immutable"
TWIN_ID, TWIN_YEAR = 990000001, 1990      # a synthetic second cast in the cell of a real one


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    """No pause between chunks and a disk that is not the CI runner's."""
    monkeypatch.setattr(wc, "SLICE_PAUSE_S", 0)
    monkeypatch.setattr(wc, "_disk_usage", lambda path: (1000 * GIB, 100 * GIB, 900 * GIB))


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(route, "_refreshing", None, raising=False)
    monkeypatch.setattr(route, "_meta_cache", None, raising=False)
    monkeypatch.setenv("WOD_TILE_CACHE_DIR", str(tmp_path / "tiles"))
    monkeypatch.setattr(route, "_live", (None, 0.0), raising=False)
    return tmp_path / "tiles"


# ── the test's own arithmetic ────────────────────────────────────────────────────────────────────────────
def _oracle_casts() -> list[dict]:
    out = []
    for exp in EXPECTED.values():
        for k, c in exp["casts"].items():
            if c["status"] == "drawn":
                out.append({"id": int(k), "lat": c["lat"], "lon": c["lon"], "year": int(c["time"]["date"][:4]),
                            "picks": c["picks"]})
    return out


CASTS = _oracle_casts()
assert len(CASTS) == 21
ME = next(c for c in CASTS if c["id"] == 17813889)


def _merc(c) -> tuple[float, float]:
    lat = max(-MERC_LAT, min(MERC_LAT, c["lat"]))
    return (R_EARTH * math.radians(c["lon"]),
            R_EARTH * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))


def _interleave(a: int, b: int) -> int:
    """a in the even bits, b in the odd bits."""
    out = 0
    for i in range(20):
        out |= ((a >> i) & 1) << (2 * i) | ((b >> i) & 1) << (2 * i + 1)
    return out


def _kbits(z: int) -> int:
    """Cells per tile axis = 2^(kbits - z): 256 from POINT_MIN_ZOOM, 64 / 32 below it (LOD level z // 2)."""
    return z + 8 if z >= R.POINT_MIN_ZOOM else 6 + 2 * (z // 2)


def _cell(c, z: int) -> tuple[int, int, int]:
    """(tile x, tile y, q) of the cast at zoom z: q interleaves the cell's column (even bits) and row (odd bits)
    counted from the tile's west / NORTH edge."""
    mx, my = _merc(c)
    n = 1 << 20
    gx = min(n - 1, max(0, math.floor((mx + WORLD) / (2 * WORLD) * n)))
    gy = min(n - 1, max(0, math.floor((WORLD - my) / (2 * WORLD) * n)))
    k = _kbits(z)
    cx, cy = gx >> (20 - k), gy >> (20 - k)
    per = k - z
    return cx >> per, cy >> per, _interleave(cx & ((1 << per) - 1), cy & ((1 << per) - 1))


def _cells(casts, z: int, years=None) -> dict:
    """{(tx, ty, q): [casts]} of the casts (optionally of one year range) at zoom z."""
    out: dict = {}
    for c in casts:
        if years is None or years[0] <= c["year"] <= years[1]:
            out.setdefault(_cell(c, z), []).append(c)
    return out


def _value(c, var: str, d: int):
    pick = c["picks"].get(var, [None] * 8)[d]
    return None if pick is None else pick[2] * R.SCALES[var]


def _mean(group, var: str, d: int):
    vals = [v for v in (_value(c, var, d) for c in group) if v is not None]
    return sum(vals) / len(vals) if vals else None


def _check(props, group, var: str):
    """One feature against the casts it must stand for."""
    assert props["k"] == len(group)
    assert props["id"] == max(c["id"] for c in group)
    assert (props["a"], props["b"]) == (min(c["year"] for c in group), max(c["year"] for c in group))
    for d in range(len(R.DEPTHS)):
        m = _mean(group, var, d)
        if m is None:
            assert f"d{d}" not in props, f"d{d} must be absent when no cast has a value"
        else:
            assert abs(props[f"d{d}"] - m) <= 1, (d, props[f"d{d}"], m)


def _decode(data):
    return mapbox_vector_tile.decode(data)["wod"]["features"]


async def _tile(var, z, x, y, query=""):
    return await api_get(f"/v1/wod/tiles/{var}/{z}/{x}/{y}.pbf{query}")


async def _version(db):
    return await db.fetchval("SELECT tile_version FROM wod_casts_source WHERE id = 1")


async def _add_twin(db, cast_id: int, new_id: int, year: int):
    """A second cast at the SAME position (same key, same picks) in another year, then a real LOD rebuild."""
    await db.execute(
        "INSERT INTO wod_casts (cast_id, file_id, instrument, dataset, lat, lon, cast_date, time_precision, year, "
        "depth, depth_flag, pflag, n_src, n_good) "
        "SELECT $2, file_id, instrument, dataset, lat, lon, make_date($3, 6, 1), 'day', $3, depth, depth_flag, "
        "pflag, n_src, n_good FROM wod_casts WHERE cast_id = $1", cast_id, new_id, year)
    await db.execute(
        "INSERT INTO wod_cast_points (cast_id, file_id, year, key, x, y, picks) "
        "SELECT $2, file_id, $3, key, x, y, picks FROM wod_cast_points WHERE cast_id = $1", cast_id, new_id, year)
    await wc.rebuild_lod(db)


def _twin():
    return {**ME, "id": TWIN_ID, "year": TWIN_YEAR}


# ── before the first build ───────────────────────────────────────────────────────────────────────────────
@needs_db
async def test_tile_503_before_first_build(db, cache):
    assert (await _tile("nope", 0, 0, 0)).status_code == 404
    assert (await _tile("temperature", 13, 0, 0)).status_code == 404 and not cache.exists()
    assert (await _tile("temperature", 2, 4, 0)).status_code == 404
    assert (await _tile("temperature", 0, 0, 0, "?y0=2015")).status_code == 400
    r = await _tile("temperature", 0, 0, 0)
    assert r.status_code == 503 and r.headers["retry-after"] == "300"
    assert not cache.exists()                     # nothing cached for a state that is not data
    r = await _tile("oxygen", R.POINT_MIN_ZOOM + 1, 5, 7)
    assert r.status_code == 503 and r.headers["retry-after"] == "300" and not cache.exists()
    r = await api_get("/v1/wod/cell/0/0/0/0")
    assert r.status_code == 503 and r.headers["retry-after"] == "300"
    r = await api_get("/v1/wod/cast/22708857")
    assert r.status_code == 503 and r.headers["retry-after"] == "300"
    meta = await api_get("/v1/wod/meta")
    assert meta.status_code == 200 and meta.json()["health"]["status"] == "not_loaded"
    assert meta.json()["tile_version"] is None


@needs_db
async def test_slow_tile_is_503_and_nothing_is_cached(db, cache, tmp_path, monkeypatch):
    import asyncpg
    assert (await load_fixtures(db, tmp_path))["outcome"] == "complete"

    async def too_slow(*a, **kw):
        raise asyncpg.QueryCanceledError("canceling statement due to statement timeout")
    monkeypatch.setattr(route.tiles, "render", too_slow)
    r = await _tile("temperature", 0, 0, 0)
    assert r.status_code == 503 and r.headers["retry-after"] == "5"
    assert not cache.exists() or not list(cache.rglob("*.pbf"))


@needs_db
async def test_hit_path_never_touches_the_database(db, cache, tmp_path, monkeypatch):
    assert (await load_fixtures(db, tmp_path))["outcome"] == "complete"
    v1 = await _version(db)
    first = await _tile("temperature", 0, 0, 0)
    assert first.status_code == 200
    monkeypatch.setattr(route.db, "pool", None)             # any database access now fails
    hit = await _tile("temperature", 0, 0, 0, f"?v={v1}")
    assert hit.status_code == 200 and hit.content == first.content
    assert (await _tile("temperature", 0, 0, 0)).status_code == 503     # without v the version is needed


# ── the point zoom: one feature per cell, computed here from the oracle ──────────────────────────────────
@needs_db
async def test_point_tile_carries_the_casts_picks(db, cache, tmp_path):
    assert (await load_fixtures(db, tmp_path))["outcome"] == "complete"
    z = 12
    tx, ty, q_me = _cell(ME, z)
    r = await _tile("temperature", z, tx, ty)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.mapbox-vector-tile")
    feats = _decode(r.content)
    want = {k[2]: g for k, g in _cells(CASTS, z).items() if k[:2] == (tx, ty)}
    assert {f["properties"]["q"] for f in feats} == set(want)
    for f in feats:
        _check(f["properties"], want[f["properties"]["q"]], "temperature")
    mine = next(f for f in feats if f["properties"]["q"] == q_me)
    assert any(c["id"] == 17813889 for c in want[q_me]) and mine["properties"]["k"] == len(want[q_me])
    # the dot sits at the mean position of its casts (x checked: MVT y runs down)
    size = 2 * WORLD / 2 ** z
    px = (sum(_merc(c)[0] for c in want[q_me]) / len(want[q_me]) - (-WORLD + tx * size)) / size * 4096
    assert abs(mine["geometry"]["coordinates"][0] - px) <= 2

    # the same tile for another variable: same cells, that variable's means
    r = await _tile("oxygen", z, tx, ty)
    assert r.status_code == 200
    for f in _decode(r.content):
        _check(f["properties"], want[f["properties"]["q"]], "oxygen")

    # the first point zoom is a point tile too: every cast of the tile counted once
    zp = R.POINT_MIN_ZOOM
    px_, py_, _ = _cell(ME, zp)
    r = await _tile("temperature", zp, px_, py_)
    assert r.status_code == 200
    group_by_q = {k[2]: g for k, g in _cells(CASTS, zp).items() if k[:2] == (px_, py_)}
    assert sum(f["properties"]["k"] for f in _decode(r.content)) == sum(len(g) for g in group_by_q.values())


# ── the coarse zoom: LOD cells ───────────────────────────────────────────────────────────────────────────
@needs_db
async def test_lod_tile_counts_every_cast(db, cache, tmp_path):
    assert (await load_fixtures(db, tmp_path))["outcome"] == "complete"
    n_points = await db.fetchval("SELECT count(*) FROM wod_cast_points")
    assert n_points == len(CASTS)
    r = await _tile("temperature", 0, 0, 0)
    assert r.status_code == 200
    feats = _decode(r.content)
    assert sum(f["properties"]["k"] for f in feats) == n_points
    assert all(0 <= f["properties"]["q"] < 64 * 64 for f in feats)
    for z in range(R.POINT_MIN_ZOOM):
        cells = _cells(CASTS, z)
        total = 0
        for (tx, ty) in sorted({k[:2] for k in cells}):
            r = await _tile("temperature", z, tx, ty)
            assert r.status_code == 200, (z, tx, ty)
            got = _decode(r.content)
            want = {k[2]: g for k, g in cells.items() if k[:2] == (tx, ty)}
            assert {f["properties"]["q"] for f in got} == set(want), z
            assert all(f["properties"]["q"] < (1 << (_kbits(z) - z)) ** 2 for f in got), z
            for f in got:
                _check(f["properties"], want[f["properties"]["q"]], "temperature")
            total += sum(f["properties"]["k"] for f in got)
        assert total == n_points, z
    r = await _tile("oxygen", 0, 0, 0)
    want0 = {k[2]: g for k, g in _cells(CASTS, 0).items()}
    for f in _decode(r.content):
        _check(f["properties"], want0[f["properties"]["q"]], "oxygen")


# ── what a feature stands for ────────────────────────────────────────────────────────────────────────────
@needs_db
async def test_cell_lists_what_the_feature_stands_for(db, cache, tmp_path):
    assert (await load_fixtures(db, tmp_path))["outcome"] == "complete"
    await _add_twin(db, ME["id"], TWIN_ID, TWIN_YEAR)
    version = await _version(db)
    casts = CASTS + [_twin()]
    z = 12
    tx, ty, q = _cell(ME, z)

    feats = _decode((await _tile("temperature", z, tx, ty)).content)
    feat = next(f["properties"] for f in feats if f["properties"]["q"] == q)
    assert feat["k"] == 2 and feat["id"] == TWIN_ID and (feat["a"], feat["b"]) == (TWIN_YEAR, ME["year"])

    r = await api_get(f"/v1/wod/cell/{z}/{tx}/{ty}/{q}?v={version}")
    assert r.status_code == 200 and r.headers["cache-control"] == IMMUTABLE_CC
    body = r.json()
    assert body["n_casts"] == feat["k"] == 2 and body["truncated"] is False
    assert [c["cast_id"] for c in body["casts"]] == [ME["id"], TWIN_ID]            # year descending
    assert [c["year"] for c in body["casts"]] == [ME["year"], TWIN_YEAR]
    assert (body["year_min"], body["year_max"]) == (TWIN_YEAR, ME["year"])
    assert body["cell"]["west"] < body["casts"][0]["lon"] < body["cell"]["east"]
    assert body["cell"]["south"] < body["casts"][0]["lat"] < body["cell"]["north"]
    for c in body["casts"]:                                  # every id opens the cast it names
        one = await api_get(f"/v1/wod/cast/{c['cast_id']}")
        assert one.status_code == 200 and one.json()["cast_id"] == c["cast_id"]
    # the year range narrows the list exactly as it narrows the tile
    for y, only in ((ME["year"], ME["id"]), (TWIN_YEAR, TWIN_ID)):
        one = await api_get(f"/v1/wod/cell/{z}/{tx}/{ty}/{q}?y0={y}&y1={y}")
        assert one.status_code == 200 and [c["cast_id"] for c in one.json()["casts"]] == [only]
        assert one.json()["years"] == [y, y]
    # not the live version: still served, but not marked immutable
    stale = await api_get(f"/v1/wod/cell/{z}/{tx}/{ty}/{q}?v=20200101000000-aaaaaa")
    assert stale.status_code == 200 and "immutable" not in stale.headers["cache-control"]

    # a coarse dot: the LOD cell lists the same casts the dot counted
    k0, q0 = _cells(casts, 0)[_cell(ME, 0)], _cell(ME, 0)[2]
    lod = _decode((await _tile("temperature", 0, 0, 0)).content)
    assert next(f["properties"]["k"] for f in lod if f["properties"]["q"] == q0) == len(k0)
    r = await api_get(f"/v1/wod/cell/0/0/0/{q0}")
    assert r.status_code == 200 and r.json()["n_casts"] == len(k0)
    assert [c["year"] for c in r.json()["casts"]] == sorted((c["year"] for c in k0), reverse=True)

    used = {k[2] for k in _cells(casts, z) if k[:2] == (tx, ty)}
    empty_q = next(i for i in range(65536) if i not in used)
    assert (await api_get(f"/v1/wod/cell/{z}/{tx}/{ty}/{empty_q}")).status_code == 404
    assert (await api_get(f"/v1/wod/cell/{z}/{tx}/{ty}/{q}?y0=1800&y1=1800")).status_code == 404
    for out_of_range in (f"/v1/wod/cell/{z}/{tx}/{ty}/65536", "/v1/wod/cell/0/0/0/4096", "/v1/wod/cell/13/0/0/0",
                         f"/v1/wod/cell/{z}/{2 ** z}/0/0", f"/v1/wod/cell/3/0/0/{4 ** (_kbits(3) - 3)}"):
        assert (await api_get(out_of_range)).status_code == 404, out_of_range
    for malformed in (f"/v1/wod/cell/{z}/{tx}/{ty}/abc", f"/v1/wod/cell/{z}/{tx}/{ty}/{q}?y0=2015",
                      f"/v1/wod/cell/{z}/{tx}/{ty}/{q}?y0=2016&y1=2015", f"/v1/wod/cell/{z}/{tx}/{ty}/{q}?y0=20x5&y1=2015"):
        assert (await api_get(malformed)).status_code == 400, malformed


# ── year ranges, reloads and purges never share bytes ────────────────────────────────────────────────────
@needs_db
async def test_year_range_and_reload_never_share_bytes(db, cache, tmp_path):
    assert (await load_fixtures(db, tmp_path))["outcome"] == "complete"
    v1 = await _version(db)
    y = ME["year"]
    on_disk = lambda v, key: cache / v / key / "0" / "0" / "0.pbf"   # noqa: E731

    r_all = await _tile("temperature", 0, 0, 0)
    r_year = await _tile("temperature", 0, 0, 0, f"?y0={y}&y1={y}")
    assert r_all.status_code == r_year.status_code == 200
    n_year = sum(1 for c in CASTS if c["year"] == y)
    assert 0 < n_year < len(CASTS)
    assert sum(f["properties"]["k"] for f in _decode(r_all.content)) == len(CASTS)
    assert sum(f["properties"]["k"] for f in _decode(r_year.content)) == n_year
    assert on_disk(v1, "t-all").read_bytes() == r_all.content
    assert on_disk(v1, f"t-{y}-{y}").read_bytes() == r_year.content != r_all.content
    assert (await _tile("temperature", 0, 0, 0, "?y0=1800&y1=1800")).status_code == 204     # a year range with no casts
    assert (await _tile("temperature", 0, 0, 0, "?y0=1800&y1=1800")).status_code == 204     # and from the cache
    assert (await _tile("oxygen", 0, 0, 0)).content != r_all.content
    assert on_disk(v1, "o-all").exists()

    # the swap: a real LOD rebuild writes a new tile_version (1 s resolution -> sleep before it, P10)
    await asyncio.sleep(1.1)
    await wc.rebuild_lod(db)
    v2 = await _version(db)
    assert v2 != v1
    r = await _tile("temperature", 0, 0, 0)                  # no v: bytes rendered under v2
    assert r.status_code == 200 and on_disk(v2, "t-all").exists() and on_disk(v1, "t-all").exists()
    assert "immutable" not in r.headers["cache-control"]
    r = await _tile("temperature", 0, 0, 0, f"?v={v1}")      # the old version is still on disk but is no longer live
    assert r.status_code == 200 and "immutable" not in r.headers["cache-control"]
    r = await _tile("temperature", 0, 0, 0, f"?v={v2}")
    assert r.status_code == 200 and r.headers["cache-control"] == IMMUTABLE_CC

    # the psql purge: tile_version = NULL, then the admin cache sweep inside a running loop
    await db.execute("UPDATE wod_casts_source SET tile_version = NULL WHERE id = 1")
    route.clear_caches()
    await route._reconcile_task
    assert not (cache / v1).exists() and not (cache / v2).exists()
    for q in ("", f"?v={v1}", f"?v={v2}"):
        r = await _tile("temperature", 0, 0, 0, q)
        assert r.status_code == 503 and r.headers["retry-after"] == "300", q
    assert (await api_get("/v1/wod/cell/0/0/0/0")).status_code == 503


# ── one cast ─────────────────────────────────────────────────────────────────────────────────────────────
@needs_db
async def test_cast_payload(db, tmp_path, monkeypatch):
    assert (await load_fixtures(db, tmp_path))["outcome"] == "complete"
    monkeypatch.setattr(woa_climatology, "CACHE_DIR", tmp_path / "no-woa")          # no grid on disk
    r = await api_get("/v1/wod/cast/22708857?var=oxygen&depth=0")
    assert r.status_code == 200 and "NaN" not in r.text and "Infinity" not in r.text
    body = r.json()
    assert (body["cast_id"], body["instrument"], body["dataset"]) == (22708857, "pfl", "profiling float")
    assert body["date"] == "2024-07-15" and body["time"] == "14:12:11" and body["time_precision"] == "second"
    assert abs(body["lat"] - (-10.776062)) < 1e-5 and abs(body["lon"] - (-82.912605)) < 1e-5
    assert body["access_no"] == 42682
    assert body["accession_url"] == "https://www.ncei.noaa.gov/archive/accession/42682"
    assert body["source_file_url"].endswith("/wod_pfl_2024.nc")
    assert body["cruise"] == "FR017070" and body["wmo_id"] == "6902961"
    assert len(body["pflag"]) == len(R.VARS) and len(body["n_src"]) == len(R.VARS)
    assert "Temperature" in body["flag_meanings"] and "z" in body["flag_meanings"]
    assert body["licence"].startswith("Public use") and body["citation"].startswith("Mishonov A.V., T. P. Boyer")
    # levels: at most MAX_LEVELS per variable, finite, and the oracle's oxygen pick is among them
    assert 0 < len(body["levels"]["o"]) <= R.MAX_LEVELS
    assert all(len(row) == 3 and all(math.isfinite(v) for v in row) for rows in body["levels"].values() for row in rows)
    oracle = EXPECTED["wod_pfl_2024_cut.nc"]["casts"]["22708857"]["picks"]["oxygen"]
    for pick in (p for p in oracle if p is not None):
        assert any(abs(d - pick[1]) < 1e-3 and abs(v - pick[2]) < 1e-4 and f == 0 for d, v, f in body["levels"]["o"])
    # no WOA grid on disk: the field is null at every display depth
    assert body["field"] == {"variable": "oxygen", "selected_depth": 0,
                             "values": {str(d): None for d in R.DEPTHS}}

    # the panel's picks equal the oracle's for EVERY drawn cast and every variable (N* included)
    for c in CASTS:
        got = (await api_get(f"/v1/wod/cast/{c['id']}")).json()["picks"]
        assert set(got) == set(R.PICK_VARS), c["id"]
        for var in R.PICK_VARS:
            want = [None if p is None else p[2] for p in c["picks"].get(var, [None] * 8)]
            for g, w in zip(got[var], want, strict=True):
                assert (g is None) == (w is None), (c["id"], var)
                if w is not None:
                    assert g == pytest.approx(w, rel=1e-6, abs=1e-6), (c["id"], var)

    # the field comes from sample_annual_point at the 8 display depths for the asked variable
    calls = []

    def fake(var, lat, lon, depth):
        calls.append((var, depth))
        return depth * 1.5
    monkeypatch.setattr(woa_climatology, "sample_annual_point", fake)
    r = await api_get("/v1/wod/cast/22708857?var=nstar&depth=500")
    assert r.json()["field"] == {"variable": "nstar", "selected_depth": 500,
                                 "values": {str(d): d * 1.5 for d in R.DEPTHS}}
    assert calls == [("nstar", float(d)) for d in R.DEPTHS]

    assert (await api_get("/v1/wod/cast/1")).status_code == 404
    for bad in ("/v1/wod/cast/abc", "/v1/wod/cast/1234567890", "/v1/wod/cast/22708857?var=nope",
                "/v1/wod/cast/22708857?depth=7"):
        assert (await api_get(bad)).status_code == 400, bad


@needs_db
async def test_meta_health_is_live_and_the_arithmetic_is_cached(db, cache, tmp_path):
    assert (await load_fixtures(db, tmp_path))["outcome"] == "complete"
    meta = (await api_get("/v1/wod/meta")).json()
    assert meta["tile_version"] == await _version(db) and meta["point_min_zoom"] == R.POINT_MIN_ZOOM
    assert meta["variables"] == list(R.PICK_VARS) and meta["depths"] == list(R.DEPTHS)
    assert meta["windows"] == [list(w) for w in R.WINDOWS] and meta["scales"] == R.SCALES
    assert meta["n_stored"] == meta["n_drawn"] == len(CASTS) and meta["year_min"] <= meta["year_max"]
    assert meta["licence"].startswith("Public use") and meta["citation"].startswith("Mishonov A.V., T. P. Boyer")
    assert set(meta["lod_counts"]) == {str(lv) for lv in R.LOD_LEVELS}
    assert meta["health"]["status"] == "ok" and meta["health"]["files"] == []
    for inst in ("osd", "ctd", "pfl"):
        cuts = [e for name, e in EXPECTED.items() if name.split("_")[1] == inst]
        a = meta["arithmetic"][inst]
        assert a["files"] == len(cuts)
        assert (a["source"], a["stored"], a["drawn"]) == tuple(
            sum(e["counts"][k] for e in cuts) for k in ("source", "stored", "drawn"))

    # P35: a file that fails after the load shows in `health` at once; the cached arithmetic is untouched
    await db.execute("UPDATE wod_files SET status = 'failed', failure = 'boom', failed_at = now() "
                     "WHERE file_id = (SELECT min(file_id) FROM wod_files)")
    again = (await api_get("/v1/wod/meta")).json()
    assert again["health"]["status"] == "failing" and again["health"]["failed_files"] == 1
    assert again["health"]["files"][0]["failure"] == "boom"
    assert again["arithmetic"] == meta["arithmetic"]


# ── the API never imports the loader ─────────────────────────────────────────────────────────────────────
def test_api_does_not_import_the_loader():
    """A fresh interpreter, so imports made earlier in this test session cannot mask the answer."""
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import domains.wod_casts; "
            "bad = [m for m in ('ingestion.wod_casts', 'ingestion.wod_casts_parse', 'wod_casts_worker', 'netCDF4') "
            "if m in sys.modules]; print(bad); sys.exit(1 if bad else 0)")
    backend = str(pathlib.Path(__file__).parent.parent)
    r = subprocess.run([sys.executable, "-I", "-c", code, backend], cwd=backend, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


# ── the one-value WOA reader, on a tiny grid written here ────────────────────────────────────────────────
FILL = 9.96921e36


def _write_annual(var_key: str, data: np.ndarray):
    """A 2 depth x 2 lat x 2 lon annual file where woa_climatology expects it for var_key."""
    import netCDF4
    path = woa_climatology._local_path(var_key, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    with netCDF4.Dataset(str(path), "w") as ds:
        for name, size in (("time", 1), ("depth", 2), ("lat", 2), ("lon", 2)):
            ds.createDimension(name, size)
        for name, vals in (("depth", [0.0, 50.0]), ("lat", [-0.5, 0.5]), ("lon", [-0.5, 0.5])):
            ds.createVariable(name, "f4", (name,))[:] = np.array(vals, dtype="f4")
        v = ds.createVariable(woa_climatology.WOA_VARS[var_key]["an_var"], "f4", ("time", "depth", "lat", "lon"),
                              fill_value=np.float32(FILL))
        v[0] = data
    return path


def test_sample_annual_point_reads_one_element(tmp_path, monkeypatch):
    monkeypatch.setattr(woa_climatology, "CACHE_DIR", tmp_path)
    grids_before = dict(woa_climatology._GRID_CACHE)
    data = np.array([[[0.25, 1.25], [10.25, 11.25]], [[100.25, 101.25], [110.25, 111.25]]], dtype="f4")
    data[1, 0, 0] = np.float32(FILL)                                  # depth 50 m, lat -0.5, lon -0.5: land
    _write_annual("temperature", data)
    f = woa_climatology.sample_annual_point
    assert f("temperature", 0.4, -0.4, 0.0) == 10.25                  # nearest cell: lat index 1, lon index 0
    assert f("temperature", -0.4, 0.4, 0.0) == 1.25
    assert f("temperature", 0.4, 0.4, 60.0) == 111.25                 # nearest depth is 50 m
    assert f("temperature", -0.4, -0.4, 50.0) is None                 # fill
    assert f("salinity", 0.4, -0.4, 0.0) is None                      # no file for this variable
    assert f("nonsense", 0.4, -0.4, 0.0) is None
    assert woa_climatology._GRID_CACHE == grids_before                # the whole grid is never loaded


def test_sample_annual_point_derives_nstar_from_two_reads(tmp_path, monkeypatch):
    monkeypatch.setattr(woa_climatology, "CACHE_DIR", tmp_path)
    nitrate = np.full((2, 2, 2), 20.0, dtype="f4")
    phosphate = np.full((2, 2, 2), 1.0, dtype="f4")
    phosphate[0, 1, 0] = np.float32(FILL)
    _write_annual("nitrate", nitrate)
    _write_annual("phosphate", phosphate)
    f = woa_climatology.sample_annual_point
    assert f("nstar", -0.4, -0.4, 0.0) == pytest.approx(20.0 - 16.0 * 1.0)
    assert f("nstar", 0.4, -0.4, 0.0) is None                          # fill in either input gives None, never 0
    assert f("nstar", 0.4, 0.4, 0.0) == pytest.approx(4.0)
