# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""The area export of the AOC2025 POC preview layer: served fields only, current
version only, provenance in the file. Needs PostGIS (skips without TEST_DATABASE_URL)."""
import json

from domains import aoc2025_poc as dm
from ingestion import aoc2025_poc as parser
from aoc2025_poc_helpers import CSV, conn, fake_fetch, needs_db  # noqa: F401

pytestmark = needs_db


async def test_area_export_serves_only_served_fields(conn, monkeypatch):
    monkeypatch.setattr(dm, "_fetch_bytes", fake_fetch({parser.SOURCE_URL: CSV}))
    await dm.sync_aoc2025_poc()
    from routers.export import export_data
    bbox = "-180,-90,180,90"
    geo = await export_data("greenland-sea-poc-aoc2025", bbox=bbox, poly=None, cells=None, format="geojson")
    csv = await export_data("greenland-sea-poc-aoc2025", bbox=bbox, poly=None, cells=None, format="csv")
    fc = json.loads(geo.body)
    assert len(fc["features"]) == 94
    for f in fc["features"]:
        assert set(f["properties"]) <= set(dm.AOC_POC_SERVED_FIELDS)
        assert "raw" not in f["properties"]
    assert csv.body.decode().splitlines()[0]
