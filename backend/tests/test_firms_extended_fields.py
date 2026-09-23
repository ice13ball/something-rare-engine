# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""FIRMS publishes scan, track, version, bright_ti5, daynight per row and we
were dropping all five. Confirmed against the live FIRMS CSV 2026-09-23,
example row:

    55.09597,21.8019,301.75,0.46,0.39,2026-09-23,122,N,VIIRS,n,2.0NRT,281.2,0.62,N

This exercises the real per-row mapping function used by the sync
(`_firms_row_to_fields`), not a re-implementation of it.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from domains.land.hazards import _firms_row_to_fields  # noqa: E402

EXAMPLE_ROW = {
    "latitude": "55.09597",
    "longitude": "21.8019",
    "bright_ti4": "301.75",
    "scan": "0.46",
    "track": "0.39",
    "acq_date": "2026-09-23",
    "acq_time": "122",
    "satellite": "N",
    "instrument": "VIIRS",
    "confidence": "n",
    "version": "2.0NRT",
    "bright_ti5": "281.2",
    "frp": "0.62",
    "daynight": "N",
}


def test_the_example_row_stores_all_five_new_fields_exactly_as_published():
    fields = _firms_row_to_fields(EXAMPLE_ROW)
    assert fields["scan"] == 0.46
    assert fields["track"] == 0.39
    assert fields["version"] == "2.0NRT"
    assert fields["bright_ti5"] == 281.2
    assert fields["daynight"] == "N"
    # NASA's own fields, not a label we invent from the request we made.
    assert fields["instrument"] == "VIIRS"
    assert fields["satellite"] == "N"


def test_empty_string_becomes_none_not_zero():
    row = dict(EXAMPLE_ROW)
    row["scan"] = ""
    row["version"] = ""
    row["daynight"] = ""
    fields = _firms_row_to_fields(row)
    assert fields["scan"] is None
    assert fields["version"] is None
    assert fields["daynight"] is None


def test_no_rounding_happens_to_the_numeric_fields():
    row = dict(EXAMPLE_ROW)
    row["scan"] = "0.463217"
    fields = _firms_row_to_fields(row)
    assert fields["scan"] == 0.463217
