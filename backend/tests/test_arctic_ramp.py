# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

# backend/tests/test_arctic_ramp.py
from backend.services.arctic_ramp import arctic_catchment_color, ARCTIC_VARS


def test_all_vars_known():
    assert ARCTIC_VARS == ("ocs_mean", "oc_tot", "runoff_mean", "pf_frac", "t_2m_mean")


def test_min_maps_to_lo_max_to_hi():
    # ocs_mean lo=(255,247,236) at 50, hi=(127,39,4) at 115, alpha 170
    assert arctic_catchment_color(50, "ocs_mean") == (255, 247, 236, 170)
    assert arctic_catchment_color(115, "ocs_mean") == (127, 39, 4, 170)


def test_clamps_below_and_above():
    assert arctic_catchment_color(0, "ocs_mean") == (255, 247, 236, 170)     # clamp low
    assert arctic_catchment_color(9999, "ocs_mean") == (127, 39, 4, 170)     # clamp high


def test_midpoint_interpolates():
    # pf_frac 0..1 lo(255,255,229) hi(49,54,149) at 0.5 → midpoint rounded
    # Uses round-half-up (int(x+0.5)) to match JS Math.round exactly: round(154.5)=155.
    r, g, b, a = arctic_catchment_color(0.5, "pf_frac")
    assert (r, g, b, a) == (152, 155, 189, 170)


def test_null_is_muted_slate():
    assert arctic_catchment_color(None, "ocs_mean") == (100, 116, 139, 90)
    assert arctic_catchment_color(float("nan"), "pf_frac") == (100, 116, 139, 90)


def test_kelvin_domain_for_temp():
    assert arctic_catchment_color(250, "t_2m_mean") == (5, 48, 97, 170)
    assert arctic_catchment_color(282, "t_2m_mean") == (165, 0, 38, 170)
