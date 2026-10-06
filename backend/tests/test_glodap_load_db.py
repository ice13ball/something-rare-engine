# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
import json
import csv
import pathlib
import zipfile
from collections import defaultdict

import asyncpg
import pytest

from plankton_helpers import conn, needs_db  # noqa: F401
from schema.glodap_bottles import ensure_glodap_bottles
from ingestion import glodap_bottles as g
from ingestion.glodap_bottles_rules import build_cast

FIXCSV = pathlib.Path(__file__).parent / "fixtures" / "glodap_v3" / "glodapv3_excerpt.csv"


def _fixture_casts():
    by = defaultdict(list)
    with FIXCSV.open(newline="") as f:
        for row in csv.DictReader(f):
            by[(row["expocode"], row["station"], row["cast"])].append(row)
    return by


def _fetch_from(csv_path):
    def fetch(dest: pathlib.Path):
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(csv_path, "GLODAPv3_Merged_Master_File.csv")
        return {"etag": '"t1"', "content_length": dest.stat().st_size, "last_modified": "x"}
    return fetch


def _ships(codes):
    return {"06AQ": "Polarstern", "49UF": "Keifu Maru", "316N": "Knorr"}


def _edited_copy(tmp_path, edits, name="edited.csv"):
    """The committed fixture with `edits(row)` applied to every row (same header, same text format)."""
    out = tmp_path / name
    with FIXCSV.open(newline="") as f, out.open("w", newline="") as o:
        rd = csv.DictReader(f)
        w = csv.DictWriter(o, fieldnames=rd.fieldnames, lineterminator="\n")
        w.writeheader()
        for row in rd:
            edits(row)
            w.writerow(row)
    return out


@pytest.fixture(autouse=True)
def alerts(monkeypatch):
    """No Telegram from tests; the messages sent are collected."""
    sent = []

    async def fake(message, title="", **kw):
        sent.append(message)
        return True
    monkeypatch.setattr(g, "notify_telegram", fake)
    return sent


async def _fresh(conn):
    for t in ("glodap_casts_new", "glodap_cruises_new", "glodap_casts", "glodap_cruises", "glodap_bottle_source"):
        await conn.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    await conn.execute("""CREATE TABLE IF NOT EXISTS sync_log (source text PRIMARY KEY,
        last_synced_at timestamptz, records_added integer, total_records integer,
        skipped_reason text, skipped_at timestamptz)""")
    await conn.execute("DELETE FROM sync_log WHERE source = 'glodap-bottles'")
    await ensure_glodap_bottles(conn)


async def _objects(conn):
    """Every relation (table, index, sequence) of the glodap family, by name."""
    return sorted(r["relname"] for r in await conn.fetch(
        "SELECT relname FROM pg_class WHERE relnamespace = current_schema()::regnamespace "
        "AND relname LIKE 'glodap\\_%' AND relkind IN ('r','i','S')"))


