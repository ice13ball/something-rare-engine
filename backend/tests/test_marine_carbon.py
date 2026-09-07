# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from backend.services import marine_carbon as mc


def test_color_vars_are_known_and_default_first():
    assert mc.COLOR_VARS[0] == "co2_fco2"
    for k in mc.COLOR_VARS:
        assert k in mc.MARINE_CARBON_VARS


def test_every_var_has_required_meta():
    for k, cfg in mc.MARINE_CARBON_VARS.items():
        assert set(cfg) >= {"group", "label", "units", "source"}
        # categorical variables (e.g. substrate) carry a class code, not a magnitude,
        # so they don't participate in the vmin/vmax colour ramp.
        if not cfg.get("categorical"):
            assert "vmin" in cfg and "vmax" in cfg
            assert cfg["vmax"] > cfg["vmin"]


def test_group_point_groups_in_stable_order_and_passes_nulls():
    sampled = {k: (1.0 if k == "dic" else None) for k in mc.MARINE_CARBON_VARS}
    groups = mc.group_point(sampled)
    # groups appear in first-seen order of MARINE_CARBON_VARS
    seen = [g["group"] for g in groups]
    assert seen == list(dict.fromkeys(c["group"] for c in mc.MARINE_CARBON_VARS.values()))
    # dic value preserved, others null
    dic_row = next(v for g in groups for v in g["variables"] if v["key"] == "dic")
    assert dic_row["value"] == 1.0
    assert dic_row["label"] and dic_row["units"]


def test_group_point_rejects_unknown_key():
    # unknown keys in the sampled dict are ignored, not crashed on
    groups = mc.group_point({"nonsense": 5.0})
    assert all(v["key"] != "nonsense" for g in groups for v in g["variables"])


def test_color_vars_route_through_known_branches():
    # every var key must hit a real branch in the endpoint's _mc_sample dispatch
    # (guards against a typo'd sub-key map). Assert the sub-key sets cover them.
    co2 = {"co2_fco2", "co2_sst", "co2_sal"}
    glodap = {"dic", "talk", "ph", "cant"}
    oxy = {"o2_recent", "deox_delta"}
    woa = {"woa_temp", "woa_sal", "woa_o2", "woa_nitrate", "woa_phosphate", "woa_silicate"}
    acid = {"omega_arag", "omega_calc", "arag_horizon", "arag_horizon_shift"}
    seafloor = {"seafloor_depth", "substrate"}
    assert co2 | glodap | oxy | woa | acid | seafloor == set(mc.MARINE_CARBON_VARS)


def test_acidification_and_seafloor_groups_present_in_order():
    keys = {k for k, _ in _iter_vars()}
    for k in ("omega_arag", "omega_calc", "arag_horizon", "arag_horizon_shift",
              "seafloor_depth", "substrate"):
        assert k in keys
    groups = [g["group"] for g in mc.group_point({})]
    # new groups appended after the existing four, acidification before seafloor
    assert groups.index("Acidification (GLODAP + platform)") < groups.index("Seafloor")
    assert groups.index("Physical & nutrients (WOA)") < groups.index("Acidification (GLODAP + platform)")


def test_group_point_prefers_value_label_when_present():
    out = mc.group_point({"substrate": 2}, labels={"substrate": "Sand"})
    seafloor = next(g for g in out if g["group"] == "Seafloor")
    sub = next(v for v in seafloor["variables"] if v["key"] == "substrate")
    assert sub["value_label"] == "Sand"


def test_group_point_value_label_absent_by_default():
    out = mc.group_point({"omega_arag": 1.2})
    acid = next(g for g in out if g["group"] == "Acidification (GLODAP + platform)")
    oa = next(v for v in acid["variables"] if v["key"] == "omega_arag")
    assert oa["value"] == 1.2
    assert oa.get("value_label") is None


def test_omega_arag_is_colourable():
    assert "omega_arag" in mc.COLOR_VARS


def _iter_vars():
    return [(k, v) for k, v in mc.MARINE_CARBON_VARS.items()]
