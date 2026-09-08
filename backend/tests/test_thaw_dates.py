# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The imagery windows both permafrost sources publish, and were being thrown away.

Shapes taken from the LIVE sources on 2026-09-08: ARTS v6.0.0 writes a comma pair
("2020-07-05,2020-08-20", present on all 4,069 features sampled); Alaska Permafrost
Thaw Database v2.0.0 writes "A through B" on 17,245 of 19,540 features, and most of
those bounds are bare years.
"""
import datetime

from ingestion.thaw_dates import (parse_observation_window, parse_single_date,
                                  window_fields)


def test_arts_comma_pair_is_a_campaign_window():
    w = parse_observation_window("2020-07-05,2020-08-20")
    assert w.as_tuple() == (2020, 2020,
                            datetime.date(2020, 7, 5), datetime.date(2020, 8, 20),
                            "campaign")


def test_alaska_full_date_range():
    w = parse_observation_window("1950-01-01 through 2015-12-31")
    assert (w.start_year, w.end_year) == (1950, 2015)
    assert w.precision == "campaign"


def test_a_bare_year_range_never_becomes_january_the_first():
    """⛔ The rule this whole exercise exists to protect. "1985 through 2015" gives
    years and only years; widening them to 1985-01-01 would invent a day, and a day
    that looks exactly like a real observation date."""
    w = parse_observation_window("1985 through 2015")
    assert (w.start_year, w.end_year) == (1985, 2015)
    assert w.start_date is None and w.end_date is None
    assert w.precision == "campaign"


def test_a_single_acquisition_is_a_day_not_a_window():
    w = parse_observation_window("2020-07-05")
    assert w.precision == "day"
    assert w.start_date == w.end_date == datetime.date(2020, 7, 5)


def test_a_single_year_stays_a_year():
    w = parse_observation_window("1999")
    assert w.precision == "year"
    assert w.start_date is None


def test_missing_and_placeholder_values_are_none_not_a_guess():
    for raw in (None, "", "   ", "N/A", "unknown", "-"):
        assert parse_observation_window(raw).precision == "none", raw


def test_bounds_written_backwards_are_ordered():
    w = parse_observation_window("2015 through 1985")
    assert (w.start_year, w.end_year) == (1985, 2015)


def test_an_impossible_date_keeps_its_year():
    """A year is still an anchor even when the day beside it is not a real date."""
    w = parse_observation_window("2011-02-30 through 2015-12-31")
    assert w.start_year == 2011
    assert w.start_date is None
    assert w.end_date == datetime.date(2015, 12, 31)


def test_a_four_digit_number_that_is_not_a_year_is_rejected():
    assert parse_observation_window("9999").precision == "none"


def test_contribution_date_is_parsed_but_kept_separate():
    """⛔ ARTS contributes digitisations years after the imagery: 2024-02-01 for
    2020 imagery in the sampled data. It must never stand in for an observation."""
    assert parse_single_date("2024-02-01") == datetime.date(2024, 2, 1)
    assert parse_single_date("not a date") is None
    assert parse_single_date(None) is None


def test_window_fields_matches_the_column_names_the_insert_uses():
    f = window_fields("1985 through 2015")
    assert set(f) == {"obs_start_year", "obs_end_year", "obs_start", "obs_end",
                      "date_precision"}
