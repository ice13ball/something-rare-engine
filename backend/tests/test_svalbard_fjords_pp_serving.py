# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""What leaves the API for the Svalbard fjords primary-production preview
layer: SERVED/HIDDEN partition, stations/samples/meta endpoints, and the
metadata-vs-data discrepancy notes."""
import json

import pytest
from fastapi import HTTPException

from domains import svalbard_fjords_pp as dm
from ingestion import svalbard_fjords_pp as parser
from svalbard_fjords_pp_helpers import CSV, conn, fake_fetch, needs_db  # noqa: F401

STRUCTURAL = ("version_id", "row_no", "raw", "geom")


def test_every_stored_column_is_in_exactly_one_list():
    stored = set(STRUCTURAL) | set(parser.FIELDS)
    served, hidden = dm.SVALBARD_FJORDS_PP_SERVED_FIELDS, dm.SVALBARD_FJORDS_PP_HIDDEN_FIELDS
    assert len(served) == len(set(served)), "duplicate in SERVED"
    assert not set(served) & set(hidden), f"in both lists: {set(served) & set(hidden)}"
    assert set(served) | set(hidden) == stored, (
        f"in neither list: {stored - set(served) - set(hidden)}; "
        f"not stored at all: {(set(served) | set(hidden)) - stored}")
    assert all(isinstance(r, str) and r.strip() for r in hidden.values()), "every hidden field needs its reason"


def test_every_served_measurement_field_has_a_unit_source():
    measurement_fields = set(parser.FIELDS) - {
        "exposition_no", "sample_date", "region_code", "fjord_part", "station", "lat", "lon", "water_mass"}
    missing = measurement_fields - set(dm.SVALBARD_FJORDS_PP_UNITS)
    assert not missing, f"served without a documented unit: {missing}"


def test_licence_text_says_used_with_permission_not_cc_by():
    assert "Used with permission" in parser.LICENCE
    assert "CC-BY" not in parser.LICENCE
    assert "CC-BY" not in dm.CITATION


@pytest.fixture
async def seeded(conn, monkeypatch):
    monkeypatch.setattr(dm, "_fetch_bytes", fake_fetch({parser.SOURCE_URL: CSV}))
    await dm.sync_svalbard_fjords_pp()
    dm.clear_caches()
    yield conn
    dm.clear_caches()


@needs_db
class TestServing:
    async def test_stations_feature_collection_has_43_unique_positions(self, seeded):
        fc = json.loads((await dm.svalbard_fjords_pp_stations()).body)
        assert fc["type"] == "FeatureCollection"
        assert len(fc["features"]) == 43
        ids = [f["properties"]["position_id"] for f in fc["features"]]
        assert len(ids) == len(set(ids))
        one = next(f for f in fc["features"] if f["properties"]["station"] == "K2")
        assert one["geometry"]["type"] == "Point"
        assert one["properties"]["n_expositions"] >= 1
        assert one["properties"]["region_name"] == "Kongsfjorden"
        hornsund = [f for f in fc["features"] if f["properties"]["region_code"] == "H"]
        assert hornsund and {f["properties"]["region_name"] for f in hornsund} == {"Hornsund"}

    async def test_samples_for_one_k2_position_returns_only_that_positions_expositions(self, seeded):
        fc = json.loads((await dm.svalbard_fjords_pp_stations()).body)
        k2 = [f for f in fc["features"] if f["properties"]["station"] == "K2"]
        assert len(k2) == 2
        pos_id = k2[0]["properties"]["position_id"]
        body = await dm.svalbard_fjords_pp_samples(position_id=pos_id)
        assert body["station"] == "K2"
        assert body["position_id"] == pos_id
        for exp in body["expositions"]:
            for s in exp["samples"]:
                assert "raw" not in s and "geom" not in s
        dates = [e["date"] for e in body["expositions"]]
        assert dates == sorted(dates)

    async def test_pi_null_for_exposition_without_it(self, seeded):
        fc = json.loads((await dm.svalbard_fjords_pp_stations()).body)
        found_null = False
        for f in fc["features"]:
            body = await dm.svalbard_fjords_pp_samples(position_id=f["properties"]["position_id"])
            for exp in body["expositions"]:
                if exp["pi_mgc_m2_day"] is None:
                    found_null = True
        assert found_null, "expected at least one exposition with pi_mgc_m2_day == null"

    async def test_unknown_position_is_404(self, seeded):
        with pytest.raises(HTTPException) as exc:
            await dm.svalbard_fjords_pp_samples(position_id="X:no-such:0:0")
        assert exc.value.status_code == 404

    async def test_meta_has_exactly_the_four_discrepancy_keys_and_no_temporal_one(self, seeded):
        body = await dm.svalbard_fjords_pp_meta()
        v = body["version"]
        keys = {d["key"] for d in v["discrepancies"]}
        assert keys == {"incubation_total", "station_counts", "bbox_west", "station_name_reuse"}
        assert "temporal" not in " ".join(keys)
        assert v["licence"] == parser.LICENCE
        assert "Used with permission" in v["licence"]
        assert "CC-BY" not in v["licence"]
        assert v["counts"]["rows"] == 369
        assert v["counts"]["expositions"] == 45
        assert v["counts"]["positions"] == 43
        assert v["counts"]["named_stations"] == 29
        assert v["date_range"]["first_date"] == "1994-07-05"
        assert v["date_range"]["last_date"] == "2019-08-11"
