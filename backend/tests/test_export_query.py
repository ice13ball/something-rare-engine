# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import pytest
from services.export_registry import EXPORT_LAYERS
from services.export_query import parse_aoi, build_vector_sql

def test_parse_bbox_ok():
    a = parse_aoi("-12.4,8.1,-9.8,11.3", None, None)
    assert a.kind == "bbox"
    assert a.bbox == (-12.4, 8.1, -9.8, 11.3)

def test_parse_requires_exactly_one():
    with pytest.raises(ValueError):
        parse_aoi(None, None, None)
    with pytest.raises(ValueError):
        parse_aoi("-1,-1,1,1", None, "a,b")

def test_parse_bbox_malformed():
    with pytest.raises(ValueError):
        parse_aoi("a,b,c,d", None, None)
    with pytest.raises(ValueError):
        parse_aoi("1,2,3", None, None)  # wrong arity

def test_parse_cells_cap():
    with pytest.raises(ValueError):
        parse_aoi(None, None, ";".join(str(i) for i in range(501)))

def test_parse_cells_preserves_comma_ids():
    # cell_id format is "i,j" (contains a comma); the list delimiter is ";".
    # Regression: joining/splitting on "," shredded each id and matched nothing,
    # so every hex-selection export returned 0 rows.
    aoi = parse_aoi(None, None, "-27,31;-28,31;-29,31")
    assert aoi.kind == "cells"
    assert aoi.cell_ids == ("-27,31", "-28,31", "-29,31")

def test_build_vector_sql_bbox_count():
    layer = EXPORT_LAYERS["geotraces"]
    aoi = parse_aoi("-12,8,-9,11", None, None)
    sql, params = build_vector_sql(layer, aoi, count_only=True)
    assert "COUNT(*)" in sql
    assert "ST_MakeEnvelope" in sql and "&&" in sql and "ST_Intersects" in sql
    assert "LIMIT" not in sql
    assert params == [-12.0, 8.0, -9.0, 11.0]

def test_build_vector_sql_data_has_geometry_and_cap():
    layer = EXPORT_LAYERS["geotraces"]
    aoi = parse_aoi("-12,8,-9,11", None, None)
    sql, _ = build_vector_sql(layer, aoi, count_only=False)
    assert "ST_AsGeoJSON(t.geom)::json AS geometry" in sql
    assert f"LIMIT {layer.cap}" in sql
    assert "sample_id" in sql  # an exported field

def test_build_vector_sql_memento_join():
    layer = EXPORT_LAYERS["memento"]
    aoi = parse_aoi("-12,8,-9,11", None, None)
    sql, _ = build_vector_sql(layer, aoi, count_only=False)
    assert "JOIN memento_casts c ON c.cast_id = t.cast_id" in sql
    assert "ST_AsGeoJSON(c.geom)::json AS geometry" in sql

def test_build_vector_sql_poly_and_cells():
    layer = EXPORT_LAYERS["geotraces"]
    sql_p, params_p = build_vector_sql(
        layer, parse_aoi(None, '{"type":"Polygon","coordinates":[[[0,0],[1,0],[1,1],[0,0]]]}', None),
        count_only=True)
    assert "ST_GeomFromGeoJSON" in sql_p and params_p[0].startswith("{")
    sql_c, params_c = build_vector_sql(
        layer, parse_aoi(None, None, "-27,31;-28,31"), count_only=True)
    assert "density_hex_cells" in sql_c and "cell_id = ANY" in sql_c
    assert params_c == [["-27,31", "-28,31"]]
