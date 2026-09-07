# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import math

import numpy as np
import pytest
from services import acidification as acid
from services import glodap_carbon


def test_diverging_center_maps_to_midpoint():
    arr = np.array([[0.5, 1.0, 4.0]], dtype="float32")   # vmin, center, vmax
    rgba = acid.encode_diverging_to_rgba(arr, 0.5, 1.0, 4.0, "div_acid")
    # center (Ω=1) → white midpoint of RdBu
    assert tuple(rgba[0, 1, :3]) == (247, 247, 247)
    # Ω<1 → red side (more red than blue); Ω>1 → blue side (more blue than red)
    assert rgba[0, 0, 0] > rgba[0, 0, 2]
    assert rgba[0, 2, 2] > rgba[0, 2, 0]
    assert rgba[0, 1, 3] == 255


def test_diverging_nan_transparent_and_clamped():
    arr = np.array([[np.nan, -5.0, 99.0]], dtype="float32")
    rgba = acid.encode_diverging_to_rgba(arr, 0.5, 1.0, 4.0, "div_acid")
    assert rgba[0, 0, 3] == 0                       # NaN → transparent
    assert tuple(rgba[0, 1, :3]) == (178, 24, 43)   # clamped to vmin → full red
    assert tuple(rgba[0, 2, :3]) == (33, 102, 172)  # clamped to vmax → full blue


def test_horizon_encoder_shallow_is_alarming_deep_is_pale():
    arr = np.array([[0.0, 4000.0, np.nan, np.inf]], dtype="float32")
    rgba = acid.encode_horizon_to_rgba(arr, 0.0, 4000.0)
    assert tuple(rgba[0, 0, :3]) == (128, 0, 38)     # 0 m → dark red (alarming)
    assert rgba[0, 1, 0] < 128                        # deep → paler than shallow-red
    assert rgba[0, 2, 3] == 0                          # NaN land → transparent
    assert tuple(rgba[0, 3, :3]) == (200, 220, 240)   # inf (always supersat) → safe pale-blue


def test_build_meta_has_center_and_horizon():
    m = acid.build_meta()
    keys = {v["key"] for v in m["variables"]}
    assert {"aragonite", "calcite", "horizon"} <= keys
    arag = next(v for v in m["variables"] if v["key"] == "aragonite")
    assert arag["center"] == 1.0
    assert "citation" in m


def test_horizon_interpolates_crossing():
    depths = [0, 100, 200, 300]
    col = [3.0, 2.0, 0.5, 0.2]           # crosses 1.0 between 100 (2.0) and 200 (0.5)
    h = acid.saturation_horizon(col, depths)
    # 100 + (1-2.0)/(0.5-2.0)*(200-100) = 100 + (-1/-1.5)*100 = 166.67
    assert abs(h - 166.6667) < 1e-2


def test_horizon_surface_corrosive_is_zero():
    assert acid.saturation_horizon([0.8, 0.7], [0, 100]) == 0.0


def test_horizon_all_supersaturated_is_inf():
    assert math.isinf(acid.saturation_horizon([3.0, 2.5, 1.2], [0, 100, 200]))


def test_horizon_all_nan_is_none():
    assert acid.saturation_horizon([float("nan"), float("nan")], [0, 100]) is None


def test_horizon_skips_nan_gaps():
    # NaN at 100 skipped; crossing computed between 0 (2.0) and 200 (0.0)
    h = acid.saturation_horizon([2.0, float("nan"), 0.0], [0, 100, 200])
    assert abs(h - 100.0) < 1e-6   # 0 + (1-2)/(0-2)*(200-0) = 100


def test_horizon_skips_float32_nan_gaps():
    # numpy.float32 does NOT subclass Python float, so an isinstance(o, float) guard
    # misses a float32 NaN. The real grid (_load_grid casts dtype="float32") feeds
    # horizon_grid() exactly this shape via list(g.data[:, yi, xi]).
    col = [np.float32(2.0), np.float32("nan"), np.float32(0.0)]
    h = acid.saturation_horizon(col, [np.float32(0), np.float32(100), np.float32(200)])
    assert h is not None and abs(h - 100.0) < 1e-4


def test_bake_all_writes_pngs(tmp_path, monkeypatch):
    monkeypatch.setattr(acid, "BAKE_DIR", tmp_path)
    monkeypatch.setattr(acid, "ensure_holdings", lambda force=False: True)
    fake = glodap_carbon._Grid(
        np.array([0.0, 1.0]), np.array([0.0, 1.0]),
        np.array([0.0, 100.0]),
        np.array([[[3.0, 3.0], [0.5, 0.5]], [[2.0, 2.0], [0.2, 0.2]]], dtype="float32"))
    monkeypatch.setattr(acid, "_load_grid", lambda v: fake)
    acid._GRID_CACHE.clear(); acid._HORIZON_CACHE.clear()
    n = acid.bake_all()
    assert n > 0
    assert (tmp_path / "aragonite" / "0.png").exists()
    assert (tmp_path / "horizon.png").exists()


