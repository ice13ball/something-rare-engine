# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from sar_correlator import classify, MIN_COVERAGE_NEIGHBORS

def test_matched_when_has_match():
    assert classify(True, 0, 1) == "matched"
    assert classify(True, 5, 1) == "matched"

def test_dark_when_no_match_and_neighbors_present():
    assert classify(False, 1, 1) == "dark"
    assert classify(False, 9, 1) == "dark"

def test_ambiguous_when_no_match_and_no_neighbors():
    assert classify(False, 0, 1) == "ambiguous"

def test_boundary_respects_min_neighbors():
    assert classify(False, 2, 3) == "ambiguous"
    assert classify(False, 3, 3) == "dark"

def test_default_min_is_module_constant():
    assert MIN_COVERAGE_NEIGHBORS == 1
    assert classify(False, 1) == "dark"
    assert classify(False, 0) == "ambiguous"
