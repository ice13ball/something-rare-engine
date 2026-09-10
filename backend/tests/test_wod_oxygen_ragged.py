# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Regression tests for WOD ragged-array slicing.

Fixture `wod_oxygen_real_slice.npz` holds 16 VERBATIM casts (indices 150-165) from
the real NOAA file `wod_osd_1965.nc`. It is kept because it contains oxygen-less
casts: `z` carries 159 levels while `Oxygen` carries only 57 observations, so the
two ragged arrays have divergent cumulative offsets.

WOD stores one independent ragged array per variable (`z` on dim `z_obs`, `Oxygen`
on dim `Oxygen_obs`). Slicing `Oxygen` with `z`'s offsets silently mis-attributes
values to the wrong cast at the wrong depth, because `zip` truncates to the
shortest sequence rather than raising.
"""
import pathlib

import numpy as np
import pytest

from ingestion.wod_oxygen_ingest import build_oxygen_rows

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "wod_oxygen_real_slice.npz"

# Ground truth read straight out of wod_osd_1965.nc with per-variable offsets.
CAST_OMZ = 8539563          # lat 17.70 — oxygen-minimum-zone profile
CAST_EQ = 440164            # lat -2.55 — equatorial profile, O2 min at 387 m

EXPECTED_OMZ = [
    [0.0, 218.721], [50.0, 199.551], [200.0, 15.685],
    [300.0, 13.942], [500.0, 10.892], [1000.0, 20.042],
]
# Casts whose Oxygen_row_size == 0 must never appear (verbatim from the fixture).
OXYGEN_LESS_IDS = [
    6636988, 6636948, 6636997, 6637049, 440166, 440165,
    440163, 8539564, 440167, 8552309, 440169, 8539565,
]


def _fixture() -> dict:
    d = np.load(FIXTURE)
    return {k: d[k] for k in d.files}


def _rows(**over):
    args = _fixture()
    args.update(over)
    return build_oxygen_rows(
        min_lat=-90.0, dataset="OSD", country=None, oxygen_units="umol/kg", **args
    )


def test_only_oxygen_bearing_casts_are_emitted():
    rows = _rows()
    assert len(rows) == 4, "4 of the 16 real casts carry oxygen"
    ids = {r["wod_cast_id"] for r in rows}
    assert ids == {"8539563", "440164", "440168", "10077931"}


def test_oxygen_is_sliced_with_its_own_offsets():
    """The bug: slicing Oxygen with z's cumulative offsets corrupts every cast."""
    row = next(r for r in _rows() if r["wod_cast_id"] == str(CAST_OMZ))
    assert row["o2_profile"] == EXPECTED_OMZ
    assert row["n_levels"] == 6
    assert row["max_depth_m"] == 1000.0


def test_recovers_real_oxygen_minimum_zone():
    """Physical sanity: O2 must collapse at mid-depth, not stay flat."""
    row = next(r for r in _rows() if r["wod_cast_id"] == str(CAST_EQ))
    prof = dict(row["o2_profile"])
    assert prof[0.0] == pytest.approx(207.393, abs=1e-3)
    assert prof[387.0] == pytest.approx(84.526, abs=1e-3)   # O2 minimum
    assert prof[1450.0] == pytest.approx(217.85, abs=1e-3)  # re-oxygenated below
    o2 = [v for _, v in row["o2_profile"]]
    assert min(o2) < 0.5 * max(o2), "profile must vary strongly with depth"


def test_oxygen_less_casts_never_emitted():
    rows = _rows()
    ids = {r["wod_cast_id"] for r in rows}
    for bad in OXYGEN_LESS_IDS:
        assert str(bad) not in ids


def test_fill_epoch_time_is_rejected():
    """WOD uses time == 0 as a fill; decoding it yields a bogus 1770-01-01 date."""
    args = _fixture()
    t = args["time_days"].copy()
    t[5] = 0.0                       # cast 8539563
    rows = _rows(time_days=t)
    assert str(CAST_OMZ) not in {r["wod_cast_id"] for r in rows}


def test_fractional_epoch_day_is_rejected():
    """0 < time < 1 still decodes to 1770-01-01. Real OSD casts start in 1900,
    so any date inside the epoch day is a fill artefact, not a measurement."""
    args = _fixture()
    t = args["time_days"].copy()
    t[5] = 0.5                       # cast 8539563 -> 1770-01-01 12:00
    rows = _rows(time_days=t)
    assert str(CAST_OMZ) not in {r["wod_cast_id"] for r in rows}


def test_first_real_day_after_epoch_is_kept():
    """Guard must not eat a legitimate cast one day after the epoch."""
    args = _fixture()
    t = args["time_days"].copy()
    t[5] = 1.0
    rows = _rows(time_days=t)
    assert str(CAST_OMZ) in {r["wod_cast_id"] for r in rows}


def test_negative_depth_levels_are_rejected():
    args = _fixture()
    z = args["z"].copy()
    zc = np.concatenate([[0], np.cumsum(args["z_row_size"])])
    z[zc[5]] = -81.0                 # first level of cast 8539563
    row = next(r for r in _rows(z=z) if r["wod_cast_id"] == str(CAST_OMZ))
    assert all(d >= 0 for d, _ in row["o2_profile"])
    assert row["n_levels"] == 5


# ── what the source publishes and we were throwing away ─────────────────────
# ⛔ `cruise` and `probe_type` were hardcoded `None` at the single row-building
# call site, so both columns were 0.000% populated across all 978,476 live
# rows — while being exported in the public Area Export `fields` tuple and
# rendered as panel Rows. Nobody had asked the source.
#
# Measured against the real wod_osd_2015.nc (8,987 casts) on 2026-09-10:
#     WOD_cruise_identifier .... 82.1% populated, e.g. 'AU006994'
#     Oxygen_Instrument ........  3.3% populated, e.g. 'CTD: TYPE UNKNOWN'
# So one was a real loss, and the other is sparse AT SOURCE — a distinction
# these tests keep, because "we dropped it" and "they barely have it" call for
# opposite responses.