@needs_db
async def test_first_run_swaps_every_cast_with_depth(conn, tmp_path):
    await _fresh(conn)
    out = await g.sync_glodap_bottles(fetch=_fetch_from(FIXCSV), ship_lookup=_ships, scratch=tmp_path / "s")
    assert out["outcome"] == "swapped", out
    expected = sum(1 for rows in _fixture_casts().values() if build_cast(rows) is not None)
    assert expected == 16
    assert await conn.fetchval("SELECT count(*) FROM glodap_casts") == out["casts"] == expected
    assert await conn.fetchval("SELECT to_regclass('glodap_casts_new')") is None
    assert await conn.fetchval("SELECT to_regclass('glodap_cruises_new')") is None
    src = await conn.fetchrow("SELECT * FROM glodap_bottle_source")
    assert src["n_rows_source"] == 368 and src["etag"] == '"t1"' and src["loaded_at"] is not None
    assert src["n_casts"] == out["casts"]
    # depth fill: 4 rows in 06AQ19890906 213/1, 1 in 49NZ20030803 182/1, 1 in 49NZ20050525 35/1
    assert src["n_rows_depthless"] == 6 and src["n_samples"] == 368 - 6
    assert src["sha256"] and len(src["sha256"]) == 64
    assert await conn.fetchval("SELECT ship_name FROM glodap_cruises WHERE expocode='06AQ19890906'") == "Polarstern"
    assert await conn.fetchval("SELECT ship_name FROM glodap_cruises WHERE expocode='IcelandSea'") is None
    # flags stored with every value; fill stored as NULL never 0
    r = await conn.fetchrow("SELECT tco2, tco2_f FROM glodap_casts WHERE cast_key='49UF20150620_4511_1'")
    assert len(r["tco2"]) == len(r["tco2_f"])
    assert all((v is None) == (f == 9) for v, f in zip(r["tco2"], r["tco2_f"]))
    # the depth-less rows are not stored: 06AQ19890906 213/1 has 21 rows, 4 of them without depth
    assert await conn.fetchval(
        "SELECT n_samples FROM glodap_casts WHERE cast_key='06AQ19890906_213_1'") == 21 - 4
    # real date-only cast: no time of day claimed
    r = await conn.fetchrow("SELECT obs_time, time_precision FROM glodap_casts WHERE cast_key='74AB19900528_1_1'")
    assert r["obs_time"] is None and r["time_precision"] == "day"
    # cruise table agrees with the casts
    assert await conn.fetchval("SELECT sum(n_casts) FROM glodap_cruises") == expected
    assert await conn.fetchval("SELECT count(*) FROM glodap_cruises") == await conn.fetchval(
        "SELECT count(DISTINCT expocode) FROM glodap_casts")
    row = await conn.fetchrow("SELECT skipped_reason, last_synced_at, total_records FROM sync_log "
                              "WHERE source='glodap-bottles'")
    assert row["skipped_reason"] is None and row["last_synced_at"] is not None and row["total_records"] == expected
    print("glodap_casts bytes for 16 casts:", await conn.fetchval("SELECT pg_total_relation_size('glodap_casts')"))


@needs_db
async def test_swap_leaves_no_new_named_object_and_a_later_ensure_adds_no_index(conn, tmp_path):
    # Task 3 builds staging from the shared DDL, so its pkey/unique/indexes/sequence carry `_new` names.
    await _fresh(conn)
    before_swap = await _objects(conn)
    out = await g.sync_glodap_bottles(fetch=_fetch_from(FIXCSV), ship_lookup=_ships, scratch=tmp_path / "s")
    assert out["outcome"] == "swapped", out
    after = await _objects(conn)
    assert not [n for n in after if "_new" in n], after
    assert after == before_swap                       # the very same set of names the DDL gives a fresh install
    constraints = [r["conname"] for r in await conn.fetch(
        "SELECT conname FROM pg_constraint WHERE conrelid IN ('glodap_casts'::regclass, 'glodap_cruises'::regclass)")]
    assert not [c for c in constraints if "_new" in c], constraints
    idx = await conn.fetchval("SELECT count(*) FROM pg_indexes WHERE tablename = 'glodap_casts'")
    assert idx == 5          # pkey, cast_key unique, expocode, year, geom
    await ensure_glodap_bottles(conn)
    assert await conn.fetchval("SELECT count(*) FROM pg_indexes WHERE tablename = 'glodap_casts'") == idx
    assert await _objects(conn) == after
    # the identity sequence still belongs to the live table and keeps counting
    seq = await conn.fetchval("SELECT pg_get_serial_sequence('glodap_casts', 'id')")
    assert seq.endswith("glodap_casts_id_seq")
    # a second full refresh over the renamed objects works (no name collision on the next staging build)
    out2 = await g.sync_glodap_bottles(fetch=_fetch_from(FIXCSV), ship_lookup=_ships, scratch=tmp_path / "t")
    assert out2["outcome"] == "swapped", out2
    assert await _objects(conn) == after


