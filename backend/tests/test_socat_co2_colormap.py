# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import numpy as np
from services import socat_co2 as sc   # conftest adds backend/ to sys.path

def test_vars_and_decades():
    assert set(sc.CO2_VARS) == {"fco2", "density", "sst", "salinity"}
    assert sc.CO2_VARS["fco2"]["nc_var"] == "fco2_ave_weighted_decade"
    assert [d["label"] for d in sc.DECADES] == ["1970s","1980s","1990s","2000s","2010s","2020s"]

def test_encode_nan_transparent_and_opaque():
    arr = np.array([[np.nan, 380.0]], dtype="float32")
    rgba = sc.encode_field_to_rgba(arr, 280, 450, "matter")
    assert rgba[0, 0, 3] == 0 and rgba[0, 1, 3] == 255

def test_ramp_hex_uses_pos_key():
    for stop in sc._ramp_hex("matter"):
        assert set(stop.keys()) == {"pos", "hex"}

def test_build_meta_shape():
    m = sc.build_meta()
    assert {v["key"] for v in m["variables"]} == {"fco2","density","sst","salinity"}
    assert [d["label"] for d in m["decades"]] == ["1970s","1980s","1990s","2000s","2010s","2020s"]
    assert "Bakker" in m["citation"] and "Sabine" in m["citation"]

import pathlib

PANEL = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "components" / "panels" / "fields" / "Co2PointPanel.tsx"

def test_panel_never_renders_a_bare_decade_index():
    """`Decade: {decade}s` prints the store's integer index — production showed
    'Decade: 5s'. The panel must render the server-provided label instead."""
    src = PANEL.read_text(encoding="utf-8")
    assert "{decade}s" not in src, "panel still interpolates the raw decade index"
    assert "decade_label" in src, "panel does not read the server-provided label"

def test_panel_cites_the_socat_release_we_actually_serve():
    src = PANEL.read_text(encoding="utf-8")
    assert "v2024" not in src, "panel still links SOCAT v2024; we serve v2026"
    assert "v2026" in src

def test_every_decade_index_maps_to_a_human_label():
    """Regression guard on the constant the endpoint will now read from."""
    from services import socat_co2
    assert len(socat_co2.DECADES) == 6
    for i, d in enumerate(socat_co2.DECADES):
        assert d["index"] == i
        assert d["label"][:4].isdigit(), f"decade {i} label {d['label']!r} is not year-like"

def test_no_source_claims_a_socat_release_we_do_not_serve():
    """We serve SOCATv2026. A version string is a provenance claim, and it lives
    in more places than the panel — the layer catalogue carries one too. `.snap`
    is included: a Vitest snapshot is human-readable rendered output, and it was
    the one place this guard missed on 2026-09-04 (caught only by running vitest)."""
    roots = [
        pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src",
        pathlib.Path(__file__).resolve().parents[2] / "frontend" / "public",
    ]
    offenders = []
    for root in roots:
        for path in (list(root.rglob("*.ts")) + list(root.rglob("*.tsx"))
                     + list(root.rglob("*.json")) + list(root.rglob("*.snap"))):
            text = path.read_text(encoding="utf-8")
            if "SOCAT v2024" in text or "SOCATv2024" in text:
                offenders.append(str(path))
    assert offenders == [], f"these still cite a SOCAT release we do not serve: {offenders}"
