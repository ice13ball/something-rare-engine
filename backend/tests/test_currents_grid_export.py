# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import json, numpy as np
from PIL import Image
from services import currents_grid_export as cge
from services.currents_bake import encode_uv_to_rgba, UNSCALE_MIN, UNSCALE_MAX

def _write_depth(dirpath, u, v, bounds):
    dirpath.mkdir(parents=True, exist_ok=True)
    rgba = encode_uv_to_rgba(u, v)
    Image.fromarray(rgba, "RGBA").save(dirpath / "latest.png")
    (dirpath / "latest.json").write_text(json.dumps({
        "bounds": bounds, "width": int(rgba.shape[1]), "height": int(rgba.shape[0]),
        "imageUnscale": [UNSCALE_MIN, UNSCALE_MAX],
    }))

def test_decode_roundtrip_and_sample(tmp_path, monkeypatch):
    # 2x2 grid over the whole globe; north row first (N→S)
    u = np.array([[1.0, -2.0], [0.5, np.nan]], dtype="float32")
    v = np.array([[0.0,  2.5], [-1.0, np.nan]], dtype="float32")
    bounds = [-180.0, -90.0, 180.0, 90.0]  # [W,S,E,N]
    monkeypatch.setattr(cge, "CACHE_DIR", tmp_path)
    _write_depth(tmp_path / "surface", u, v, bounds)
    _write_depth(tmp_path / "1000m",  u, v, bounds)
    cge.reset_cache()
    g = cge._load_grid("u")
    assert list(g.depths) == [0, 1000]
    assert g.lats[0] > g.lats[-1]            # N→S
    # top-left cell ≈ (lat +45, lon -90) → u≈1.0 within 6/255 quantization
    su = cge.sample("u", 45.0, -90.0, 0)
    assert abs(su - 1.0) <= (UNSCALE_MAX - UNSCALE_MIN) / 255 + 1e-6
    # NaN cell → None
    assert cge.sample("u", -45.0, 90.0, 0) is None

def test_missing_textures_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(cge, "CACHE_DIR", tmp_path)  # empty dir
    cge.reset_cache()
    assert cge._load_grid("u") is None
