# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

# backend/tests/test_arcade_ingest.py
import json, os
from backend.ingestion import arcade_ingest

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "arcade")

def _load_sample():
    base = os.path.join(FIX, "arcade_v1_sample")
    with open(base + ".shp", "rb") as f: shp = f.read()
    with open(base + ".shx", "rb") as f: shx = f.read()
    with open(base + ".dbf", "rb") as f: dbf = f.read()
    return arcade_ingest.build_catchment_rows(shp, shx, dbf)

def _ring_counts(wkt):
    """Parse a MULTIPOLYGON WKT and return ring count per polygon (no shapely)."""
    body = wkt[len("MULTIPOLYGON"):]
    depth = 0
    counts = []
    for ch in body:
        if ch == "(":
            depth += 1
            if depth == 2:
                counts.append(0)   # new polygon
            elif depth == 3:
                counts[-1] += 1    # new ring within current polygon
        elif ch == ")":
            depth -= 1
    return counts


def test_parses_all_records():
    rows = _load_sample()
    assert len(rows) == 8

def test_curated_columns_match_real_values():
    rows = {r["gid"]: r for r in _load_sample()}
    exp = json.load(open(os.path.join(FIX, "expected_curated.json")))
    for e in exp:
        r = rows[e["gid"]]
        assert r["continent"] == e["continent"]
        assert abs(r["area_km2"] - e["area_km2"]) < 1e-6
        assert abs(r["ocs_mean"] - e["ocs_mean"]) < 1e-3
        assert abs(r["pf_frac"] - e["pf_frac"]) < 1e-6
        # source column runoff_mea maps to runoff_mean
        assert abs(r["runoff_mean"] - e["runoff_mea"]) < 1e-6
        # source column `order` maps to stream_order
        assert r["stream_order"] == (None if e["order"] is None else int(e["order"]))

def test_empty_name_coerced_to_none():
    rows = _load_sample()
    # rec gid=1 has name "" in the real fixture
    r = next(r for r in rows if r["gid"] == 1)
    assert r["name"] is None

def test_params_packs_depth_and_permafrost_classes():
    r = next(r for r in _load_sample() if r["gid"] == 1)
    assert len(r["params"]["soc_depth"]) == 6
    assert set(r["params"]["pf_classes"]) == {"cont", "disc", "isol", "spor"}
    # NDVI emitted as snake_case (DBF col is uppercase NDVI_mean)
    assert "ndvi_mean" in r["params"]
    assert "NDVI_mean" not in r["params"]

def test_wkt_is_polygon_in_source_metres():
    r = _load_sample()[0]
    assert r["wkt"].startswith(("POLYGON", "MULTIPOLYGON"))
    # EASE-Grid metres: |coord| are large (millions), never lat/lon range
    assert "179." not in r["wkt"][:40]  # not lon/lat


def test_holes_become_interior_rings():
    rows = {r["gid"]: r for r in _load_sample()}
    exp = json.load(open(os.path.join(FIX, "hole_structure.json")))
    for gid_str, info in exp.items():
        r = rows[int(gid_str)]
        # the polygon with the most rings = exterior + its holes
        max_rings = max(_ring_counts(r["wkt"]))
        assert max_rings == info["nrings"]
