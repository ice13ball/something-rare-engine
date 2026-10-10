# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""SOCAT points API on the REAL fixture rows (tests/fixtures/socat_points/), loaded by the real loader.
The expectations are computed here from the stored observations (own Web-Mercator and cell arithmetic), never
read back from the tile SQL: a tile that groups, clamps or versions wrongly turns a test red."""
import math
import pathlib
import subprocess
import sys

import mapbox_vector_tile
import pytest

from domains import socat_points as route
from ingestion import socat_points as sp
from plankton_helpers import tile_of
from socat_helpers import api_get, conn, db, load_excerpt, needs_db  # noqa: F401  (fixtures)

WORLD = 20037508.342789244
R_EARTH = 6378137.0
IMMUTABLE_CC = "public, max-age=31536000, immutable"
V2 = "20261010000000-abcdef"


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    """No Telegram, no pause between batches, and a disk that is not the CI runner's."""
    async def fake(message, title="", **kw):
        return True
    monkeypatch.setattr(sp, "notify_telegram", fake)
    monkeypatch.setattr(sp, "SLICE_PAUSE_S", 0)
    monkeypatch.setattr(sp, "_disk_usage", lambda: (1000 * 1024 ** 3, 100 * 1024 ** 3))


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(route, "_refreshing", None, raising=False)
    monkeypatch.setenv("SOCAT_TILE_CACHE_DIR", str(tmp_path / "tiles"))
    monkeypatch.setattr(route, "_live", (None, 0.0), raising=False)
    return tmp_path / "tiles"


# ── the test's own arithmetic ────────────────────────────────────────────────────────────────────────────
def _merc(lon, lat):
    lat = max(-85.0511, min(85.0511, lat))
    return R_EARTH * math.radians(lon), R_EARTH * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def _box(z, x, y):
    size = 2 * WORLD / 2 ** z
    xmin, ymax = -WORLD + x * size, WORLD - y * size
    return xmin, ymax - size, xmin + size, ymax


def _cell(mx, my, box):
    xmin, ymin, xmax, ymax = box
    cx = min(255, int((mx - xmin) / (xmax - xmin) * 256))
    cy = min(255, int((ymax - my) / (ymax - ymin) * 256))
    return cy * 256 + cx


async def _stored_obs(db):
    """Every stored observation, unnested from the segments (the stored values, not the TSV)."""
    return await db.fetch("""
        SELECT s.expocode AS e, s.ord0 + u.i - 1 AS n, s.t0 + make_interval(secs => u.dt) AS ts,
               extract(year FROM (s.t0 + make_interval(secs => u.dt)) AT TIME ZONE 'UTC')::int AS yr,
               u.lon, u.lat, u.f, u.tc, u.sa, u.wf, s.qc_flag
        FROM socat_segments s
        CROSS JOIN LATERAL unnest(s.lon, s.lat, s.dt_s, s.fco2, s.sst, s.sal, s.fco2_flag)
             WITH ORDINALITY AS u(lon, lat, dt, f, tc, sa, wf, i)""")


def _expected(rows, z, x, y):
    """{(year, q): observations sorted by (time, expocode, ordinal)} of the drawable observations in tile z/x/y."""
    box = _box(z, x, y)
    groups = {}
    for r in rows:
        if r["wf"] != 2 or r["qc_flag"] not in "ABCD":
            continue
        mx, my = _merc(r["lon"], r["lat"])
        if box[0] <= mx < box[2] and box[1] < my <= box[3]:
            groups.setdefault((r["yr"], _cell(mx, my, box)), []).append(r)
    for g in groups.values():
        g.sort(key=lambda r: (r["ts"], r["e"], r["n"]))
    return groups


def _mean(values):
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _decode(data, layer="socat"):
    return mapbox_vector_tile.decode(data)[layer]["features"]


async def _tile(z, x, y, query=""):
    return await api_get(f"/v1/socat/tiles/{z}/{x}/{y}.pbf{query}")


def _check_feature(props, group):
    first = group[0]
    assert (props["e"], props["n"], props["k"], props["c"]) == (first["e"], first["n"], len(group),
                                                                 len({g["e"] for g in group}))
    assert abs(props["f"] - round(_mean([g["f"] for g in group]) * 10)) <= 1
    for key, col, scale in (("t", "tc", 100), ("s", "sa", 100)):
        m = _mean([g[col] for g in group])
        if m is None:
            assert key not in props, f"{key} must be absent when every value is missing"
        else:
            assert abs(props[key] - round(m * scale)) <= 1


# ── before the first build ───────────────────────────────────────────────────────────────────────────────
@needs_db
async def test_tile_503_before_first_build(db, cache):
    from services import socat_tiles
    assert route.MAX_ZOOM == socat_tiles.TILE_MAX_ZOOM == 12   # the route keeps a literal (import cycle through schema)
    assert (await _tile(13, 0, 0)).status_code == 400 and not cache.exists()
    r = await _tile(0, 0, 0)
    assert r.status_code == 503 and r.headers["retry-after"] == "300"
    assert not cache.exists()                     # nothing cached for a state that is not data
    r = await _tile(9, 261, 169)
    assert r.status_code == 503 and r.headers["retry-after"] == "300" and not cache.exists()


