# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""Parser for the Svalbard fjords primary-production preview layer, against
the REAL downloaded CSV (27,663 bytes, 369 data rows, 45 expositions, 43
positions, 29 named stations)."""
import datetime
import pathlib

import pytest

from ingestion import svalbard_fjords_pp as p

FIX = pathlib.Path(__file__).parent / "fixtures" / "svalbard_fjords_pp" / "svalbard_fjords_pp.csv"
RAW = FIX.read_bytes()


def _records() -> list[dict]:
    pf = p.parse_csv(RAW)
    return [p.parse_row(i + 1, cells) for i, cells in enumerate(pf.rows)]


def test_parses_the_whole_file():
    pf = p.parse_csv(RAW)
    assert pf.header == p.EXPECTED_HEADER
    assert len(pf.rows) == 369


def test_exposition_position_and_station_counts():
    records = _records()
    assert len(records) == 369
    assert len({r["exposition_no"] for r in records}) == 45
    assert len({p.position_id(r) for r in records}) == 43
    assert len({r["station"] for r in records}) == 29


def test_region_split():
    records = _records()
    assert sum(1 for r in records if r["region_code"] == "K") == 232
    assert sum(1 for r in records if r["region_code"] == "H") == 137


def test_fjord_part_split():
    records = _records()
    from collections import Counter
    c = Counter(r["fjord_part"] for r in records)
    assert c["Inner"] == 237
    assert c["Glacier"] == 70
    assert c["Outer"] == 62


def test_water_mass_split():
    records = _records()
    from collections import Counter
    c = Counter(r["water_mass"] for r in records)
    assert c["SW"] == 296
    assert c["IW"] == 43
    assert c["LW"] == 17
    assert c["AW"] == 10
    assert c["TAW"] == 3


def test_first_row_values_and_depth_zero_kept():
    r = _records()[0]
    assert r["exposition_no"] == "1"
    assert r["sample_date"] == datetime.date(1994, 7, 5)
    assert r["region_code"] == "K"
    assert r["fjord_part"] == "Glacier"
    assert r["station"] == "K2"
    assert r["lat"] == pytest.approx(78.88)
    assert r["lon"] == pytest.approx(12.48)
    assert r["depth_m"] == 0
    assert r["depth_m"] is not None
    assert r["temperature_degc"] == pytest.approx(0.26)
    assert r["salinity"] == pytest.approx(31.35)
    assert r["ca_mg_m3"] == pytest.approx(0.56)
    assert r["pe_mgc_m3_h"] == pytest.approx(0.99)
    assert r["pi_mgc_m2_day"] == pytest.approx(39)
    assert r["water_mass"] == "LW"


def test_date_parsed_from_ddmmyyyy():
    records = _records()
    dts = [r["sample_date"] for r in records]
    assert min(dts) == datetime.date(1994, 7, 5)
    assert max(dts) == datetime.date(2019, 8, 11)


def test_observation_window():
    lo, hi = p.observation_window(_records())
    assert lo == datetime.date(1994, 7, 5)
    assert hi == datetime.date(2019, 8, 11)


def test_empty_cells_become_none_not_zero():
    records = _records()
    assert sum(1 for r in records if r["ca_mg_m3"] is None) == 121
    assert sum(1 for r in records if r["temperature_degc"] is None) == 12
    assert sum(1 for r in records if r["salinity"] is None) == 12


def test_station_name_reused_at_different_positions():
    """29 named stations but 43 distinct positions: e.g. K2 was sampled at two
    different coordinate sets in different years. Positions are never merged."""
    records = _records()
    k2_positions = {p.position_id(r) for r in records if r["station"] == "K2"}
    assert len(k2_positions) == 2


def test_pi_present_only_once_per_exposition_on_shallowest_row():
    records = _records()
    p.validate_pi_placement(records)  # must not raise
    groups = p.group_by_exposition(records)
    n_with_pi = sum(1 for recs in groups.values() if any(r["pi_mgc_m2_day"] is not None for r in recs))
    assert n_with_pi == 37
    assert len(groups) - n_with_pi == 8
    for recs in groups.values():
        pi_idx = [i for i, r in enumerate(recs) if r["pi_mgc_m2_day"] is not None]
        assert pi_idx in ([], [0])


# ── Header guard and Pi-placement guard: sabotage targets ──────────────────

def test_header_mismatch_refuses_to_parse():
    mutated = RAW.replace(b"Pi_[mgC_m-2_day-1]<Float32>", b"Pi_[mgC_m-2_day-1]_CHANGED<Float32>")
    assert mutated != RAW, "sabotage did not change the bytes - fix the test"
    with pytest.raises(p.SvalbardFjordsPpFormatError):
        p.parse_csv(mutated)


def test_row_with_wrong_cell_count_refuses():
    mutated = RAW.replace(b'"K2"', b'"K2","EXTRA"', 1)
    with pytest.raises(p.SvalbardFjordsPpFormatError):
        p.parse_csv(mutated)


def test_second_pi_in_one_exposition_raises():
    """A second Pi value on a non-shallowest row of the same exposition must be
    refused rather than silently accepted or averaged."""
    records = _records()
    groups = p.group_by_exposition(records)
    no, recs = next((no, recs) for no, recs in groups.items()
                     if any(r["pi_mgc_m2_day"] is not None for r in recs) and len(recs) > 1)
    recs[1]["pi_mgc_m2_day"] = 999.0
    with pytest.raises(p.SvalbardFjordsPpFormatError):
        p.validate_pi_placement(records)
