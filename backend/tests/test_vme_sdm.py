# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from services import vme_sdm as v


def test_omega_arag_open_ocean_supersaturated():
    # Shallow warm surface-ish water is aragonite-supersaturated (Omega > 1).
    om = v.omega_arag(dic=2000.0, talk=2300.0, temp_c=15.0, salinity=35.0, pressure_dbar=0.0)
    assert om is not None and 2.0 < om < 5.0


def test_omega_arag_deep_cold_undersaturated():
    # Deep cold high-DIC water drops below saturation (Omega < 1).
    om = v.omega_arag(dic=2300.0, talk=2350.0, temp_c=2.0, salinity=34.7, pressure_dbar=4000.0)
    assert om is not None and om < 1.5


def test_omega_arag_nan_inputs_return_none():
    assert v.omega_arag(dic=float("nan"), talk=2300.0, temp_c=10.0, salinity=35.0, pressure_dbar=0.0) is None


def test_encode_none_is_muted_slate():
    assert v.encode_suitability_to_rgba(None) == (100, 116, 139, 140)


def test_encode_monotonic_alpha_or_hue():
    lo = v.encode_suitability_to_rgba(0.05)
    hi = v.encode_suitability_to_rgba(0.95)
    assert lo != hi  # ramp actually varies


def test_boyce_perfect_ranking_is_high():
    # Presences all score high, background spread low -> Boyce near +1.
    pres = [0.9, 0.85, 0.95, 0.8, 0.88]
    bg = [0.1, 0.2, 0.15, 0.3, 0.05, 0.9, 0.85]
    assert v.boyce_index(pres, bg) > 0.5


def test_thin_one_per_cell_species():
    # two points in same 0.1-deg-ish cell + species collapse to one
    pts = [(10.00, -20.00, 1), (10.001, -20.001, 1), (10.00, -20.00, 2)]
    out = v.thin_to_cells(pts)
    assert len(out) == 2  # species 1 collapsed, species 2 distinct


def test_spatial_blocks_assigns_k_folds():
    coords = [(float(i), float(j)) for i in range(-40, 40, 7) for j in range(-160, 160, 13)]
    folds = v.spatial_blocks(coords, block_deg=5.0, k=5)
    assert len(folds) == len(coords)
    assert set(folds) <= {0, 1, 2, 3, 4}
    assert len(set(folds)) >= 2


def test_encode_clamps_out_of_range():
    v_lo = v.encode_suitability_to_rgba(-0.5)   # below 0 -> first ramp stop
    v_hi = v.encode_suitability_to_rgba(1.5)     # above 1 -> last ramp stop
    assert v_lo == v.encode_suitability_to_rgba(0.0)
    assert v_hi == v.encode_suitability_to_rgba(1.0)


def test_encode_endpoints_match_ramp_ends():
    import services.vme_sdm as mod
    def _hex(h):
        h = h.lstrip("#"); return (int(h[0:2],16), int(h[2:4],16), int(h[4:6],16))
    r0, g0, b0 = _hex(mod.RAMP_HEX[0]); r1, g1, b1 = _hex(mod.RAMP_HEX[-1])
    assert v.encode_suitability_to_rgba(0.0)[:3] == (r0, g0, b0)
    assert v.encode_suitability_to_rgba(1.0)[:3] == (r1, g1, b1)


def test_boyce_counts_saturated_max_value():
    # A presence exactly at the global max must still be counted (regression for the last-bin bug).
    import math
    pres = [1.0, 1.0, 0.9, 0.95, 0.85]
    bg = [0.1, 0.2, 0.15, 0.3, 0.05, 1.0]
    b = v.boyce_index(pres, bg)
    assert not math.isnan(b)


def test_boyce_degenerate_inputs_return_nan():
    import math
    assert math.isnan(v.boyce_index([], [0.1, 0.2]))
    assert math.isnan(v.boyce_index([0.5], []))
    assert math.isnan(v.boyce_index([0.5, 0.5], [0.5, 0.5]))  # hi <= lo


def test_seafloor_sample_uses_seafloor_depth_and_flags_missing(monkeypatch):
    from services import vme_sdm as v
    import services.vme_sdm as mod

    # bathymetry_grid_export.sample() returns raw GEBCO elevation: negative below sea
    # level. -1200.0 = a seafloor 1200 m deep; seafloor_sample() takes abs() for depth_m.
    monkeypatch.setattr(mod, "_depth_at", lambda lat, lon: -1200.0)
    # Real woa_climatology.sample() var keys are the WOA_VARS top-level keys
    # ("temperature", "salinity"), not the nested an_var codes ("t_an", "s_an").
    monkeypatch.setattr(mod, "_woa_at", lambda var, lat, lon, d: 4.0 if var == "temperature" else 34.9)
    monkeypatch.setattr(mod, "_substrate_at", lambda lat, lon: 3)
    monkeypatch.setattr(mod, "_o2_at", lambda lat, lon, d, grid: 180.0)
    monkeypatch.setattr(mod, "_glodap_at", lambda var, lat, lon, d: 2300.0 if var == "dic" else 2350.0)

    out = v.seafloor_sample(10.0, -30.0)
    assert out["depth_m"] == 1200.0
    assert out["temp_c"] == 4.0
    assert out["substrate"] == 3
    assert out["omega_arag"] is not None
    assert out["predictors_missing"] is False


