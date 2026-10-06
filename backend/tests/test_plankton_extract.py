# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Extraction of one OBIS parquet to the local plankton parquet — DuckDB only, no network."""
import pathlib

import duckdb
import pytest

from ingestion import plankton_obis as p

FIX = pathlib.Path(__file__).parent / "fixtures" / "plankton_obis" / "occurrences.parquet"
COLS = ["dataset_id", "grp", "keep", "sciname", "aphiaid", "ord", "genus", "lat", "lon",
        "depth", "dmin", "dmax", "month", "eventdate", "basis", "edna_struct",
        "absence", "dropped", "flags"]


def _cols(path):
    return [r[0] for r in duckdb.sql(f"DESCRIBE SELECT * FROM read_parquet('{path}')").fetchall()]


def _group_count(path):
    return duckdb.sql(
        f"SELECT count(*) FROM read_parquet('{path}') WHERE ({p.GROUP_SQL}) IS NOT NULL").fetchone()[0]


def test_extract_writes_only_group_rows_and_reports_count(tmp_path):
    con = p.connect_duckdb(tmp_path)
    dest = tmp_path / "out.parquet"
    n = p.extract_dataset(con, str(FIX), dest)
    assert n == _group_count(FIX) > 0
    assert _cols(dest) == COLS
    assert duckdb.sql(f"SELECT count(*) FROM read_parquet('{dest}')").fetchone()[0] == n
    assert not list(tmp_path.glob("out.parquet.*"))  # no leftover slice dir / tmp


def test_extract_does_not_apply_keep_filter(tmp_path):
    """G1: rows failing KEEP_SQL stay in the file (keep=false) so the loader can count them."""
    con = p.connect_duckdb(tmp_path)
    dest = tmp_path / "out.parquet"
    n = p.extract_dataset(con, str(FIX), dest)
    kept = duckdb.sql(f"SELECT count(*) FROM read_parquet('{dest}') WHERE keep").fetchone()[0]
    expected_kept = duckdb.sql(
        f"SELECT count(*) FROM read_parquet('{FIX}') WHERE ({p.GROUP_SQL}) IS NOT NULL AND {p.KEEP_SQL}"
    ).fetchone()[0]
    assert kept == expected_kept
    assert n >= kept


def test_extract_of_a_file_without_plankton_writes_nothing(tmp_path):
    empty = tmp_path / "none.parquet"
    duckdb.sql(f"COPY (SELECT * FROM read_parquet('{FIX}') WHERE ({p.GROUP_SQL}) IS NULL LIMIT 5) "
               f"TO '{empty}' (FORMAT PARQUET)")
    con = p.connect_duckdb(tmp_path)
    dest = tmp_path / "out.parquet"
    assert p.extract_dataset(con, str(empty), dest) == 0
    assert not dest.exists()


def test_scratch_never_lands_in_tmpfs(tmp_path):
    con = p.connect_duckdb(tmp_path)
    tmpdir = con.execute("SELECT current_setting('temp_directory')").fetchone()[0]
    assert tmpdir.startswith(str(tmp_path))


def test_memory_limit_is_bounded(tmp_path):
    con = p.connect_duckdb(tmp_path)
    limit = con.execute("SELECT current_setting('memory_limit')").fetchone()[0]
    assert limit.endswith("MiB") or limit.endswith("MB")
    assert float(limit.split()[0].rstrip("MiB").rstrip("MB")) <= 750


def _small_row_groups(tmp_path, extra_select="*", name="rg.parquet"):
    """The fixture repeated to ~9k rows in row groups of 2048 -> several row groups."""
    out = tmp_path / name
    duckdb.sql(
        f"COPY (SELECT {extra_select} FROM read_parquet('{FIX}'), range(40)) TO '{out}' "
        f"(FORMAT PARQUET, ROW_GROUP_SIZE 2048)")
    return out


def test_multi_row_group_file_is_extracted_in_several_slices_with_same_total(tmp_path):
    big = _small_row_groups(tmp_path)
    con = p.connect_duckdb(tmp_path)
    slices = p.plan_slices(con, str(big), slice_bytes=1)  # force one row group per slice
    assert len(slices) > 1
    assert slices[0][0] == 0
    assert all(a[1] == b[0] for a, b in zip(slices, slices[1:]))  # contiguous, no gap/overlap
    total_rows = duckdb.sql(f"SELECT count(*) FROM read_parquet('{big}')").fetchone()[0]
    assert slices[-1][1] == total_rows

    sliced = tmp_path / "sliced.parquet"
    single = tmp_path / "single.parquet"
    n_sliced = p.extract_dataset(con, str(big), sliced, slice_bytes=1)
    n_single = p.extract_dataset(con, str(big), single, slice_bytes=1 << 40)
    assert len(p.plan_slices(con, str(big), 1 << 40)) == 1
    assert n_sliced == n_single == _group_count(big) > 0
    q = "SELECT count(*), sum(aphiaid), round(sum(lat), 6), count(*) FILTER (WHERE keep) FROM read_parquet('{}')"
    assert duckdb.sql(q.format(sliced)).fetchall() == duckdb.sql(q.format(single)).fetchall()


