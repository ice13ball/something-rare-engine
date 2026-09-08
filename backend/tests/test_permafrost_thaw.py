# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import json
import os

from backend.ingestion import permafrost_thaw as pt

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "permafrost_thaw", "alaska_thaw_sample.geojson")


def _gj():
    with open(FIX, encoding="utf-8") as f:
        return json.load(f)


def test_build_rows_basic_shape():
    rows = pt.build_thaw_rows(_gj())
    assert len(rows) > 0
    r = rows[0]
    assert set(r) == {"source", "unique_id", "feature_name", "feature_type",
                      "feature_category", "thaw_type", "data_source_type", "authors", "source_doi", "imagery",
                      "lat", "lon",
                      # Added 2026-09-08: the imagery window both sources publish
                      # and both were folding into the free-text `imagery` blob.
                      "obs_start_year", "obs_end_year", "obs_start", "obs_end",
                      "date_precision", "contribution_date"}
    assert r["source"] == "alaska_webb"
    assert isinstance(r["lat"], float) and isinstance(r["lon"], float)
    assert -180 <= r["lon"] <= 180 and 50 <= r["lat"] <= 75  # Alaska


def test_na_doi_coerced_to_none():
    gj = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "geometry": {"type": "Point", "coordinates": [-150.0, 65.0]},
        "properties": {"DOI": "N/A", "FeatureName": "",
                       "FeatureType": "thermokarst lake", "FeatureCategory": "Thermokarst Lake",
                       "ThawType": "abrupt", "DataSourceType": "Field - unpublished",
                       "Authors": "Webb et al. (2025)"}}]}
    r = pt.build_thaw_rows(gj)[0]
    assert r["source_doi"] is None
    assert r["feature_name"] is None          # empty string -> None
    assert r["thaw_type"] == "abrupt"
    assert r["unique_id"]  # non-empty deterministic hash (source has no UniqueID column)


def test_dedup_on_unique_id():
    feat = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-150.0, 65.0]},
            "properties": {"FeatureName": "Duplicate Site", "FeatureType": "thermokarst lake",
                            "Authors": "Webb et al. (2025)", "DOI": "https://doi.org/10.1/x"}}
    gj = {"type": "FeatureCollection", "features": [feat, dict(feat)]}
    rows = pt.build_thaw_rows(gj)
    assert len(rows) == 1


def test_unique_id_differs_for_different_features():
    gj = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-150.0, 65.0]},
         "properties": {"FeatureName": "Site A", "FeatureType": "thermokarst lake"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-151.0, 66.0]},
         "properties": {"FeatureName": "Site B", "FeatureType": "thermokarst lake"}},
    ]}
    rows = pt.build_thaw_rows(gj)
    assert len(rows) == 2
    assert rows[0]["unique_id"] != rows[1]["unique_id"]


def test_skips_missing_coordinates():
    gj = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "geometry": None,
        "properties": {"FeatureName": "No Coords"}}]}
    assert pt.build_thaw_rows(gj) == []
