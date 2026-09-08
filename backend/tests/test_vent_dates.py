# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""hydrothermal_vents.discovery_year is free text. These exercise the parser that
turns it into a machine-readable (discovery_year_num, date_precision) pair without
ever inventing a date the source did not give. Shapes taken from the live table,
verified 2026-09-08: 691/721 rows begin with a clean 4-digit year (min 1800, max
2018); the other 30 are 29x the literal "NotProvided" and one multi-event string.
"""
import datetime

from ingestion.vent_dates import parse_discovery_year


def test_a_clean_leading_year():
    assert parse_discovery_year("1985") == (1985, "year")


def test_a_year_plus_method_text():
    assert parse_discovery_year("1985 submersible") == (1985, "year")


def test_not_provided_literal_is_none():
    assert parse_discovery_year("NotProvided") == (None, "none")


def test_empty_and_none_are_none():
    assert parse_discovery_year("") == (None, "none")
    assert parse_discovery_year(None) == (None, "none")
    assert parse_discovery_year("   ") == (None, "none")


def test_multi_event_string_never_harvests_the_middle_year():
    """⛔ The rule this exists to protect: "nearshore: since antiquity; offshore:
    1997 SCUBA" describes two events centuries apart. Picking 1997 out of the
    middle would silently discard "since antiquity" and assert a precision
    nobody gave us. NOT 1997 — (None, "none")."""
    raw = "nearshore: since antiquity; offshore: 1997 SCUBA"
    assert parse_discovery_year(raw) == (None, "none")


def test_a_year_below_the_plausible_floor_is_rejected():
    assert parse_discovery_year("1749 galleon log") == (None, "none")


def test_a_year_above_next_year_is_rejected():
    next_year = datetime.date.today().year + 2
    assert parse_discovery_year(f"{next_year} expedition") == (None, "none")


def test_the_plausible_floor_and_next_year_are_still_accepted():
    """Boundary check the pair above brackets: 1750 and (current year + 1) are
    both inside the accepted range, not just outside it."""
    this_year_plus_one = datetime.date.today().year + 1
    assert parse_discovery_year("1750 log") == (1750, "year")
    assert parse_discovery_year(f"{this_year_plus_one} expedition") == \
        (this_year_plus_one, "year")
