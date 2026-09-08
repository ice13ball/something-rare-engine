# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""What CCHDO actually dates, and at what precision.

⛔ The precision must never come out finer than `campaign`. A row in
cchdo_stations is a vertex of the cruise track — CCHDO dates the cruise, not the
vertex — so a `day` here would attach a calendar date to a position the ship may
have occupied four days later. These tests exist to keep a future "improvement"
from tightening that.

Shapes taken from the live API on 2026-09-08: /cruise/all returns 2,558 cruises,
2,510 with startDate and 2,505 with endDate, every one formatted YYYY-MM-DD.
"""
from datetime import date

from domains.land.density import _cchdo_cruise_dates


def test_full_window_is_campaign_precision():
    start, end, precision, year = _cchdo_cruise_dates(
        {"startDate": "2007-07-06", "endDate": "2007-07-10"})
    assert (start, end) == (date(2007, 7, 6), date(2007, 7, 10))
    assert precision == "campaign"
    assert year == 2007


def test_precision_never_tightens_to_day_for_a_one_day_cruise():
    # A cruise that began and ended on the same day is still a cruise window.
    # The vertex it dates was not necessarily occupied on that day either.
    _, _, precision, _ = _cchdo_cruise_dates(
        {"startDate": "1991-03-14", "endDate": "1991-03-14"})
    assert precision == "campaign"


def test_year_comes_from_the_start_never_the_end():
    # A cruise crossing New Year would otherwise report the year it finished in.
    start, end, _, year = _cchdo_cruise_dates(
        {"startDate": "1994-12-27", "endDate": "1995-01-19"})
    assert (start.year, end.year) == (1994, 1995)
    assert year == 1994


def test_missing_end_keeps_the_start_and_stays_campaign():
    start, end, precision, year = _cchdo_cruise_dates({"startDate": "2003-05-02"})
    assert start == date(2003, 5, 2)
    assert end is None
    assert precision == "campaign"
    assert year == 2003


def test_only_end_still_yields_a_year():
    start, end, precision, year = _cchdo_cruise_dates({"endDate": "1988-09-30"})
    assert start is None
    assert end == date(1988, 9, 30)
    assert precision == "campaign"
    assert year == 1988


def test_no_dates_is_none_not_a_silent_null():
    # ~1.9% of cruises (48 of 2,558 live). "none" is the answer "the source has no
    # date" AND the sentinel that stops the backfill re-asking about this cruise
    # for ever. A bare NULL would do neither.
    assert _cchdo_cruise_dates({}) == (None, None, "none", None)
    assert _cchdo_cruise_dates({"startDate": "", "endDate": None}) == (None, None, "none", None)


def test_unparseable_date_is_none_rather_than_a_guess():
    for bad in ("not-a-date", "1994", "94-12-27", "1994-13-45"):
        start, end, precision, year = _cchdo_cruise_dates({"startDate": bad})
        assert (start, end, precision, year) == (None, None, "none", None), bad