@needs_db
async def test_failed_refresh_keeps_live_rows(conn, tmp_path):
    # failure mode: ingest blanking existing rows on a failed refresh
    await _fresh(conn)
    await g.sync_glodap_bottles(fetch=_fetch_from(FIXCSV), ship_lookup=_ships, scratch=tmp_path / "a")
    before = await conn.fetchval("SELECT count(*) FROM glodap_casts")

    def broken(dest):
        dest.write_bytes(b"not a zip")
        return {"etag": '"t2"', "content_length": 9, "last_modified": "y"}
    out = await g.sync_glodap_bottles(fetch=broken, ship_lookup=_ships, scratch=tmp_path / "b")
    assert out["outcome"] == "error"
    assert await conn.fetchval("SELECT count(*) FROM glodap_casts") == before
    assert await conn.fetchval("SELECT etag FROM glodap_bottle_source") == '"t1"'
    assert await conn.fetchval("SELECT to_regclass('glodap_casts_new')") is None
    assert await conn.fetchval("SELECT skipped_reason FROM sync_log WHERE source='glodap-bottles'")


@needs_db
async def test_a_fetch_that_raises_is_an_outcome_not_an_exception(conn, tmp_path, alerts):
    await _fresh(conn)

    def down(dest):
        raise ConnectionResetError("peer reset")
    out = await g.sync_glodap_bottles(fetch=down, ship_lookup=_ships, scratch=tmp_path / "s")
    assert out["outcome"] == "error" and "peer reset" in " ".join(out["reasons"])
    assert "peer reset" in await conn.fetchval("SELECT skipped_reason FROM sync_log WHERE source='glodap-bottles'")
    assert alerts and "glodap-bottles" in alerts[0]


@needs_db
async def test_an_unusable_scratch_dir_is_an_outcome(conn, tmp_path):
    await _fresh(conn)
    blocker = tmp_path / "file"
    blocker.write_text("x")
    out = await g.sync_glodap_bottles(fetch=_fetch_from(FIXCSV), ship_lookup=_ships, scratch=blocker / "s")
    assert out["outcome"] == "error"
    assert "scratch" in await conn.fetchval("SELECT skipped_reason FROM sync_log WHERE source='glodap-bottles'")


