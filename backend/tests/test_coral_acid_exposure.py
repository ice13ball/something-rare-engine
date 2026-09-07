# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import math
import pytest
from backend.services import coral_acid_exposure as cae


# ---- classify -------------------------------------------------------------
def test_seafloor_above_todays_horizon_is_supersaturated():
    # Seafloor at 800 m, horizon at 1200 m today -> the bed sits in supersaturated water.
    assert cae.classify(800.0, 1200.0, 2000.0) == "supersaturated"


def test_seafloor_below_both_horizons_was_already_corrosive():
    assert cae.classify(2500.0, 1200.0, 2000.0) == "corrosive_preindustrial"


def test_seafloor_between_the_two_horizons_is_newly_corrosive():
    """The headline state: corrosive today, supersaturated before industrialisation."""
    assert cae.classify(1500.0, 1200.0, 2000.0) == "newly_corrosive"


def test_boundary_exactly_at_todays_horizon_counts_as_supersaturated():
    assert cae.classify(1200.0, 1200.0, 2000.0) == "supersaturated"


def test_boundary_exactly_at_the_preindustrial_horizon_is_newly_corrosive():
    assert cae.classify(2000.0, 1200.0, 2000.0) == "newly_corrosive"


def test_infinite_horizon_means_column_never_corrosive():
    """inf = Omega never drops below 1 anywhere in the column, so no seafloor can be
    exposed no matter how deep it is."""
    assert cae.classify(5000.0, math.inf, math.inf) == "supersaturated"


def test_infinite_today_but_finite_pi_is_still_supersaturated_today():
    assert cae.classify(5000.0, math.inf, 2000.0) == "supersaturated"


def test_missing_inputs_yield_no_data():
    assert cae.classify(None, 1200.0, 2000.0) == "no_data"
    assert cae.classify(1500.0, None, 2000.0) == "no_data"
    assert cae.classify(1500.0, 1200.0, None) == "no_data"


def test_nan_inputs_yield_no_data():
    assert cae.classify(float("nan"), 1200.0, 2000.0) == "no_data"


def test_land_elevation_is_rejected_as_no_data():
    """Callers pass seafloor depth as a POSITIVE metre value. A non-positive depth means the
    GEBCO cell was land (elevation >= 0) and must never be classified."""
    assert cae.classify(0.0, 1200.0, 2000.0) == "no_data"
    assert cae.classify(-50.0, 1200.0, 2000.0) == "no_data"


# ---- weighted_exposure ----------------------------------------------------
def test_weighted_exposure_weights_by_suitability_not_cell_count():
    """One highly-suitable exposed cell must outweigh one barely-suitable unexposed cell.
    This is the whole point of weighting: it removes the arbitrary presence threshold."""
    rows = [(0.9, "newly_corrosive"), (0.1, "supersaturated")]
    out = cae.weighted_exposure(rows)
    assert out["exposed"] == pytest.approx(0.9)
    assert out["newly"] == pytest.approx(0.9)


def test_weighted_exposure_counts_both_corrosive_states_as_exposed():
    rows = [(1.0, "corrosive_preindustrial"), (1.0, "supersaturated")]
    out = cae.weighted_exposure(rows)
    assert out["exposed"] == pytest.approx(0.5)
    assert out["newly"] == pytest.approx(0.0)


def test_weighted_exposure_excludes_no_data_from_the_denominator():
    """A cell we could not classify must not silently count as unexposed — that would bias
    the headline downwards."""
    rows = [(1.0, "newly_corrosive"), (1.0, "no_data")]
    out = cae.weighted_exposure(rows)
    assert out["exposed"] == pytest.approx(1.0)
    assert out["total_weight"] == pytest.approx(1.0)


def test_weighted_exposure_of_nothing_is_none_not_zero():
    out = cae.weighted_exposure([])
    assert out["exposed"] is None
    assert out["total_weight"] == 0.0


# ---- threshold_table ------------------------------------------------------
def test_threshold_table_reports_one_row_per_cutoff():
    rows = [(0.8, "newly_corrosive"), (0.4, "supersaturated"), (0.2, "newly_corrosive")]
    table = cae.threshold_table(rows)
    assert [r["cutoff"] for r in table] == [0.3, 0.5, 0.7]


def test_threshold_table_is_count_based_within_each_cutoff():
    rows = [(0.8, "newly_corrosive"), (0.4, "supersaturated")]
    at_03 = cae.threshold_table(rows)[0]
    assert at_03["n_cells"] == 2
    assert at_03["exposed_pct"] == pytest.approx(50.0)


def test_threshold_table_marks_empty_cutoffs_rather_than_dividing_by_zero():
    rows = [(0.2, "newly_corrosive")]
    at_07 = cae.threshold_table(rows)[2]
    assert at_07["n_cells"] == 0
    assert at_07["exposed_pct"] is None


# ---- seafloor_from_elevation -----------------------------------------------
def test_seafloor_from_elevation_flips_sign_and_rejects_land():
    """GEBCO returns elevation: negative below sea level. Verified on the live grid
    2026-07-20 — Fram Strait -2713, Gotland Deep -242, Sahara +756."""
    assert cae.seafloor_from_elevation(-2713.0) == pytest.approx(2713.0)
    assert cae.seafloor_from_elevation(756.0) is None
    assert cae.seafloor_from_elevation(0.0) is None
    assert cae.seafloor_from_elevation(None) is None
