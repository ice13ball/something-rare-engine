# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Placeholder-date detection for offshore registry ingests.

Ghana's GNPC ArcGIS service publishes `Start_date`/`End_date` as
`-2209161600000` epoch-ms for licences whose date is simply unknown. That value
is 1899-12-30 — serial 0 of the Excel / OLE Automation date epoch, i.e. an empty
spreadsheet cell that acquired a date type somewhere upstream.

Two licences (ENI Block 4, and one KOSMOS block) carry it on BOTH awarded and
expires, meaning they would read as "awarded and expired on the same day, 91
years before GNPC existed". It is a fill, not a measurement — and a fill that
precedes every observation ever made, which makes it poison for any
`awarded_date <= sample_time` temporal-precedence join.
"""
import datetime as dt

import pytest

from backend.ingestion.date_sentinels import (
    EPOCH_SENTINEL_MS,
    is_placeholder_date,
)


def test_excel_epoch_zero_in_ms_is_the_documented_constant():
    """The value Ghana actually sends, decoded, is 1899-12-30 UTC."""
    decoded = dt.datetime.fromtimestamp(EPOCH_SENTINEL_MS / 1000, dt.UTC).date()
    assert decoded == dt.date(1899, 12, 30)


def test_excel_epoch_zero_is_a_placeholder():
    assert is_placeholder_date(dt.date(1899, 12, 30)) is True


def test_none_is_not_a_placeholder():
    """None is already absent; the caller must not treat it as a sentinel hit."""
    assert is_placeholder_date(None) is False


@pytest.mark.parametrize("d", [
    dt.date(2006, 7, 19),    # TEN / Tullow — the real Ghanaian award date
    dt.date(1970, 6, 9),     # UK P110 / BP — oldest genuine licence in the table
    dt.date(1899, 12, 31),   # one day after the sentinel: real, keep it
    dt.date(1900, 1, 1),
    dt.date(2036, 1, 1),     # ESDM BERAU — a real future contract start, not a typo
])
def test_real_dates_are_never_placeholders(d):
    assert is_placeholder_date(d) is False


def test_seabed_mining_min_award_date_survives():
    """seabed_mining's oldest awarded_date (1973-06-28) must not be swallowed."""
    assert is_placeholder_date(dt.date(1973, 6, 28)) is False