# ── the point zoom: one feature per (UTC year, cell), computed here from the stored observations ─────────
@needs_db
async def test_point_tile_has_the_observation(db, tmp_path, cache):
    assert (await load_excerpt(tmp_path))["outcome"] == "swapped"
    rows = await _stored_obs(db)

    # z12 over the first observation of 76XL20160724 whose SST is missing (NaN in the source)
    nan = next(r for r in rows if r["e"] == "76XL20160724" and r["tc"] is None)
    x, y = tile_of(nan["lon"], nan["lat"], 12)
    r = await _tile(12, x, y)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.mapbox-vector-tile")
    feats = _decode(r.content)
    want = _expected(rows, 12, x, y)
    assert {(f["properties"]["y"], f["properties"]["q"]) for f in feats} == set(want)
    for f in feats:
        _check_feature(f["properties"], want[(f["properties"]["y"], f["properties"]["q"])])
    mx, my = _merc(nan["lon"], nan["lat"])
    mine = want[(nan["yr"], _cell(mx, my, _box(12, x, y)))]
    assert any(g["e"] == nan["e"] and g["n"] == nan["n"] for g in mine)
    if all(g["tc"] is None for g in mine):          # the cell holds only NaN-SST rows: no `t` property at all
        feat = next(f for f in feats if f["properties"]["q"] == _cell(mx, my, _box(12, x, y)))
        assert "t" not in feat["properties"]

    # z9 over 11BE20021104: features == distinct (cell, year); every observation counted once
    first = next(r for r in rows if r["e"] == "11BE20021104")
    x9, y9 = tile_of(first["lon"], first["lat"], 9)
    r = await _tile(9, x9, y9)
    assert r.status_code == 200
    feats = _decode(r.content)
    want = _expected(rows, 9, x9, y9)
    keys = [(f["properties"]["y"], f["properties"]["q"]) for f in feats]
    assert len(keys) == len(set(keys)) == len(want) and set(keys) == set(want)
    assert sum(f["properties"]["k"] for f in feats) == sum(len(g) for g in want.values())
    assert all(0 <= f["properties"]["q"] < 65536 for f in feats)
    for f in feats:
        _check_feature(f["properties"], want[(f["properties"]["y"], f["properties"]["q"])])


# ── what a feature stands for ────────────────────────────────────────────────────────────────────────────
@needs_db
async def test_cell_lists_what_the_feature_stands_for(db, tmp_path, cache):
    assert (await load_excerpt(tmp_path))["outcome"] == "swapped"
    rows = await _stored_obs(db)
    version = await db.fetchval("SELECT tile_version FROM socat_points_source WHERE id = 1")
    first = next(r for r in rows if r["e"] == "11BE20021104")
    x, y = tile_of(first["lon"], first["lat"], 9)
    feats = _decode((await _tile(9, x, y)).content)
    feat = max(feats, key=lambda f: f["properties"]["k"])["properties"]
    assert feat["k"] > 1                              # the station sat still for hours: many rows in one cell

    r = await api_get(f"/v1/socat/cell/9/{x}/{y}/{feat['q']}?year={feat['y']}&v={version}")
    assert r.status_code == 200 and r.headers["cache-control"] == IMMUTABLE_CC
    body = r.json()
    assert body["n_obs"] == feat["k"] and body["n_cruises"] == feat["c"]
    assert len(body["observations"]) == feat["k"] and body["observations_truncated"] is False
    times = [o["time"] for o in body["observations"]]
    assert times == sorted(times)
    assert body["observations"][0]["obs_key"] == f"{feat['e']}~{feat['n']}"
    assert body["cruises"][0]["expocode"] == feat["e"] and body["cruises"][0]["n_obs"] == feat["k"]
    assert body["cell"]["west"] < body["observations"][0]["lon"] < body["cell"]["east"]
    for o in body["observations"]:                     # every key opens the observation it names
        one = await api_get(f"/v1/socat/obs/{o['obs_key']}")
        assert one.status_code == 200 and one.json()["obs_key"] == o["obs_key"]
        assert one.json()["time"] == o["time"]
    # not the live version: still served, but not marked immutable
    stale = await api_get(f"/v1/socat/cell/9/{x}/{y}/{feat['q']}?year={feat['y']}&v=20200101000000-aaaaaa")
    assert stale.status_code == 200 and "immutable" not in stale.headers["cache-control"]

    used = {f["properties"]["q"] for f in feats if f["properties"]["y"] == feat["y"]}
    empty_q = next(q for q in range(65536) if q not in used)
    r = await api_get(f"/v1/socat/cell/9/{x}/{y}/{empty_q}?year={feat['y']}")
    assert r.status_code == 404
    assert (await api_get(f"/v1/socat/cell/9/{x}/{y}/{feat['q']}?year=1999")).status_code == 404
    for bad in (f"/v1/socat/cell/9/{x}/{y}/65536?year=2002", f"/v1/socat/cell/9/{x}/{y}/abc?year=2002",
                f"/v1/socat/cell/8/{x // 2}/{y // 2}/5?year=2002", f"/v1/socat/cell/13/0/0/5?year=2002",
                f"/v1/socat/cell/9/{x}/{y}/5", f"/v1/socat/cell/9/{x}/{y}/5?year=20x2",
                f"/v1/socat/cell/9/{2 ** 9}/0/5?year=2002"):
        assert (await api_get(bad)).status_code == 400, bad
    assert (await api_get("/v1/socat/obs/11BE20021104~99999")).status_code == 404     # past the cruise's rows
    assert (await api_get("/v1/socat/obs/NOSUCHCRUISE~0")).status_code == 404
    assert (await api_get("/v1/socat/obs/not%20a%20key")).status_code == 400