def test_file_without_extensions_column_falls_back_to_title_regex(tmp_path):
    """G2/M2: a new OBIS dataset may lack `extensions`; extraction must not crash."""
    noext = tmp_path / "noext.parquet"
    duckdb.sql(f"COPY (SELECT * EXCLUDE (extensions) FROM read_parquet('{FIX}')) TO '{noext}' (FORMAT PARQUET)")
    con = p.connect_duckdb(tmp_path)
    plain, edna = tmp_path / "plain.parquet", tmp_path / "edna.parquet"
    n = p.extract_dataset(con, str(noext), plain, title="Continuous Plankton Recorder")
    assert n == _group_count(FIX)
    assert duckdb.sql(f"SELECT count(*) FILTER (WHERE edna_struct) FROM read_parquet('{plain}')").fetchone()[0] == 0
    p.extract_dataset(con, str(noext), edna, title="Southern Ocean 18S metabarcoding")
    assert duckdb.sql(f"SELECT bool_and(edna_struct) FROM read_parquet('{edna}')").fetchone()[0] is True


def test_file_without_flags_column_extracts_with_null_flags(tmp_path):
    noflags = tmp_path / "noflags.parquet"
    duckdb.sql(f"COPY (SELECT * EXCLUDE (flags) FROM read_parquet('{FIX}')) TO '{noflags}' (FORMAT PARQUET)")
    con = p.connect_duckdb(tmp_path)
    dest = tmp_path / "out.parquet"
    n = p.extract_dataset(con, str(noflags), dest)
    assert n == _group_count(FIX)
    assert _cols(dest) == COLS
    assert duckdb.sql(f"SELECT count(flags) FROM read_parquet('{dest}')").fetchone()[0] == 0


def _single_pass(con, source, dest):
    """Reference: the previous one-scan implementation."""
    select = p._SELECT.format(edna=p.EDNA_SQL)
    con.execute(f"COPY (SELECT {select} FROM read_parquet('{source}') "
                f"WHERE ({p.GROUP_SQL}) IS NOT NULL) TO '{dest}' (FORMAT PARQUET)")


def _rows(path):
    return sorted(duckdb.sql(f"SELECT * FROM read_parquet('{path}')").fetchall(), key=repr)


def test_two_pass_equals_single_pass_on_fixture_and_multi_row_group_file(tmp_path):
    con = p.connect_duckdb(tmp_path)
    for name, src in (("fix", FIX), ("big", _small_row_groups(tmp_path))):
        ref, got = tmp_path / f"{name}_ref.parquet", tmp_path / f"{name}_got.parquet"
        _single_pass(con, src, ref)
        p.extract_dataset(con, str(src), got, slice_bytes=1)
        assert _cols(got) == _cols(ref)
        assert _rows(got) == _rows(ref)


def test_slice_without_hits_never_runs_pass_2(tmp_path, monkeypatch):
    # rows with NO plankton group first (own row groups), plankton rows after
    mixed = tmp_path / "mixed.parquet"
    duckdb.sql(
        f"COPY (SELECT * FROM (SELECT f.*, 0 AS o FROM read_parquet('{FIX}') f, range(600) WHERE ({p.GROUP_SQL}) IS NULL "
        f"UNION ALL SELECT *, 1 FROM read_parquet('{FIX}') WHERE ({p.GROUP_SQL}) IS NOT NULL) "
        f"ORDER BY o) TO '{mixed}' (FORMAT PARQUET, ROW_GROUP_SIZE 2048)")
    calls = []
    real = p._pass2_write
    monkeypatch.setattr(p, "_pass2_write", lambda *a, **k: (calls.append(a[2:4]), real(*a, **k))[1])
    con = p.connect_duckdb(tmp_path)
    n_slices = len(p.plan_slices(con, str(mixed), 1))
    # all-miss file: zero pass-2 calls, no output
    miss = tmp_path / "miss.parquet"
    duckdb.sql(f"COPY (SELECT * FROM read_parquet('{FIX}') WHERE ({p.GROUP_SQL}) IS NULL) TO '{miss}' (FORMAT PARQUET)")
    assert p.extract_dataset(con, str(miss), tmp_path / "m.parquet") == 0
    assert calls == []
    n = p.extract_dataset(con, str(mixed), tmp_path / "x.parquet", slice_bytes=1)
    assert n == _group_count(FIX)
    assert n_slices > 2 and 0 < len(calls) < n_slices  # the no-hit slices were skipped


def _interp_fields(src):
    return [r[0] for r in duckdb.sql(f"DESCRIBE SELECT interpreted.* FROM read_parquet('{src}')").fetchall()]


