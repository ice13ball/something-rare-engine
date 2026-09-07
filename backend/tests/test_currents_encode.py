# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import numpy as np
from services.currents_bake import encode_uv_to_rgba, UNSCALE_MIN, UNSCALE_MAX


def test_zero_velocity_maps_to_midpoint():
    u = np.array([[0.0]], dtype="float32")
    v = np.array([[0.0]], dtype="float32")
    rgba = encode_uv_to_rgba(u, v)
    # 0 m/s sits at the midpoint of [-3, 3] -> ~127/128, alpha opaque
    assert rgba.shape == (1, 1, 4)
    assert 126 <= rgba[0, 0, 0] <= 129  # R (u)
    assert 126 <= rgba[0, 0, 1] <= 129  # G (v)
    assert rgba[0, 0, 3] == 255         # alpha


def test_nan_is_transparent():
    u = np.array([[np.nan]], dtype="float32")
    v = np.array([[np.nan]], dtype="float32")
    rgba = encode_uv_to_rgba(u, v)
    assert rgba[0, 0, 3] == 0  # land / no-data -> fully transparent


def test_clamps_beyond_range():
    u = np.array([[100.0]], dtype="float32")   # far above UNSCALE_MAX
    v = np.array([[-100.0]], dtype="float32")  # far below UNSCALE_MIN
    rgba = encode_uv_to_rgba(u, v)
    assert rgba[0, 0, 0] == 255  # u clamps high
    assert rgba[0, 0, 1] == 0    # v clamps low
    assert rgba[0, 0, 3] == 255


def test_extremes_match_unscale_constants():
    assert UNSCALE_MIN == -3.0
    assert UNSCALE_MAX == 3.0
