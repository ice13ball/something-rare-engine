# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import inspect

import pytest

from domains import arctic

# ⛔ 2026-09-18: every test in this file was a substring search in
# inspect.getsource(arctic.cascade_point) — nothing here ever called the
# endpoint. Under Michal's rule (a guard polices DATA, never CODE) all three are
# disabled rather than repaired. They are kept in place, not deleted, because
# each records what the response is supposed to carry and the behavioural
# version is a straight rewrite: call cascade_point against the test database
# and assert on the JSON body it returns. That rewrite is NOT done here.
_SOURCE_SHAPE = (
    "Source-shape guard, disabled 2026-09-18 under Michal's rule that a test "
    "polices DATA, not code. The assertion is a substring search in "
    "inspect.getsource(arctic.cascade_point); the endpoint is never called, so "
    "the test cannot tell a field that reaches the client from a field name "
    "that merely appears in the function body. ⚠️ UNGUARDED now: "
)


@pytest.mark.skip(reason=_SOURCE_SHAPE + (
    "that /cascade-point actually returns a sampling_context block at all."))
def test_cascade_point_returns_a_sampling_context():
    src = inspect.getsource(arctic.cascade_point)
    assert "sampling_context" in src


@pytest.mark.skip(reason=_SOURCE_SHAPE + (
    "that the caveat travels with the sampling context. Without it the block "
    "reads as 'these are the interpolation's inputs', which is a stronger "
    "claim than we can make — they are our stations inside a radius, not the "
    "points CASCADE fed to its own interpolation."))
def test_the_caveat_is_not_optional():
    """Without it the block reads as 'these are the interpolation's inputs',
    which is a stronger claim than we can make: these are our stations inside
    a radius, not the points CASCADE fed to its own interpolation."""
    src = inspect.getsource(arctic.cascade_point)
    assert "caveat_key" in src
    assert "notInterpolationInputs" in src


@pytest.mark.skip(reason=_SOURCE_SHAPE + (
    "that undated stations are reported as n_undated rather than silently "
    "dropped from the count."))
def test_undated_stations_are_counted_not_dropped():
    src = inspect.getsource(arctic.cascade_point)
    assert "n_undated" in src
