# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""SOCAT points loader run on the REAL fixture rows (tests/fixtures/socat_points/), zipped like the NCEI file.
Each test guards one silent failure: lost or doubled rows, `_new`-named leftovers after the swap, a
degenerate bbox killing the COPY, a resume that double-loads, a version not tied to the data."""
import re

import pytest

from ingestion import socat_points as sp
from schema.socat_points import ensure_socat_points
from socat_helpers import conn, db, excerpt_rows, load_excerpt, needs_db  # noqa: F401  (fixtures)

ROWS = len(excerpt_rows())
EXPOCODES = sorted({ln.split("\t", 1)[0] for ln in excerpt_rows()})


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    """No Telegram, no pause between batches, and a disk that is not the CI runner's."""
    async def fake(message, title="", **kw):
        return True
    monkeypatch.setattr(sp, "notify_telegram", fake)
    monkeypatch.setattr(sp, "SLICE_PAUSE_S", 0)
    monkeypatch.setattr(sp, "_disk_usage", lambda: (1000 * 1024 ** 3, 100 * 1024 ** 3))


@needs_db
async def test_load_counts_and_swap(db, tmp_path):
    res = await load_excerpt(tmp_path)
    assert res["outcome"] == "swapped", res
    assert res["rows"] == ROWS == 1195
    assert await db.fetchval("SELECT sum(n_obs) FROM socat_segments") == ROWS
    assert await db.fetchval("SELECT sum(n_obs) FROM socat_cruises") == ROWS
    # 12 cruises have rows; 09SS20080228 is listed in the dataset table but has none -> no cruise row
    assert [r["expocode"] for r in await db.fetch("SELECT expocode FROM socat_cruises ORDER BY expocode")] == EXPOCODES
    assert len(EXPOCODES) == 12 and "09SS20080228" not in EXPOCODES
    assert await db.fetchval("SELECT count(DISTINCT expocode) FROM socat_segments") == 12
    # every LOD level stands for the same observations the segments draw
    for lv in range(4):
        assert await db.fetchval("SELECT sum(n_obs) FROM socat_lod WHERE level = $1", lv) == ROWS
    src = await db.fetchrow("SELECT * FROM socat_points_source WHERE id = 1")
    assert (src["n_rows_stored"], src["n_rows_source"], src["n_cruises"], src["n_datasets_listed"]) == (ROWS, ROWS, 12, 13)
    assert src["n_rows_rejected"] == 0 and src["staging_sha256"] is None
    # the metadata of a cruise came from the dataset table, the position summary from the rows
    row = await db.fetchrow("SELECT platform_name, qc_flag FROM socat_cruises WHERE expocode = '06AQ19911114'")
    assert (row["platform_name"], row["qc_flag"]) == ("Polarstern", "D")
    assert await db.fetchval("SELECT count(*) FROM pg_class WHERE relname LIKE 'socat%\\_new%'") == 0


@needs_db
async def test_swap_renames_indexes(db, tmp_path):
    res = await load_excerpt(tmp_path)
    assert res["outcome"] == "swapped", res

    async def per_table():
        return {r["tablename"]: r["n"] for r in await db.fetch(
            "SELECT tablename, count(*) AS n FROM pg_indexes WHERE schemaname = current_schema() "
            "AND tablename LIKE 'socat\\_%' AND tablename <> 'socat_points_source' GROUP BY tablename")}

    after_swap = await per_table()
    assert after_swap == {"socat_segments": 3, "socat_lod": 4, "socat_cruises": 1}
    await ensure_socat_points(db)                       # what the API/worker does at start
    assert await per_table() == after_swap              # no second set of indexes beside the renamed ones
    leftovers = await db.fetch(
        "SELECT relname FROM pg_class WHERE relnamespace = current_schema()::regnamespace "
        "AND relname LIKE 'socat%\\_new%'")
    assert leftovers == []
    cons = await db.fetch("SELECT c.conname FROM pg_constraint c JOIN pg_class r ON r.oid = c.conrelid "
                          "WHERE r.relname LIKE 'socat\\_%' AND c.conname LIKE '%\\_new%'")
    assert cons == []
    seq = await db.fetchval("SELECT pg_get_serial_sequence('socat_segments', 'seg_id')")
    assert seq.endswith("socat_segments_seg_id_seq")


