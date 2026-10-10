# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""WOD casts loader run on the REAL cut files (tests/fixtures/wod_casts/), the counts compared with the
independent oracle in expected.json. Each test guards one silent failure: lost or doubled casts, a refresh that
deletes without inserting, a duplicate cast id dropped without a count, LOD sums that disagree with the casts,
`_new` names left behind after the swap, a disk stop that touched the live tables."""
import json
import re

import pytest

from ingestion import wod_casts as wc
from ingestion import wod_casts_rules as R
from wod_helpers import (EXPECTED, FIX, base_url, conn, db, load_fixtures, needs_db,  # noqa: F401
                         register, run_loader)

GIB = 1024 ** 3
ORACLE_IDS = {int(k) for exp in EXPECTED.values() for k, c in exp["casts"].items()
              if c["status"] not in ("no_depth_levels", "no_values", "bad_coords")}
assert len(ORACLE_IDS) == 21


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    """No pause between chunks and a disk that is not the CI runner's."""
    monkeypatch.setattr(wc, "SLICE_PAUSE_S", 0)
    monkeypatch.setattr(wc, "_disk_usage", lambda path: (1000 * GIB, 100 * GIB, 900 * GIB))


async def _files(db):
    return {r["url"].rsplit("/", 1)[-1]: r for r in await db.fetch("SELECT * FROM wod_files ORDER BY file_id")}


@needs_db
async def test_load_counts_equal_the_oracle(db, tmp_path):
    res = await load_fixtures(db, tmp_path)
    assert res["outcome"] == "complete", res
    assert re.fullmatch(r"\d{14}-[0-9a-f]{6}", res["version"]), res
    rows = await _files(db)
    for cut, exp in EXPECTED.items():
        r, c = rows[exp["source_file"]], exp["counts"]
        rej = json.loads(r["rejects"])
        assert r["status"] == "loaded" and r["failure"] is None, cut
        assert (r["n_casts_source"], r["n_stored"], r["n_drawn"]) == (c["source"], c["stored"], c["drawn"]), cut
        for k in ("source", "no_depth_levels", "no_values", "no_good", "no_date"):   # P19: the oracle's keys
            assert rej.get(k, 0) == c[k], (cut, k)
        assert rej["stored"] == c["stored"] and rej.get("duplicate_cast_id", 0) == 0 and rej.get("bad_coords", 0) == 0
        assert rej["source"] == (rej.get("no_depth_levels", 0) + rej.get("no_values", 0) + rej.get("bad_coords", 0)
                                 + rej.get("duplicate_cast_id", 0) + rej["stored"]), cut
        assert r["n_drawn"] == r["n_stored"] - rej.get("no_good", 0) - rej.get("no_date", 0), cut
        assert r["loaded_content_length"] == r["content_length"] and r["loaded_at"] is not None
        assert await db.fetchval("SELECT count(*) FROM wod_casts WHERE file_id = $1", r["file_id"]) == c["stored"]
        assert await db.fetchval("SELECT count(*) FROM wod_cast_points WHERE file_id = $1", r["file_id"]) == c["drawn"]
    stored = sum(e["counts"]["stored"] for e in EXPECTED.values())
    drawn = sum(e["counts"]["drawn"] for e in EXPECTED.values())
    assert await db.fetchval("SELECT count(*) FROM wod_casts") == stored
    assert await db.fetchval("SELECT count(*) FROM wod_cast_points") == drawn
    assert {r["cast_id"] for r in await db.fetch("SELECT cast_id FROM wod_casts")} == ORACLE_IDS
    assert await db.fetchval("SELECT count(*) FROM wod_casts_stage") == 0
    assert await db.fetchval("SELECT count(*) FROM wod_points_stage") == 0
    src = await db.fetchrow("SELECT * FROM wod_casts_source WHERE id = 1")
    assert (src["n_stored"], src["n_drawn"]) == (stored, drawn)
    assert "z" in json.loads(src["flag_meanings"]) and "Temperature" in json.loads(src["flag_meanings"])
    log = await db.fetchrow("SELECT * FROM sync_log WHERE source = 'wod-casts'")
    assert log["total_records"] == stored and log["last_synced_at"] is not None and log["skipped_reason"] is None


