# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The gross range test of the history endpoint: physically impossible values the
source did NOT flag are withheld and counted in ``range_withheld``.

⛔ The three counts stay three: ``missing`` (no value recorded), ``qc_withheld`` (the
source's own flag), ``range_withheld`` (our physical-range test). And a unit is never
guessed: a quantity whose declared unit is not a known one is never tested.

The numbers below are the real offenders found in the first production sync,
2026-10-01 (ALOHA UCUR +-12 m/s, PAP PSAL 0 with QC 1, CCE UCUR -39.088 cm/s,
PYLOS TEMP -999.99 / PSAL 99.999, CORC-GIZO TEMP 105, LINE-W TEMP -17.8).
"""
from datetime import datetime, timedelta, timezone

import pytest

from domains.oceansites_history import merge_series

T0 = datetime(2010, 1, 1, tzinfo=timezone.utc)


def _series(std, units, vals, qc=None):
    n = len(vals)
    row = dict(file="f", data_mode="D", gdac_update_date=None, variable="X", depth_m=10.0,
               units=units, long_name="x", standard_name=std, n_total=n, stride=1,
               times=[T0 + timedelta(hours=i) for i in range(n)], vals=vals,
               qc=qc if qc is not None else [1] * n)
    return merge_series([row])[0]


def _kept(s):
    return [p[1] for p in s["points"]]


# (standard_name, units, lowest kept, highest kept)
FAMILIES = [
    ("sea_water_temperature", "degree_Celsius", -2.5, 40.0),
    ("sea_water_temperature", "degrees_Celsius", -2.5, 40.0),
    ("sea_water_temperature", "degree_C", -2.5, 40.0),
    ("sea_water_temperature", "deg_C", -2.5, 40.0),
    ("sea_water_temperature", "celsius", -2.5, 40.0),
    ("sea_water_temperature", "Celsius", -2.5, 40.0),
    ("sea_surface_temperature", "degree_Celsius", -2.5, 40.0),
    ("sea_water_practical_salinity", "1", 2.0, 41.0),
    ("sea_water_practical_salinity", "psu", 2.0, 41.0),
    ("sea_water_salinity", "PSU", 2.0, 41.0),
    ("sea_water_salinity", "1e-3", 2.0, 41.0),
    ("sea_water_salinity", "0.001", 2.0, 41.0),
    ("eastward_sea_water_velocity", "m/s", -5.0, 5.0),
    ("northward_sea_water_velocity", "m s-1", -5.0, 5.0),
    ("eastward_sea_water_velocity", "meters_per_second", -5.0, 5.0),
    ("northward_sea_water_velocity", "m.s-1", -5.0, 5.0),
    ("eastward_sea_water_velocity", "cm/s", -500.0, 500.0),
    ("northward_sea_water_velocity", "cm s-1", -500.0, 500.0),
    ("eastward_sea_water_velocity", "centimeters_per_second", -500.0, 500.0),
]


@pytest.mark.parametrize("std,units,lo,hi", FAMILIES)
def test_the_limits_are_inclusive_and_one_step_past_them_is_withheld(std, units, lo, hi):
    eps = 1e-6
    s = _series(std, units, [lo - eps, lo, (lo + hi) / 2, hi, hi + eps])

    assert _kept(s) == [lo, (lo + hi) / 2, hi]
    assert s["range_withheld"] == 2
    assert s["qc_withheld"] == 0 and s["missing"] == 0


@pytest.mark.parametrize("std,units,vals", [
    ("sea_water_temperature", "degC", [105.0, -17.8]),          # not in the family: never guessed
    ("sea_water_temperature", "K", [300.0]),
    ("sea_water_temperature", None, [105.0]),
    ("sea_water_practical_salinity", "g/kg", [0.0, 99.999]),
    ("sea_water_salinity", None, [0.0]),
    ("eastward_sea_water_velocity", "m", [12.0]),               # a bare metre is not a speed
    ("eastward_sea_water_velocity", None, [12.0]),
    ("eastward_sea_water_velocity", "knots", [12.0]),
    ("mass_concentration_of_chlorophyll_in_sea_water", "ug/l", [-5.0, 1e6]),   # no test for this quantity
    ("sea_water_temperature", "degree_Celsius ", [105.0]),      # stripped spelling IS the family (see below)
])
def test_an_unknown_unit_or_an_untested_quantity_is_left_alone(std, units, vals):
    s = _series(std, units, vals)

    if units == "degree_Celsius ":
        assert s["range_withheld"] == 1       # whitespace around a declared unit is not a different unit
        return
    assert _kept(s) == vals
    assert s["range_withheld"] == 0


def test_a_cm_per_s_series_is_not_judged_by_the_m_per_s_ceiling():
    s = _series("eastward_sea_water_velocity", "cm/s", [39.088, -250.0, 499.9])

    assert _kept(s) == [39.088, -250.0, 499.9] and s["range_withheld"] == 0


def test_the_production_offenders_are_withheld():
    cases = [
        ("eastward_sea_water_velocity", "m/s", [12.0, -12.0, 0.4], 2),                # ALOHA, no QC
        ("sea_water_practical_salinity", "1", [0.0, 35.1], 1),                         # PAP, QC 1
        ("eastward_sea_water_velocity", "cm/s", [-39.088] * 3 + [10.0], 0),           # CCE: 39 cm/s is in range
        ("sea_water_temperature", "degree_Celsius", [-999.99, 12.0], 1),              # PYLOS, QC 0
        ("sea_water_salinity", "psu", [99.999, 35.0], 1),                              # E1M3A, QC 1
        ("sea_water_temperature", "degree_Celsius", [105.0, 18.0], 1),                # CORC-GIZO
        ("sea_water_temperature", "degree_Celsius", [-17.8, 4.0], 1),                 # LINE-W, QC 1
    ]
    for std, units, vals, withheld in cases:
        s = _series(std, units, vals, qc=[1] * len(vals))
        assert s["range_withheld"] == withheld, (std, units, vals)
        assert len(s["points"]) == len(vals) - withheld


def test_the_three_counts_are_separate_and_the_order_is_missing_then_qc_then_range():
    vals = [None, 105.0, 105.0, 12.0, 13.0, None, 14.0]
    qc = [9, 4, 1, 1, 4, 1, None]
    s = _series("sea_water_temperature", "degree_Celsius", vals, qc)

    assert s["missing"] == 2                  # the two NULLs (one carries QC 9)
    assert s["qc_withheld"] == 2              # 105 with QC 4, 13 with QC 4
    assert s["range_withheld"] == 1           # 105 with QC 1: no flag, impossible
    assert _kept(s) == [12.0, 14.0]


def test_a_withheld_extreme_does_not_reach_the_points_the_sparkline_scales_by():
    s = _series("eastward_sea_water_velocity", "m/s", [0.1, 12.0, -0.2, 0.3])

    assert max(_kept(s)) == 0.3 and min(_kept(s)) == -0.2
