# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""CHI (cumulative human impact) service tests.

Pure encoder/ramp/meta tests always run. The reproject + sample tests run against the REAL
source fixture (a Mollweide GeoTIFF crop of ssp245_current.tif) and are skipped where
rasterio is absent (e.g. the Mac dev venv) — they run on the VPS/CI where rasterio 1.5 lives.
"""
import importlib.util
import pathlib

import numpy as np
import pytest

from services import chi_impact as chi

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "chi" / "chi_ssp245_current_crop.tif"

_NO_RASTERIO = importlib.util.find_spec("rasterio") is None
_needs_rasterio = pytest.mark.skipif(_NO_RASTERIO, reason="rasterio not installed (runs on VPS/CI)")


# ── Pure encoder / ramp / meta ────────────────────────────────────────────────

def test_encode_nan_is_transparent():
    arr = np.array([[np.nan, 0.5]], dtype="float32")
    rgba = chi.encode_field_to_rgba(arr, 0.0, 1.0, "seq_chi")
    assert rgba[0, 0, 3] == 0            # nan → alpha 0
    assert tuple(rgba[0, 0]) == (0, 0, 0, 0)
    assert rgba[0, 1, 3] == 255          # real value → opaque


def test_encode_hits_ramp_anchor_colours():
    # vmin (0.0) → first stop; >=vmax (1.0) → last stop; exact anchor 0.35 → second stop.
    arr = np.array([[0.0, 1.0, 0.35]], dtype="float32")
    rgba = chi.encode_field_to_rgba(arr, 0.0, 1.0, "seq_chi")
    assert tuple(rgba[0, 0, :3]) == (33, 78, 100)     # calm teal (low)
    assert tuple(rgba[0, 1, :3]) == (150, 28, 28)     # deep red (high)
    assert tuple(rgba[0, 2, :3]) == (78, 160, 160)    # cyan mid anchor


def test_encode_saturates_above_vmax():
    # A value beyond the domain (the real max is 1.82 > vmax 1.0) must clamp, not wrap.
    arr = np.array([[1.82]], dtype="float32")
    rgba = chi.encode_field_to_rgba(arr, 0.0, 1.0, "seq_chi")
    assert tuple(rgba[0, 0, :3]) == (150, 28, 28)


def test_ramp_hex_shape():
    ramp = chi._ramp_hex("seq_chi")
    assert ramp[0]["pos"] == 0.0 and ramp[-1]["pos"] == 1.0
    assert all(h["hex"].startswith("#") and len(h["hex"]) == 7 for h in ramp)


def test_build_meta_single_dimensionless_var_and_citation():
    m = chi.build_meta()
    assert [v["key"] for v in m["variables"]] == ["impact"]
    v = m["variables"][0]
    assert v["units"] == "index" and v["ramp"]                    # dimensionless index
    # Editorial guardrail + licence must ride in the citation surfaced by the panel.
    assert "CC0" in m["citation"]
    assert "not a causal source" in m["citation"]
    assert "not a measurement" in m["citation"]


def test_nearest_idx():
    coords = np.array([10.0, 5.0, 0.0, -5.0])   # descending, like our lats
    assert chi._nearest_idx(coords, 4.9) == 1
    assert chi._nearest_idx(coords, -4.0) == 3


# ── Reproject + sample against the REAL fixture (rasterio-gated) ────────────────

def test_fixture_exists():
    assert FIXTURE.exists(), "real CHI fixture missing — Phase 0 was not saved"


@_needs_rasterio
def test_reproject_preserves_value_range_and_nodata():
    data, lats, lons = chi._reproject_to_4326(FIXTURE)
    assert data.shape == (1800, 3600)
    assert lats[0] > lats[-1]                     # row 0 = north (descending)
    assert lons[0] < lons[-1]                     # ascending
    finite = data[np.isfinite(data)]
    assert finite.size > 0, "reproject produced no valid cells"
    # Fixture window values are 0.667–0.953; warping must not invent values outside that.
    assert finite.min() >= 0.6 and finite.max() <= 1.0
    assert np.isnan(data).any()                   # land/outside footprint stays nan


@_needs_rasterio
def test_sample_roundtrips_a_known_cell():
    data, lats, lons = chi._reproject_to_4326(FIXTURE)
    chi._GRID_CACHE["impact"] = chi._Grid(lats, lons, data)
    try:
        ys, xs = np.where(np.isfinite(data))
        yi, xi = int(ys[0]), int(xs[0])
        got = chi.sample(float(lats[yi]), float(lons[xi]))
        assert got is not None and abs(got - float(data[yi, xi])) < 1e-5
        # A point far from the tiny fixture footprint is land/no-data → None.
        assert chi.sample(-89.5, 0.0) is None
    finally:
        chi._GRID_CACHE.pop("impact", None)
