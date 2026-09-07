# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import numpy as np
from services.oxygen_deox import (
    encode_change_to_rgba, regrid_nearest, diverging_ramp_hex,
    RECENT_VMIN, RECENT_VMAX, CHANGE_VLIM,
)


def test_change_nan_transparent():
    rgba = encode_change_to_rgba(np.array([[np.nan]], "float32"), 60.0)
    assert rgba.shape == (1, 1, 4)
    assert rgba[0, 0, 3] == 0


def test_change_zero_is_opaque_mid():
    rgba = encode_change_to_rgba(np.array([[0.0]], "float32"), 60.0)
    assert rgba[0, 0, 3] == 255


def test_change_loss_is_red_gain_is_blue():
    loss = encode_change_to_rgba(np.array([[-60.0]], "float32"), 60.0)  # O2 loss
    gain = encode_change_to_rgba(np.array([[60.0]], "float32"), 60.0)   # O2 gain
    # loss redder than blue; gain bluer than red
    assert loss[0, 0, 0] > loss[0, 0, 2]
    assert gain[0, 0, 2] > gain[0, 0, 0]


def test_change_clamps_beyond_vlim():
    a = encode_change_to_rgba(np.array([[-999.0]], "float32"), 60.0)
    b = encode_change_to_rgba(np.array([[-60.0]], "float32"), 60.0)
    assert tuple(a[0, 0, :3]) == tuple(b[0, 0, :3])


def test_regrid_nearest_maps_cells():
    src = np.array([[1.0, 2.0], [3.0, 4.0]], dtype="float32")
    src_lats = np.array([10.0, -10.0]); src_lons = np.array([0.0, 10.0])
    out = regrid_nearest(src, src_lats, src_lons,
                         np.array([10.0, -10.0]), np.array([0.0, 10.0]))
    assert out.shape == (2, 2)
    assert out[0, 0] == 1.0 and out[1, 1] == 4.0


def test_regrid_masks_out_of_coverage_lats():
    src = np.array([[5.0]], dtype="float32")
    out = regrid_nearest(src, np.array([0.0]), np.array([0.0]),
                         np.array([80.0, 0.0, -80.0]), np.array([0.0]))
    assert np.isnan(out[0, 0]) and np.isnan(out[2, 0])
    assert out[1, 0] == 5.0


def test_ramp_hex_has_stops():
    stops = diverging_ramp_hex()
    assert len(stops) >= 3 and all("hex" in s and "pos" in s for s in stops)


def test_constants():
    assert (RECENT_VMIN, RECENT_VMAX, CHANGE_VLIM) == (0.0, 350.0, 60.0)


def test_nearest_grid_value_picks_nearest_cell():
    import numpy as np
    from services.oxygen_deox import nearest_grid_value
    lats = np.array([60.0, 65.0, 70.0])
    lons = np.array([-20.0, -10.0, 0.0])
    depths = np.array([0.0, 100.0, 500.0])
    # data shape (depth, lat, lon)
    data = np.arange(3 * 3 * 3, dtype="float32").reshape(3, 3, 3)
    # nearest to (depth 480 -> idx2, lat 64 -> idx1, lon -11 -> idx1) = data[2,1,1]
    assert nearest_grid_value(lats, lons, depths, data, 64.0, -11.0, 480.0) == data[2, 1, 1]

def test_nearest_grid_value_nan_returns_none():
    import numpy as np
    from services.oxygen_deox import nearest_grid_value
    lats = np.array([60.0]); lons = np.array([0.0]); depths = np.array([0.0])
    data = np.array([[[np.nan]]], dtype="float32")
    assert nearest_grid_value(lats, lons, depths, data, 60.0, 0.0, 0.0) is None


def test_hex_feature_shape():
    from services.oxygen_deox import hex_feature
    geom = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
    f = hex_feature(65.0, -10.0, 301.4, geom)
    assert f["type"] == "Feature"
    assert f["geometry"] is geom
    assert f["properties"] == {"lat": 65.0, "lon": -10.0, "value": 301.4}
