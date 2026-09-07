# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import inspect
from domains import arctic


def test_cascade_point_returns_a_sampling_context():
    src = inspect.getsource(arctic.cascade_point)
    assert "sampling_context" in src


def test_the_caveat_is_not_optional():
    """Without it the block reads as 'these are the interpolation's inputs',
    which is a stronger claim than we can make: these are our stations inside
    a radius, not the points CASCADE fed to its own interpolation."""
    src = inspect.getsource(arctic.cascade_point)
    assert "caveat_key" in src
    assert "notInterpolationInputs" in src


def test_undated_stations_are_counted_not_dropped():
    src = inspect.getsource(arctic.cascade_point)
    assert "n_undated" in src