# ── the pole ─────────────────────────────────────────────────────────────────────────────────────────────
@needs_db
async def test_pole_tile_renders(db, tmp_path, cache):
    assert (await load_excerpt(tmp_path))["outcome"] == "swapped"
    rows = await _stored_obs(db)
    pole = next(r for r in rows if r["e"] == "06AQ20200801" and r["lat"] > 85.2)   # clamped to 85.0511 in the tile
    assert max(r["lat"] for r in rows if r["e"] == "06AQ20200801") >= 89.9     # lat 90 must not become NaN geometry
    x, y = tile_of(pole["lon"], 85.0511, 9)
    r = await _tile(9, x, y)
    assert r.status_code == 200
    feats = _decode(r.content)
    want = _expected(rows, 9, x, y)
    assert feats and {(f["properties"]["y"], f["properties"]["q"]) for f in feats} == set(want)
    assert any(f["properties"]["e"] == "06AQ20200801" for f in feats)
    # the reduced pieces of the same cruise: the L3 tile (z7) and the world tile (L0)
    x7, y7 = tile_of(pole["lon"], 85.0511, 7)
    for z, tx, ty in ((7, x7, y7), (0, 0, 0)):
        r = await _tile(z, tx, ty)
        assert r.status_code == 200, z
        assert any(f["properties"]["e"] == "06AQ20200801" for f in _decode(r.content)), z


# ── a reload or a purge never serves the old version as current ──────────────────────────────────────────
@needs_db
async def test_reload_never_serves_old_version(db, tmp_path, cache):
    assert (await load_excerpt(tmp_path))["outcome"] == "swapped"
    v1 = await db.fetchval("SELECT tile_version FROM socat_points_source WHERE id = 1")
    rows = await _stored_obs(db)
    first = next(r for r in rows if r["e"] == "11BE20021104")
    x, y = tile_of(first["lon"], first["lat"], 9)
    on_disk = lambda v: cache / v / "all" / "9" / str(x) / f"{y}.pbf"   # noqa: E731

    r = await _tile(9, x, y)                                            # no v: rendered, filed under v1
    assert r.status_code == 200 and on_disk(v1).exists() and "immutable" not in r.headers["cache-control"]
    r = await _tile(9, x, y, f"?v={v1}")                                 # v is the live version: immutable
    assert r.status_code == 200 and r.headers["cache-control"] == IMMUTABLE_CC

    # the swap: new data version (the swap transaction writes tile_version)
    await db.execute("UPDATE socat_points_source SET tile_version = $1 WHERE id = 1", V2)
    r = await _tile(9, x, y)                                            # no v: bytes rendered under V2
    assert r.status_code == 200 and on_disk(V2).exists() and on_disk(v1).exists()
    assert "immutable" not in r.headers["cache-control"]
    r = await _tile(9, x, y, f"?v={v1}")                                 # the old version is still on disk, but is no longer live
    assert r.status_code == 200 and "immutable" not in r.headers["cache-control"]
    r = await _tile(9, x, y, f"?v={V2}")
    assert r.status_code == 200 and r.headers["cache-control"] == IMMUTABLE_CC

    # the psql purge (C5): TRUNCATE + tile_version = NULL, then the admin cache sweep inside a running loop
    await db.execute("TRUNCATE socat_segments, socat_lod, socat_cruises")
    await db.execute("UPDATE socat_points_source SET tile_version = NULL WHERE id = 1")
    route.clear_caches()
    await route._reconcile_task
    assert not (cache / v1).exists() and not (cache / V2).exists()
    for q in ("", f"?v={v1}", f"?v={V2}"):
        r = await _tile(9, x, y, q)
        assert r.status_code == 503 and r.headers["retry-after"] == "300", q
    assert (await api_get(f"/v1/socat/cell/9/{x}/{y}/5?year=2002")).status_code == 503


def test_api_does_not_import_loader():
    """A fresh interpreter, so imports made earlier in this test session cannot mask the answer."""
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import domains.socat_points; "
            "bad = [m for m in ('ingestion.socat_points', 'socat_points_worker', 'duckdb') if m in sys.modules]; "
            "print(bad); sys.exit(1 if bad else 0)")
    backend = str(pathlib.Path(__file__).parent.parent)
    r = subprocess.run([sys.executable, "-I", "-c", code, backend], cwd=backend, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
