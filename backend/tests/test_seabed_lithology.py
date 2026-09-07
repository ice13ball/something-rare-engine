# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import os, pathlib, pytest
import numpy as np
from backend.services import seabed_lithology as sl

FIX = pathlib.Path(__file__).parent / "fixtures" / "seabed" / "seabed_clip.nc"

def _grid_deps_available() -> bool:
	try:
		import xarray  # noqa: F401
		import netCDF4  # noqa: F401
		from PIL import Image  # noqa: F401
		return True
	except Exception:
		return False

pytestmark_grid = pytest.mark.skipif(
	not (FIX.exists() and _grid_deps_available()),
	reason="fixture is licence-restricted (CC-BY-NC, Dutkiewicz et al. 2015) and excluded from "
	       "the public repository, or geo deps (xarray/netCDF4/PIL) are absent — see DATA-LICENCES.md",
)

EXPECTED_RGB = {
    1: (128,130,132), 2: (255,241,0), 3: (250,169,25), 4: (112,75,42),
    5: (14,145,207), 6: (13,150,71), 7: (190,215,83), 8: (85,147,141),
    9: (131,112,178), 10: (247,187,213), 11: (234,27,27), 12: (195,154,107),
    13: (0,46,167),
}

def test_all_13_classes_named():
    assert set(sl.LITHOLOGY_CLASSES) == set(range(1, 14))
    assert sl.LITHOLOGY_CLASSES[5] == "Calcareous ooze"
    assert sl.CLASS_KEYS[5] == "calcareous_ooze"

def test_cpt_rgb_matches_official_palette():
    for code, rgb in EXPECTED_RGB.items():
        assert sl.CPT_RGB[code] == rgb, f"class {code}"

def test_class_color_has_alpha_and_nodata_transparent():
    assert sl.class_color(4) == (112, 75, 42, sl.FILL_ALPHA)
    assert sl.class_color(0) == (0, 0, 0, 0)      # nodata
    assert sl.class_color(99) == (0, 0, 0, 0)     # out of range

def test_palette_lut_shape_and_values():
    assert sl.PALETTE_LUT.shape == (14, 4)
    assert sl.PALETTE_LUT.dtype == np.uint8
    assert tuple(sl.PALETTE_LUT[4]) == (112, 75, 42, sl.FILL_ALPHA)
    assert tuple(sl.PALETTE_LUT[0]) == (0, 0, 0, 0)

def test_build_meta_lists_classes_and_citation():
    meta = sl.build_meta()
    assert len(meta["classes"]) == 13
    assert meta["classes"][0] == {"code": 1, "key": "gravel",
                                  "name": "Gravel and coarser", "rgb": [128,130,132]}
    assert "Dutkiewicz" in meta["citation"]
    assert meta["license"] == "CC-BY-NC"


# ── Grid tests (require real .nc clip fixture) ──────────────────────────────

@pytestmark_grid
def test_load_grid_axes_ascending(monkeypatch):
    sl._GRID = None
    monkeypatch.setattr(sl, "_grid_path", lambda: FIX)
    g = sl.load_grid()
    assert g is not None
    assert g.lons.min() >= -180.0 and g.lons.max() <= 180.0
    assert (np.diff(g.lats) > 0).all() and (np.diff(g.lons) > 0).all()

@pytestmark_grid
def test_sample_returns_known_class_or_none(monkeypatch):
    sl._GRID = None
    monkeypatch.setattr(sl, "_grid_path", lambda: FIX)
    g = sl.load_grid()
    # centre of the clip: sample equals the raw nearest cell
    lat = float(g.lats[len(g.lats)//2]); lon = float(g.lons[len(g.lons)//2])
    raw = int(g.data[len(g.lats)//2, len(g.lons)//2])
    got = sl.sample(lat, lon)
    assert got == (raw if 1 <= raw <= 13 else None)
    assert sl.sample(999, 999) is None      # off-grid clamped→edge, still valid code or None; ensure no crash

@pytestmark_grid
def test_render_tile_returns_png(monkeypatch):
    sl._GRID = None
    monkeypatch.setattr(sl, "_grid_path", lambda: FIX)
    png = sl.render_tile(0, 0, 0)
    assert png is not None and png[:8] == b"\x89PNG\r\n\x1a\n"

def test_render_tile_none_without_holdings(monkeypatch):
    sl._GRID = None
    monkeypatch.setattr(sl, "_grid_path", lambda: pathlib.Path("/nonexistent.nc"))
    assert sl.render_tile(0, 0, 0) is None
