# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""
Tests for Task 6: field native-grid export + marine-carbon composite ZIP+MANIFEST.

These tests require baked NetCDF/grid holdings on disk (VPS only).
They are skipped locally when TEST_FIELD_HOLDINGS is not set.
"""
from __future__ import annotations

import io
import os
import zipfile

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_FIELD_HOLDINGS"),
    reason="needs baked field holdings on disk (set TEST_FIELD_HOLDINGS=1 on VPS)",
)


@pytest.mark.asyncio
async def test_marine_carbon_returns_zip_of_four_sources(export_client):
    r = await export_client.get("/v2/export/marine-carbon?bbox=-30,60,30,80&format=csv")
    assert r.status_code == 200
    assert "application/zip" in r.headers["content-type"]
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    assert any(n.startswith("socat") for n in names), f"no socat file in {names}"
    assert any(n.startswith("glodap") for n in names), f"no glodap file in {names}"
    assert any(n.startswith("isas") for n in names), f"no isas file in {names}"
    assert any(n.startswith("woa") for n in names), f"no woa file in {names}"
    assert "MANIFEST.txt" in names, f"MANIFEST.txt missing from {names}"
    manifest = z.read("MANIFEST.txt").decode()
    assert "Bakker" in manifest, "SOCAT citation missing from MANIFEST"
    assert "Lauvset" in manifest, "GLODAP citation missing from MANIFEST"
    assert "ISAS20" in manifest, "ISAS20 source missing from MANIFEST"
    assert "WOA23" in manifest or "World Ocean Atlas" in manifest, "WOA source missing from MANIFEST"


@pytest.mark.asyncio
async def test_marine_carbon_count_is_per_member(export_client):
    r = await export_client.get("/v2/export/marine-carbon/count?bbox=-30,60,30,80")
    assert r.status_code == 200
    data = r.json()
    assert "members" in data, f"expected 'members' key, got {list(data.keys())}"
    members = data["members"]
    ids = {m["id"] for m in members}
    assert ids == {"socat-co2", "glodap-carbon", "isas20-oxygen", "woa23"}, (
        f"unexpected member ids: {ids}"
    )
    for m in members:
        assert "count" in m and "cap" in m and "capped" in m, (
            f"member {m['id']} missing count/cap/capped keys"
        )


@pytest.mark.asyncio
async def test_field_source_count(export_client):
    r = await export_client.get("/v2/export/socat-co2/count?bbox=-30,60,30,80")
    assert r.status_code == 200
    data = r.json()
    assert "count" in data and "cap" in data and "capped" in data
    assert isinstance(data["count"], int)
    assert data["cap"] == 20_000


@pytest.mark.asyncio
async def test_field_source_geojson(export_client):
    r = await export_client.get("/v2/export/socat-co2?bbox=-10,65,10,75&format=geojson")
    assert r.status_code == 200
    assert "geo+json" in r.headers["content-type"]
    fc = r.json()
    assert fc["type"] == "FeatureCollection"
    if fc["features"]:
        feat = fc["features"][0]
        assert feat["type"] == "Feature"
        assert feat["geometry"]["type"] == "Point"
        props = feat["properties"]
        assert "lat" in props and "lon" in props


@pytest.mark.asyncio
async def test_field_source_csv(export_client):
    r = await export_client.get("/v2/export/glodap-carbon?bbox=-10,65,10,75&format=csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    lines = r.text.splitlines()
    # At minimum: comment header + column header
    assert len(lines) >= 2


@pytest.mark.asyncio
async def test_marine_carbon_geojson_zip(export_client):
    """Composite with format=geojson should still return a ZIP (one .geojson per member)."""
    r = await export_client.get("/v2/export/marine-carbon?bbox=-10,65,10,75&format=geojson")
    assert r.status_code == 200
    assert "application/zip" in r.headers["content-type"]
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    geojson_files = [n for n in names if n.endswith(".geojson")]
    assert len(geojson_files) == 4, f"expected 4 .geojson files, got {geojson_files}"
    assert "MANIFEST.txt" in names
