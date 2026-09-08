# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import json
import os

from backend.ingestion import arts_ingest as a

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "arts", "arts_sample.geojson")


def _gj():
    with open(FIX) as f:
        return json.load(f)


def test_rows_shape_and_source():
    rows = a.build_arts_rows(_gj())
    assert len(rows) > 0
    r = rows[0]
    assert set(r) == {"source", "unique_id", "feature_name", "feature_type", "feature_category",
                      "thaw_type", "data_source_type", "authors", "source_doi", "imagery",
                      "lat", "lon",
                      # Added 2026-09-08: the imagery window both sources publish
                      # and both were folding into the free-text `imagery` blob.
                      "obs_start_year", "obs_end_year", "obs_start", "obs_end",
                      "date_precision", "contribution_date"}
    assert r["source"] == "arts_panarctic"
    assert r["feature_category"] == "retrogressive thaw slump"
    assert r["thaw_type"] == "abrupt"
    assert isinstance(r["lat"], float) and isinstance(r["lon"], float)
    assert 45 <= r["lat"] <= 84 and -180 <= r["lon"] <= 180  # circumpolar Arctic


def test_only_positive_kept():
    gj = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[100, 70], [100.01, 70], [100.01, 70.01], [100, 70.01], [100, 70]]]},
         "properties": {"UID": "p1", "TrainClass": "Positive"}},
        {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[10, 60], [10.01, 60], [10.01, 60.01], [10, 60.01], [10, 60]]]},
         "properties": {"UID": "n1", "TrainClass": "Negative"}}]}
    rows = a.build_arts_rows(gj)
    assert [r["unique_id"] for r in rows] == ["p1"]


def test_centroid_within_polygon_bbox():
    gj = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[100, 70], [102, 70], [102, 72], [100, 72], [100, 70]]]},
         "properties": {"UID": "c1", "TrainClass": "Positive"}}]}
    r = a.build_arts_rows(gj)[0]
    assert 100 <= r["lon"] <= 102 and 70 <= r["lat"] <= 72
