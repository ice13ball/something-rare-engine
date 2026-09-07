# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import numpy as np
from services import glodap_carbon as gc


def test_vars_and_depths():
    assert set(gc.CARBON_VARS) == {"dic", "talk", "ph", "cant"}
    assert gc.CARBON_VARS["dic"]["nc_var"] == "TCO2"
    assert gc.CARBON_VARS["ph"]["nc_var"] == "pHtsinsitutp"
    assert all(isinstance(d, int) for d in gc.DISPLAY_DEPTHS)


def test_encode_nan_transparent_and_opaque():
    arr = np.array([[np.nan, 2000.0]], dtype="float32")
    rgba = gc.encode_field_to_rgba(arr, 1900, 2400, "matter")
    assert rgba.shape == (1, 2, 4)
    assert rgba[0, 0, 3] == 0    # NaN -> transparent
    assert rgba[0, 1, 3] == 255  # value -> opaque


def test_build_meta_shape():
    m = gc.build_meta()
    keys = {v["key"] for v in m["variables"]}
    assert keys == {"dic", "talk", "ph", "cant"}
    assert m["depths"] == gc.DISPLAY_DEPTHS
    assert "Lauvset" in m["citation"]


def test_ramp_hex_uses_pos_key():
    ramp = gc._ramp_hex("matter")
    assert isinstance(ramp, list) and ramp
    for stop in ramp:
        assert set(stop.keys()) == {"pos", "hex"}        # frontend reads .pos
        assert isinstance(stop["pos"], (int, float))
        assert stop["hex"].startswith("#")
    # and build_meta's per-variable ramp must carry pos too
    for v in gc.build_meta()["variables"]:
        assert all("pos" in s for s in v["ramp"])


def test_meta_states_when_the_observations_were_made():
    """A release name is not an observation window. 'GLODAPv2.2016b' tells the
    reader when we packaged the product, not when the ships were at sea."""
    from services import glodap_carbon
    meta = glodap_carbon.build_meta()
    win = meta.get("observation_window")
    assert win is not None, "meta states no observation window"
    assert isinstance(win["start"], int) and isinstance(win["end"], int)
    assert win["end"] > win["start"]
    assert win["source"], "the window must name where it came from"