@needs_db
async def test_a_refresh_that_loses_more_than_ten_percent_is_blocked(conn, tmp_path, alerts):
    await _fresh(conn)
    await g.sync_glodap_bottles(fetch=_fetch_from(FIXCSV), ship_lookup=_ships, scratch=tmp_path / "a")
    lines = FIXCSV.read_text().splitlines()
    half = tmp_path / "half.csv"
    half.write_text("\n".join(lines[: len(lines) // 3]) + "\n")
    out = await g.sync_glodap_bottles(fetch=_fetch_from(half), ship_lookup=_ships, scratch=tmp_path / "b")
    assert out["outcome"] == "blocked" and any("dropped" in r for r in out["reasons"])
    assert await conn.fetchval("SELECT count(*) FROM glodap_casts") == 16
    assert await conn.fetchval("SELECT to_regclass('glodap_casts_new')") is None   # staging dropped
    assert await conn.fetchval("SELECT etag FROM glodap_bottle_source") == '"t1"'
    assert any("dropped" in m for m in alerts)
    # losing ONE cast of 16 is 6.25 % (< 10 %): that refresh must go through
    one_cast_less = _edited_copy(tmp_path, lambda r: r.update(depth="-9999") if r["expocode"] == "IcelandSea"
                                 and r["station"] == "2" else None, "minus_one.csv")
    out = await g.sync_glodap_bottles(fetch=_fetch_from(one_cast_less), ship_lookup=_ships, scratch=tmp_path / "c")
    assert out["outcome"] == "swapped" and out["casts"] == 15
    assert await conn.fetchval("SELECT count(*) FROM glodap_casts") == 15


@needs_db
async def test_changed_header_blocks_before_staging_and_keeps_live_rows(conn, tmp_path):
    # Review Focus 5
    await _fresh(conn)
    await g.sync_glodap_bottles(fetch=_fetch_from(FIXCSV), ship_lookup=_ships, scratch=tmp_path / "a")
    text = FIXCSV.read_text().replace("phtsinsitutpf", "phtsinsitutp_flag", 1)
    renamed = tmp_path / "renamed.csv"
    renamed.write_text(text)
    out = await g.sync_glodap_bottles(fetch=_fetch_from(renamed), ship_lookup=_ships, scratch=tmp_path / "b")
    assert out["outcome"] == "schema" and "phtsinsitutpf" in " ".join(out["reasons"])
    assert await conn.fetchval("SELECT count(*) FROM glodap_casts") == 16
    reason = await conn.fetchval("SELECT skipped_reason FROM sync_log WHERE source='glodap-bottles'")
    assert reason and "phtsinsitutpf" in reason


@needs_db
async def test_ship_lookup_failure_is_not_fatal(conn, tmp_path):
    await _fresh(conn)

    def down(codes):
        raise OSError("nvs down")
    out = await g.sync_glodap_bottles(fetch=_fetch_from(FIXCSV), ship_lookup=down, scratch=tmp_path / "s")
    assert out["outcome"] == "swapped"
    assert await conn.fetchval("SELECT count(*) FROM glodap_cruises WHERE ship_name IS NOT NULL") == 0
    assert await conn.fetchval("SELECT ship_lookup_failed FROM glodap_bottle_source") > 0


@needs_db
async def test_leftover_staging_from_a_killed_run_is_rebuilt(conn, tmp_path):
    await _fresh(conn)
    await g.build_staging(conn)
    await conn.execute("INSERT INTO glodap_cruises_new (expocode, first_date, last_date, n_casts, first_cast_key, lat, lon) "
                       "VALUES ('Z', '2000-01-01', '2000-01-01', 1, 'Z_1_1', 0, 0)")
    await g.build_staging(conn)
    assert await conn.fetchval("SELECT count(*) FROM glodap_cruises_new") == 0
    # and a full run over such a leftover works
    await conn.execute("INSERT INTO glodap_cruises_new (expocode, first_date, last_date, n_casts, first_cast_key, lat, lon) "
                       "VALUES ('Z', '2000-01-01', '2000-01-01', 1, 'Z_1_1', 0, 0)")
    out = await g.sync_glodap_bottles(fetch=_fetch_from(FIXCSV), ship_lookup=_ships, scratch=tmp_path / "s")
    assert out["outcome"] == "swapped"
    assert await conn.fetchval("SELECT count(*) FROM glodap_cruises WHERE expocode = 'Z'") == 0


@needs_db
async def test_a_lock_timeout_leaves_live_untouched_and_drops_staging(conn, tmp_path, monkeypatch, alerts):
    await _fresh(conn)
    await g.sync_glodap_bottles(fetch=_fetch_from(FIXCSV), ship_lookup=_ships, scratch=tmp_path / "a")

    async def no_lock(c, *a, **kw):
        raise asyncpg.exceptions.LockNotAvailableError("canceling statement due to lock timeout")
    monkeypatch.setattr(g, "swap", no_lock)
    out = await g.sync_glodap_bottles(fetch=_fetch_from(FIXCSV), ship_lookup=_ships, scratch=tmp_path / "b")
    assert out["outcome"] == "lock_timeout"
    assert await conn.fetchval("SELECT count(*) FROM glodap_casts") == 16
    assert await conn.fetchval("SELECT to_regclass('glodap_casts_new')") is None
    assert "lock_timeout" in await conn.fetchval("SELECT skipped_reason FROM sync_log WHERE source='glodap-bottles'")
    assert alerts


# --- fill / NaN policy, on real fixture rows with a minimal edit -------------------------------------

def _partial_fills(row):
    k = (row["expocode"], row["station"])
    if k == ("IcelandSea", "1") and row["bottle"] in ("1.0", "2.0", "3.0"):
        row["latitude"] = "-9999"                       # 3 rows: position fill
    if k == ("29HE20030408", "1"):
        if row["bottle"] in ("8.0", "23.0"):
            row["month"] = "NaN"                        # 2 rows: date NaN
    if k == ("29HE20030408", "2") and row["bottle"] == "24.0":
        row["year"] = ""                                # 1 row: date empty
    if row["expocode"] == "49UF20150620":
        row["tco2qc"] = "-9999"
        row["talkqc"] = "NaN"
    if row["expocode"] == "316N19720718":
        row["hour"], row["minute"] = "25.0", "10.0"     # impossible clock -> date only


@needs_db
async def test_fill_and_nan_rows_are_rejected_counted_and_never_stored(conn, tmp_path):
    await _fresh(conn)
    src = _edited_copy(tmp_path, _partial_fills)
    clean_rows = {k: len(v) for k, v in _fixture_casts().items()}
    out = await g.sync_glodap_bottles(fetch=_fetch_from(src), ship_lookup=_ships, scratch=tmp_path / "s")
    assert out["outcome"] == "swapped", out
    assert out["rejected"] == {"position": 3, "date": 3}
    assert out["casts"] == 16                                   # no cast lost, rows only
    s = await conn.fetchrow("SELECT n_rows_source, n_rows_depthless, n_samples FROM glodap_bottle_source")
    assert (s["n_rows_source"], s["n_rows_depthless"]) == (368, 6)
    assert s["n_samples"] == 368 - 6 - 6
    assert await conn.fetchval("SELECT n_samples FROM glodap_casts WHERE cast_key='IcelandSea_1_1'") == \
        clean_rows[("IcelandSea", "1", "1.0")] - 3
    # nothing fill-like in the stored coordinates, dates or qc
    assert await conn.fetchval("SELECT count(*) FROM glodap_casts WHERE lat < -90 OR year < 1900") == 0
    r = await conn.fetchrow("SELECT tco2_qc, talk_qc FROM glodap_casts WHERE cast_key='49UF20150620_4511_1'")
    assert r["tco2_qc"] is None and r["talk_qc"] is None
    assert await conn.fetchval("SELECT count(*) FROM glodap_casts WHERE tco2_qc < 0 OR talk_qc < 0") == 0
    r = await conn.fetchrow("SELECT obs_time, time_precision FROM glodap_casts WHERE cast_key='316N19720718_54_2'")
    assert r["obs_time"] is None and r["time_precision"] == "day"
    # the run summary reaches sync_log (on the success row) and the alert channel
    row = await conn.fetchrow("SELECT skipped_reason, last_synced_at FROM sync_log WHERE source='glodap-bottles'")
    assert row["last_synced_at"] is not None
    assert row["skipped_reason"].startswith(g.SWAPPED_WITH_REJECTS_PREFIX) and "rejected_rows=6" in row["skipped_reason"]
    assert "position=3" in row["skipped_reason"] and "date=3" in row["skipped_reason"]
    # ...and persists in glodap_bottle_source, where the daily timer cannot overwrite it
    r = await conn.fetchrow("SELECT last_rejects::text AS j, last_rejects_at FROM glodap_bottle_source")
    assert json.loads(r["j"]) == {"rejected_rows": 6, "by_reason": {"date": 3, "position": 3}}
    assert r["last_rejects_at"] is not None


@needs_db
async def test_a_cast_whose_every_row_is_rejected_disappears_consistently(conn, tmp_path):
    await _fresh(conn)

    def lose_iceland_2(row):
        if row["expocode"] == "IcelandSea" and row["station"] == "2":
            row["longitude"] = "-9999"
    src = _edited_copy(tmp_path, lose_iceland_2)
    out = await g.sync_glodap_bottles(fetch=_fetch_from(src), ship_lookup=_ships, scratch=tmp_path / "s")
    assert out["outcome"] == "swapped" and out["casts"] == 15 and out["rejected"] == {"position": 19}
    assert await conn.fetchval("SELECT count(*) FROM glodap_casts WHERE expocode='IcelandSea'") == 1
    assert await conn.fetchval("SELECT n_casts FROM glodap_cruises WHERE expocode='IcelandSea'") == 1


@needs_db
async def test_two_source_groups_with_one_cast_key_keep_the_first_and_count_the_other(conn, tmp_path):
    await _fresh(conn)

    def twin(row):
        if row["expocode"] == "IcelandSea" and row["station"] == "2":
            row["station"] = "1"
            row["cast"] = "1.00"      # a distinct source group, the same cast_key IcelandSea_1_1
    src = _edited_copy(tmp_path, twin)
    out = await g.sync_glodap_bottles(fetch=_fetch_from(src), ship_lookup=_ships, scratch=tmp_path / "s")
    assert out["outcome"] == "swapped", out
    assert out["casts"] == 15
    assert await conn.fetchval("SELECT count(*) FROM glodap_casts WHERE cast_key='IcelandSea_1_1'") == 1
    assert "duplicate_casts=1" in await conn.fetchval(
        "SELECT skipped_reason FROM sync_log WHERE source='glodap-bottles'")


def _no_cast_numbers(row):
    """Casts the source gives no number for: three spellings of 'missing', one station also holding a real cast."""
    if row["expocode"] == "49UF20150620":
        row["cast"] = "-9999"
    if (row["expocode"], row["station"], row["cast"]) == ("318M19730822", "280", "3.0"):
        row["cast"] = ["-9999", "NaN", ""][int(float(row["bottle"])) % 3]   # same cast, spelt three ways


@needs_db
async def test_casts_without_a_cast_number_are_kept_as_one_nc_cast(conn, tmp_path):
    await _fresh(conn)
    clean_rows = {k: len(v) for k, v in _fixture_casts().items()}
    out = await g.sync_glodap_bottles(fetch=_fetch_from(_edited_copy(tmp_path, _no_cast_numbers)),
                                      ship_lookup=_ships, scratch=tmp_path / "s")
    assert out["outcome"] == "swapped", out
    assert out["rejected"] == {} and out["casts"] == 16                 # nothing rejected, no cast lost or split
    keys = {r["cast_key"] for r in await conn.fetch("SELECT cast_key FROM glodap_casts")}
    assert "49UF20150620_4511_nc" in keys and "49UF20150620_4511_1" not in keys
    assert "318M19730822_280_nc" in keys and "318M19730822_280_1" in keys    # beside the real cast 1
    assert not {k for k in keys if k.startswith("318M19730822_280_")} - {"318M19730822_280_nc", "318M19730822_280_1"}
    r = await conn.fetchrow("SELECT cast_no, n_samples, expocode, station FROM glodap_casts "
                            "WHERE cast_key = '49UF20150620_4511_nc'")
    assert r["cast_no"] is None and (r["expocode"], r["station"]) == ("49UF20150620", "4511")
    assert r["n_samples"] == clean_rows[("49UF20150620", "4511", "1.0")]
    assert await conn.fetchval("SELECT n_samples FROM glodap_casts WHERE cast_key='318M19730822_280_nc'") == \
        clean_rows[("318M19730822", "280", "3.0")]
    assert await conn.fetchval("SELECT count(*) FROM glodap_casts WHERE cast_key !~ '^[A-Za-z0-9._-]+$'") == 0
    assert await conn.fetchval("SELECT n_casts FROM glodap_cruises WHERE expocode='49UF20150620'") == 1
    # a second load of the same file gives the same keys (stable across reloads)
    out2 = await g.sync_glodap_bottles(fetch=_fetch_from(_edited_copy(tmp_path, _no_cast_numbers, "again.csv")),
                                       ship_lookup=_ships, scratch=tmp_path / "s2")
    assert out2["outcome"] == "swapped", out2
    assert {r["cast_key"] for r in await conn.fetch("SELECT cast_key FROM glodap_casts")} == keys


@needs_db
async def test_a_row_without_a_station_is_still_rejected_as_key(conn, tmp_path):
    await _fresh(conn)

    def lose_station(row):
        if row["expocode"] == "IcelandSea" and row["station"] == "2":
            row["station"] = ""
            row["cast"] = "-9999"
    out = await g.sync_glodap_bottles(fetch=_fetch_from(_edited_copy(tmp_path, lose_station)),
                                      ship_lookup=_ships, scratch=tmp_path / "s")
    assert out["outcome"] == "swapped", out
    assert out["rejected"] == {"key": 19} and out["casts"] == 15
    assert await conn.fetchval("SELECT count(*) FROM glodap_casts WHERE expocode='IcelandSea'") == 1   # station 1 only


@needs_db
async def test_an_unparseable_cast_is_skipped_and_counted_not_fatal(conn, tmp_path):
    await _fresh(conn)

    def junk(row):
        if row["expocode"] == "IcelandSea" and row["station"] == "2" and row["bottle"] == "1.0":
            row["tco2"] = "oops"
    src = _edited_copy(tmp_path, junk)
    out = await g.sync_glodap_bottles(fetch=_fetch_from(src), ship_lookup=_ships, scratch=tmp_path / "s")
    assert out["outcome"] == "swapped", out
    assert out["casts"] == 15
    assert "unparseable_casts=1" in await conn.fetchval(
        "SELECT skipped_reason FROM sync_log WHERE source='glodap-bottles'")


@needs_db
async def test_a_refresh_with_a_clean_file_clears_the_previous_reject_note(conn, tmp_path):
    await _fresh(conn)
    await g.sync_glodap_bottles(fetch=_fetch_from(_edited_copy(tmp_path, _partial_fills)),
                                ship_lookup=_ships, scratch=tmp_path / "a")
    assert await conn.fetchval("SELECT skipped_reason FROM sync_log WHERE source='glodap-bottles'")
    # a failure stamp from an earlier run is cleared by the swap, in the same transaction
    await conn.execute("UPDATE glodap_bottle_source SET last_failed_at=now(), last_failure='blocked'")
    out = await g.sync_glodap_bottles(fetch=_fetch_from(FIXCSV), ship_lookup=_ships, scratch=tmp_path / "b")
    assert out["outcome"] == "swapped" and out["rejected"] == {}
    r = await conn.fetchrow("SELECT last_rejects::text AS j, last_failed_at, last_failure FROM glodap_bottle_source")
    assert json.loads(r["j"]) == {} and r["last_failed_at"] is None and r["last_failure"] is None
    assert await conn.fetchval("SELECT skipped_reason FROM sync_log WHERE source='glodap-bottles'") is None


@needs_db
@pytest.mark.parametrize("chunk,batch", [(1, 1), (3, 5), (4, 4), (100, 100)])
async def test_chunk_and_batch_boundaries_lose_and_duplicate_nothing(conn, tmp_path, monkeypatch, chunk, batch):
    # 16 casts: chunk 4 ends exactly on a boundary (the end-of-source sentinel arrives in its own call),
    # chunk 3 / batch 5 end mid-way, chunk 1 / batch 1 is a COPY per cast.
    await _fresh(conn)
    monkeypatch.setattr(g, "CHUNK", chunk)
    monkeypatch.setattr(g, "BATCH", batch)
    out = await g.sync_glodap_bottles(fetch=_fetch_from(FIXCSV), ship_lookup=_ships, scratch=tmp_path / "s")
    assert out["outcome"] == "swapped" and out["casts"] == 16, out
    keys = [r[0] for r in await conn.fetch("SELECT cast_key FROM glodap_casts ORDER BY cast_key")]
    assert len(keys) == len(set(keys)) == 16
    assert await conn.fetchval("SELECT sum(n_samples) FROM glodap_casts") == 368 - 6


def test_every_outbound_request_carries_the_shared_user_agent(monkeypatch, tmp_path):
    """One string, one place (ingestion.USER_AGENT): the master file, the monthly HEAD and the NVS lookup."""
    import io
    import urllib.request
    from ingestion import USER_AGENT
    assert g.USER_AGENT == USER_AGENT and "contact" in USER_AGENT
    seen = []

    class Resp(io.BytesIO):
        headers = {"Content-Length": "2", "ETag": '"x"'}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        seen.append((req.get_method(), req.full_url, req.get_header("User-agent")))
        return Resp(b'{"skos:prefLabel": {"@value": "RV Test"}}' if "vocab.nerc" in req.full_url else b"ok")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    g.head_fingerprint()
    g.default_fetch(tmp_path / "f.zip")
    assert g.default_ship_lookup(["74E9"]) == {"74E9": "RV Test"}
    assert [m for m, _, _ in seen] == ["HEAD", "GET", "GET"]
    assert {ua for _, _, ua in seen} == {USER_AGENT}
