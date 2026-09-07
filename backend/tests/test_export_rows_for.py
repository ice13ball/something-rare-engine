# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

# backend/tests/test_export_rows_for.py
import asyncio
import pytest
from services.export_registry import EXPORT_LAYERS, CompositeExport, VectorExport, FieldSource
import routers.export as ex


def test_rows_for_is_dispatchable():
    assert hasattr(ex, "_rows_for") and hasattr(ex, "_vector_rows") and hasattr(ex, "_members_of")


def test_marine_carbon_members_resolve_to_field():
    mc = EXPORT_LAYERS["marine-carbon"]
    assert isinstance(mc, CompositeExport)
    members = ex._members_of(mc)
    assert all(isinstance(m, FieldSource) for m in members)
    assert len(members) == 4


def test_members_of_supports_vector_members(monkeypatch):
    # a synthetic composite whose members are vector layers resolves to VectorExport entries
    comp = CompositeExport(id="x", label="X", members=("geotraces", "memento"))
    members = ex._members_of(comp)
    assert all(isinstance(m, VectorExport) for m in members)


def test_rows_for_composite_raises():
    # composite entry → ValueError before aoi is ever touched (kind_of check fires first)
    with pytest.raises(ValueError):
        asyncio.run(ex._rows_for(EXPORT_LAYERS["marine-carbon"], object()))
