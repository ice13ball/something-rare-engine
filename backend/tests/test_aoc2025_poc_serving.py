# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""What leaves the API for the AOC2025 POC preview layer: SERVED/HIDDEN
partition, stations/samples/meta endpoints, and the metadata-discrepancy note."""
import json

import pytest
from fastapi import HTTPException

from domains import aoc2025_poc as dm
from ingestion import aoc2025_poc as parser
from aoc2025_poc_helpers import CSV, conn, fake_fetch, needs_db  # noqa: F401

STRUCTURAL = ("version_id", "row_no", "raw", "geom")


def test_every_stored_column_is_in_exactly_one_list():
    stored = set(STRUCTURAL) | set(parser.FIELDS)
    served, hidden = dm.AOC_POC_SERVED_FIELDS, dm.AOC_POC_HIDDEN_FIELDS
    assert len(served) == len(set(served)), "duplicate in SERVED"
    assert not set(served) & set(hidden), f"in both lists: {set(served) & set(hidden)}"
    assert set(served) | set(hidden) == stored, (
        f"in neither list: {stored - set(served) - set(hidden)}; "
        f"not stored at all: {(set(served) | set(hidden)) - stored}")
    assert all(isinstance(r, str) and r.strip() for r in hidden.values()), "every hidden field needs its reason"


def test_every_served_measurement_field_has_a_unit_source():
    measurement_fields = set(parser.FIELDS) - {
        "cruise_id", "station", "sample_date", "lat", "lon", "activity", "sample_id"}
    missing = measurement_fields - set(dm.AOC_POC_UNITS)
    assert not missing, f"served without a documented unit: {missing}"


@pytest.fixture
async def seeded(conn, monkeypatch):
    monkeypatch.setattr(dm, "_fetch_bytes", fake_fetch({parser.SOURCE_URL: CSV}))
    await dm.sync_aoc2025_poc()
    dm.clear_caches()
    yield conn
    dm.clear_caches()


@needs_db
class TestServing:
    async def test_stations_feature_collection(self, seeded):
        fc = json.loads((await dm.aoc2025_poc_stations()).body)
        assert fc["type"] == "FeatureCollection"
        assert len(fc["features"]) == 32
        one = next(f for f in fc["features"] if f["properties"]["station"] == "AOC2025-2")
        assert one["geometry"]["type"] == "Point"
        assert one["properties"]["n_samples"] >= 1
        assert "depth_min_db" in one["properties"] and "depth_max_db" in one["properties"]

    async def test_samples_for_one_station_ordered_by_depth(self, seeded):
        body = await dm.aoc2025_poc_samples(station="AOC2025-2")
        assert body["station"] == "AOC2025-2"
        samples = body["samples"]
        assert len(samples) >= 1
        depths = [s["prespr01_db"] for s in samples if s["prespr01_db"] is not None]
        assert depths == sorted(depths)
        for s in samples:
            assert "raw" not in s and "geom" not in s
        assert body["units"]["poc_mg_dm3"] == parser.POC_PN_UNIT

    async def test_unknown_station_is_404(self, seeded):
        with pytest.raises(HTTPException) as exc:
            await dm.aoc2025_poc_samples(station="no-such-station")
        assert exc.value.status_code == 404

    async def test_meta_carries_citation_and_discrepancy_note(self, seeded):
        body = await dm.aoc2025_poc_meta()
        v = body["version"]
        assert v["doi"] == parser.DOI
        assert v["citation"] == dm.CITATION
        assert v["license"] == dm.LICENSE
        assert "2024-07-24" in v["temporal_extent_discrepancy"]
        assert "May 2025" in v["temporal_extent_discrepancy"]
        assert v["units"]["d13c_permil"] == parser.D13C_UNIT