@needs_db
async def test_bbox_is_always_a_polygon(db, tmp_path):
    res = await load_excerpt(tmp_path)
    assert res["outcome"] == "swapped", res
    # the fixture's real degenerate envelopes: 1-observation segments (06AQ20200801 sits at lat 90 -> clamped flat)
    for expo in ("06AQ20200801", "31HO19571021", "64SA20060719"):
        assert await db.fetchval("SELECT count(*) FROM socat_segments WHERE expocode = $1 AND n_obs = 1", expo) > 0, expo
    bad = await db.fetch("SELECT seg_id FROM socat_segments WHERE GeometryType(bbox) <> 'POLYGON' "
                         "OR ST_NPoints(bbox) <> 5 OR NOT ST_IsValid(bbox)")
    assert bad == []
    one = await db.fetch("SELECT GeometryType(bbox) AS g, ST_NPoints(bbox) AS n FROM socat_segments "
                         "WHERE n_obs = 1 AND expocode IN ('06AQ20200801', '31HO19571021', '64SA20060719')")
    assert one and {(r["g"], r["n"]) for r in one} == {("POLYGON", 5)}


@needs_db
async def test_resume_skips_committed_cruises(db, tmp_path, monkeypatch):
    monkeypatch.setattr(sp, "BATCH_MIN_OBS", 1)          # one cruise per batch
    stop = {"at": 1}

    async def kill(n):
        if n == stop["at"]:
            raise RuntimeError("killed after batch 1")
    monkeypatch.setattr(sp, "_after_batch", kill)
    first = await load_excerpt(tmp_path)
    assert first["outcome"] == "resumable", first
    src = await db.fetchrow("SELECT staging_last_expocode, staging_rows FROM socat_points_source WHERE id = 1")
    assert src["staging_last_expocode"] == "06AQ19911114" and src["staging_rows"] == 100     # file order, first cruise
    assert await db.fetchval("SELECT count(*) FROM socat_cruises_new") == 1
    assert await db.fetchval("SELECT count(*) FROM socat_segments") == 0                      # live untouched

    stop["at"] = None
    second = await load_excerpt(tmp_path)               # same file -> same sha
    assert second["outcome"] == "swapped", second
    assert second["rows"] == ROWS
    assert await db.fetchval("SELECT sum(n_obs) FROM socat_segments") == ROWS
    assert await db.fetchval("SELECT count(*) FROM socat_cruises") == 12
    assert await db.fetchval("SELECT count(*) FROM (SELECT expocode, ord0 FROM socat_segments "
                             "GROUP BY 1, 2 HAVING count(*) > 1) d") == 0
    for lv in range(4):
        assert await db.fetchval("SELECT sum(n_obs) FROM socat_lod WHERE level = $1", lv) == ROWS


@needs_db
async def test_swap_sets_version_atomically(db, tmp_path):
    await db.execute("UPDATE socat_points_source SET tile_version = 'old' WHERE id = 1")
    await db.execute("INSERT INTO socat_cruises (expocode, qc_flag, first_time, last_time, n_obs, n_segments, "
                     "n_rejected, crosses_antimeridian) VALUES ('MARKER', 'A', now(), now(), 1, 1, 0, false)")
    # a swap whose in-transaction step fails rolls EVERYTHING back: live rows, names and version stay
    await sp.build_staging(db, "f" * 64)

    async def boom(c):
        await c.execute("UPDATE socat_points_source SET tile_version = 'half' WHERE id = 1")
        raise RuntimeError("fails inside the swap transaction")
    with pytest.raises(RuntimeError):
        await sp.swap(db, backoff=(), in_tx=boom)
    assert await db.fetchval("SELECT tile_version FROM socat_points_source WHERE id = 1") == "old"
    assert await db.fetchval("SELECT count(*) FROM socat_cruises WHERE expocode = 'MARKER'") == 1
    assert await db.fetchval("SELECT to_regclass('socat_cruises_new')::text") is not None
    await sp.discard_staging(db)

    res = await load_excerpt(tmp_path)
    assert res["outcome"] == "swapped", res
    src = await db.fetchrow("SELECT tile_version, sha256 FROM socat_points_source WHERE id = 1")
    assert re.fullmatch(r"\d{14}-[0-9a-f]{6}", src["tile_version"]), src["tile_version"]
    assert src["tile_version"].endswith("-" + src["sha256"][:6])
    assert await db.fetchval("SELECT count(*) FROM socat_cruises WHERE expocode = 'MARKER'") == 0
    assert await db.fetchval("SELECT sum(n_obs) FROM socat_segments") == ROWS
