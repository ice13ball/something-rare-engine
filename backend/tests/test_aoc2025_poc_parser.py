# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""Parser for the AOC2025 POC preview layer, against the REAL downloaded CSV.

Fixture is the WHOLE file (13,104 bytes, 94 data rows, 32 stations) — no
personal data (no names, no e-mail addresses; confirmed by inspection of every
column: Cruise-ID, Station, Date, Latitude, Longitude, PRESPR01, Pressure_(db),
Activity, Sample_ID, Salinity, Temperature, D15N, D13C, CORGCAP1, NTOTCAP1).
"""
import datetime
import pathlib

import pytest

from ingestion import aoc2025_poc as p

FIX = pathlib.Path(__file__).parent / "fixtures" / "aoc2025_poc" / "aoc2025_poc.csv"
RAW = FIX.read_bytes()


def _records() -> list[dict]:
    pf = p.parse_csv(RAW)
    return [p.parse_row(i + 1, cells) for i, cells in enumerate(pf.rows)]


def test_fixture_has_no_personal_data():
    text = RAW.decode("utf-8")
    assert "@" not in text
    for header_cell in p.EXPECTED_HEADER:
        assert "name" not in header_cell.lower() and "email" not in header_cell.lower()


def test_parses_the_whole_file():
    pf = p.parse_csv(RAW)
    assert pf.header == p.EXPECTED_HEADER
    assert len(pf.rows) == 94


def test_row_count_and_station_count():
    records = _records()
    assert len(records) == 94
    assert len({r["station"] for r in records}) == 32


def test_first_row_values():
    r = _records()[0]
    assert r["cruise_id"] == "AOC2025"
    assert r["station"] == "AOC2025-2"
    assert r["sample_date"] == datetime.datetime(2025, 5, 19, 4, 30, tzinfo=datetime.timezone.utc)
    assert r["lat"] == pytest.approx(73.02205)
    assert r["lon"] == pytest.approx(-5.362583333)
    assert r["prespr01_db"] == pytest.approx(5)
    assert r["pressure_db"] == pytest.approx(4.652)
    assert r["activity"] == "9"
    assert r["sample_id"] == "KOW3"
    assert r["salinity"] == pytest.approx(34.5031)
    assert r["temp_c"] == pytest.approx(0.4349)
    assert r["d15n_permil"] == pytest.approx(3.421)
    assert r["d13c_permil"] == pytest.approx(-22.321)
    assert r["poc_mg_dm3"] == pytest.approx(0.500199883)
    assert r["pn_mg_dm3"] == pytest.approx(0.085944997)
    assert r["raw"] == [
        "AOC2025", "AOC2025-2", "2025-05-19T04:30:00Z", "73.02205", "-5.362583333",
        "5", "4.652", "9", "KOW3", "34.5031", "0.4349", "3.421", "-22.321",
        "0.500199883", "0.085944997",
    ]


def test_dates_are_may_2025_not_the_metadata_extent():
    """Known source defect #1: the ISO metadata's temporal extent
    (2024-07-24..2024-08-09) does not match the data. Every actual sample date
    is May 2025 — this platform uses the dates IN THE DATA."""
    dts = [r["sample_date"].date() for r in _records()]
    assert min(dts) == datetime.date(2025, 5, 19)
    assert max(dts) == datetime.date(2025, 5, 31)
    assert all(d.year == 2025 and d.month == 5 for d in dts)


def test_observation_window():
    lo, hi = p.observation_window(_records())
    assert lo == datetime.date(2025, 5, 19)
    assert hi == datetime.date(2025, 5, 31)


def test_empty_cells_become_none_not_zero():
    records = _records()
    n_no_salinity = sum(1 for r in records if r["salinity"] is None)
    n_no_temp = sum(1 for r in records if r["temp_c"] is None)
    assert n_no_salinity == 4
    assert n_no_temp == 4
    assert 90 == sum(1 for r in records if r["salinity"] is not None)
    assert 90 == sum(1 for r in records if r["temp_c"] is not None)


def test_poc_pn_unit_is_from_the_abstract_not_the_file():
    """Known source defect #2: no unit for POC/PN anywhere in the CSV."""
    assert "abstract" in p.POC_PN_UNIT
    assert "mg dm-3" in p.POC_PN_UNIT


def test_units_resolved_from_seadatanet_p01_are_cited_in_code():
    assert "P01" in p.PRESPR01_UNIT
    assert "PRESPR01" in p.PRESPR01_UNIT
    assert "D13CMOP11" in p.D13C_UNIT
    assert "D15NEAM1" in p.D15N_UNIT


# ── Header guard: the sabotage target ───────────────────────────────────────

def test_header_mismatch_refuses_to_parse():
    mutated = RAW.replace(b"SDN:P01::CORGCAP1<Float32>", b"SDN:P01::CORGCAP1_CHANGED<Float32>")
    assert mutated != RAW, "sabotage did not change the bytes - fix the test"
    with pytest.raises(p.Aoc2025PocFormatError):
        p.parse_csv(mutated)


def test_header_matches_the_real_download_byte_for_byte():
    pf = p.parse_csv(RAW)
    assert pf.header == p.EXPECTED_HEADER


def test_row_with_wrong_cell_count_refuses():
    mutated = RAW.replace(b'"KOW3"', b'"KOW3","EXTRA"')
    with pytest.raises(p.Aoc2025PocFormatError):
        p.parse_csv(mutated)