@needs_db
async def test_reload_same_file_is_idempotent(db, tmp_path):
    first = await load_fixtures(db, tmp_path)
    assert first["outcome"] == "complete", first
    ids = {r["cast_id"] for r in await db.fetch("SELECT cast_id FROM wod_casts")}
    n_points = await db.fetchval("SELECT count(*) FROM wod_cast_points")
    await db.execute("UPDATE wod_files SET status = 'pending' WHERE url LIKE '%/wod_osd_2015.nc'")
    second = await run_loader(tmp_path)
    assert second["outcome"] == "complete", second
    assert [x["outcome"] for x in second["files"]] == ["loaded"] and second["files"][0]["stored"] == 5
    assert {r["cast_id"] for r in await db.fetch("SELECT cast_id FROM wod_casts")} == ids
    assert await db.fetchval("SELECT count(*) - count(DISTINCT cast_id) FROM wod_casts") == 0
    assert await db.fetchval("SELECT count(*) - count(DISTINCT cast_id) FROM wod_cast_points") == 0
    assert await db.fetchval("SELECT count(*) FROM wod_cast_points") == n_points
    assert (await _files(db))["wod_osd_2015.nc"]["n_stored"] == 5
    for lv in R.LOD_LEVELS:                                       # the refresh made the LOD due again and it was rebuilt
        assert await db.fetchval("SELECT sum(n) FROM wod_cells WHERE level = $1", lv) == n_points


@needs_db
async def test_shrunk_file_blocks_and_keeps_rows(db, tmp_path):
    first = await load_fixtures(db, tmp_path)
    fid = (await _files(db))["wod_osd_2015.nc"]["file_id"]
    ids = {r["cast_id"] for r in await db.fetch("SELECT cast_id FROM wod_casts WHERE file_id = $1", fid)}
    assert len(ids) == 5
    await db.execute("UPDATE wod_files SET status = 'pending', n_stored = n_stored * 10 WHERE file_id = $1", fid)
    res = await run_loader(tmp_path)
    assert res["outcome"] == "blocked", res
    assert [x["outcome"] for x in res["files"]] == ["blocked"]
    row = (await _files(db))["wod_osd_2015.nc"]
    assert row["status"] == "blocked" and "drop" in row["failure"] and row["n_stored"] == 50
    assert {r["cast_id"] for r in await db.fetch("SELECT cast_id FROM wod_casts WHERE file_id = $1", fid)} == ids
    assert await db.fetchval("SELECT count(*) FROM wod_cast_points WHERE file_id = $1", fid) == 5
    assert res["version"] == first["version"]                     # nothing loaded, no rebuild
    assert await db.fetchval("SELECT count(*) FROM wod_casts_stage") == 0


@needs_db
async def test_duplicate_cast_id_is_counted(db, tmp_path):
    await register(db, "wod_osd_2015.nc")
    await register(db, "wod_osd_2015.nc", url=f"{base_url()}/2016/wod_osd_2015.nc")   # the same casts, another file
    res = await run_loader(tmp_path)
    assert res["outcome"] == "complete", res
    rows = list(await db.fetch("SELECT * FROM wod_files ORDER BY file_id"))
    first, second = rows
    assert first["n_stored"] == 5 and second["n_stored"] == 0 and second["n_drawn"] == 0
    rej = json.loads(second["rejects"])
    assert rej["duplicate_cast_id"] == first["n_stored"] == 5      # P11
    assert second["n_casts_source"] == 5 and rej["stored"] == 0
    assert rej["source"] == (rej.get("no_depth_levels", 0) + rej.get("no_values", 0) + rej.get("bad_coords", 0)
                             + rej["duplicate_cast_id"] + rej["stored"])
    assert await db.fetchval("SELECT count(*) FROM wod_casts") == 5
    assert await db.fetchval("SELECT count(*) FROM wod_cast_points") == 5
    assert await db.fetchval("SELECT count(*) FROM wod_casts WHERE file_id = $1", second["file_id"]) == 0
    # a later refresh of the all-duplicate file: previous stored 0 neither blocks nor divides
    await db.execute("UPDATE wod_files SET status = 'pending' WHERE file_id = $1", second["file_id"])
    again = await run_loader(tmp_path)
    assert again["outcome"] == "complete", again
    assert [x["outcome"] for x in again["files"]] == ["loaded"]
    assert await db.fetchval("SELECT count(*) FROM wod_casts") == 5


