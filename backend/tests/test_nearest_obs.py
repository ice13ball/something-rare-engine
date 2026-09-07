# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from backend.services import nearest_obs as no


def test_shape_rows_sorts_ascending_and_rounds():
    raw = [
        {"source": "argo", "id": "a1", "distance_km": 47.28, "summary": "x", "lat": 1.0, "lon": 2.0, "deck_layer_id": "argo-floats-3d"},
        {"source": "vents", "id": "v1", "distance_km": 3.114, "summary": "y", "lat": 3.0, "lon": 4.0, "deck_layer_id": "hydrothermal-vents-active"},
    ]
    out = no.shape_rows(raw)
    assert [r["source"] for r in out] == ["vents", "argo"]
    assert out[0]["distance_km"] == 3.1
    assert out[1]["distance_km"] == 47.3


def test_shape_rows_drops_null_id_rows():
    """A source with no rows in range comes back with id None — omit it, never show 0 km."""
    raw = [
        {"source": "cascade", "id": None, "distance_km": None, "summary": None, "lat": None, "lon": None, "deck_layer_id": "arctic-sediment-carbon-stations"},
        {"source": "argo", "id": "a1", "distance_km": 10.0, "summary": "x", "lat": 1.0, "lon": 2.0, "deck_layer_id": "argo-floats-3d"},
    ]
    out = no.shape_rows(raw)
    assert [r["source"] for r in out] == ["argo"]


def test_registry_has_eight_ocean_chemistry_sources():
    keys = {s["key"] for s in no.OBS_SOURCES}
    assert keys == {"argo", "geotraces", "memento", "wod-oxygen", "cascade",
                    "methane-seeps", "vents", "deepdata-stations"}
    # every entry names a table, geom col, id col and a deck layer id
    for s in no.OBS_SOURCES:
        assert s["table"] and s["geom_col"] and s["id_col"] and s["deck_layer_id"]


def test_geography_sources_flagged_for_geometry_cast():
    by = {s["key"]: s for s in no.OBS_SOURCES}
    assert by["vents"]["geog"] is True
    assert by["deepdata-stations"]["geog"] is True
    assert by["argo"]["geog"] is False


def test_shape_rows_keeps_zero_and_none_distance_and_orders_them():
    """A real id with distance_km 0.0 (click exactly on a feature) must not be dropped by a
    falsy-value check, and must sort first. A real id with distance_km None (anomalous null
    distance) must not be dropped either, and must sort last with no TypeError."""
    raw = [
        {"source": "b", "id": "b1", "distance_km": 5.0, "summary": "x", "lat": 1.0, "lon": 2.0, "deck_layer_id": "argo-floats-3d"},
        {"source": "on_it", "id": "z1", "distance_km": 0.0, "summary": "y", "lat": 3.0, "lon": 4.0, "deck_layer_id": "hydrothermal-vents-active"},
        {"source": "anom", "id": "n1", "distance_km": None, "summary": "z", "lat": 5.0, "lon": 6.0, "deck_layer_id": "memento"},
    ]
    out = no.shape_rows(raw)
    assert [r["source"] for r in out] == ["on_it", "b", "anom"]
    assert out[0]["distance_km"] == 0.0
