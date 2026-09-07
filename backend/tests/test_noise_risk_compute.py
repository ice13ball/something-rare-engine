# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Guards for noise_risk_grid's risk_index — the bound must not re-band the map.

See rules/subsystems/units-and-passthrough.md: a derived index is not a
measurement, but bounding it must not silently rescale the distribution
risk_level()'s thresholds were calibrated against.
"""
import pytest

from backend.ingestion.noise_risk_compute import compute_risk_index, risk_level


def test_species_weight_two_clamps_to_one():
    """A cell at max noise, max cetacean presence, and the CR (2.0) species
    weight is 2.0 unclamped — must be bounded to 1.0."""
    assert compute_risk_index(1.0, 1.0, 2.0) == 1.0


def test_common_species_weight_still_reaches_high_band():
    """species_weight = 1.0 (NT/LC, the default and most common weight) with
    a high noise measure and a high cetacean_norm must still classify as
    'high' or 'critical'. A divisor by the 2.0 species-weight ceiling would
    halve this index to 0.36 and silently reclassify it as 'moderate' or
    below — this is the assertion that would have caught that regression."""
    idx = compute_risk_index(0.9, 0.8, 1.0)
    assert idx == pytest.approx(0.72)
    assert risk_level(idx, data_gap=False) in ("high", "critical")


def test_risk_index_never_exceeds_one():
    for noise in (0.0, 0.3, 0.7, 1.0):
        for cet in (None, 0.0, 0.5, 1.0):
            for weight in (1.0, 1.2, 1.5, 2.0):
                idx = compute_risk_index(noise, cet, weight)
                assert 0.0 <= idx <= 1.0


def test_no_cetacean_data_halves_the_noise_measure():
    """The data-gap branch (no cetacean survey coverage) is unaffected by the
    clamp/divisor question — it was already bounded to <= 0.5."""
    assert compute_risk_index(1.0, None, 1.0) == pytest.approx(0.5)
    assert compute_risk_index(0.6, None, 2.0) == pytest.approx(0.3)