@needs_db
async def test_lod_sums_and_swap(db, tmp_path):
    res = await load_fixtures(db, tmp_path)
    assert res["outcome"] == "complete", res
    n_points = await db.fetchval("SELECT count(*) FROM wod_cast_points")
    assert n_points == sum(e["counts"]["drawn"] for e in EXPECTED.values()) == 21
    for lv in R.LOD_LEVELS:
        assert await db.fetchval("SELECT sum(n) FROM wod_cells WHERE level = $1", lv) == n_points, lv
    assert await db.fetchval("SELECT count(DISTINCT level) FROM wod_cells") == len(R.LOD_LEVELS)
    # one oracle cast: its pick sits in its cell at every level (s and c at the temperature slot)
    cid, val = next((int(k), c["picks"]["temperature"][0][2]) for exp in EXPECTED.values()
                    for k, c in exp["casts"].items()
                    if c["status"] == "drawn" and c["picks"].get("temperature", [None])[0] is not None)
    p = await db.fetchrow("SELECT key, year, picks FROM wod_cast_points WHERE cast_id = $1", cid)
    slot = R.slot("temperature", 0)
    assert p["picks"][slot] is not None and abs(p["picks"][slot] - R.scaled(val, "temperature")) <= 1
    for lv in R.LOD_LEVELS:
        shift = 2 * (R.GRID_BITS - R.level_bits(lv))
        cell = p["key"] >> shift
        got = await db.fetchrow("SELECT s[$4::int] AS s, c[$4::int] AS c, n FROM wod_cells "
                                "WHERE level = $1 AND cell = $2 AND year = $3", lv, cell, p["year"], slot + 1)
        want = await db.fetchrow("SELECT sum(picks[$3::int])::real AS s, count(picks[$3::int]) AS c, count(*) AS n "
                                 "FROM wod_cast_points WHERE (key >> $1::int) = $2::bigint AND year = $4",
                                 shift, cell, slot + 1, p["year"])
        assert got is not None and got["c"] >= 1 and got["s"] is not None, lv
        assert (got["s"], got["c"], got["n"]) == (want["s"], want["c"], want["n"]), lv
    # the swap left no `_new` name behind and the pkey carries the live name
    left = await db.fetch("SELECT relname FROM pg_class WHERE relnamespace = current_schema()::regnamespace "
                          "AND relname LIKE 'wod\\_%\\_new%'")
    assert left == []
    assert [r["indexname"] for r in await db.fetch(
        "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema() AND tablename = 'wod_cells'")] == ["wod_cells_pkey"]
    assert [r["conname"] for r in await db.fetch(
        "SELECT conname FROM pg_constraint WHERE conrelid = 'wod_cells'::regclass")] == ["wod_cells_pkey"]
    src = await db.fetchrow("SELECT * FROM wod_casts_source WHERE id = 1")
    assert re.fullmatch(r"\d{14}-[0-9a-f]{6}", src["tile_version"]) and src["tile_version"] == res["version"]
    assert src["tile_built_at"] is not None and src["point_min_zoom"] == R.POINT_MIN_ZOOM
    assert src["n_drawn"] == n_points and src["year_min"] <= src["year_max"]
    assert set(json.loads(src["lod_counts"])) == {str(lv) for lv in R.LOD_LEVELS}
    assert json.loads(src["last_rejects"])["source"] == sum(e["counts"]["source"] for e in EXPECTED.values())


@needs_db
async def test_disk_projection_refuses_before_touching_anything(db, tmp_path, monkeypatch):
    monkeypatch.setattr(wc, "_disk_usage", lambda path: (1000 * GIB, 799 * GIB, 900 * GIB))
    res = await load_fixtures(db, tmp_path)
    assert res["outcome"] == "disk" and res["files"] == [], res
    assert await db.fetchval("SELECT count(*) FROM wod_files WHERE status = 'pending'") == 5
    assert await db.fetchval("SELECT count(*) FROM wod_casts") == 0
    log = await db.fetchrow("SELECT * FROM sync_log WHERE source = 'wod-casts'")
    assert log["skipped_reason"].startswith("disk")


