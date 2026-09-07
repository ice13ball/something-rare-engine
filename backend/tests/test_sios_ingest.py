# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

# backend/tests/test_sios_ingest.py
import json, pathlib
from backend.ingestion import sios_ingest as si

FIX = json.load(open(pathlib.Path(__file__).parent / "fixtures/sios/data_page_sample.json"))
ROWS = FIX["rows"]

def _insitu():
    return [r for r in ROWS if "In Situ" in (r.get("activity_type") or "")]

def test_decode_keywords_splits_and_unescapes():
    assert si.decode_keywords("A &gt; B, C &gt; D") == ["A > B", "C > D"]
    assert si.decode_keywords("") == []

def test_parse_collections_flags_core_data():
    cols = si.parse_collections("GCW, SIOSCD, SIOS, NSDN, ADC")
    assert "SIOSCD" in cols and "SIOS" in cols

def test_point_from_bbox_reads_east_typo_key():
    r = _insitu()[0]
    pt = si.point_from_bbox(r)
    assert pt is not None
    lat, lon = pt
    assert 74.0 <= lat <= 81.5 and -15.0 <= lon <= 40.0

def test_point_from_bbox_rejects_global_satellite():
    sat = next(r for r in ROWS if "Space" in (r.get("activity_type") or ""))
    assert si.point_from_bbox(sat) is None  # global/large bbox → not a point

def test_is_mappable_excludes_satellite_keeps_insitu():
    assert si.is_mappable(_insitu()[0]) is True
    sat = next(r for r in ROWS if "Space" in (r.get("activity_type") or ""))
    assert si.is_mappable(sat) is False

def test_parse_record_shape():
    rec = si.parse_record(_insitu()[0])
    assert rec is not None
    for k in ("metadata_id","title","is_core_data","activity_type","iso_topic",
              "keywords","platform_long","institution","time_start","time_end",
              "license","url_opendap","lat","lon"):
        assert k in rec, k
    assert isinstance(rec["is_core_data"], bool)
    assert isinstance(rec["keywords"], list)
    assert isinstance(rec["lat"], float) and isinstance(rec["lon"], float)

def test_parse_record_none_for_satellite():
    sat = next(r for r in ROWS if "Space" in (r.get("activity_type") or ""))
    assert si.parse_record(sat) is None

def test_point_from_bbox_rejects_large_span():
    import copy
    r = copy.deepcopy(_insitu()[0])
    # Set a Svalbard-centered bbox with a basin-scale span > 3° (north - south = 5°)
    r["geographic_extent_rectangle_north"] = "80.0"
    r["geographic_extent_rectangle_south"] = "75.0"
    r["geographic_extent_rectangle_west"] = "10.0"
    r["geographic_extent_ectangle_east"] = "15.0"
    # span = 80.0 - 75.0 = 5.0° > 3.0°, should reject as too large to be a local footprint
    assert si.point_from_bbox(r) is None

def test_is_mappable_rejects_non_open():
    import copy
    r = copy.deepcopy(_insitu()[0])
    # Valid Svalbard point (from fixture), set access_constraint to non-Open
    r["access_constraint"] = "Restricted"
    assert si.is_mappable(r) is False