def test_seafloor_sample_missing_predictor_flags_missing(monkeypatch):
    from services import vme_sdm as v
    import services.vme_sdm as mod
    monkeypatch.setattr(mod, "_depth_at", lambda lat, lon: -1200.0)
    monkeypatch.setattr(mod, "_woa_at", lambda var, lat, lon, d: None)  # WOA undefined this deep
    monkeypatch.setattr(mod, "_substrate_at", lambda lat, lon: None)
    monkeypatch.setattr(mod, "_o2_at", lambda lat, lon, d, grid: None)
    monkeypatch.setattr(mod, "_glodap_at", lambda var, lat, lon, d: None)
    out = v.seafloor_sample(0.0, 0.0)
    assert out["predictors_missing"] is True


# --- extrapolation: envelope, not missing-data -------------------------------------
# `extrapolated` used to be an alias of predictors_missing, which made it tautologically
# FALSE in vme_cells (bake_vme drops every predictor-gap cell before insert, so the only
# rows that could carry the flag were exactly the rows never stored) and left the panel's
# "extrapolated beyond the sampled predictor range" warning permanently unreachable.
# FEATURE_ORDER = [depth_m, temp_c, salinity, o2, substrate, omega_arag].

def _env():
    from services import vme_sdm as v
    return v.training_envelope([
        [1000.0, 4.0, 34.9, 180.0, 3, 1.2],
        [2000.0, 2.0, 34.5, 150.0, 5, 0.9],
    ])


def test_in_envelope_is_not_extrapolated():
    from services import vme_sdm as v
    assert v.is_extrapolated([1500.0, 3.0, 34.7, 165.0, 3, 1.0], _env()) is False


def test_continuous_outside_range_is_extrapolated():
    from services import vme_sdm as v
    # 6000 m is far deeper than anything fitted (max 2000 m)
    assert v.is_extrapolated([6000.0, 3.0, 34.7, 165.0, 3, 1.0], _env()) is True
    # 25 C is far warmer than anything fitted (max 4 C)
    assert v.is_extrapolated([1500.0, 25.0, 34.7, 165.0, 3, 1.0], _env()) is True


def test_unseen_substrate_class_is_extrapolated():
    from services import vme_sdm as v
    # substrate is CATEGORICAL: class 9 was never fitted, even though 3 <= 9 is not a
    # meaningful comparison. A range test would wrongly pass 4 and wrongly fail nothing.
    assert v.is_extrapolated([1500.0, 3.0, 34.7, 165.0, 9, 1.0], _env()) is True
    # class 4 lies numerically between the fitted 3 and 5 but was never seen -> extrapolated
    assert v.is_extrapolated([1500.0, 3.0, 34.7, 165.0, 4, 1.0], _env()) is True


def test_envelope_boundaries_are_inclusive():
    from services import vme_sdm as v
    assert v.is_extrapolated([1000.0, 4.0, 34.9, 180.0, 3, 1.2], _env()) is False
    assert v.is_extrapolated([2000.0, 2.0, 34.5, 150.0, 5, 0.9], _env()) is False


def test_empty_envelope_cannot_judge():
    from services import vme_sdm as v
    assert v.training_envelope([]) is None
    assert v.is_extrapolated([1.0, 2.0, 3.0, 4.0, 5, 6.0], None) is False


def test_extrapolated_is_not_an_alias_of_predictors_missing():
    """The exact regression: a fully-sampled cell can still be an extrapolation."""
    from services import vme_sdm as v
    feats = [9000.0, 3.0, 34.7, 165.0, 3, 1.0]   # nothing missing, depth way out of range
    assert not any(f is None for f in feats)
    assert v.is_extrapolated(feats, _env()) is True


def test_fit_evaluate_and_predict_separable(monkeypatch):
    import numpy as np
    from services import vme_sdm as v
    rng = np.random.default_rng(0)
    # presences cluster in one env corner, background in another -> high AUC expected
    pres = rng.normal(loc=[1200, 4, 34.9, 180, 3, 1.2], scale=[50, 0.3, 0.05, 10, 0.2, 0.05], size=(120, 6))
    bg = rng.normal(loc=[300, 15, 35.2, 240, 1, 3.0], scale=[80, 1.0, 0.1, 20, 0.4, 0.2], size=(400, 6))
    X = np.vstack([pres, bg])
    y = np.array([1] * len(pres) + [0] * len(bg))
    coords = [(float(i % 60 - 30), float((i * 7) % 300 - 150)) for i in range(len(y))]
    res = v.fit_and_evaluate(X, y, coords)
    assert res["n_occurrences"] == 120
    assert res["auc"] >= 0.70
    assert len(res["models"]) >= 2
    mean, std = v.predict_ensemble(res["models"], pres[:5])
    assert len(mean) == 5 and len(std) == 5
    assert all(0.0 <= m <= 1.0 for m in mean)


def test_format_top_predictors_shape():
    top = {"depth_m": 1200.0, "temp_c": 4.0, "salinity": 34.9, "o2": 180.0, "substrate": 3, "omega_arag": 1.2}
    out = v.format_top_predictors(top)
    assert isinstance(out, list) and len(out) == 6
    assert out[0] == {"key": "depth_m", "label": "Seafloor depth", "value": 1200.0, "units": "m"}
    assert [p["key"] for p in out] == v.FEATURE_ORDER  # ordered
    assert all(set(p) == {"key", "label", "value", "units"} for p in out)


def test_format_top_predictors_skips_missing_and_none():
    assert v.format_top_predictors(None) == []
    partial = v.format_top_predictors({"depth_m": 900.0})
    assert len(partial) == 1 and partial[0]["key"] == "depth_m"
