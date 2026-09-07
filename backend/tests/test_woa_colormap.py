# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import numpy as np
from services.woa_climatology import encode_field_to_rgba, WOA_VARS, DISPLAY_DEPTHS


def test_land_nan_is_transparent():
    arr = np.array([[np.nan]], dtype="float32")
    rgba = encode_field_to_rgba(arr, vmin=0.0, vmax=10.0, cmap="oxy")
    assert rgba.shape == (1, 1, 4)
    assert rgba[0, 0, 3] == 0  # NaN -> fully transparent


def test_water_value_is_opaque_and_in_range():
    arr = np.array([[5.0]], dtype="float32")
    rgba = encode_field_to_rgba(arr, vmin=0.0, vmax=10.0, cmap="oxy")
    assert rgba[0, 0, 3] == 255
    assert 0 <= int(rgba[0, 0, 0]) <= 255


def test_min_and_max_pick_ramp_ends():
    lo = encode_field_to_rgba(np.array([[0.0]], "float32"), 0.0, 10.0, "thermal")
    hi = encode_field_to_rgba(np.array([[10.0]], "float32"), 0.0, 10.0, "thermal")
    assert tuple(lo[0, 0, :3]) != tuple(hi[0, 0, :3])


def test_clamps_beyond_range():
    below = encode_field_to_rgba(np.array([[-99.0]], "float32"), 0.0, 10.0, "thermal")
    above = encode_field_to_rgba(np.array([[99.0]], "float32"), 0.0, 10.0, "thermal")
    lo = encode_field_to_rgba(np.array([[0.0]], "float32"), 0.0, 10.0, "thermal")
    hi = encode_field_to_rgba(np.array([[10.0]], "float32"), 0.0, 10.0, "thermal")
    assert tuple(below[0, 0, :3]) == tuple(lo[0, 0, :3])
    assert tuple(above[0, 0, :3]) == tuple(hi[0, 0, :3])


def test_config_covers_eight_variables():
    assert len(WOA_VARS) == 8
    assert set(DISPLAY_DEPTHS) == {0, 50, 100, 200, 500, 1000, 1500, 2000}
    for v in WOA_VARS.values():
        assert v["cmap"] in ("thermal", "haline", "oxy", "matter")
