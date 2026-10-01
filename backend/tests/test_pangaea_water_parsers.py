# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""Parsers for the two PANGAEA water-column layers, against real source bytes.

Every expectation below was read off the downloaded files on 2026-09-25, never
typed from memory. The CoastDOM fixture is a slice: its comment block states the
WHOLE file's Size (1,286,555 data points), so the slice's own count (207) is
substituted in memory where a test needs `validate` to pass.
"""
import datetime
import os
import pathlib

import pytest

from ingestion import coastdom, greenland_pp, pangaea_tsv
from ingestion.pangaea_tsv import PangaeaFormatError

FIX = pathlib.Path(__file__).parent / "fixtures"
C_TSV = (FIX / "coastdom" / "coastdom_slice.tsv").read_bytes()
C_LD = (FIX / "coastdom" / "coastdom_meta.jsonld").read_bytes()
P_TSV = (FIX / "greenland_pp" / "greenland_pp.tsv").read_bytes()
P_LD = (FIX / "greenland_pp" / "greenland_pp_meta.jsonld").read_bytes()


def _coastdom_file() -> pangaea_tsv.PangaeaFile:
    pf = pangaea_tsv.split_pangaea(C_TSV.decode("utf-8"))
    pangaea_tsv.check_header(pf.header, coastdom.EXPECTED_HEADER)
    return pf


def _coastdom_rows() -> list[dict]:
    return [coastdom.parse_row(n, cells) for n, cells in pangaea_tsv.iter_rows(_coastdom_file())]


def _pp_rows() -> list[dict]:
    pf = pangaea_tsv.split_pangaea(P_TSV.decode("utf-8"))
    pangaea_tsv.check_header(pf.header, greenland_pp.EXPECTED_HEADER)
    return [greenland_pp.parse_row(n, cells) for n, cells in pangaea_tsv.iter_rows(pf)]


def _data_lines(raw: bytes) -> list[bytes]:
    lines = raw.split(b"\n")
    close = lines.index(b"*/")
    return lines[close + 2 : -1]


# ── CoastDOM ────────────────────────────────────────────────────────────────

def test_coastdom_comment_block_citation_and_size():
    pf = _coastdom_file()
    assert pf.size_data_points == 1286555
    assert pf.meta["Citation"].startswith("Lønborg, Christian; Carreira, Cátia;")
    assert pf.meta["Citation"].endswith("[dataset]. PANGAEA, https://doi.org/10.1594/PANGAEA.964012")
    assert pf.meta["Supplement to"].endswith("https://doi.org/10.5194/essd-16-1107-2024")
    assert pf.meta["License"].startswith("Creative Commons Attribution 4.0 International (CC-BY-4.0)")


def test_coastdom_header_repeats_names_so_columns_resolve_by_position():
    pf = _coastdom_file()
    assert len(pf.header) == 49 == len(coastdom.COLUMNS) == len(coastdom.FIELDS)
    assert sum(h.startswith("Analyt method (") for h in pf.header) == 6
    assert sum(h.startswith("Reference (") for h in pf.header) == 3
    assert sum(h.startswith("PI (") for h in pf.header) == 2


def test_header_guard_refuses_a_changed_unit():
    pf = _coastdom_file()
    bad = list(pf.header)
    assert bad[18] == "DOC [µmol/l]"
    bad[18] = "DOC [µmol/kg]"
    with pytest.raises(PangaeaFormatError, match="header differs"):
        pangaea_tsv.check_header(tuple(bad), coastdom.EXPECTED_HEADER)


def test_expected_header_uses_the_micro_sign():
    # U+00B5 MICRO SIGN, as the source writes it. U+03BC GREEK SMALL LETTER MU
    # looks identical and would make the guard refuse every real download.
    for h in coastdom.EXPECTED_HEADER:
        assert "μ" not in h, h
    assert "µ" in coastdom.EXPECTED_HEADER[18]
    assert coastdom.EXPECTED_HEADER[7] == "Temp [°C]"


def test_undated_row_is_null_and_has_no_position():
    r = _coastdom_rows()[9]                     # slice row 10 = source row 36612
    assert r["row_no"] == 10
    assert r["location"] == "Chesapeake Bay to Middle Atlantic"
    assert r["sample_date"] is None             # never today's date
    assert r["sample_date"] != datetime.date.today()
    assert r["lat"] is None and r["lon"] is None
    assert not coastdom.is_mappable(r)
    assert _coastdom_rows()[10]["location"] == "Bight"


def test_row_with_a_date_but_no_longitude_is_unmappable():
    r = _coastdom_rows()[8]                     # Parker River
    assert r["location"] == "Parker River estuary"
    assert r["sample_date"] == datetime.date(1999, 1, 14)
    assert r["lat"] == 42.76 and r["lon"] is None
    assert not coastdom.is_mappable(r)


def test_row_accounting_matches_the_slice():
    pf = _coastdom_file()
    # The slice keeps the whole file's Size line, so validate must refuse it as-is...
    with pytest.raises(PangaeaFormatError, match="data points"):
        pangaea_tsv.validate(coastdom, pf, 1286555)
    # ...and accept it once the slice's own count is stated.
    text = C_TSV.decode("utf-8").replace("Size:\t1286555 data points", "Size:\t207 data points")
    rows, unmappable, points = pangaea_tsv.validate(coastdom, pangaea_tsv.split_pangaea(text), 207)
    assert (rows, unmappable, points) == (12, 2, 207)
    assert rows - unmappable == 10


def test_two_depths_at_one_location_stay_two_samples():
    rows = _coastdom_rows()
    a, b = rows[2], rows[3]
    assert (a["lat"], a["lon"]) == (b["lat"], b["lon"]) == (24.393, 117.929)
    assert (a["depth_m"], b["depth_m"]) == (1.0, 4.0)
    assert (a["doc_umol_l"], b["doc_umol_l"]) == (171.0, 195.0)
    assert a["row_no"] != b["row_no"]


def test_raw_is_the_source_cells_byte_for_byte():
    rows = _coastdom_rows()
    lines = _data_lines(C_TSV)
    assert len(rows) == len(lines) == 12
    for rec, line in zip(rows, lines):
        assert len(rec["raw"]) == 49
        assert "\t".join(rec["raw"]).encode("utf-8") == line
    assert rows[7]["raw"][0] == "East China Sea "      # trailing NBSP kept
    assert rows[7]["location"] == "East China Sea "
    assert rows[4]["raw"][48].startswith('"Parts of this dataset')  # quotes kept


def test_quality_flags_are_integers_and_empty_is_null():
    rows = _coastdom_rows()
    assert rows[0]["qf_doc"] == 2
    assert rows[5]["qf_doc"] == 6
    assert rows[6]["qf_doc"] == 1 and rows[6]["doc_umol_l"] is None
    assert rows[9]["qf_doc"] is None                           # empty → NULL, never 0
    assert rows[0]["qf_tpn"] == 2 and rows[0]["pn_umol_l"] == 0.5


def test_numeric_looking_method_stays_text():
    r = _coastdom_rows()[11]                                   # source row 63030
    assert r["pn_method"] == "5.4" and isinstance(r["pn_method"], str)
    assert r["pn_umol_l"] is None


def test_pi_email_is_parsed_for_storage():
    rows = _coastdom_rows()
    assert rows[0]["pi_email"] == "pi1@example.org"
    assert rows[8]["pi_email"] is None


def test_coastdom_jsonld():
    m = pangaea_tsv.parse_jsonld(C_LD)
    assert m.date_published == datetime.date(2023, 12, 12)
    assert m.size_data_points == 1286555
    assert m.license == "https://creativecommons.org/licenses/by/4.0/"
    assert m.identifier == "https://doi.org/10.1594/PANGAEA.964012"


# ── Greenland Sea primary production ────────────────────────────────────────

def test_pp_header_size_and_rows():
    pf = pangaea_tsv.split_pangaea(P_TSV.decode("utf-8"))
    assert pf.header == greenland_pp.EXPECTED_HEADER
    assert pf.size_data_points == 12
    assert pf.meta["Citation"].startswith("Cherkasheva, Alexandra; Manurov, Rustam; Kowalczuk, Piotr (2025)")
    assert pangaea_tsv.validate(greenland_pp, pf, 12) == (12, 0, 12)


def test_pp_values_are_the_source_values():
    rows = _pp_rows()
    first, ninth = rows[0], rows[8]
    assert (first["event"], first["event_2"]) == ("FS21_06E", None)
    assert (first["lat"], first["lon"]) == (78.833, 6.0)
    assert first["sample_date"] == datetime.date(2021, 8, 2)
    assert first["gpp_c_mg_m2_day"] == 2234.38
    assert ninth["event_2"] == "Ardencaple Shelf 1"
    assert rows[-1]["event"] == "KO2" and rows[-1]["sample_date"] == datetime.date(2022, 8, 22)


def test_pp_raw_is_byte_for_byte():
    for rec, line in zip(_pp_rows(), _data_lines(P_TSV)):
        assert len(rec["raw"]) == 6
        assert "\t".join(rec["raw"]).encode("utf-8") == line


def test_pp_jsonld():
    m = pangaea_tsv.parse_jsonld(P_LD)
    assert m.date_published == datetime.date(2025, 4, 7)
    assert m.size_data_points == 12


# ── Refusals ────────────────────────────────────────────────────────────────

def test_an_html_page_is_refused():
    with pytest.raises(PangaeaFormatError, match="not a PANGAEA textfile"):
        pangaea_tsv.split_pangaea("<!DOCTYPE html><html><body>503</body></html>\n")


def test_a_file_cut_mid_row_is_refused():
    with pytest.raises(PangaeaFormatError, match="truncated"):
        pangaea_tsv.split_pangaea(P_TSV.decode("utf-8")[:-7])


def test_a_file_missing_its_last_row_fails_the_data_point_count():
    text = P_TSV.decode("utf-8")
    text = text[: text.rstrip("\n").rfind("\n") + 1]
    with pytest.raises(PangaeaFormatError, match="11 data points counted"):
        pangaea_tsv.validate(greenland_pp, pangaea_tsv.split_pangaea(text), 12)


def test_a_row_with_the_wrong_cell_count_is_refused():
    text = P_TSV.decode("utf-8").replace("FS21_06E\t\t78.8330", "FS21_06E\t78.8330", 1)
    with pytest.raises(PangaeaFormatError, match="row 1: 5 cells"):
        list(pangaea_tsv.iter_rows(pangaea_tsv.split_pangaea(text)))


def test_jsonld_that_is_not_json_is_refused():
    with pytest.raises(PangaeaFormatError):
        pangaea_tsv.parse_jsonld(b"<html>")


def test_jsonld_without_a_date_gives_none():
    import json
    d = json.loads(P_LD)
    del d["datePublished"]
    assert pangaea_tsv.parse_jsonld(json.dumps(d).encode()).date_published is None


# ── Whole-file facts, only where the real download is on disk ───────────────

@pytest.mark.skipif(not os.getenv("PANGAEA_SOURCE_DIR"), reason="set PANGAEA_SOURCE_DIR to the download dir")
def test_whole_coastdom_file_facts():
    src = pathlib.Path(os.environ["PANGAEA_SOURCE_DIR"]) / "coastdom" / "data.tsv"
    pf = pangaea_tsv.split_pangaea(src.read_text(encoding="utf-8"))
    assert pangaea_tsv.validate(coastdom, pf, 1286555) == (70823, 532, 1286555)
    positions, undated_located = set(), 0
    for n, cells in pangaea_tsv.iter_rows(pf):
        r = coastdom.parse_row(n, cells)
        if coastdom.is_mappable(r):
            positions.add((r["lat"], r["lon"]))
            undated_located += r["sample_date"] is None
    assert len(positions) == 11438
    assert undated_located == 0
