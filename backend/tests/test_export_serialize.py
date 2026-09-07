# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import datetime
import json
from decimal import Decimal

from services.export_registry import Provenance
from services.export_serialize import rows_to_geojson, rows_to_csv, PASS_THROUGH_NOTE, dumps_geojson

PROV = Provenance(source="SRC", source_url="https://x", license="CC-BY 4.0", citation="Cite 2020")

def test_dumps_geojson_serializes_date_datetime_decimal():
    """dumps_geojson must not raise on date/datetime/Decimal — previously caused HTTP 500."""
    rows = [
        {
            "id": 1,
            "record_date": datetime.date(2020, 1, 2),
            "created_at": datetime.datetime(2024, 6, 15, 12, 0, 0),
            "score": Decimal("3.14"),
            "geometry": {"type": "Point", "coordinates": [10.0, 20.0]},
        }
    ]
    fc = rows_to_geojson(rows, PROV, retrieved_at="2026-06-29T00:00:00Z", capped=False, layer_id="wdpa")
    # Must not raise TypeError
    serialized = dumps_geojson(fc)
    parsed = json.loads(serialized)
    props = parsed["features"][0]["properties"]
    # date → ISO string
    assert props["record_date"] == "2020-01-02"
    # datetime → ISO string
    assert props["created_at"] == "2024-06-15T12:00:00"
    # Decimal → float (numeric in JSON, not string)
    assert props["score"] == 3.14
    assert isinstance(props["score"], float)


def test_geojson_shape_and_metadata():
    rows = [{"id": 1, "v": 3.5, "geometry": {"type": "Point", "coordinates": [10, 20]}}]
    fc = rows_to_geojson(rows, PROV, retrieved_at="2026-06-28T00:00:00Z", capped=False, layer_id="geotraces")
    assert fc["type"] == "FeatureCollection"
    assert fc["features"][0]["properties"] == {"id": 1, "v": 3.5}
    assert fc["features"][0]["geometry"]["coordinates"] == [10, 20]
    md = fc["metadata"]
    assert md["source"] == "SRC" and md["citation"] == "Cite 2020"
    assert md["feature_count"] == 1 and md["capped"] is False
    assert md["note"] == PASS_THROUGH_NOTE
    assert md["layer"] == "geotraces"

def test_csv_point_has_latlon_and_provenance_columns():
    rows = [{"id": 1, "v": 3.5, "geometry": {"type": "Point", "coordinates": [10.5, 20.5]}}]
    csv = rows_to_csv(rows, "point", PROV)
    header, line = csv.splitlines()
    assert header == "id,v,lat,lon,source,source_url"
    assert line == "1,3.5,20.5,10.5,SRC,https://x"
    assert csv.endswith("\r\n")

