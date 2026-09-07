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
