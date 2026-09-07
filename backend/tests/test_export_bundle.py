# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import io
import os
import zipfile

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs DB"
)


@pytest.mark.asyncio
async def test_bundle_unknown_layer_400(export_client):
    r = await export_client.get(
        "/v2/export/bundle?layers=geotraces,not-a-layer&bbox=-180,-90,180,90"
    )
    assert r.status_code == 400
    assert "not-a-layer" in r.text


@pytest.mark.asyncio
async def test_bundle_zip_shape(export_client):
    r = await export_client.get(
        "/v2/export/bundle?layers=geotraces,marine-carbon&bbox=-30,60,30,80&format=geojson"
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    assert "geotraces.geojson" in names
    assert any(
        n.startswith("marine-carbon/") and n.endswith(".geojson") for n in names
    )
    assert "MANIFEST.txt" in names