def test_csv_polygon_has_wkt():
    rows = [{"gid": 9, "geometry": {"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,0]]]}}]
    csv = rows_to_csv(rows, "polygon", PROV)
    header = csv.splitlines()[0]
    assert header == "gid,geometry_wkt,source,source_url"
    assert "POLYGON" in csv.splitlines()[1]

def test_csv_quotes_commas():
    rows = [{"name": "a,b", "geometry": {"type": "Point", "coordinates": [0, 0]}}]
    csv = rows_to_csv(rows, "point", PROV)
    assert '"a,b"' in csv

# --- CSV formula injection neutralization tests ---

def test_csv_formula_equals_neutralized():
    """String starting with '=' must be prefixed with apostrophe."""
    rows = [{"title": "=cmd /c calc", "geometry": {"type": "Point", "coordinates": [0, 0]}}]
    csv = rows_to_csv(rows, "point", PROV)
    assert "'=cmd /c calc" in csv.splitlines()[1]

def test_csv_formula_plus_neutralized():
    rows = [{"val": "+1234", "geometry": {"type": "Point", "coordinates": [0, 0]}}]
    csv = rows_to_csv(rows, "point", PROV)
    assert "'+1234" in csv.splitlines()[1]

def test_csv_formula_at_neutralized():
    rows = [{"val": "@SUM(A1:A10)", "geometry": {"type": "Point", "coordinates": [0, 0]}}]
    csv = rows_to_csv(rows, "point", PROV)
    assert "'@SUM(A1:A10)" in csv.splitlines()[1]

def test_csv_formula_tab_neutralized():
    rows = [{"val": "\tcmd", "geometry": {"type": "Point", "coordinates": [0, 0]}}]
    csv = rows_to_csv(rows, "point", PROV)
    assert "'\tcmd" in csv.splitlines()[1]

def test_csv_negative_number_not_neutralized():
    """Negative float must stay as-is; only string-typed values are prefixed."""
    rows = [{"depth": -12.5, "geometry": {"type": "Point", "coordinates": [0, 0]}}]
    csv = rows_to_csv(rows, "point", PROV)
    data_line = csv.splitlines()[1]
    assert "-12.5" in data_line
    assert "'-12.5" not in data_line

def test_csv_normal_string_unchanged():
    rows = [{"name": "hello world", "geometry": {"type": "Point", "coordinates": [0, 0]}}]
    csv = rows_to_csv(rows, "point", PROV)
    assert "hello world" in csv.splitlines()[1]


# --- Collision-proof provenance column tests ---

def test_csv_no_duplicate_source_url_when_row_has_source_url():
    """Row already contains source_url → trailing source_url prov column renamed; source stays."""
    rows = [{"source_url": "https://row-url", "geometry": {"type": "Point", "coordinates": [1.0, 2.0]}}]
    csv = rows_to_csv(rows, "point", PROV)
    header = csv.splitlines()[0]
    cols = header.split(",")
    # source_url must not appear twice
    assert cols.count("source_url") == 1, f"Duplicate source_url in header: {header}"
    # trailing prov source_url column renamed; source not colliding so keeps default name
    assert "dataset_source_url" in cols
    assert "source" in cols  # no collision on "source" key
    data_line = csv.splitlines()[1]
    # per-row source_url preserved AND layer prov source_url also present
    assert "https://row-url" in data_line
    assert "https://x" in data_line


def test_csv_no_duplicate_source_when_row_has_both():
    """Row already contains both source and source_url → both trailing names renamed."""
    rows = [{"source": "row-src", "source_url": "https://row-url",
             "geometry": {"type": "Point", "coordinates": [0.0, 0.0]}}]
    csv = rows_to_csv(rows, "point", PROV)
    header = csv.splitlines()[0]
    cols = header.split(",")
    assert cols.count("source") == 1, f"Duplicate 'source' in header: {header}"
    assert cols.count("source_url") == 1, f"Duplicate 'source_url' in header: {header}"
    assert "dataset_source" in cols
    assert "dataset_source_url" in cols
    data_line = csv.splitlines()[1]
    assert "row-src" in data_line
    assert "SRC" in data_line      # prov.source still written, now under dataset_source


def test_csv_no_collision_when_row_has_no_source_keys():
    """No collision → trailing columns keep the default names 'source' / 'source_url'."""
    rows = [{"val": 1, "geometry": {"type": "Point", "coordinates": [0, 0]}}]
    csv = rows_to_csv(rows, "point", PROV)
    header = csv.splitlines()[0]
    assert "source" in header.split(",")
    assert "source_url" in header.split(",")
    assert "dataset_source" not in header


# --- Bug-fix: lat/lon dedup for point layers that store lat/lon natively ---

def test_csv_point_latlon_in_props_no_dedup():
    """When row props already include lat and lon, header must have them exactly once."""
    rows = [{"id": 1, "lat": 20.5, "lon": 10.5,
             "geometry": {"type": "Point", "coordinates": [10.5, 20.5]}}]
    csv = rows_to_csv(rows, "point", PROV)
    header = csv.splitlines()[0]
    cols = header.split(",")
    assert cols.count("lat") == 1, f"lat appears {cols.count('lat')} times: {header}"
    assert cols.count("lon") == 1, f"lon appears {cols.count('lon')} times: {header}"
    assert header == "id,lat,lon,source,source_url"


# --- Bug-fix: stable header on empty export (columns= parameter) ---

def test_csv_empty_rows_stable_header_with_columns():
    """With 0 rows and columns provided, header uses those columns, not just geo+prov."""
    csv = rows_to_csv([], "point", PROV, columns=["station_id", "value"])
    header = csv.strip().splitlines()[0]
    assert header == "station_id,value,lat,lon,source,source_url"


def test_csv_empty_rows_no_columns_fallback():
    """With 0 rows and no columns, only geo + provenance columns appear (unchanged behaviour)."""
    csv = rows_to_csv([], "point", PROV)
    header = csv.strip().splitlines()[0]
    assert header == "lat,lon,source,source_url"
