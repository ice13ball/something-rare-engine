# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from backend.services import cascade_ramp as r

def test_none_is_transparent():
    assert r.cascade_color(None, "oc") == (0, 0, 0, 0)
    assert r.cascade_color(-9999, "oc") == (0, 0, 0, 0)

def test_all_vars_present():
    assert set(r.CASCADE_VARS) == {"oc", "tn", "d13c", "d14c"}
    for v in r.CASCADE_VARS:
        c = r.cascade_color(r.RAMPS[v]["domain"][0], v)
        assert len(c) == 4 and c[3] > 0

def test_monotonic_alpha_opaque_in_range():
    lo, hi = r.RAMPS["oc"]["domain"]
    mid = r.cascade_color((lo + hi) / 2, "oc")
    assert mid[3] == 220

def test_unknown_var_falls_back():
    assert r.cascade_color(1.0, "zzz")[3] >= 0  # no crash