def test_load_grid_horizon_reuses_aragonite_axes():
    # horizon has no NetCDF (nc_file=None) — _load_grid("horizon") must fall back to
    # the aragonite grid's axes (values come from horizon_grid, not this cube).
    from services import glodap_carbon
    import numpy as np
    fake = glodap_carbon._Grid(
        np.array([0.0, 1.0]), np.array([0.0, 1.0]),
        np.array([0.0, 100.0]), np.zeros((2, 2, 2), dtype="float32"))
    acid._GRID_CACHE.clear()
    acid._GRID_CACHE["aragonite"] = fake        # pre-seed so no xarray/NetCDF needed
    try:
        assert acid._load_grid("horizon") is fake
    finally:
        acid._GRID_CACHE.clear()


def test_horizon_shift_is_positive_when_pi_horizon_is_deeper():
    """Shift = horizon_PI - horizon_today. Less anthropogenic CO2 preindustrially means a
    deeper (larger) horizon, so a shoaled horizon yields a POSITIVE shift."""
    assert acid._shift_value(2000.0, 1200.0) == pytest.approx(800.0)


def test_horizon_shift_is_none_when_either_side_is_infinite():
    """inf = column never crosses Omega=1. A difference against inf is meaningless, and inf
    would serialise as the invalid JSON token Infinity."""
    assert acid._shift_value(float("inf"), 1200.0) is None
    assert acid._shift_value(2000.0, float("inf")) is None
    assert acid._shift_value(float("inf"), float("inf")) is None


def test_horizon_shift_is_none_when_either_side_is_missing():
    assert acid._shift_value(None, 1200.0) is None
    assert acid._shift_value(2000.0, None) is None


def test_horizon_shift_clamps_negative_noise_to_zero():
    """A reconstructed PI horizon marginally shallower than today's is numerical noise, not a
    deepening horizon. Clamp instead of emitting a physically backwards negative shift."""
    assert acid._shift_value(1199.5, 1200.0) == pytest.approx(0.0)


def test_acid_vars_has_horizon_shift_with_no_depth_axis():
    cfg = acid.ACID_VARS["horizon-shift"]
    assert cfg["depths"] == []
    assert cfg["kind"] == "shift"
    assert cfg["units"] == "m"


def test_build_meta_exposes_horizon_shift():
    keys = {v["key"] for v in acid.build_meta()["variables"]}
    assert "horizon-shift" in keys


def test_horizon_shift_export_source_is_registered_and_depth_free():
    from backend.services.export_registry import _FIELDS
    fs = _FIELDS["ocean-acidification-horizon-shift"]
    assert fs.vars == ("horizon_shift",)
    assert fs.has_depth is False
    assert "platform-derived" in fs.prov.note.lower()


def test_sample_accepts_underscore_alias_for_horizon_shift(monkeypatch):
    # The export path calls sample(fs.vars[0], ...) i.e. sample("horizon_shift", ...) —
    # the underscore variant must be aliased to the hyphenated "horizon-shift" key so it
    # hits the same branch, not the generic _load_grid(var) fallback (which would KeyError:
    # "horizon_shift" is not a key in ACID_VARS).
    fake = glodap_carbon._Grid(
        np.array([0.0, 10.0]), np.array([0.0, 10.0]),
        np.array([0.0, 100.0]), np.zeros((2, 2, 2), dtype="float32"))
    acid._GRID_CACHE.clear()
    acid._GRID_CACHE["aragonite"] = fake
    monkeypatch.setattr(acid, "horizon_shift_grid", lambda: np.array([[42.0, np.nan], [np.nan, np.nan]]))
    try:
        assert acid.sample("horizon_shift", 0.0, 0.0, None) == pytest.approx(42.0)
        assert acid.sample("horizon_shift", 0.0, 0.0, None) == acid.sample("horizon-shift", 0.0, 0.0, None)
    finally:
        acid._GRID_CACHE.clear()


def test_load_grid_has_underscore_to_hyphen_alias(monkeypatch):
    """Regression: _load_grid() must alias "horizon_shift" (underscore) to "horizon-shift"
    (hyphenated).

    The export path (routers/export.py → _load_any_grid) calls _load_grid() directly with
    fs.vars[0], which is the underscore form from the FieldSource registry. If the alias
    does not exist here, the export endpoint 500s. (Note: sample() also has this alias,
    but the export path calls _load_grid directly, not through sample().)

    This test works locally without GLODAP holdings by mocking the aragonite grid and
    checking that both underscore and hyphenated forms populate the cache with the SAME
    hyphenated key—proving the underscore form was aliased before the cache lookup."""
    fake = glodap_carbon._Grid(
        np.array([0.0, 10.0]), np.array([0.0, 10.0]),
        np.array([0.0, 100.0]), np.zeros((2, 2, 2), dtype="float32"))
    acid._GRID_CACHE.clear()
    acid._GRID_CACHE["aragonite"] = fake
    try:
        # Call with underscore form (what the export path uses)
        result1 = acid._load_grid("horizon_shift")
        # Call with hyphenated form (what ACID_VARS uses)
        result2 = acid._load_grid("horizon-shift")

        # Both should return the same grid (aragonite axes)
        assert result1 is result2, "Both forms should return the same grid object"

        # The cache should have a key for "horizon-shift", not "horizon_shift".
        # If the alias is missing, the cache will have "horizon_shift" and this fails.
        assert "horizon-shift" in acid._GRID_CACHE, (
            "horizon-shift not in cache; underscore-to-hyphen alias missing from _load_grid()."
        )
        assert "horizon_shift" not in acid._GRID_CACHE, (
            "horizon_shift in cache (underscore form); alias was not applied in _load_grid()."
        )
    finally:
        acid._GRID_CACHE.clear()