def test_the_cruise_identifier_the_source_publishes_is_kept():
    ids = _fixture()["wod_cast_id"]
    cruise = np.array([b"AU006994"] * len(ids))
    row = next(r for r in _rows(cruise=cruise) if r["wod_cast_id"] == str(CAST_OMZ))
    assert row["cruise"] == "AU006994", (
        "WOD_cruise_identifier is populated on 82.1% of casts and reached the "
        "row as None — the column is exported and rendered, so this is a "
        "dead panel row and a dead export column at once"
    )


def test_the_instrument_the_source_publishes_is_kept():
    ids = _fixture()["wod_cast_id"]
    probe = np.array([b"CTD: TYPE UNKNOWN"] * len(ids))
    row = next(r for r in _rows(probe=probe) if r["wod_cast_id"] == str(CAST_OMZ))
    assert row["probe_type"] == "CTD: TYPE UNKNOWN"


def test_a_file_without_those_variables_still_parses():
    """⛔ Not every WOD year carries every variable — `country` is already read
    this way. Absence must give None, never raise, or one old year kills the
    whole backfill."""
    row = next(r for r in _rows(cruise=None, probe=None)
               if r["wod_cast_id"] == str(CAST_OMZ))
    assert row["cruise"] is None and row["probe_type"] is None


def test_an_empty_string_from_the_source_is_None_not_an_empty_cell():
    """WOD pads its |S170 fields with spaces. A blank must read as absent, not
    as a cruise whose name is nothing."""
    ids = _fixture()["wod_cast_id"]
    row = next(r for r in _rows(cruise=np.array([b"   "] * len(ids)))
               if r["wod_cast_id"] == str(CAST_OMZ))
    assert row["cruise"] is None


# ── the time of day WOD records ─────────────────────────────────────────────
# ⛔ `_EPOCH` is a `date`, and `date + timedelta` uses only the whole days. So
# `_EPOCH + timedelta(days=float(t))` silently discarded the fraction: a cast
# at 06:02 UTC and one at 23:58 the same day produced the identical value.
#
# Measured on the real wod_osd_2015.nc (8,987 casts) 2026-09-10:
#     fraction != 0 (time recorded) .... 8,450 = 94.0%
#     fraction == 0 (no time) .........    537 =  6.0%
# 6% landing on exactly 00:00:00.000 is not a distribution — a uniform day puts
# ~1 cast in 86,400 there. Zero means "not recorded", and must not read as
# midnight.
#
# ⚠️ The label is "time", not "minute": 89% of non-zero fractions are whole
# minutes, 11% are not (quarter-minute steps and float noise), so claiming
# minute granularity would be a claim the data does not support.
import datetime as _dt


def _one_cast_at(fraction_of_day):
    """The OMZ cast, re-timed. `t` is days since 1770-01-01 UTC."""
    args = _fixture()
    t = np.array(args["time_days"], dtype="float64")
    base = np.floor(t)
    t = base + fraction_of_day
    return _rows(time_days=t)


def test_the_time_of_day_is_kept():
    rows = _one_cast_at(0.25138888888)          # 06:02:00 UTC
    row = next(r for r in rows if r["wod_cast_id"] == str(CAST_OMZ))
    assert row["profile_time"] is not None, (
        "the source recorded a time of day and it was discarded — two casts "
        "eighteen hours apart became the same value"
    )
    assert (row["profile_time"].hour, row["profile_time"].minute) == (6, 2)
    assert row["time_precision"] == "time"


def test_the_stored_time_is_UTC_aware():
    """⛔ The units attribute says 'days since 1770-01-01 00:00:00 UTC'. A naive
    datetime would be a guess, and comparing it with an aware one raises."""
    row = next(r for r in _one_cast_at(0.5) if r["wod_cast_id"] == str(CAST_OMZ))
    assert row["profile_time"].tzinfo is not None
    assert row["profile_time"].utcoffset() == _dt.timedelta(0)


def test_a_whole_day_means_no_time_recorded_not_midnight():
    rows = _one_cast_at(0.0)
    row = next(r for r in rows if r["wod_cast_id"] == str(CAST_OMZ))
    assert row["profile_time"] is None, (
        "an exact whole day is WOD's 'time not recorded'; storing it as "
        "00:00 would invent a midnight cast for 6% of the layer"
    )
    assert row["time_precision"] == "day"


def test_the_date_is_unchanged_by_the_fraction():
    """⛔ profile_date is indexed, exported and queried. Recovering the hour
    must not move the day."""
    a = next(r for r in _one_cast_at(0.0) if r["wod_cast_id"] == str(CAST_OMZ))
    b = next(r for r in _one_cast_at(0.99) if r["wod_cast_id"] == str(CAST_OMZ))
    assert a["profile_date"] == b["profile_date"]
    assert a["decade"] == b["decade"]


def test_a_fraction_that_rounds_to_a_full_day_stays_inside_the_day():
    """0.9999999 * 86400 rounds to 86400 seconds — that would be tomorrow."""
    row = next(r for r in _one_cast_at(0.9999999) if r["wod_cast_id"] == str(CAST_OMZ))
    assert row["profile_time"].date() == row["profile_date"], (
        "the recovered time rolled over into the next day"
    )
    assert (row["profile_time"].hour, row["profile_time"].minute) == (23, 59)
