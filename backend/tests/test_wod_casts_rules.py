# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""WOD casts: pure rules (picks, thinning, scaling, time, Morton cells). No DB."""
from datetime import date, datetime, timezone
import numpy as np
import pytest
from ingestion import wod_casts_rules as R
from services import woa_climatology as W

def test_depths_are_the_woa_display_depths():           # the colour depth and the field depth are one list
    assert list(R.DEPTHS) == list(W.DISPLAY_DEPTHS) and len(R.WINDOWS) == len(R.DEPTHS)
    assert all(lo <= d <= hi for d, (lo, hi) in zip(R.DEPTHS, R.WINDOWS))
    assert set(R.PICK_VARS) <= set(W.WOA_VARS)          # every picked variable is a WOA variable key

def test_pick_nearest_good_tie_shallower():
    z = np.array([0.0, 8.0, 48.0, 52.0, 497.0, 503.0, 2101.0], dtype=np.float32)
    good = np.array([True, True, True, True, False, True, True])
    p = R.pick_levels(z, good)
    assert p[0] == 0                                     # 0 m beats 8 m
    assert p[1] == 2                                     # 48 and 52 tie at 2 m -> shallower
    assert p[4] == 5                                     # 497 is flagged -> 503
    assert p[7] is None                                  # 2101 is outside 1900-2100

def test_thinning_keeps_picks_and_ends():
    z = np.linspace(0, 2000, 1500).astype(np.float32)
    good = np.ones_like(z, dtype=bool)
    picks = {j for j in R.pick_levels(z, good) if j is not None}
    kept = R.thin_indices(z, picks)
    assert len(kept) <= R.MAX_LEVELS and picks <= set(kept.tolist())
    assert {int(np.argmin(z)), int(np.argmax(z))} <= set(kept.tolist())
    assert R.pick_levels(z[kept], good[kept]) == [None if j is None else int(np.flatnonzero(kept == j)[0])
                                                  for j in R.pick_levels(z, good)]

def test_scaled_clamps_and_keeps_zero():
    assert R.scaled(0.0, "temperature") == 0
    assert R.scaled(-1.234, "nstar") == -12
    assert R.scaled(2373.9, "phosphate") == 32767         # GEOSECS-like absurd value: clamps, never overflows

def test_decode_time():
    assert R.decode_time(73048.0, None) == (date(1970, 1, 1), None, "day")            # 1970-01-01 is real
    d, t, p = R.decode_time(73048.25, None)                       # 200 x 365 + 48 leap days
    assert (d, t, p) == (date(1970, 1, 1), datetime(1970, 1, 1, 6, tzinfo=timezone.utc), "second")
    assert R.decode_time(0.5, 19550700) == (date(1955, 7, 1), None, "month")          # fill time, date has no day
    assert R.decode_time(-1e10, 19550000) == (date(1955, 1, 1), None, "year")
    assert R.decode_time(-1e10, None) == (None, None, None)

def test_morton_edges():
    x, y = R.to_3857(np.array([-180.0, 180.0, 0.0]), np.array([89.99, -80.0, 0.0]))
    k = R.morton_key(x, y)
    lo, hi = R.tile_key_range(1, 1, 1)                   # lon 180 / lat -80 -> south-east z1 tile
    assert lo <= int(k[1]) < hi
    lo, hi = R.tile_key_range(1, 0, 0)                   # lon -180 / lat 89.99 (clamped 85.0511) -> north-west
    assert lo <= int(k[0]) < hi
    for z in range(0, R.TILE_MAX_ZOOM + 1):              # every cell of every tile is inside its tile's range
        tlo, thi = R.tile_key_range(z, 0, 0)
        n = 1 << (2 * (R.cell_bits(z) - z))
        assert R.cell_key_range(z, 0, 0, 0)[0] == tlo and R.cell_key_range(z, 0, 0, n - 1)[1] == thi


def test_cell_bounds_follow_the_grid_and_contain_their_keys():
    size = 2 * R.WORLD / (1 << 16)                       # z8: 16 bits -> 256 cells per tile axis
    x0, y0, x1, y1 = R.cell_bounds_3857(8, 0, 0, 0)
    assert (x0, y1) == (-R.WORLD, R.WORLD)               # cell 0 of tile 0/0 is the north-west corner
    assert x1 - x0 == pytest.approx(size) and y1 - y0 == pytest.approx(size)
    assert R.cell_bounds_3857(8, 0, 0, 1)[0] == pytest.approx(-R.WORLD + size)         # q bit 0 = east
    assert R.cell_bounds_3857(8, 0, 0, 2)[3] == pytest.approx(R.WORLD - size)          # q bit 1 = south
    for z, tx, ty, q in ((9, 3, 5, 77), (3, 2, 1, 100), (12, 1000, 2000, 65535)):
        bx0, by0, bx1, by1 = R.cell_bounds_3857(z, tx, ty, q)
        k = int(R.morton_key(np.array([(bx0 + bx1) / 2]), np.array([(by0 + by1) / 2]))[0])
        lo, hi = R.cell_key_range(z, tx, ty, q)
        assert lo <= k < hi


def test_lod_level_refuses_point_zoom():
    assert [R.lod_level(z) for z in range(R.POINT_MIN_ZOOM)] == [0, 0, 1, 1, 2, 2]
    with pytest.raises(ValueError):
        R.lod_level(R.POINT_MIN_ZOOM)
