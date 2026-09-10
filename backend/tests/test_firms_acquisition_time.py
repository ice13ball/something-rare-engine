# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""FIRMS publishes the time. We kept the date and promised the time.

Confirmed against the live FIRMS CSV on 2026-09-10 — its columns are:

    acq_date, acq_time, bright_ti4, bright_ti5, confidence, daynight, frp,
    instrument, latitude, longitude, satellite, scan, track, version

`acq_time` sat next to `acq_date` on all 294,496 rows and was never read, while
four locales said "click for exact date/time". `instrument` and `satellite` are
two separate NASA fields; the `instrument` column held OUR fused label
("VIIRS_SNPP"), a name we invented rather than one NASA gave.

⛔ FIRMS drops the leading zero: 09:30 arrives as "930" and 00:05 as "5". A
naive slice reads hour 93. And an unparseable stamp must yield NO time, never
midnight — a midnight we invented is an observation NASA never made, which is
the same rule that removed the fabricated ONC cast date.
"""
import datetime
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from domains.land.hazards import _firms_instant   # noqa: E402

D = datetime.date(2026, 9, 10)
UTC = datetime.timezone.utc


def test_a_normal_four_digit_stamp_parses():
    assert _firms_instant(D, "1342") == datetime.datetime(2026, 9, 10, 13, 42, tzinfo=UTC)


def test_the_leading_zero_firms_drops_is_restored():
    # ⛔ The whole reason this helper exists. "930" is 09:30, not hour 93.
    assert _firms_instant(D, "930") == datetime.datetime(2026, 9, 10, 9, 30, tzinfo=UTC)
    assert _firms_instant(D, "5") == datetime.datetime(2026, 9, 10, 0, 5, tzinfo=UTC)
    assert _firms_instant(D, "42") == datetime.datetime(2026, 9, 10, 0, 42, tzinfo=UTC)


@pytest.mark.parametrize("bad", ["", None, "abcd", "9999", "2500", "1270", "12345"])
def test_an_unusable_stamp_yields_no_time_rather_than_midnight(bad):
    got = _firms_instant(D, bad)
    assert got is None, (
        f"{bad!r} produced {got} — an unparseable stamp became a real instant. "
        "Midnight here is an observation NASA never made."
    )


def test_no_date_means_no_instant():
    assert _firms_instant(None, "1342") is None


def test_the_result_is_utc_because_firms_publishes_utc():
    got = _firms_instant(D, "1342")
    assert got.tzinfo is not None and got.utcoffset() == datetime.timedelta(0)


# ── The call sites ──────────────────────────────────────────────────────────
# ⛔ A correct helper nobody calls is the failure that has recurred three times
# this week: MOSAIC's retry, offshore's 4-of-7, the currents float grid.

HAZARDS = pathlib.Path(__file__).resolve().parents[1] / "domains" / "land" / "hazards.py"
_SRC = HAZARDS.read_text(encoding="utf-8")


def test_the_sync_actually_stores_what_firms_sent():
    ins = _SRC[_SRC.index("INSERT INTO active_fires"):]
    ins = ins[:ins.index('"""', ins.index('"""') + 3)]
    for col in ("acq_time", "observed_at", "satellite"):
        assert col in ins, f"the fires INSERT does not write {col}"
    assert "_firms_instant(" in _SRC, "nothing calls the helper"
    assert 'r.get("instrument")' in _SRC, (
        "the instrument column no longer holds NASA's own instrument field"
    )
    assert 'r.get("satellite")' in _SRC, (
        "the satellite column no longer holds NASA's own satellite field"
    )


def test_the_endpoint_hands_those_fields_on():
    # Check 24d: a column nobody can read is a column nobody has.
    api = _SRC[_SRC.index('@router.get("/fires")'):]
    api = api[:api.index("return Response", api.index("FROM active_fires"))]
    for col in ("acq_time", "observed_at", "satellite"):
        assert f"'{col}'" in api, f"/fires does not return {col}"


def test_the_dedup_key_keeps_two_detections_of_the_same_pixel_at_different_times():
    key = _SRC[_SRC.index("        key = ("):]
    key = key[:key.index("\n\n")]
    assert "acq_time" in key, (
        "the dedup key omits acq_time, so two genuine detections of one pixel "
        "hours apart collapse into one. Measured 2026-09-10: small (20 rows of "
        "294,496, 2 of them distinct times) but they are NASA's records."
    )