def _without_field(tmp_path, field, name):
    pack = ", ".join(f'"{f}" := interpreted."{f}"' for f in _interp_fields(FIX) if f != field)
    out = tmp_path / name
    duckdb.sql(f"COPY (SELECT * REPLACE (struct_pack({pack}) AS interpreted) FROM read_parquet('{FIX}')) "
               f"TO '{out}' (FORMAT PARQUET)")
    assert field not in _interp_fields(out)
    return out


def test_interpreted_struct_lacking_a_rank_field_extracts_with_that_field_as_null(tmp_path):
    """A new OBIS dataset whose `interpreted` struct has no `subclass` (DuckDB raises on a missing
    struct key) must extract like a file where that rank is NULL — never abort the run."""
    lacking = _without_field(tmp_path, "subclass", "nosub.parquet")
    nulled = tmp_path / "nulled.parquet"
    pack = ", ".join('"subclass" := NULL::VARCHAR' if f == "subclass" else f'"{f}" := interpreted."{f}"'
                     for f in _interp_fields(FIX))
    duckdb.sql(f"COPY (SELECT * REPLACE (struct_pack({pack}) AS interpreted) "
               f"FROM read_parquet('{FIX}')) TO '{nulled}' (FORMAT PARQUET)")
    con = p.connect_duckdb(tmp_path)
    got, ref = tmp_path / "got.parquet", tmp_path / "ref.parquet"
    n = p.extract_dataset(con, str(lacking), got)
    assert n == p.extract_dataset(con, str(nulled), ref) > 0
    assert _rows(got) == _rows(ref)


@pytest.mark.parametrize("field", ["infraphylum", "division", "subphylum", "class", "order", "genus"])
def test_interpreted_struct_lacking_any_rank_field_extracts(tmp_path, field):
    lacking = _without_field(tmp_path, field, "lack.parquet")
    assert p.extract_dataset(p.connect_duckdb(tmp_path), str(lacking), tmp_path / "o.parquet") > 0


def test_load_connection_is_memory_capped_and_spills_next_to_the_extract(tmp_path):
    con = p._load_connection(tmp_path / "x.parquet")
    limit = con.execute("SELECT current_setting('memory_limit')").fetchone()[0]
    assert float(limit.split()[0].rstrip("MiB").rstrip("MB")) <= 750
    assert con.execute("SELECT current_setting('temp_directory')").fetchone()[0].startswith(str(tmp_path))


@pytest.mark.parametrize("missing", ["month", "depth", "minimumDepthInMeters", "maximumDepthInMeters",
                                     "eventDate", "basisOfRecord", "aphiaid", "scientificName"])
def test_interpreted_struct_lacking_a_non_rank_field_extracts_with_that_column_null(tmp_path, missing):
    lacking = _without_field(tmp_path, missing, "lack.parquet")
    out = tmp_path / "o.parquet"
    n = p.extract_dataset(p.connect_duckdb(tmp_path), str(lacking), out)
    assert n == p.extract_dataset(p.connect_duckdb(tmp_path), str(FIX), tmp_path / "full.parquet") > 0
    col = {"month": "month", "depth": "depth", "minimumDepthInMeters": "dmin", "maximumDepthInMeters": "dmax",
           "eventDate": "eventdate", "basisOfRecord": "basis", "aphiaid": "aphiaid",
           "scientificName": "sciname"}[missing]
    assert duckdb.sql(f"SELECT count({col}) FROM read_parquet('{out}')").fetchone()[0] == 0
    assert duckdb.sql(f"SELECT count(*) FROM read_parquet('{tmp_path / 'full.parquet'}') "
                      f"WHERE {col} IS NOT NULL").fetchone()[0] > 0          # the column is NULL only because it was cut


async def test_load_extract_reads_through_the_memory_capped_connection(tmp_path, monkeypatch):
    """load_extract must open its DuckDB via _load_connection (cap + spill dir), not a bare duckdb.connect()."""
    seen = []
    real = p._load_connection

    def spy(path):
        con = real(path)
        seen.append((path, con.execute("SELECT current_setting('memory_limit')").fetchone()[0],
                     con.execute("SELECT current_setting('temp_directory')").fetchone()[0]))
        return con
    monkeypatch.setattr(p, "_load_connection", spy)

    class _Conn:
        async def fetch(self, *a, **k):
            return []                      # no known datasets: every row counts as unknown_dataset

        async def copy_records_to_table(self, *a, **k):
            pass
    out = tmp_path / "e.parquet"
    assert p.extract_dataset(p.connect_duckdb(tmp_path), str(FIX), out) > 0
    await p.load_extract(_Conn(), out, {})
    assert len(seen) == 1 and seen[0][0] == out
    assert float(seen[0][1].split()[0].rstrip("MiB").rstrip("MB")) <= 750
    assert seen[0][2].startswith(str(tmp_path))
