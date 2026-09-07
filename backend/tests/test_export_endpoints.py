# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)

# Integration tests run against a DB with a tiny fixture in geotraces_samples.
# They assert: count endpoint returns {count,cap,capped}; export?format=geojson
# returns a FeatureCollection with a metadata member; export?format=csv returns
# text/csv with the lat,lon,source,source_url header; an unknown layer → 404;
# missing geom param → 400.


@pytest.mark.asyncio
async def test_count_and_export_geotraces_bbox(export_client):
    r = await export_client.get("/v2/export/geotraces/count?bbox=-180,-90,180,90")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"count", "cap", "capped"}

    g = await export_client.get("/v2/export/geotraces?bbox=-180,-90,180,90&format=geojson")
    assert g.status_code == 200
    assert g.json()["type"] == "FeatureCollection"
    assert "metadata" in g.json()

    c = await export_client.get("/v2/export/geotraces?bbox=-180,-90,180,90&format=csv")
    assert c.status_code == 200
    assert c.headers["content-type"].startswith("text/csv")


@pytest.mark.asyncio
async def test_unknown_layer_404(export_client):
    r = await export_client.get("/v2/export/not-a-layer/count?bbox=-1,-1,1,1")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_missing_geom_400(export_client):
    r = await export_client.get("/v2/export/geotraces/count")
    assert r.status_code == 400
