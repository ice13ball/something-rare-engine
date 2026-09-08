# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Unit tests for the EMODnet INER (pulse-block-days) CSV aggregation.

Until this task, the year EMODNET_INER_CSV sends (pulsedays,subsquare,year)
was requested over the network and then thrown away — one cell's retained
max could be from 2015 and its neighbour's from 2021 with nothing recording
the difference. These tests EXECUTE aggregate_emodnet_iner_rows() against
CSV rows in the real column order, not a paraphrase of it.
"""
from backend.ingestion.noise_ingest import aggregate_emodnet_iner_rows, decode_subsquare, cell_key


# Two real, decodable EMODnet INER sub-rectangle codes, resolved once so the
# fixtures below can assert on the resulting cell_key without hardcoding a
# second, independently-typed copy of decode_subsquare's arithmetic.
SQ_A = "07C09"
SQ_B = "07C10"  # decodes to a different sub-position; same cell after snap() for pbd's 1° grid

_coords_a = decode_subsquare(SQ_A)
assert _coords_a is not None
_KEY_A = cell_key(_coords_a[0], _coords_a[1], "emodnet_iner")


def test_three_years_keep_max_year_and_full_span():
    """A cell seeing three rows from different years keeps the year of the
    row with the max pulsedays, and pbd_year_min/max cover every year seen —
    not just the winner's."""
    lines = [
        f"10.0,{SQ_A},2015",
        f"55.0,{SQ_A},2021",   # this one wins the max
        f"30.0,{SQ_A},2018",
    ]
    cells = aggregate_emodnet_iner_rows(lines)
    assert _KEY_A in cells
    cell = cells[_KEY_A]
    assert cell["pbd"] == 55.0
    assert cell["pbd_year"] == 2021
    assert cell["pbd_year_min"] == 2015
    assert cell["pbd_year_max"] == 2021


def test_blank_year_still_contributes_pulsedays_but_no_year():
    """A row with a blank year field keeps its pulsedays in the max
    computation; it must not be dropped, and no year is invented for it."""
    lines = [
        f"10.0,{SQ_A},2015",
        f"99.0,{SQ_A},",       # blank year, but the highest pulsedays
    ]
    cells = aggregate_emodnet_iner_rows(lines)
    cell = cells[_KEY_A]
    assert cell["pbd"] == 99.0
    # The winning row had no year — pbd_year must stay missing, not fall back
    # to the losing row's 2015.
    assert cell["pbd_year"] is None
    # The span still reflects the one row that DID have a year.
    assert cell["pbd_year_min"] == 2015
    assert cell["pbd_year_max"] == 2015


def test_unparseable_year_is_treated_as_missing_not_dropped():
    lines = [f"42.0,{SQ_A},not-a-year"]
    cells = aggregate_emodnet_iner_rows(lines)
    cell = cells[_KEY_A]
    assert cell["pbd"] == 42.0
    assert cell["pbd_year"] is None
    assert cell["pbd_year_min"] is None
    assert cell["pbd_year_max"] is None


def test_row_with_no_year_column_at_all_is_missing_not_dropped():
    """Only two fields present (no third column) — still keeps pulsedays."""
    lines = [f"17.5,{SQ_A}"]
    cells = aggregate_emodnet_iner_rows(lines)
    cell = cells[_KEY_A]
    assert cell["pbd"] == 17.5
    assert cell["pbd_year"] is None


def test_blank_subsquare_is_skipped_as_today():
    lines = [
        "12.0,,2020",     # blank subsquare — the source's own gap
        f"8.0,{SQ_A},2020",
    ]
    cells = aggregate_emodnet_iner_rows(lines)
    assert len(cells) == 1
    assert cells[_KEY_A]["pbd"] == 8.0


def test_single_row_sets_year_and_span_to_that_year():
    lines = [f"5.0,{SQ_A},2017"]
    cells = aggregate_emodnet_iner_rows(lines)
    cell = cells[_KEY_A]
    assert cell["pbd_year"] == 2017
    assert cell["pbd_year_min"] == 2017
    assert cell["pbd_year_max"] == 2017


def test_malformed_pulsedays_row_is_skipped():
    lines = [f"not-a-number,{SQ_A},2020"]
    cells = aggregate_emodnet_iner_rows(lines)
    assert cells == {}


def test_two_subsquares_in_the_same_1deg_cell_aggregate_together():
    """SQ_A and SQ_B decode to different ICES sub-positions but the same 1°
    grid cell after snap() — both must land in one aggregated cell."""
    coords_b = decode_subsquare(SQ_B)
    assert coords_b is not None
    key_b = cell_key(coords_b[0], coords_b[1], "emodnet_iner")
    assert key_b == _KEY_A  # same 1° cell

    lines = [
        f"20.0,{SQ_A},2016",
        f"60.0,{SQ_B},2019",
    ]
    cells = aggregate_emodnet_iner_rows(lines)
    assert len(cells) == 1
    cell = cells[_KEY_A]
    assert cell["pbd"] == 60.0
    assert cell["pbd_year"] == 2019
    assert cell["pbd_year_min"] == 2016
    assert cell["pbd_year_max"] == 2019