@needs_db
async def test_download_filesystem_needs_the_file_plus_one_gib(db, tmp_path, monkeypatch):
    monkeypatch.setattr(wc, "_disk_usage", lambda path: (1000 * GIB, 100 * GIB, GIB // 2))
    res = await load_fixtures(db, tmp_path)
    assert res["outcome"] == "disk" and "download filesystem" in res["reasons"][0], res
    assert await db.fetchval("SELECT count(*) FROM wod_casts") == 0


@needs_db
async def test_actual_disk_stop_mid_file_keeps_the_live_tables(db, tmp_path, monkeypatch):
    monkeypatch.setattr(wc, "_db_fraction", lambda: 0.9)
    res = await load_fixtures(db, tmp_path)
    assert res["outcome"] == "disk", res
    assert await db.fetchval("SELECT count(*) FROM wod_casts") == 0
    assert await db.fetchval("SELECT count(*) FROM wod_casts_stage") == 0   # the staging is truncated
    assert await db.fetchval("SELECT count(*) FROM wod_files WHERE status = 'pending'") == 5


@needs_db
async def test_size_mismatch_fails_the_file_and_the_run_goes_on(db, tmp_path):
    await register(db, "wod_osd_2015.nc")
    await register(db, "wod_ctd_2015.nc")
    await db.execute("UPDATE wod_files SET content_length = content_length + 1 WHERE url LIKE '%/wod_osd_2015.nc'")
    res = await run_loader(tmp_path)
    assert res["outcome"] == "error", res
    rows = await _files(db)
    assert rows["wod_osd_2015.nc"]["status"] == "failed" and "size" in rows["wod_osd_2015.nc"]["failure"]
    assert rows["wod_ctd_2015.nc"]["status"] == "loaded"
    assert list((tmp_path / "download").iterdir()) == []         # nothing left in the download directory


@needs_db
async def test_discovery_marks_new_changed_missing_and_reappeared(db):
    base = base_url()
    root = (FIX / "listing_root.html").read_text()
    y1800 = (FIX / "listing_1800.html").read_text()

    def page(*names):
        return "".join(f'<tr><td><a href="{n}">{n}</a></td></tr>' for n in names)

    state = {"raise_year": None, "ctd_1901": False, "head_fail": None, "head_1900": None}

    def get_text(url):
        if url == base + "/":
            return root
        y = int(url.rstrip("/").rsplit("/", 1)[1])
        if y == state["raise_year"]:
            raise OSError("listing failed")
        if y == 1800:
            return y1800
        if y == 1901 and state["ctd_1901"]:
            return page("wod_ctd_1901.nc")
        return page(f"wod_osd_{y}.nc")

    def head_fn(url):
        y = int(url.rsplit("_", 1)[1][:4])
        if url.endswith("wod_osd_1950.nc") and state["head_fail"]:
            raise OSError("HEAD failed")
        return {"content_length": (5000 if url.endswith("wod_osd_1900.nc") and state["head_1900"] else 1000) + y,
                "last_modified": "lm"}

    r1 = await wc.discover_and_mark(db, get_text=get_text, head_fn=head_fn)
    assert (r1["new"], r1["changed"], r1["missing"], r1["listed"]) == (128, 0, 0, 128), r1
    assert r1["years_failed"] == [] and r1["heads_failed"] == []
    assert await db.fetchval("SELECT count(*) FROM wod_files WHERE status = 'pending'") == 128
    assert await db.fetchval("SELECT last_checked_at IS NOT NULL FROM wod_casts_source WHERE id = 1")
    await db.execute("UPDATE wod_files SET status = 'loaded', loaded_content_length = content_length, "
                     "loaded_last_modified = last_modified, loaded_at = now()")

    state.update(raise_year=2000, ctd_1901=True, head_fail=True, head_1900=True)
    r2 = await wc.discover_and_mark(db, get_text=get_text, head_fn=head_fn)
    assert (r2["new"], r2["changed"], r2["missing"], r2["reappeared"]) == (1, 1, 1, 0), r2
    assert r2["years_failed"] == [2000] and r2["heads_failed"] == [f"{base}/1950/wod_osd_1950.nc"]
    st = {r["url"].rsplit("/", 1)[-1]: r["status"] for r in await db.fetch("SELECT url, status FROM wod_files")}
    assert st["wod_osd_1900.nc"] == "pending" and st["wod_osd_1901.nc"] == "missing"
    assert st["wod_osd_2000.nc"] == "loaded" and st["wod_osd_1950.nc"] == "loaded" and st["wod_ctd_1901.nc"] == "pending"

    state.update(raise_year=None, ctd_1901=False, head_fail=False, head_1900=False)
    r3 = await wc.discover_and_mark(db, get_text=get_text, head_fn=head_fn)
    assert (r3["new"], r3["changed"], r3["missing"], r3["reappeared"]) == (0, 0, 1, 1), r3
    st = {r["url"].rsplit("/", 1)[-1]: r["status"] for r in await db.fetch("SELECT url, status FROM wod_files")}
    assert st["wod_osd_1901.nc"] == "loaded" and st["wod_ctd_1901.nc"] == "missing" and st["wod_osd_1900.nc"] == "pending"
    assert await db.fetchval("SELECT count(*) FROM wod_files") == 129                      # rows are never deleted


def test_listing_parsers_on_real_html():
    years = wc.parse_year_dirs((FIX / "listing_root.html").read_text())
    assert years == sorted(set(years)) and len(years) == 128
    assert years[0] == 1800 and years[1] == 1900 and years[-1] == 2026
    assert all(y == 1800 or 1900 <= y <= 2026 for y in years)
    assert wc.parse_year_files((FIX / "listing_1800.html").read_text()) == [("wod_osd_1800.nc", "osd", 1800)]
    assert wc.parse_year_files((FIX / "listing_root.html").read_text()) == []     # pre1900 / surf_all are not year files
